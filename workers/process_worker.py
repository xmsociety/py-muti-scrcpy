#!/usr/bin/python
# -*- coding: UTF-8 -*-
import socket
import threading
import time
from multiprocessing import get_context

import numpy as np
from adbutils import adb
from loguru import logger

from scrcpy import MutiClient

from .schemas import ServerInfo


class ProcessWorker:
    """基于子进程的worker，通过管道与主进程通信"""
    
    def __init__(self, row, serial_no, serverinfo: ServerInfo, signal=None):
        self.row = row
        self.serial_no = serial_no
        self.serverinfo = serverinfo
        self.signal = signal
        self.process = None
        self.parent_conn = None
        self.child_conn = None
        self.stop_event = None
        self.is_running = False
        self._death_reported = False
        self.last_status = {}
        self.last_seen = None
        self.last_error = None
        # Reuse a single spawn context across pipe + Event so they're compatible.
        self._ctx = get_context("spawn")
        self._setup_communication()
        self._frame_count = 0
        self._last_status_time = time.time()

    def _setup_communication(self):
        """重建跨进程通信对象。

        - ``parent_conn``/``child_conn``: 子进程→父进程的状态上报通道（单向语义）
        - ``stop_event``: 父进程→子进程的停止信号（无 IPC 轮询开销）
        """
        self.parent_conn, self.child_conn = self._ctx.Pipe()
        self.stop_event = self._ctx.Event()
    
    def start(self):
        """启动子进程"""
        try:
            if self.process and self.process.is_alive():
                logger.warning(f"设备 {self.serial_no} 的进程已在运行")
                return True
            if self.process:
                self._cleanup_process()
                self._setup_communication()
            
            self.process = self._ctx.Process(
                target=self._run_worker_process,
                args=(
                    self.child_conn,
                    self.stop_event,
                    self.row,
                    self.serial_no,
                    self.serverinfo,
                ),
            )
            
            # 启动进程
            self.process.start()
            self.is_running = True
            self._death_reported = False
            self.last_status = {}
            self.last_seen = time.time()
            self.last_error = None
            if self.child_conn:
                self.child_conn.close()
                self.child_conn = None

            logger.info(f"设备 {self.serial_no} 的子进程已启动")
            return True
            
        except Exception as e:
            logger.error(f"启动设备 {self.serial_no} 子进程失败: {e}")
            self._cleanup_process()
            return False
    
    def stop(self):
        """停止子进程"""
        try:
            if not self.process or not self.process.is_alive():
                logger.warning(f"设备 {self.serial_no} 的进程未运行")
                self.is_running = False
                return True

            # 通过共享 Event 通知子进程退出，避免管道轮询带来的延迟
            try:
                if self.stop_event is not None:
                    self.stop_event.set()
                self.process.join(timeout=3)
            except Exception as e:
                logger.error(f"停止设备 {self.serial_no} 进程时发送停止信号失败: {e}")

            # 如果进程仍然存活，强制终止
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
                if self.process.is_alive():
                    self.process.kill()
            
            self.is_running = False
            logger.info(f"设备 {self.serial_no} 的子进程已停止")
            return True
            
        except Exception as e:
            logger.error(f"停止设备 {self.serial_no} 子进程失败: {e}")
            return False
        finally:
            self._cleanup_process()
    
    def _cleanup_process(self):
        """清理进程资源"""
        try:
            if self.process:
                self.process = None
            if self.parent_conn:
                self.parent_conn.close()
                self.parent_conn = None
            if self.child_conn:
                self.child_conn.close()
                self.child_conn = None
        except Exception as e:
            logger.error(f"清理设备 {self.serial_no} 进程资源失败: {e}")
    
    def get_status(self) -> dict:
        """获取进程状态"""
        try:
            if not self.process:
                return {
                    "running": False,
                    "alive": False,
                    "last_status": self.last_status,
                    "last_seen": self.last_seen,
                    "last_error": self.last_error,
                }
            
            alive = self.process.is_alive()
            return {
                "running": self.is_running,
                "alive": alive,
                "pid": self.process.pid,
                "exitcode": self.process.exitcode,
                "last_status": self.last_status,
                "last_seen": self.last_seen,
                "last_error": self.last_error,
            }
        except Exception as e:
            logger.error(f"获取设备 {self.serial_no} 状态失败: {e}")
            return {
                "running": False,
                "alive": False,
                "error": str(e),
                "last_status": self.last_status,
                "last_seen": self.last_seen,
                "last_error": self.last_error,
            }
    
    @staticmethod
    def _run_worker_process(parent_conn, stop_event, row, serial_no, serverinfo):
        """在子进程中运行的函数"""
        frame_count = 0
        last_status_time = time.time()
        last_status_frame_count = 0
        client = None
        server_socket = None

        def send_message(message):
            try:
                parent_conn.send(message)
            except Exception as e:
                logger.debug(f"设备 {serial_no} 向主进程发送消息失败: {e}")

        try:
            logger.info(f"子进程开始: 设备 {serial_no}")

            # 初始化设备连接
            device = adb.device(serial=serial_no)
            if not device:
                error_msg = f"设备 {serial_no} 未找到"
                logger.error(error_msg)
                send_message({"action": "error", "message": error_msg, "serial": serial_no})
                return

            logger.info(f"设备 {serial_no} 连接成功，开始初始化客户端")
            client = MutiClient(device=device, block_frame=False, max_width=720)

            # 设置服务器
            if serverinfo:
                try:
                    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    server_socket.setblocking(0)
                except Exception as e:
                    logger.warning(f"设置服务器失败: {e}")

            logger.info(f"设备 {serial_no} 开始视频流处理")

            try:
                for frame in client.start():
                    # 通过 Event 检查停止信号，无 IPC 轮询开销
                    if stop_event is not None and stop_event.is_set():
                        logger.info(f"视频流中收到停止信号: 设备 {serial_no}")
                        break

                    # 发送帧统计信息（不发送实际图像数据）
                    if frame is not None and isinstance(frame, np.ndarray):
                        frame_count += 1

                        # 每5帧或者每2秒发送一次状态信息
                        current_time = time.time()
                        if frame_count % 5 == 0 or (current_time - last_status_time) > 2:
                            elapsed = max(current_time - last_status_time, 0.1)
                            delta_frames = frame_count - last_status_frame_count
                            status_msg = {
                                "action": "frame_info",
                                "serial": serial_no,
                                "frame_count": frame_count,
                                "timestamp": current_time,
                                "fps": delta_frames / elapsed,
                            }
                            send_message(status_msg)
                            last_status_frame_count = frame_count
                            last_status_time = current_time

                    time.sleep(0.01)  # 避免CPU占用过高
            except Exception as e:
                error_msg = f"子进程处理视频流失败: {e}"
                logger.error(error_msg)
                send_message({"action": "error", "message": str(e), "serial": serial_no})
            
            # 发送最终状态
            final_msg = {
                "action": "stopped", 
                "serial": serial_no,
                "total_frames": frame_count,
                "final_timestamp": time.time()
            }
            send_message(final_msg)
            logger.info(f"设备 {serial_no} 子进程正常结束，总帧数: {frame_count}")
            
        except Exception as e:
            error_msg = f"子进程运行失败: {e}"
            logger.error(error_msg)
            send_message({"action": "error", "message": str(e), "serial": serial_no})
        finally:
            if client:
                try:
                    client.stop()
                    logger.info(f"设备 {serial_no} 客户端已停止")
                except Exception as e:
                    logger.error(f"停止客户端失败: {e}")
                    
            if server_socket:
                try:
                    server_socket.close()
                except Exception as e:
                    logger.error(f"关闭服务端 socket 失败: {e}")

            try:
                parent_conn.close()
            except Exception as e:
                logger.error(f"关闭子进程通信管道失败: {e}")
            logger.info(f"子进程结束: 设备 {serial_no}")


