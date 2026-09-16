import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .app import MainWindow
from .i18n import LANGUAGE


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        # Give the taskbar a Chopper identity when launched through pythonw.exe.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Chopper.WavSplitter")

    QLocale.setDefault(QLocale(LANGUAGE))
    app = QApplication(sys.argv)
    # Qt dialogs use the same language as the application, independent of the OS.
    translator = QTranslator(app)
    if translator.load(
        f"qtbase_{LANGUAGE}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)
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
