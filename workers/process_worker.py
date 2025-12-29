#!/usr/bin/python
# -*- coding: UTF-8 -*-
import json
import multiprocessing
import socket
import sys
import threading
import time
from multiprocessing import Pipe, Process, Queue
from typing import Optional

import numpy as np
from adbutils import adb
from loguru import logger
from PySide6.QtCore import Signal

from scrcpy import MutiClient

from .schemas import RspInfo, ServerInfo
from .utils import imencode


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
        self.is_running = False
        self._setup_communication()
        self._frame_count = 0
        self._last_status_time = time.time()
    
    def _setup_communication(self):
        """设置进程间通信管道"""
        self.parent_conn, self.child_conn = Pipe()
    
    def start(self):
        """启动子进程"""
        try:
            if self.process and self.process.is_alive():
                logger.warning(f"设备 {self.serial_no} 的进程已在运行")
                return True
            
            # 创建子进程
            self.process = Process(
                target=self._run_worker_process,
                args=(self.child_conn, self.row, self.serial_no, self.serverinfo)
            )
            
            # 启动进程
            self.process.start()
            self.is_running = True
            
            # 发送启动命令
            self.parent_conn.send({"action": "start"})
            
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
                return
            
            # 发送停止命令
            try:
                self.parent_conn.send({"action": "stop"})
                # 等待进程结束（最多3秒）
                self.process.join(timeout=3)
            except Exception as e:
                logger.error(f"停止设备 {self.serial_no} 进程时发送命令失败: {e}")
            
            # 如果进程仍然存活，强制终止
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
                if self.process.is_alive():
                    self.process.kill()
            
            self.is_running = False
            logger.info(f"设备 {self.serial_no} 的子进程已停止")
            
        except Exception as e:
            logger.error(f"停止设备 {self.serial_no} 子进程失败: {e}")
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
                return {"running": False, "alive": False}
            
            return {
                "running": self.is_running,
                "alive": self.process.is_alive(),
                "pid": self.process.pid
            }
        except Exception as e:
            logger.error(f"获取设备 {self.serial_no} 状态失败: {e}")
            return {"running": False, "alive": False, "error": str(e)}
    
    @staticmethod
    def _run_worker_process(parent_conn, row, serial_no, serverinfo):
        """在子进程中运行的函数"""
        frame_count = 0
        last_status_time = time.time()
        
        try:
            # 在子进程中设置信号处理
            import signal
            signal.signal(signal.SIGTERM, lambda signum, frame: None)
            signal.signal(signal.SIGINT, lambda signum, frame: None)
            
            logger.info(f"子进程开始: 设备 {serial_no}")
            
            # 初始化设备连接
            device = adb.device(serial=serial_no)
            if not device:
                error_msg = f"设备 {serial_no} 未找到"
                logger.error(error_msg)
                try:
                    parent_conn.send({"action": "error", "message": error_msg, "serial": serial_no})
                except:
                    pass
                return
            
            logger.info(f"设备 {serial_no} 连接成功，开始初始化客户端")
            client = MutiClient(device=device, block_frame=False, max_width=720)
            
            # 设置服务器
            server_socket = None
            if serverinfo:
                try:
                    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    server_socket.setblocking(0)
                except Exception as e:
                    logger.warning(f"设置服务器失败: {e}")
            
            running = True
            
            logger.info(f"设备 {serial_no} 开始视频流处理")
            
            while running:
                # 检查是否有来自父进程的消息
                try:
                    if parent_conn.poll(0.1):  # 非阻塞检查
                        msg = parent_conn.recv()
                        if msg.get("action") == "stop":
                            logger.info(f"收到停止命令: 设备 {serial_no}")
                            running = False
                            break
                except Exception as e:
                    logger.error(f"子进程接收消息失败: {e}")
                    break
                
                # 处理视频流
                try:
                    for frame in client.start():
                        if not running:
                            break
                        
                        # 发送帧统计信息（不发送实际图像数据）
                        if frame is not None and isinstance(frame, np.ndarray):
                            frame_count += 1
                            
                            # 每5帧或者每2秒发送一次状态信息
                            current_time = time.time()
                            if frame_count % 5 == 0 or (current_time - last_status_time) > 2:
                                try:
                                    status_msg = {
                                        "action": "frame_info",
                                        "serial": serial_no,
                                        "frame_count": frame_count,
                                        "timestamp": current_time,
                                        "fps": frame_count / max(current_time - last_status_time, 0.1)
                                    }
                                    parent_conn.send(status_msg)
                                    last_status_time = current_time
                                except Exception as e:
                                    logger.error(f"子进程发送帧信息失败: {e}")
                        
                        # 检查停止信号
                        try:
                            if parent_conn.poll():
                                msg = parent_conn.recv()
                                if msg.get("action") == "stop":
                                    logger.info(f"视频流中收到停止命令: 设备 {serial_no}")
                                    running = False
                                    break
                        except:
                            pass
                        
                        time.sleep(0.01)  # 避免CPU占用过高
                        
                except Exception as e:
                    error_msg = f"子进程处理视频流失败: {e}"
                    logger.error(error_msg)
                    try:
                        parent_conn.send({"action": "error", "message": str(e), "serial": serial_no})
                    except:
                        pass
                    break
            
            # 发送最终状态
            try:
                final_msg = {
                    "action": "stopped", 
                    "serial": serial_no,
                    "total_frames": frame_count,
                    "final_timestamp": time.time()
                }
                parent_conn.send(final_msg)
                logger.info(f"设备 {serial_no} 子进程正常结束，总帧数: {frame_count}")
            except Exception as e:
                logger.error(f"发送最终状态失败: {e}")
            
            # 清理资源
            try:
                client.stop()
                logger.info(f"设备 {serial_no} 客户端已停止")
            except Exception as e:
                logger.error(f"停止客户端失败: {e}")
                
            if server_socket:
                try:
                    server_socket.close()
                except:
                    pass
            
        except Exception as e:
            error_msg = f"子进程运行失败: {e}"
            logger.error(error_msg)
            try:
                parent_conn.send({"action": "error", "message": str(e), "serial": serial_no})
            except:
                pass
        
        logger.info(f"子进程结束: 设备 {serial_no}")


