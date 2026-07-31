"""Punto de entrada para la app de macOS empaquetada con PyInstaller.

Arranca el servidor local (los datos nunca salen del ordenador) y abre el
navegador por defecto en esa dirección. Pensado para ejecutarse con doble
clic desde el .app, sin terminal visible: por eso los errores se escriben
en un fichero de log en vez de a stdout (que nadie vería).
"""
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _log_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path.home()
    base.mkdir(parents=True, exist_ok=True)
    return base / "CojointAnalyzer.log"


def _find_free_port(start: int = 8756, tries: int = 30) -> int:
    port = start
    for _ in range(tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start


def main() -> None:
    logging.basicConfig(
        filename=_log_path(),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.info("Iniciando Cojoint Analyzer…")

    from app.main import app  # importado aquí para que cualquier error de arranque quede en el log

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    def open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    logging.info("Servidor en %s", url)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    except Exception:
        logging.exception("El servidor terminó con un error")
        raise


if __name__ == "__main__":
    main()
