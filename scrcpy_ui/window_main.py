import os
import threading
import time
from multiprocessing import get_context

from adbutils import adb
from loguru import logger
from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from workers import run_udp_server
from workers.process_worker import ProcessWorkerManager
from workers.schemas import ServerInfo

from .schemas import runmode
from .ui_main import Ui_MainWindow
from .window_config_edit import ConfigEditWindow
from .window_screen import ScreenWindow


class MainWindow(QMainWindow):
    signal_screen_close = Signal(int, str)
    signal_config_edit_close = Signal(int, str)
    signal_update_table = Signal(list)
    signal_worker_operation_finished = Signal(str, str, bool, str)

    def __init__(self, account_info=None):
        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.SerialColNum = 2
        self.StatusColNum = 6
        self._ensure_status_column()

        self._is_closing = False
        self._device_scan_stop = threading.Event()

        # 操作锁 - 解决线程安全问题
        self._operation_lock = threading.Lock()
        self._operation_status = {}  # 跟踪操作状态

        self.process_manager = ProcessWorkerManager()

        # sub process
        self.serverinfo = ServerInfo(host="127.0.0.1", port=9090)
        try:
            process_context = get_context("spawn")
            self.subprocess = process_context.Process(
                target=run_udp_server, args=(self.serverinfo.host, self.serverinfo.port)
            )
            self.subprocess.start()
        except Exception as e:
            logger.error(f"启动UDP服务器失败: {e}")
            self.subprocess = None
            
        # bind events
        self.ui.checkbox_devices.clicked.connect(self.on_click_check_all)
        self.ui.button_all_satrt.clicked.connect(self.on_click_all_start)
        self.ui.button_all_stop.clicked.connect(self.on_click_all_stop)

        self.ui.table_devices.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )  # noEdit
        self.ui.table_devices.setSelectionMode(
            QAbstractItemView.NoSelection
        )  # noSelection
        self._setup_table_columns()
        self.dict_window_screen = {}
        self.dict_window_edit = {}

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

        # close screnn window
        self.signal_screen_close.connect(self.close_all_about_show)
        self.signal_config_edit_close.connect(self.close_all_about_edit_show)
        self.signal_update_table.connect(self.on_device_snapshot)
        self.signal_worker_operation_finished.connect(self.on_worker_operation_finished)
        self.show()

        threading.Thread(
            target=self.listen_device, args=(self.signal_update_table,), daemon=True
        ).start()

        self._start_process_monitoring()

    def get_device_nick_name(self, serial):
        data = ConfigEditWindow.get_config_info_from_file(
            os.path.join(ConfigEditWindow.root_dir, serial)
        )
        return data.get("nickname") if data else ""

    def refresh_device_nick_name(self, serial_no):
        row = self._find_row_by_serial(serial_no)
        if row == -1:
            return
        self.ui.table_devices.setItem(
            row, 1, QTableWidgetItem(self.get_device_nick_name(serial_no))
        )

    def get_table_data(self):
        data = []
        try:
            for i in adb.device_list():
                serial = i.serial
                if serial:  # 添加空值检查
                    data.append(
                        [
                            self.check_box_widget,
                            self.get_device_nick_name(serial=serial),
                            serial,
                            self.combo_box_widget,
                            self.operate_button_widget,
                            self.others_buttons_widget,
                            "未启动",
                        ]
                    )
        except Exception as e:
            logger.error(f"获取设备列表失败: {e}")
        return data

    def _ensure_status_column(self):
        if self.ui.table_devices.columnCount() <= self.StatusColNum:
            self.ui.table_devices.setColumnCount(self.StatusColNum + 1)
        self.ui.table_devices.setHorizontalHeaderItem(
            self.StatusColNum, QTableWidgetItem("状态")
        )

    def _setup_table_columns(self):
        """统一设置表格列宽。

        .ui 文件里 ``QTableWidget`` 的列默认宽度只有 100 px，导致 ``Others``
        列里的"编辑 / 显示画面"两个中文按钮被截断；这里给每列分配合理宽度，
        并让"状态"列自动拉伸填满剩余空间。
        """
        header = self.ui.table_devices.horizontalHeader()
        # 行号→宽度（与 .ui 中 column 顺序保持一致）：
        # 0 复选框 | 1 设备别名 | 2 序列号 | 3 运行模式 | 4 操作 | 5 其他按钮组 | 6 状态
        column_widths = {
            0: 36,
            1: 120,
            2: 170,
            3: 130,
            4: 90,
            5: 200,
        }
        for col, width in column_widths.items():
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.ui.table_devices.setColumnWidth(col, width)

        # 状态列拉伸填满剩余宽度
        header.setSectionResizeMode(self.StatusColNum, QHeaderView.Stretch)

    # region widgets数据缓存
    def add_button2table_dict(self, row, data):
        if not self.dict_table_buttons.get(row):
            self.dict_table_buttons[row] = {}
        self.dict_table_buttons[row].update(data)

    def chg_button2table_dict(self, row, name, status):
        """
        统一管理按钮状态的方法
        """
        if row == -1:
            return
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

    def update_device_status(self, serial_no, text, abnormal=False):
        row = self._find_row_by_serial(serial_no)
        if row == -1:
            return
        item = QTableWidgetItem(text)
        if abnormal:
            item.setBackground(QColor("LightCoral"))
        elif text.startswith("运行"):
            item.setBackground(QColor("LightGreen"))
        self.ui.table_devices.setItem(row, self.StatusColNum, item)

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
        if row is not None and not checkbox:
            checkbox = self.dict_table_box["check"].get(row)
        if checkbox is None:
            return
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
        # 中文按钮（"显示画面"/"取消编辑" 等）默认 sizeHint 偏窄，在表格里易被截断；
        # 给最小宽度兜底，配合 _setup_table_columns 的列宽。
        button_edit = QPushButton("编辑")
        button_edit.setMinimumWidth(70)
        button_edit.clicked.connect(self.on_click_edit)
        button_show = QPushButton(self.dict_ui_text["buttons"]["show"][-1])
        button_show.setMinimumWidth(90)
        button_show.clicked.connect(self.on_click_show)
        hlayout.addWidget(button_edit)
        hlayout.addWidget(button_show)
        self.add_button2table_dict(row, {"edit": button_edit, "show": button_show})
        hlayout.setContentsMargins(5, 2, 5, 2)
        widget.setLayout(hlayout)
        return widget

    # endregion

    # region 事件处理
    def listen_device(self, signal):
        while not self._device_scan_stop.is_set():
            data = self.get_table_data()
            signal.emit(data)
            self._device_scan_stop.wait(2)

    def on_device_snapshot(self, data):
        """在主线程中对比设备快照并更新表格。"""
        all_serials = {d[2] for d in data}
        old_serials = {
            self.ui.table_devices.item(row, self.SerialColNum).text()
            for row in range(self.ui.table_devices.rowCount())
            if self.ui.table_devices.item(row, self.SerialColNum)
        }
        keep = all_serials & old_serials
        to_insert_data = [d for d in data if d[2] not in keep]
        to_remove = [serial for serial in old_serials if serial not in keep]
        if to_insert_data or to_remove:
            self.update_table_data(to_insert_data, to_remove)

    def on_click_all_start(self):
        """批量启动所有选中的设备"""
        for row, box in self.dict_table_box["check"].items():
            row, _, serial_no = self.get_table_row_info(row)
            status = self.process_manager.get_worker_status(serial_no)
            if box.isChecked() and not self._is_worker_active(status):
                self.request_worker_operation(row, serial_no, "start")

    def on_click_all_stop(self):
        """批量停止所有选中的设备"""
        for row, box in self.dict_table_box["check"].items():
            row, _, serial_no = self.get_table_row_info(row)
            status = self.process_manager.get_worker_status(serial_no)
            if box.isChecked() and self._is_worker_active(status):
                self.request_worker_operation(row, serial_no, "stop")

    def on_click_check_all(self):
        for row, box in self.dict_table_box["check"].items():
            if self.ui.checkbox_devices.isChecked():
                self.chg_box2table_dict(row, sure=1, checkbox=box)
            else:
                self.chg_box2table_dict(row, sure=-1, checkbox=box)

    @staticmethod
    def _is_worker_active(status):
        return status.get("running") and status.get("alive")

    def get_table_row_info(self, row):
        serial_no = self.ui.table_devices.item(row, 2).text()
        name = self.ui.table_devices.item(row, 1).text()
        return row, name, serial_no

    def get_screen_window_title(self, name, serial_no):
        device_label = "Device"
        if name:
            device_label = f"{name} ({device_label})"
        return f"{device_label} - Serial: {serial_no}"

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

    @staticmethod
    def _is_window_alive(window) -> bool:
        """检查 Qt 窗口对象是否还活着且可见。

        signal 偶尔会丢失（外部强杀、deleteLater 时序、main close 时
        子窗 closeEvent 抛异常等），导致 dict 里残留一个已死的引用。下次
        点击时直接 ``win.close()`` 等于无操作，窗口再也开不出来——这是
        历史 P3-20 报告的"ScreenWindow 不能复活"现象。
        """
        if window is None:
            return False
        try:
            return bool(window.isVisible())
        except RuntimeError:
            # PySide6 在底层 C++ 对象被释放后访问任何方法都会抛
            # "Internal C++ object already deleted."
            return False

    def _bind_window_lifecycle(self, window, registry: dict, serial_no: str):
        """挂上 ``destroyed`` 兜底，确保 dict 始终能被清理。"""

        def _drop(*_):
            registry.pop(serial_no, None)

        try:
            window.destroyed.connect(_drop)
        except Exception as e:
            logger.debug(f"绑定 destroyed 信号失败 ({serial_no}): {e}")

    def on_click_edit(self):
        row, name, serial_no = self.get_table_row_info_by_button(by_parent_pos=True)
        win_edit = self.dict_window_edit.get(serial_no)
        if self._is_window_alive(win_edit):
            win_edit.close()
            return

        # 残留则丢弃
        self.dict_window_edit.pop(serial_no, None)

        self.chg_button2table_dict(row, "edit", 1)
        _win_edit = ConfigEditWindow(
            name, row, serial_no, self.signal_config_edit_close
        )
        self.dict_window_edit[serial_no] = _win_edit
        self._bind_window_lifecycle(_win_edit, self.dict_window_edit, serial_no)

    def close_all_about_edit_show(self, row, serial_no):
        self.dict_window_edit.pop(serial_no, None)
        row = self._find_row_by_serial(serial_no)
        self.refresh_device_nick_name(serial_no)
        self.chg_button2table_dict(row, "edit", -1)

    def close_all_about_show(self, row, serial_no):
        self.dict_window_screen.pop(serial_no, None)
        row = self._find_row_by_serial(serial_no)
        self.chg_button2table_dict(row, "show", -1)

    def on_click_show(self):
        row, name, serial_no = self.get_table_row_info_by_button(by_parent_pos=True)
        win_screen = self.dict_window_screen.get(serial_no)
        if self._is_window_alive(win_screen):
            win_screen.close()
            return

        # 残留窗口直接丢弃，下面新建一个
        if win_screen is not None:
            logger.debug(f"清理设备 {serial_no} 残留 ScreenWindow")
            self.dict_window_screen.pop(serial_no, None)

        title = self.get_screen_window_title(name, serial_no)
        _win_screen = ScreenWindow(name, row, serial_no, self.signal_screen_close)
        _win_screen.setWindowTitle(title)
        self.dict_window_screen[serial_no] = _win_screen
        self._bind_window_lifecycle(_win_screen, self.dict_window_screen, serial_no)
        _win_screen.tworker.start()
        self.chg_button2table_dict(row, "show", 1)

    def on_click_operate(self, row=None, serial_no=None):
        if row is None or serial_no is None:
            row, _, serial_no = self.get_table_row_info_by_button(by_parent_pos=False)
        if isinstance(row, int) and not serial_no:
            row, _, serial_no = self.get_table_row_info(row=row)

        worker_status = self.process_manager.get_worker_status(serial_no)
        operation = "stop" if self._is_worker_active(worker_status) else "start"
        self.request_worker_operation(row, serial_no, operation)

    def request_worker_operation(self, row, serial_no, operation):
        """请求启动或停止 worker；耗时操作在线程执行，UI 更新回到主线程。"""
        with self._operation_lock:
            if self._operation_status.get(serial_no) == 'starting':
                logger.warning(f"设备 {serial_no} 正在启动中，请稍候...")
                return
            elif self._operation_status.get(serial_no) == 'stopping':
                logger.warning(f"设备 {serial_no} 正在停止中，请稍候...")
                return
            worker_status = self.process_manager.get_worker_status(serial_no)
            if operation == "start" and self._is_worker_active(worker_status):
                return
            if operation == "stop" and not self._is_worker_active(worker_status):
                return

            self._operation_status[serial_no] = (
                "starting" if operation == "start" else "stopping"
            )
            self.update_device_status(
                serial_no, "启动中" if operation == "start" else "停止中"
            )

        threading.Thread(
            target=self._run_worker_operation,
            args=(row, serial_no, operation),
            daemon=True,
        ).start()

    def _run_worker_operation(self, row, serial_no, operation):
        try:
            if operation == "start":
                success = self.process_manager.start_worker(row, serial_no, self.serverinfo)
                error_msg = "" if success else "启动进程失败"
            else:
                success = self.process_manager.stop_worker(serial_no)
                error_msg = "" if success else "停止进程失败"
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(f"设备 {serial_no} {operation} 失败: {e}")
        self.signal_worker_operation_finished.emit(serial_no, operation, success, error_msg)

    def on_worker_operation_finished(self, serial_no, operation, success, error_msg):
        row = self._find_row_by_serial(serial_no)
        if row == -1:
            self._operation_status.pop(serial_no, None)
            return

        if operation == "start":
            if success:
                self._update_button_state_safe(row, "operate", 1)
                self.update_device_status(serial_no, "运行中")
                self._operation_status[serial_no] = "running"
                logger.info(f"设备 {serial_no} 启动成功")
            else:
                self._update_button_state_safe(row, "operate", -1)
                self.update_device_status(
                    serial_no, f"异常: {error_msg or '启动进程失败'}", abnormal=True
                )
                self._operation_status[serial_no] = None
        else:
            if success:
                self._update_button_state_safe(row, "operate", -1)
                self.update_device_status(serial_no, "已停止")
                self._operation_status[serial_no] = None
                logger.info(f"设备 {serial_no} 停止成功")
            else:
                self._update_button_state_safe(row, "operate", 1)
                self.update_device_status(
                    serial_no, f"异常: {error_msg or '停止进程失败'}", abnormal=True
                )
                self._operation_status[serial_no] = "running"

    def _update_button_state_safe(self, row, button_name, status):
        """线程安全的UI更新方法"""
        try:
            # 在主线程中更新UI
            self.chg_button2table_dict(row, button_name, status)
        except Exception as e:
            logger.error(f"更新UI状态失败 (row={row}, button={button_name}, status={status}): {e}")


    def update_table_data(self, data: list, remove_serialno: list = None):
        logger.info(f"数据刷新: {data}\n \t\t{remove_serialno}")
        remove_serialno = set(remove_serialno or [])
        if remove_serialno:
            for row_num in range(self.ui.table_devices.rowCount() - 1, -1, -1):
                item = self.ui.table_devices.item(row_num, self.SerialColNum)
                if item and item.text() in remove_serialno:
                    serial_no = item.text()
                    logger.warning(f"will remove row: {row_num}, no: {serial_no}")
                    self.process_manager.stop_worker(serial_no)
                    self._operation_status.pop(serial_no, None)
                    screen_window = self.dict_window_screen.pop(serial_no, None)
                    if screen_window:
                        screen_window.close()
                    edit_window = self.dict_window_edit.pop(serial_no, None)
                    if edit_window:
                        edit_window.close()
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
        self._rebuild_table_widget_cache()
        self._sync_window_button_states()

    def _rebuild_table_widget_cache(self):
        """根据当前表格内容重建行号到控件的缓存。"""
        self.dict_table_buttons = {}
        self.dict_table_box = {"check": {}, "combo": {}}
        for row in range(self.ui.table_devices.rowCount()):
            checkbox = self.ui.table_devices.cellWidget(row, 0)
            if isinstance(checkbox, QCheckBox):
                self.add_box2table_dict(row, "check", checkbox)

            combo = self.ui.table_devices.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                self.add_box2table_dict(row, "combo", combo)

            operate_button = self.ui.table_devices.cellWidget(row, 4)
            if isinstance(operate_button, QPushButton):
                self.add_button2table_dict(row, {"operate": operate_button})

            others_widget = self.ui.table_devices.cellWidget(row, 5)
            if others_widget:
                row_buttons = {}
                for button in others_widget.findChildren(QPushButton):
                    if button.text() in self.dict_ui_text["buttons"]["edit"].values():
                        row_buttons["edit"] = button
                    elif button.text() in self.dict_ui_text["buttons"]["show"].values():
                        row_buttons["show"] = button
                if row_buttons:
                    self.add_button2table_dict(row, row_buttons)

    def _sync_window_button_states(self):
        """设备列表刷新后，按窗口实际打开状态同步按钮文本和样式。"""
        for serial_no in list(self.dict_window_screen.keys()):
            row = self._find_row_by_serial(serial_no)
            if row == -1:
                continue
            self.chg_button2table_dict(row, "show", 1)

        for serial_no in list(self.dict_window_edit.keys()):
            row = self._find_row_by_serial(serial_no)
            if row == -1:
                continue
            self.chg_button2table_dict(row, "edit", 1)
    
    def _start_process_monitoring(self):
        """启动进程状态监控"""
        try:
            self._monitor_timer = QTimer(self)
            self._monitor_timer.timeout.connect(self._check_process_status)
            self._monitor_timer.start(2000)
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
                last_error = status.get("last_error")
                last_status = status.get("last_status") or {}
                last_seen = status.get("last_seen")
                
                # 子进程已退出后，无论 running 标记如何，都要清理 manager 残留记录。
                if not alive:
                    self._update_button_state_safe(row, "operate", -1)
                    if serial_no in self._operation_status:
                        self._operation_status[serial_no] = None
                    if last_error:
                        logger.warning(f"检测到设备 {serial_no} 进程异常退出: {last_error}")
                        self.update_device_status(
                            serial_no, f"异常: {last_error}", abnormal=True
                        )
                    elif last_status.get("action") == "stopped":
                        self.update_device_status(serial_no, "已停止")
                    else:
                        logger.warning(f"检测到设备 {serial_no} 进程异常退出")
                        exitcode = status.get("exitcode")
                        self.update_device_status(
                            serial_no, f"异常退出({exitcode})", abnormal=True
                        )
                    self.process_manager.cleanup_worker(serial_no)
                elif last_error:
                    self.update_device_status(
                        serial_no, f"异常: {last_error}", abnormal=True
                    )
                elif self._is_worker_active(status):
                    fps = last_status.get("fps")
                    frame_count = last_status.get("frame_count")
                    if last_seen and time.time() - last_seen > 10:
                        self.update_device_status(serial_no, "异常: 心跳超时", abnormal=True)
                    elif fps is not None and frame_count is not None:
                        self.update_device_status(
                            serial_no, f"运行 FPS {fps:.1f} / {frame_count}帧"
                        )
                    else:
                        self.update_device_status(serial_no, "运行中")
            
        except Exception as e:
            logger.error(f"检查进程状态失败: {e}")
    
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

        # 停止进程监控定时器（必须在主线程做）
        self._device_scan_stop.set()
        try:
            if hasattr(self, '_monitor_timer') and self._monitor_timer:
                self._monitor_timer.stop()
        except Exception as e:
            logger.error(f"停止监控定时器失败: {e}")

        # 立即关闭所有子窗口（轻量、必须主线程）
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

        self._operation_status.clear()

        # 子进程清理（含 join/terminate）放后台线程，不阻塞 UI 关闭。
        # daemon=False 是故意的：当 QApplication.exec() 返回后，主线程会
        # 等这些非守护线程完成再真正退出，保证子进程都收到了 stop。
        threading.Thread(
            target=self._async_shutdown_children,
            daemon=False,
            name="window-main-shutdown",
        ).start()

        logger.info("主窗口已关闭（子进程清理在后台进行）")
        return super().closeEvent(event)

    def _async_shutdown_children(self) -> None:
        """后台并发停止 worker 子进程与 UDP 服务，避免阻塞 closeEvent。"""
        try:
            self.process_manager.stop_all_workers()
        except Exception as e:
            logger.error(f"停止所有设备进程失败: {e}")
        if self.subprocess:
            try:
                self.subprocess.terminate()
                self.subprocess.join(timeout=3)
                if self.subprocess.is_alive():
                    self.subprocess.kill()
            except Exception as e:
                logger.error(f"关闭UDP服务器失败: {e}")

    # endregion