class ProcessWorkerManager:
    """进程worker管理器，用于统一管理多个进程"""
    
    def __init__(self):
        self.workers = {}
        self.status_queue = Queue()  # 用于状态更新
        self._monitoring_thread = None
        self._is_monitoring = False
    
    def start_worker(self, row, serial_no, serverinfo, signal=None):
        """启动一个worker"""
        try:
            if serial_no in self.workers:
                logger.warning(f"设备 {serial_no} 的worker已存在")
                return False
            
            worker = ProcessWorker(row, serial_no, serverinfo, signal)
            self.workers[serial_no] = worker
            worker.start()
            
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
        if not self._is_monitoring:
            self._is_monitoring = True
            self._monitoring_thread = threading.Thread(target=self._monitor_workers, daemon=True)
            self._monitoring_thread.start()
    
    def _monitor_workers(self):
        """监控worker状态并处理消息"""
        import threading
        
        while self._is_monitoring:
            try:
                # 检查所有活跃worker的消息
                for serial_no, worker in list(self.workers.items()):
                    if worker.parent_conn and worker.parent_conn.poll():
                        try:
                            msg = worker.parent_conn.recv()
                            self._handle_worker_message(serial_no, msg)
                        except Exception as e:
                            logger.error(f"处理设备 {serial_no} 消息失败: {e}")
                
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
                logger.debug(f"设备 {serial_no} 帧信息: {frame_count} 帧, FPS: {fps:.2f}")
                
            elif action == "error":
                # 处理错误消息
                error_msg = message.get("message", "未知错误")
                logger.error(f"设备 {serial_no} 错误: {error_msg}")
                
            elif action == "stopped":
                # 处理停止消息
                total_frames = message.get("total_frames", 0)
                logger.info(f"设备 {serial_no} 已停止，总帧数: {total_frames}")
                
            else:
                logger.debug(f"设备 {serial_no} 未知消息类型: {action}")
                
        except Exception as e:
            logger.error(f"处理设备 {serial_no} 消息时出错: {e}")
    
    def stop_monitoring(self):
        """停止消息监控"""
        self._is_monitoring = False
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self._monitoring_thread.join(timeout=2)
    
    def stop_worker(self, serial_no):
        """停止一个worker"""
        try:
            worker = self.workers.get(serial_no)
            if not worker:
                logger.warning(f"设备 {serial_no} 的worker不存在")
                return False
            
            worker.stop()
            del self.workers[serial_no]
            
            # 如果没有活跃的worker，停止监控
            if not self.workers:
                self.stop_monitoring()
            
            return True
            
        except Exception as e:
            logger.error(f"停止设备 {serial_no} worker失败: {e}")
            return False
    
    def get_worker_status(self, serial_no):
        """获取worker状态"""
        worker = self.workers.get(serial_no)
        if not worker:
            return {"running": False, "alive": False}
        
        return worker.get_status()
    
    def get_all_workers_status(self):
        """获取所有worker状态"""
        return {serial: self.get_worker_status(serial) for serial in self.workers}
    
    def stop_all_workers(self):
        """停止所有worker"""
        for serial_no in list(self.workers.keys()):
            self.stop_worker(serial_no)


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