class ProcessWorkerManager:
    """进程worker管理器，用于统一管理多个进程"""
    
    def __init__(self):
        self.workers = {}
        self._monitoring_thread = None
        self._is_monitoring = False
        self._lock = threading.RLock()
    
    def start_worker(self, row, serial_no, serverinfo, signal=None):
        """启动一个worker"""
        try:
            with self._lock:
                if serial_no in self.workers:
                    status = self.workers[serial_no].get_status()
                    if status.get("running") and status.get("alive"):
                        logger.warning(f"设备 {serial_no} 的worker已在运行")
                        return False
                    logger.warning(f"设备 {serial_no} 存在残留worker，先清理后重新启动")
                    self.cleanup_worker(serial_no)
                
                worker = ProcessWorker(row, serial_no, serverinfo, signal)
                self.workers[serial_no] = worker
                if not worker.start():
                    self.workers.pop(serial_no, None)
                    return False
            
            # 启动消息监听
            self._start_monitoring()
            
            return True
            
        except Exception as e:
            logger.error(f"启动设备 {serial_no} worker失败: {e}")
            if serial_no in self.workers:
                del self.workers[serial_no]
            return False
    
    def _start_monitoring(self):
        """启动消息监听线程"""
        with self._lock:
            if not self._is_monitoring:
                self._is_monitoring = True
                self._monitoring_thread = threading.Thread(target=self._monitor_workers, daemon=True)
                self._monitoring_thread.start()
    
    def _monitor_workers(self):
        """监控worker状态并处理消息"""
        while self._is_monitoring:
            try:
                # 检查所有活跃worker的消息
                with self._lock:
                    workers = list(self.workers.items())
                for serial_no, worker in workers:
                    if worker.parent_conn and worker.parent_conn.poll():
                        try:
                            msg = worker.parent_conn.recv()
                            self._handle_worker_message(serial_no, msg)
                        except Exception as e:
                            logger.error(f"处理设备 {serial_no} 消息失败: {e}")
                    status = worker.get_status()
                    if (
                        status.get("running")
                        and not status.get("alive")
                        and not worker._death_reported
                    ):
                        logger.warning(
                            f"设备 {serial_no} 子进程已退出，exitcode={status.get('exitcode')}"
                        )
                        worker._death_reported = True
                
                time.sleep(0.1)  # 避免CPU占用过高
                
            except Exception as e:
                logger.error(f"监控worker失败: {e}")
                time.sleep(1)
    
    def _handle_worker_message(self, serial_no, message):
        """处理来自worker的消息"""
        try:
            action = message.get("action")
            
            if action == "frame_info":
                # 处理帧信息更新
                frame_count = message.get("frame_count", 0)
                fps = message.get("fps", 0)
                with self._lock:
                    worker = self.workers.get(serial_no)
                if worker:
                    worker.last_status = message
                    worker.last_seen = time.time()
                    worker.last_error = None
                logger.debug(f"设备 {serial_no} 帧信息: {frame_count} 帧, FPS: {fps:.2f}")
                
            elif action == "error":
                # 处理错误消息
                error_msg = message.get("message", "未知错误")
                logger.error(f"设备 {serial_no} 错误: {error_msg}")
                with self._lock:
                    worker = self.workers.get(serial_no)
                if worker:
                    worker.is_running = False
                    worker.last_error = error_msg
                    worker.last_seen = time.time()
                
            elif action == "stopped":
                # 处理停止消息
                total_frames = message.get("total_frames", 0)
                logger.info(f"设备 {serial_no} 已停止，总帧数: {total_frames}")
                with self._lock:
                    worker = self.workers.get(serial_no)
                if worker:
                    worker.is_running = False
                    worker.last_status = message
                    worker.last_seen = time.time()
                
            else:
                logger.debug(f"设备 {serial_no} 未知消息类型: {action}")
                
        except Exception as e:
            logger.error(f"处理设备 {serial_no} 消息时出错: {e}")
    
    def stop_monitoring(self):
        """停止消息监控"""
        self._is_monitoring = False
        if (
            self._monitoring_thread
            and self._monitoring_thread.is_alive()
            and threading.current_thread() is not self._monitoring_thread
        ):
            self._monitoring_thread.join(timeout=2)
    
    def stop_worker(self, serial_no):
        """停止一个worker"""
        try:
            with self._lock:
                worker = self.workers.get(serial_no)
            if not worker:
                logger.warning(f"设备 {serial_no} 的worker不存在")
                return True
            
            success = worker.stop()
            with self._lock:
                self.workers.pop(serial_no, None)
            
            # 如果没有活跃的worker，停止监控
            with self._lock:
                has_workers = bool(self.workers)
            if not has_workers:
                self.stop_monitoring()
            
            return success
            
        except Exception as e:
            logger.error(f"停止设备 {serial_no} worker失败: {e}")
            return False

    def cleanup_worker(self, serial_no):
        """清理已退出或异常的worker记录。"""
        with self._lock:
            worker = self.workers.pop(serial_no, None)
        if not worker:
            return
        try:
            worker.stop()
        except Exception as e:
            logger.error(f"清理设备 {serial_no} worker失败: {e}")
        with self._lock:
            has_workers = bool(self.workers)
        if not has_workers:
            self.stop_monitoring()
    
    def get_worker_status(self, serial_no):
        """获取worker状态"""
        with self._lock:
            worker = self.workers.get(serial_no)
        if not worker:
            return {"running": False, "alive": False}
        
        return worker.get_status()
    
    def get_all_workers_status(self):
        """获取所有worker状态"""
        with self._lock:
            workers = list(self.workers.items())
        return {serial: worker.get_status() for serial, worker in workers}
    
    def stop_all_workers(self):
        """并发停止所有 worker。

        串行 stop 在 N 设备时最坏要 N*join_timeout 秒，足以让 UI 关闭看起来
        像卡死。每个 worker 都已通过 stop_event 立刻收到信号，因此并发
        join 只是把"等子进程退出"这件事重叠起来。
        """
        with self._lock:
            serials = list(self.workers.keys())
        if not serials:
            return

        threads = [
            threading.Thread(
                target=self.stop_worker, args=(serial,), daemon=True, name=f"stop-{serial}"
            )
            for serial in serials
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)


if __name__ == "__main__":
    # 测试代码
    from workers.schemas import ServerInfo
    
    # 创建测试worker
    serverinfo = ServerInfo(host="127.0.0.1", port=9090)
    manager = ProcessWorkerManager()
    
    # 注意：这里需要真实的设备才能测试
    # manager.start_worker(0, "test_device", serverinfo)
    # time.sleep(5)
    # manager.stop_worker("test_device")