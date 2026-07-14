"""Exportação e apagamento completo dos dados do usuário.

Exportar gera um JSON com todas as tabelas em data/exportacoes/ — útil como
backup ou pra levar os dados pra outro lugar. Apagar zera o banco inteiro e
recria os padrões (categorias, ajustes, conta Carteira), voltando o app ao
estado de primeira abertura.
"""

import json
import os
from datetime import datetime

from .db import get_connection, init_db, BASE_DIR
from .logger import get_logger

log = get_logger(__name__)

EXPORT_DIR = os.path.join(BASE_DIR, "data", "exportacoes")

TABELAS = [
    "ajustes", "categorias", "contas", "transacoes", "transferencias",
    "cartoes", "compras_cartao", "parcelas_cartao", "investimentos", "aportes",
    "metas", "recorrencias", "contas_pagar", "orcamentos", "aprendizado", "alertas",
]


def exportar_tudo():
    """Grava um JSON com todas as tabelas e retorna o caminho do arquivo."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = get_connection()
    try:
        dump = {"exportado_em": datetime.now().isoformat(timespec="seconds"), "tabelas": {}}
        for t in TABELAS:
            dump["tabelas"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    finally:
        conn.close()

    nome = f"MeuCaixa_dados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    caminho = os.path.join(EXPORT_DIR, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)
    log.info("Dados exportados para %s", caminho)
    return caminho


def apagar_tudo():
    """Apaga TODOS os dados e recria os padrões. Irreversível."""
    conn = get_connection()
    try:
        # filhas antes das mães, por causa das foreign keys
        for t in ["aportes", "investimentos", "parcelas_cartao", "compras_cartao",
                  "cartoes", "transferencias", "transacoes", "contas_pagar",
                  "recorrencias", "metas", "orcamentos", "aprendizado", "alertas",
                  "categorias", "contas", "ajustes"]:
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
    init_db()  # recria categorias padrão, ajustes e a conta Carteira zerada
    log.warning("TODOS os dados foram apagados a pedido do usuário; app resetado")
