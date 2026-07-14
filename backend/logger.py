"""Configuração central de logging do MeuCaixa.

O app roda como janela desktop (pywebview), então normalmente não há console
visível — o arquivo de log em data/logs/ é o único jeito de investigar um
problema depois que ele aconteceu.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .db import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
LOG_PATH = os.path.join(LOG_DIR, "meucaixa.log")

_configurado = False


def setup_logging(nivel=None):
    """Configura o logger raiz 'meucaixa' (arquivo rotativo + console). Idempotente."""
    global _configurado
    if _configurado:
        return
    os.makedirs(LOG_DIR, exist_ok=True)

    nivel = nivel or os.environ.get("MEUCAIXA_LOG_LEVEL", "INFO")
    formato = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    arquivo = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    arquivo.setFormatter(formato)

    # no Windows o console às vezes usa cp1252, que quebra com emoji — força utf-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    console = logging.StreamHandler()
    console.setFormatter(formato)

    raiz = logging.getLogger("meucaixa")
    raiz.setLevel(nivel)
    raiz.addHandler(arquivo)
    raiz.addHandler(console)
    raiz.propagate = False

    _configurado = True


def get_logger(nome):
    """Logger filho de 'meucaixa', ex.: get_logger(__name__) -> meucaixa.backend.api"""
    return logging.getLogger(f"meucaixa.{nome}")
