"""Metas financeiras: objetivos com valor alvo, prazo e progresso.

O valor atual de uma meta soma duas fontes:
1. O que o usuário "guardou" manualmente nela (valor_atual_cents).
2. O valor de mercado dos investimentos vinculados (investimentos.meta_id).

"Quanto guardar por mês" divide o que falta pelos meses até o prazo
(mínimo 1 mês — se o prazo já passou, mostra o que falta inteiro).
"""

from datetime import date

from .db import get_connection, agora
from . import investimentos
from .logger import get_logger

log = get_logger(__name__)


def _meses_restantes(prazo_str):
    if not prazo_str:
        return None
    hoje = date.today()
    prazo = date.fromisoformat(prazo_str)
    meses = (prazo.year - hoje.year) * 12 + (prazo.month - hoje.month)
    return max(0, meses)


def listar_metas():
    conn = get_connection()
    try:
        metas = [dict(r) for r in conn.execute("SELECT * FROM metas ORDER BY criado_em")]
    finally:
        conn.close()
    if not metas:
        return []

    # valor de mercado dos investimentos vinculados, somado por meta
    vinculado = {}
    for a in investimentos.carteira()["ativos"]:
        if a.get("meta_id"):
            vinculado[a["meta_id"]] = vinculado.get(a["meta_id"], 0) + a["valor_mercado_cents"]

    for m in metas:
        m["valor_vinculado_cents"] = vinculado.get(m["id"], 0)
        total = m["valor_atual_cents"] + m["valor_vinculado_cents"]
        m["valor_total_cents"] = total
        m["falta_cents"] = max(0, m["valor_alvo_cents"] - total)
        m["progresso_pct"] = min(100.0, total / m["valor_alvo_cents"] * 100) if m["valor_alvo_cents"] else 0
        meses = _meses_restantes(m["prazo"])
        m["meses_restantes"] = meses
        m["por_mes_cents"] = round(m["falta_cents"] / max(1, meses or 1))
    return metas


def criar_meta(nome, valor_alvo_cents, prazo=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO metas (nome, valor_alvo_cents, prazo, valor_atual_cents, criado_em) "
            "VALUES (?,?,?,0,?)",
            (nome.strip(), int(valor_alvo_cents), prazo, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def guardar_na_meta(meta_id, valor_cents):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE metas SET valor_atual_cents = valor_atual_cents + ? WHERE id = ?",
            (int(valor_cents), meta_id),
        )
        conn.commit()
        log.info("Guardado %s centavos na meta #%s", valor_cents, meta_id)
    finally:
        conn.close()


def excluir_meta(meta_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE investimentos SET meta_id = NULL WHERE meta_id = ?", (meta_id,))
        conn.execute("DELETE FROM metas WHERE id = ?", (meta_id,))
        conn.commit()
    finally:
        conn.close()
