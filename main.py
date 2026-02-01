import json
import os
import sys
import traceback


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    project_root = os.path.abspath(os.path.dirname(__file__))
    app_cfg = _read_json(os.path.join(project_root, "config", "app.json"), {"name": "OK-ZhuXian World", "version": "dev"})

    try:
        from PyQt6.QtCore import QCoreApplication, Qt
        from PyQt6 import QtWebEngineWidgets
        from PyQt6.QtWidgets import QApplication

        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        from app.ui.qt_toolbox import start as start_qt

        start_qt(app_name=str(app_cfg.get("name") or "OK-ZhuXian World"), version=str(app_cfg.get("version") or "dev"))
        return
    except Exception:
        traceback.print_exc()

    from app.ui.toolbox import start as start_tk

    start_tk()

if __name__ == "__main__":
    main()
