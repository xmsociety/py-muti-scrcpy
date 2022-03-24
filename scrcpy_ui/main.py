import sys
import scrcpy
import numpy as np
from adbutils import adb

from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QTableWidgetItem, QPushButton, QHBoxLayout, QWidget
from PySide6.QtWidgets import QHeaderView, QAbstractItemView
from PySide6 import QtCore # QTranslator
from PySide6.QtGui import QImage, QPixmap, QMouseEvent


from .ui_main import Ui_MainWindow
from .ui_screen import Ui_Dialog
from .worker import ThreadWorker

app = QApplication([])

class ScreenWindow(QDialog):
    def __init__(self, name='', serial_no='', *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not serial_no:
            return
        self.ui = Ui_Dialog()
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint) # 始终最前显示
        self.ui.setupUi(self)

        self.alive = True
        self.max_width = 600
        self.serial_no = serial_no
        self.device = adb.device(serial=serial_no)
        self.client = scrcpy.Client(
            device=self.device, bitrate=10000000, max_width=640,
        )
        # show
        self.client.add_listener(scrcpy.EVENT_FRAME, self.on_frame)
        # Bind mouse event
        self.ui.label_video.mousePressEvent = self.on_mouse_event(scrcpy.ACTION_DOWN)
        self.ui.label_video.mouseMoveEvent = self.on_mouse_event(scrcpy.ACTION_MOVE)
        self.ui.label_video.mouseReleaseEvent = self.on_mouse_event(scrcpy.ACTION_UP)

        self.setWindowTitle(QtCore.QCoreApplication.translate("Dialog", name, None))
        self.show()
    
    def on_frame(self, frame):
        app.processEvents()
        # print("frame~~~~")
        if frame is not None:
            # ratio = self.max_width / max(self.client.resolution)
            image = QImage(
                frame,
                frame.shape[1],
                frame.shape[0],
                frame.shape[1] * 3,
                QImage.Format_BGR888,
            )
            pix = QPixmap(image)
            # pix.setDevicePixelRatio(1 / ratio)
            self.ui.label_video.setPixmap(pix)
            self.resize(1, 1)
    
    def on_mouse_event(self, action=scrcpy.ACTION_DOWN):
        def handler(evt:  QMouseEvent):
            focused_widget = QApplication.focusWidget()
            if focused_widget is not None:
                focused_widget.clearFocus()
            ratio = self.max_width / max(self.client.resolution)
            self.client.control.touch(
                evt.position().x() / ratio, evt.position().y() / ratio, action
            )

        return handler
    
    def closeEvent(self, _):
        print("close~~~~")
        self.client.stop()
        self.alive = False


    # def showWindow(self):
    #     print("移动", self.x(), self.y())
    #     self.move(int(self.x()), int(self.y()))

class MainWindow(QMainWindow):
    def __init__(self, account_info=None):
        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # setting table
        # self.ui.table_devices.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch) # all same size
        self.ui.table_devices.horizontalHeader().setStretchLastSection(True)
        self.ui.table_devices.setEditTriggers(QAbstractItemView.NoEditTriggers) # noEdit
        self.ui.table_devices.setSelectionMode(QAbstractItemView.NoSelection) # noSelection
        
        self.write_table_demo(data=[
            ["自定义1", "QV7141QF1T", "Runing", "pvp", "self.operate_button_widget", "self.others_buttons_widget"],
            ["自定义2", "123652134125634213", "未启动", "earning", "self.operate_button_widget", "self.others_buttons_widget"]
        ])
        self.dict_client = {}
        self.dict_screen = {}
        self.show()

    def operate_button_widget(self):
        button = QPushButton('启动')
        button.clicked.connect(self.on_click_operate)
        return button

    def others_buttons_widget(self):
        widget = QWidget()
        hlayout = QHBoxLayout()
        button_edit = QPushButton('编辑')
        button_edit.setStyleSheet(''' text-align : center;
                                          background-color : NavajoWhite;
                                          height : 30px;
                                          border-style: outset;
                                          font : 13px  ''')
        button_cpy = QPushButton('复制')
        button_cpy.clicked.connect(self.on_click_cpy)
        button_del = QPushButton('删除')
        button_del.setStyleSheet(''' text-align : center;
                                    background-color : LightCoral;
                                    height : 30px;
                                    border-style: outset;
                                    font : 13px; ''')
        button_show = QPushButton('显示画面')   
        button_show.clicked.connect(self.on_click_show)
        hlayout.addWidget(button_edit)
        hlayout.addWidget(button_cpy)
        hlayout.addWidget(button_del)
        hlayout.addWidget(button_show)
        hlayout.setContentsMargins(5, 2, 5, 2)
        widget.setLayout(hlayout)
        return widget
    
    def get_table_row_info(self):
        """
        ret: tuple[str]
            row, name, serial_no
        """
        button = self.sender()
        if button:
            row = self.ui.table_devices.indexAt(button.parent().pos()).row()
            serial_no = self.ui.table_devices.item(row, 1).text()
            name = self.ui.table_devices.item(row, 0).text()
            return row, name, serial_no

    def on_click_cpy(self):
        pass

    def on_click_show(self):
        row, name, serial_no = self.get_table_row_info()
        win_screen = self.dict_screen.get(serial_no)
        if not win_screen:
            _win_screen = ScreenWindow(name, serial_no)
            self.dict_screen[serial_no] = _win_screen
            self.dict_screen[serial_no].client.start()
            # self.dict_screen[serial_no].showWindow()
        else:
            win_screen.close()
            del self.dict_screen[serial_no]
    
    def on_click_operate(self):
        row, name, serial_no = self.get_table_row_info()
        client = self.dict_client.get(serial_no)
        if not client:
            tworker = ThreadWorker(row, serial_no)
            self.dict_client[serial_no] = tworker
            self.dict_client[serial_no].start()
        else:
            client.stop()
            del self.dict_client[serial_no]

    def write_table_demo(self, data):
        for item in data:
            row = self.ui.table_devices.rowCount()
            self.ui.table_devices.insertRow(row)
            for j, v in enumerate(item):
                if "self." in v:
                    self.ui.table_devices.setCellWidget(row, j, eval(v)())
                else:
                    v = QTableWidgetItem(v)
                    self.ui.table_devices.setItem(row, j, v)

def main():
    # dialog = LoginDialog()
    # if dialog.exec() == QDialog.Accepted:
    #     m = MainWindow(dialog.account_info)
    #     m.show()
    
    # s = ScreenWindow()
    # s.show()
    m = MainWindow()
    m.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
