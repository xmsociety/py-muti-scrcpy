import os
import threading
import time
from multiprocessing import Process

from adbutils import adb
from loguru import logger
from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from workers import UDPServer
from workers.schemas import ServerInfo
from workers.process_worker import ProcessWorkerManager

from .schemas import runmode
from .ui_main import Ui_MainWindow
from .window_config_edit import ConfigEditWindow
from .window_screen import ScreenWindow


class MainWindow(QMainWindow):
    signal_screen_close = Signal(int, str)
    signal_config_edit_close = Signal(int, str)
    signal_update_table = Signal(list, list)

    def __init__(self, account_info=None):
        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.SerialColNum = 0
        
        # 初始化标志
        self._is_closing = False
        
        # 操作锁 - 解决线程安全问题
        self._operation_lock = threading.Lock()
        self._operation_status = {}  # 跟踪操作状态
        
        # 进程管理器 - 替换线程worker
        self.process_manager = ProcessWorkerManager()
        
        # sub process
        self.serverinfo = ServerInfo(host="127.0.0.1", port=9090)
        try:
            self.subprocess = Process(
                target=UDPServer().run, args=(self.serverinfo.host, self.serverinfo.port)
            )
            self.subprocess.start()
        except Exception as e:
            logger.error(f"启动UDP服务器失败: {e}")
            self.subprocess = None
            
        # bind events
        self.ui.checkbox_devices.clicked.connect(self.on_click_check_all)
        self.ui.button_all_satrt.clicked.connect(self.on_click_all_start)
        self.ui.button_all_stop.clicked.connect(self.on_click_all_stop)

        self.ui.table_devices.horizontalHeader().setStretchLastSection(True)
        self.ui.table_devices.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )  # noEdit
        self.ui.table_devices.setSelectionMode(
            QAbstractItemView.NoSelection
        )  # noSelection
        self.dict_window_screen = {}
        self.dict_window_edit = {}

        # 不再需要 dict_client，用 ProcessWorkerManager 替代
        # self.dict_client = {}

        # UI Text Dict
        self.dict_ui_text = {
            "buttons": {
                # 传入状态(运行时可关闭.关闭时可运行)
                "operate": {1: "停止", -1: "启动"},
                "show": {1: "关闭画面", -1: "显示画面"},
                "edit": {1: "取消编辑", -1: "编辑"},
            },
        }
        self.dict_table_buttons = {}
        self.dict_table_box = {"check": {}, "combo": {}}
        # self.update_table_data(data=self.get_table_data())

        # close screnn window
        self.signal_screen_close.connect(self.close_all_about_show)
        self.signal_config_edit_close.connect(self.close_all_about_edit_show)
        self.show()

        # region threads
        threading.Thread(
            target=self.listen_device, args=(self.signal_update_table,), daemon=True
        ).start()
        self.signal_update_table.connect(self.update_table_data)
        # threading.Thread(target=self.reconnect_offline, daemon=True).start()
        # endregion
        
        # 启动进程状态监控
        self._start_process_monitoring()

    def get_device_nick_name(self, serial):
        data = ConfigEditWindow.get_config_info_from_file(
            os.path.join(ConfigEditWindow.root_dir, serial)
        )
        return data.get("nickname") if data else ""

    def get_table_data(self):
        data = []
        self.SerialColNum = 2
        try:
            for i in adb.device_list():
                serial = i.serial
                if serial:  # 添加空值检查
                    data.append(
                        [
                            self.check_box_widget,
                            self.get_device_nick_name(serial=serial),
                            serial,
                            "pvp",
                            self.operate_button_widget,
                            self.others_buttons_widget,
                        ]
                    )
        except Exception as e:
            logger.error(f"获取设备列表失败: {e}")
        
        # 添加测试设备（可以配置化）
        data.append(
            [
                self.check_box_widget,
                "常驻测试",
                "fake_device",
                "pvp",
                self.operate_button_widget,  # 修复：使用widget而不是字符串
                self.others_buttons_widget,
            ]
        )
        return data

    # region widgets数据缓存
    def add_button2table_dict(self, row, data):
        if not self.dict_table_buttons.get(row):
            self.dict_table_buttons[row] = {}
        self.dict_table_buttons[row].update(data)

    def chg_button2table_dict(self, row, name, status):
        """
        统一管理按钮状态的方法
        """
        row_data = self.dict_table_buttons.get(row)
        if not row_data or name not in row_data:
            logger.warning(f"按钮 {name} 在第 {row} 行不存在")
            return
            
        button = row_data[name]
        if status > 0:
            button.setStyleSheet(
                """ text-align : center;
                    background-color : LightCoral;
                    """
            )
        else:
            button.setStyleSheet("")
            
        # 获取按钮文本，支持更灵活的配置
        ui_text = self.dict_ui_text["buttons"]
        button_text = ui_text.get(name, {}).get(status, "未知")
        button.setText(button_text)

    def add_box2table_dict(self, row, name, box_widget):
        """
        保存 box 组建:
        name str in( check, combo )
        """
        self.dict_table_box[name][row] = box_widget

    def chg_box2table_dict(self, row, reverse=True, sure=0, checkbox=None):
        """
        修改checkbox 状态
        reverse: 将当前状态反转
        sure: 1 勾选, -1 取消勾选
        """
        if row and not checkbox:
            checkbox = self.dict_table_box["check"].get(row)
        if reverse:
            _status = checkbox.isChecked()
            checkbox.setChecked(not _status)
        elif sure:
            checkbox.setChecked(sure > 0)

    # endregion

    # region 特殊Table 元素
    def combo_box_widget(self, row):
        combobox = QComboBox()
        combobox.addItems(runmode.All)
        self.add_box2table_dict(row, "combo", combobox)
        return combobox

    def check_box_widget(self, row):
        checkbox = QCheckBox()
        self.add_box2table_dict(row, "check", checkbox)
        return checkbox

    def operate_button_widget(self, row):
        button = QPushButton(self.dict_ui_text["buttons"]["operate"][-1])
        button.clicked.connect(self.on_click_operate)
        data = {"operate": button}
        self.add_button2table_dict(row, data)
        return button

    def others_buttons_widget(self, row):
        widget = QWidget()
        hlayout = QHBoxLayout()
        button_edit = QPushButton("编辑")
        button_edit.clicked.connect(self.on_click_edit)
        # button_edit.setStyleSheet(
        #     """ text-align : center;
        #         background-color : NavajoWhite;
        #         height : 30px;
        #         border-style: outset;
        #         font : 13px  """
        # )
        # button_cpy = QPushButton("复制")
        # button_cpy.clicked.connect(self.on_click_cpy)
        button_show = QPushButton(self.dict_ui_text["buttons"]["show"][-1])
        button_show.clicked.connect(self.on_click_show)
        hlayout.addWidget(button_edit)
        # hlayout.addWidget(button_cpy)
        # hlayout.addWidget(button_del)
        hlayout.addWidget(button_show)
        self.add_button2table_dict(row, {"edit": button_edit, "show": button_show})
        hlayout.setContentsMargins(5, 2, 5, 2)
        widget.setLayout(hlayout)
        return widget

    # endregion

    # region 事件处理
    def listen_device(self, signal):
        while True:
            data = self.get_table_data()
            all_serials = {d[2] for d in data}
            rows = self.ui.table_devices.rowCount()
            if not rows:
                time.sleep(2)
                rows = 1
            old_serials_map = {
                self.ui.table_devices.item(row, 2).text(): row
                for row in range(rows)
                if self.ui.table_devices.item(row, 2)
            }
            old_serials = set(old_serials_map.keys())
            keep = all_serials & old_serials
            to_insert_data = [d for d in data if d[2] not in keep]
            if to_insert_data:
                print("to insert", to_insert_data)
            to_remove = [se for se in old_serials if se not in keep]
            if to_insert_data or to_remove:
                signal.emit(to_insert_data, to_remove)
            time.sleep(2)

    # def reconnect_offline(self):
    #     import subprocess

    #     while True:
    #         time.sleep(5)
    #         try:
    #             to_reconnect_devices = []
    #             path = adb_path()
    #             try:
    #                 sys._MEIPASS
    #                 path = os.path.join("adbutils", "binaries", "adb.exe")
    #             except:
    #                 pass
    #             encoding = "utf-8"
    #             if sys.platform == "win32":
    #                 encoding = "gbk"
    #             res = subprocess.Popen(
    #                 "{} devices -l".format(path),
    #                 shell=True,
    #                 stdout=subprocess.PIPE,
    #                 encoding=encoding,
    #             )
    #             try:
    #                 res, _ = res.communicate(timeout=3)
    #             except Exception as e:
    #                 logger.error(
    #                     "{} error {}".format("{} devices -l".format(path), str(e))
    #                 )
    #                 continue

    #             for line in res.split("\n"):
    #                 line = line.strip()
    #                 if line.startswith("emulator") or not line:
    #                     continue
    #                 if "offline" in line:
    #                     res_list = line.split(" ")
    #                     device_sn = res_list[0]
    #                     to_reconnect_devices.append(device_sn)
    #             if to_reconnect_devices:
    #                 logger.info("to_reconnect_devices: {}".format(to_reconnect_devices))
    #             for device_sn in to_reconnect_devices:
    #                 subprocess.Popen(
    #                     "{} disconnect {}".format(path, device_sn), shell=True
    #                 )
    #                 subprocess.Popen(
    #                     "{} connect {}".format(path, device_sn), shell=True
    #                 )
    #                 logger.debug("{} connect {}".format(path, device_sn))
    #         except Exception as e:
    #             logger.error("reconnect error: {}".format(str(e)))

    def on_click_all_start(self):
        """批量启动所有选中的设备"""
        tasks = []
        for row, box in self.dict_table_box["check"].items():
            row, _, serial_no = self.get_table_row_info(row)
            if box.isChecked() and not self.process_manager.get_worker_status(serial_no).get('running'):
                tasks.append((row, serial_no))
        
        # 批量异步启动设备
        if tasks:
            threading.Thread(
                target=self._batch_start_devices, 
                args=(tasks,), 
                daemon=True
            ).start()

    def on_click_all_stop(self):
        """批量停止所有选中的设备"""
        tasks = []
        for row, box in self.dict_table_box["check"].items():
            row, _, serial_no = self.get_table_row_info(row)
            if box.isChecked() and self.process_manager.get_worker_status(serial_no).get('running'):
                tasks.append((row, serial_no))
        
        # 批量异步停止设备
        if tasks:
            threading.Thread(
                target=self._batch_stop_devices, 
                args=(tasks,), 
                daemon=True
            ).start()

    def _batch_start_devices(self, tasks):
        """批量启动设备的线程安全实现"""
        for row, serial_no in tasks:
            try:
                # 检查是否需要启动（可能已被其他操作启动）
                status = self.process_manager.get_worker_status(serial_no)
                if not status.get('running') and self._operation_status.get(serial_no) != 'starting':
                    self.on_click_operate(row=row, serial_no=serial_no)
            except Exception as e:
                logger.error(f"批量启动设备 {serial_no} 失败: {e}")

    def _batch_stop_devices(self, tasks):
        """批量停止设备的线程安全实现"""
        for row, serial_no in tasks:
            try:
                # 检查是否需要停止（可能已被其他操作停止）
                status = self.process_manager.get_worker_status(serial_no)
                if status.get('running') and self._operation_status.get(serial_no) != 'stopping':
                    self.on_click_operate(row=row, serial_no=serial_no)
            except Exception as e:
                logger.error(f"批量停止设备 {serial_no} 失败: {e}")


    def on_click_check_all(self):
        for row, box in self.dict_table_box["check"].items():
            if self.ui.checkbox_devices.isChecked():
                self.chg_box2table_dict(row, sure=1, checkbox=box)
            else:
                self.chg_box2table_dict(row, sure=-1, checkbox=box)

    def get_table_row_info(self, row):
        serial_no = self.ui.table_devices.item(row, 2).text()
        name = self.ui.table_devices.item(row, 1).text()
        return row, name, serial_no

    def get_table_row_info_by_button(self, by_parent_pos=False):
        """
        通过点击的button所在位置/button‘s parent所在位置获取当前行信息
        ret: tuple[str]
            row, name, serial_no
        """
        button = self.sender()
        if button:
            if by_parent_pos:
                row = self.ui.table_devices.indexAt(button.parent().pos()).row()
            else:
                row = self.ui.table_devices.indexAt(button.pos()).row()
            return self.get_table_row_info(row)

    def on_click_edit(self):
        row, name, serial_no = self.get_table_row_info_by_button(by_parent_pos=True)
        win_edit = self.dict_window_edit.get(serial_no)
        self.chg_button2table_dict(row, "edit", 1)
        if not win_edit:
            _win_edit = ConfigEditWindow(
                name, row, serial_no, self.signal_config_edit_close
            )
            self.dict_window_edit[serial_no] = _win_edit
        else:
            win_edit.close()

    # def on_click_cpy(self):
    #     pass

    def close_all_about_edit_show(self, row, serial_no):
        del self.dict_window_edit[serial_no]
        self.chg_button2table_dict(row, "edit", -1)

    def close_all_about_show(self, row, serial_no):
        del self.dict_window_screen[serial_no]
        self.chg_button2table_dict(row, "show", -1)

    def on_click_show(self):
        row, name, serial_no = self.get_table_row_info_by_button(by_parent_pos=True)
        win_screen = self.dict_window_screen.get(serial_no)
        if not win_screen:
            _win_screen = ScreenWindow(name, row, serial_no, self.signal_screen_close)
            self.dict_window_screen[serial_no] = _win_screen
            self.dict_window_screen[serial_no].tworker.start()
            self.chg_button2table_dict(row, "show", 1)
            # self.dict_window_screen[serial_no].showWindow()
        else:
            win_screen.close()
            # self.close_all_about_show(row, serial_no)

    def on_click_operate(self, row=None, serial_no=None):
        # 使用锁确保线程安全
        with self._operation_lock:
            # 检查是否已经在操作中
            if row is None or serial_no is None:
                row, name, serial_no = self.get_table_row_info_by_button(by_parent_pos=False)
            if self._operation_status.get(serial_no) == 'starting':
                logger.warning(f"设备 {serial_no} 正在启动中，请稍候...")
                return
            elif self._operation_status.get(serial_no) == 'stopping':
                logger.warning(f"设备 {serial_no} 正在停止中，请稍候...")
                return
            
            # 获取行信息
            if isinstance(row, int) and serial_no:
                pass
            elif isinstance(row, int):
                row, _, serial_no = self.get_table_row_info(row=row)
            else:
                row, _, serial_no = self.get_table_row_info_by_button()
            
            # 使用进程管理器检查状态
            worker_status = self.process_manager.get_worker_status(serial_no)
            
            if not worker_status.get('running'):
                try:
                    # 设置操作状态为启动中
                    self._operation_status[serial_no] = 'starting'
                    
                    # 使用进程管理器启动设备
                    success = self.process_manager.start_worker(
                        row, serial_no, self.serverinfo
                    )
                    
                    if success:
                        # 延迟更新UI状态，确保操作真正启动成功
                        self._update_button_state_safe(row, "operate", 1)
                        self._operation_status[serial_no] = 'running'
                        logger.info(f"设备 {serial_no} 启动成功")
                    else:
                        raise Exception("启动进程失败")
                    
                except Exception as e:
                    logger.error(f"设备 {serial_no} 启动失败: {e}")
                    self._operation_status[serial_no] = None
                    # 如果启动失败，需要回退UI状态
                    self._update_button_state_safe(row, "operate", -1)
                    
            else:
                try:
                    # 设置操作状态为停止中
                    self._operation_status[serial_no] = 'stopping'
                    
                    # 使用进程管理器停止设备
                    success = self.process_manager.stop_worker(serial_no)
                    
                    if success:
                        # 更新UI状态
                        self._update_button_state_safe(row, "operate", -1)
                        self._operation_status[serial_no] = None
                        logger.info(f"设备 {serial_no} 停止成功")
                    else:
                        raise Exception("停止进程失败")
                    
                except Exception as e:
                    logger.error(f"设备 {serial_no} 停止失败: {e}")
                    self._operation_status[serial_no] = None
                    # 回退UI状态
                    self._update_button_state_safe(row, "operate", 1)
                    self._operation_status[serial_no] = 'running'

    def _update_button_state_safe(self, row, button_name, status):
        """线程安全的UI更新方法"""
        try:
            # 在主线程中更新UI
            self.chg_button2table_dict(row, button_name, status)
        except Exception as e:
            logger.error(f"更新UI状态失败 (row={row}, button={button_name}, status={status}): {e}")


    def update_table_data(self, data: list, remove_serialno: list = None):
        logger.info(f"数据刷新: {data}\n \t\t{remove_serialno}")
        self.dict_table_buttons = {}
        self.dict_table_box = {"check": {}, "combo": {}}
        for _rm_no in remove_serialno or []:  # 添加默认值
            logger.info(
                f"self.ui.table_devices.rowCount(): {self.ui.table_devices.rowCount()}\n self.ui.table_devices.item(row_num, self.SerialColNum): {self.ui.table_devices.item(0, self.SerialColNum).text()}"
            )
            for row_num in range(self.ui.table_devices.rowCount()):
                if (
                    self.ui.table_devices.item(row_num, self.SerialColNum).text()
                    in remove_serialno
                ):
                    logger.warning(f"will remove row: {row_num}, no: {_rm_no}")
                    self.ui.table_devices.removeRow(row_num)

        for item in data:
            row = self.ui.table_devices.rowCount()
            self.ui.table_devices.insertRow(row)
            for j, v in enumerate(item):
                if callable(v):  # 修复：检查是否是可调用的（widget构造函数）
                    func_data = v(row)
                    self.ui.table_devices.setCellWidget(row, j, func_data)
                else:
                    v = QTableWidgetItem(v)
                    self.ui.table_devices.setItem(row, j, v)
    
    def _start_process_monitoring(self):
        """启动进程状态监控"""
        try:
            # 定期检查进程状态并更新UI
            self._monitor_timer = threading.Timer(2.0, self._check_process_status)
            self._monitor_timer.start()
        except Exception as e:
            logger.error(f"启动进程监控失败: {e}")
    
    def _check_process_status(self):
        """检查进程状态并更新UI"""
        try:
            if self._is_closing:
                return
                
            # 检查所有worker的状态
            all_status = self.process_manager.get_all_workers_status()
            
            for serial_no, status in all_status.items():
                # 查找对应的行
                row = self._find_row_by_serial(serial_no)
                if row == -1:
                    continue
                    
                running = status.get('running', False)
                alive = status.get('alive', False)
                
                # 如果进程不存活但UI显示为运行状态，更新UI
                if not alive and running:
                    # 进程异常退出，更新UI状态
                    self._update_button_state_safe(row, "operate", -1)
                    if serial_no in self._operation_status:
                        self._operation_status[serial_no] = None
                    logger.warning(f"检测到设备 {serial_no} 进程异常退出")
            
            # 重新启动定时器
            if not self._is_closing:
                self._monitor_timer = threading.Timer(2.0, self._check_process_status)
                self._monitor_timer.start()
                
        except Exception as e:
            logger.error(f"检查进程状态失败: {e}")
            # 出现错误时也重新启动定时器
            if not self._is_closing:
                self._monitor_timer = threading.Timer(5.0, self._check_process_status)
                self._monitor_timer.start()
    
    def _find_row_by_serial(self, serial_no):
        """根据设备序列号查找行号"""
        try:
            for row in range(self.ui.table_devices.rowCount()):
                item = self.ui.table_devices.item(row, 2)  # 序列号在第3列
                if item and item.text() == serial_no:
                    return row
            return -1
        except Exception as e:
            logger.error(f"查找设备行失败: {e}")
            return -1

    def closeEvent(self, event: QCloseEvent) -> None:
        self._is_closing = True
        
        # 停止进程监控定时器
        try:
            if hasattr(self, '_monitor_timer') and self._monitor_timer:
                self._monitor_timer.cancel()
        except Exception as e:
            logger.error(f"停止监控定时器失败: {e}")
        
        # 使用进程管理器停止所有设备进程
        try:
            self.process_manager.stop_all_workers()
        except Exception as e:
            logger.error(f"停止所有设备进程失败: {e}")
        
        # 关闭所有子窗口
        for serial_no, window in list(self.dict_window_screen.items()):
            try:
                window.close()
            except Exception as e:
                logger.error(f"关闭屏幕窗口 {serial_no} 失败: {e}")
                
        for serial_no, window in list(self.dict_window_edit.items()):
            try:
                window.close()
            except Exception as e:
                logger.error(f"关闭编辑窗口 {serial_no} 失败: {e}")
        
        # 清理操作状态
        self._operation_status.clear()
        
        # 终止UDP服务器子进程
        if self.subprocess:
            try:
                self.subprocess.terminate()
                self.subprocess.join(timeout=3)  # 等待3秒
                if self.subprocess.is_alive():
                    self.subprocess.kill()  # 强制终止
            except Exception as e:
                logger.error(f"关闭UDP服务器失败: {e}")
        
        logger.info("主窗口已关闭")
        return super().closeEvent(event)

    # endregion
