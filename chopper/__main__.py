import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        # Give the taskbar a Chopper identity when launched through pythonw.exe.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Chopper.WavSplitter")

    app = QApplication(sys.argv)
    app.setApplicationName("Chopper")
    app.setOrganizationName("Chopper")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "chopper.ico")))
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        path = sys.argv[1]
        QTimer.singleShot(0, lambda: window.controller.open_path(path))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
