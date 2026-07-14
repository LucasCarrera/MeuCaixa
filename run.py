"""MeuCaixa — ponto de entrada.

Abre uma janela de desktop (via pywebview) carregando a interface e conectando
a ponte Python. Rode com:  python run.py
"""

import os
import webview

from backend.db import init_db
from backend.api import Api
from backend.logger import setup_logging, get_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(BASE_DIR, "frontend", "index.html")

log = get_logger("run")


def main():
    setup_logging()
    log.info("Iniciando MeuCaixa")
    try:
        init_db()
        api = Api()
        webview.create_window(
            "MeuCaixa — seu dinheiro, sem complicação",
            INDEX,
            js_api=api,
            width=1120,
            height=760,
            min_size=(900, 640),
            background_color="#EEF2EF",
        )
        webview.start()
    except Exception:
        log.exception("Erro fatal ao iniciar o MeuCaixa")
        raise
    finally:
        log.info("MeuCaixa encerrado")


if __name__ == "__main__":
    main()
