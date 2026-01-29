import asyncio
import json
import threading
from pathlib import Path

from webapp.backend import Backend


def _load_app_config() -> dict:
    project_root = Path(__file__).resolve().parent.parent
    cfg_path = project_root / "config" / "app.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {"name": "OK-ZhuXian World", "version": "dev"}


def main() -> None:
    cfg = _load_app_config()
    title = f"{cfg.get('name', 'OK-ZhuXian World')} v{cfg.get('version', 'dev')}"

    backend = Backend()

    backend_thread = threading.Thread(target=lambda: asyncio.run(backend.serve()), daemon=True)
    backend_thread.start()

    import webview

    webview.create_window(
        title=title,
        url=backend.urls.http_url,
        width=1180,
        height=720,
        min_size=(980, 620),
        background_color="#0b0f14",
    )
    try:
        webview.start()
    finally:
        backend.stop()


if __name__ == "__main__":
    main()

