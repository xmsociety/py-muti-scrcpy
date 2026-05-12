import sys

from PySide6.QtWidgets import QApplication

from .window_main import MainWindow


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    m = MainWindow()
    m.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
