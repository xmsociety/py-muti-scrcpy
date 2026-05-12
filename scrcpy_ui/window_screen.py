import numpy as np
from loguru import logger
from PySide6 import QtCore  # QTranslator
from PySide6.QtCore import Signal
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QDialog

import scrcpy
from workers import ThreadWorker

from .qt_keymap import qt_keycode_to_android
from .ui_screen import Ui_Dialog


class ScreenWindow(QDialog):
    signal_frame = Signal(np.ndarray)

    def __init__(self, name, row, serial_no, signal_screen_close=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._close_notified = False
        if not serial_no:
            return
        self.signal_screen_close = signal_screen_close
        self.row = row
        self.serial_no = serial_no
        self.ui = Ui_Dialog()
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)  # 始终最前显示
        # 关闭即销毁，配合 MainWindow 的 destroyed 信号兜底清理 dict_window_screen，
        # 避免外部强杀 / closeEvent 异常时残留旧引用导致窗口"再也开不出来"。
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.ui.setupUi(self)

        self.max_width = 720
        self.serial_no = serial_no
        # # show
        # self.client.add_listener(scrcpy.EVENT_FRAME, self.on_frame)

        # show
        self.signal_frame.connect(self.on_frame)
        # Bind mouse event
        self.ui.label_video.mousePressEvent = self.on_mouse_event(scrcpy.ACTION_DOWN)
        self.ui.label_video.mouseMoveEvent = self.on_mouse_event(scrcpy.ACTION_MOVE)
        self.ui.label_video.mouseReleaseEvent = self.on_mouse_event(scrcpy.ACTION_UP)

        # Bind keyboard event：在 ScreenWindow 获焦时把按键转发到设备
        self.keyPressEvent = self.on_key_event(scrcpy.ACTION_DOWN)
        self.keyReleaseEvent = self.on_key_event(scrcpy.ACTION_UP)

        self.setWindowTitle(QtCore.QCoreApplication.translate("Dialog", name, None))
        self.tworker = ThreadWorker(0, self.serial_no, signal=self.signal_frame)
        self.show()

    def on_frame(self, frame):
        if frame is not None:
            frame = np.ascontiguousarray(frame)
            # ratio = self.max_width / max(self.client.resolution)
            image = QImage(
                frame,
                frame.shape[1],
                frame.shape[0],
                frame.shape[1] * 3,
                QImage.Format_BGR888,
            )
            pix = QPixmap(image.copy())
            # pix.setDevicePixelRatio(1 / ratio)
            self.ui.label_video.setPixmap(pix)
            self.resize(1, 1)

    def on_mouse_event(self, action=scrcpy.ACTION_DOWN):
        def handler(evt: QMouseEvent):
            client = self.tworker.client
            if not client.alive or client.control_socket is None or client.resolution is None:
                return
            focused_widget = QApplication.focusWidget()
            if focused_widget is not None:
                focused_widget.clearFocus()
            ratio = self.max_width / max(client.resolution)
            client.control.touch(
                evt.position().x() - (self.ui.label_video.geometry().x() / 2) / ratio,
                evt.position().y() - (self.ui.label_video.geometry().y() / 2) / ratio,
                action,
            )

        return handler

    def on_key_event(self, action=scrcpy.ACTION_DOWN):
        def handler(evt: QKeyEvent):
            client = self.tworker.client
            if not client.alive or client.control_socket is None:
                return
            code = qt_keycode_to_android(evt.key())
            if code != -1:
                client.control.keycode(code, action)

        return handler

    def reject(self):
        logger.debug(f"ScreenWindow {self.serial_no} reject -> close")
        self.close()

    def closeEvent(self, _):
        logger.debug(f"ScreenWindow {self.serial_no} closeEvent")
        if self._close_notified:
            return

        self._close_notified = True
        try:
            self.tworker.stop()
        except Exception as e:
            logger.warning(f"停止设备 {self.serial_no} 的画面线程失败: {e}")
        finally:
            if self.signal_screen_close:
                self.signal_screen_close.emit(self.row, self.serial_no)

