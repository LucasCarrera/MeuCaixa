"""Carteira de investimentos: ativos, aportes e rentabilidade.

Cada aporte pode informar quantidade_comprada (ações, FIIs, cripto) — nesse
caso a quantidade e o preço médio do ativo são recalculados (média
ponderada). Aportes sem quantidade (típico de renda fixa) só somam ao
valor investido, sem afetar preço médio/quantidade.

A rentabilidade compara o valor investido (soma dos aportes) com o valor
de mercado: quantidade × cotação ao vivo quando disponível, ou o próprio
valor investido quando não há cotação (renda fixa, ou ação/FII sem preço
disponível agora) — nesse caso a rentabilidade aparece como 0 até haver
cotação.
"""

from datetime import date

from .db import get_connection, agora
from . import cotacoes
from .logger import get_logger

log = get_logger(__name__)


def listar_investimentos():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM investimentos ORDER BY criado_em").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def criar_investimento(tipo, nome, corretora="", ticker=None, indexador="", vencimento=None, meta_id=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO investimentos "
            "(tipo, nome, corretora, ticker, quantidade, preco_medio_cents, indexador, vencimento, meta_id, criado_em) "
            "VALUES (?,?,?,?,0,0,?,?,?,?)",
            (tipo, nome.strip(), corretora, ticker, indexador, vencimento, meta_id, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def excluir_investimento(investimento_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM investimentos WHERE id = ?", (investimento_id,))
        conn.commit()
    finally:
        conn.close()


def registrar_aporte(investimento_id, valor_cents, quantidade_comprada=None, data_str=None):
    data_str = data_str or date.today().strftime("%Y-%m-%d")
    valor_cents = int(valor_cents)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO aportes (investimento_id, valor_cents, quantidade_comprada, data, criado_em) "
            "VALUES (?,?,?,?,?)",
            (investimento_id, valor_cents, quantidade_comprada, data_str, agora()),
        )
        if quantidade_comprada:
            inv = conn.execute(
                "SELECT quantidade, preco_medio_cents FROM investimentos WHERE id = ?", (investimento_id,)
            ).fetchone()
            valor_atual_total = inv["quantidade"] * inv["preco_medio_cents"]
            nova_qtd = inv["quantidade"] + quantidade_comprada
            novo_preco_medio = int(round((valor_atual_total + valor_cents) / nova_qtd)) if nova_qtd else 0
            conn.execute(
                "UPDATE investimentos SET quantidade = ?, preco_medio_cents = ? WHERE id = ?",
                (nova_qtd, novo_preco_medio, investimento_id),
            )
        conn.commit()
        log.info("Aporte de %s centavos no investimento #%s", valor_cents, investimento_id)
    finally:
        conn.close()


def _valor_investido_cents(conn, investimento_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(valor_cents),0) AS total FROM aportes WHERE investimento_id = ?",
        (investimento_id,),
    ).fetchone()
    return row["total"]


def carteira():
    """Retorna a carteira consolidada: totais, distribuição por tipo e cada ativo."""
    conn = get_connection()
    try:
        invs = [dict(r) for r in conn.execute("SELECT * FROM investimentos ORDER BY criado_em")]

        tickers_b3 = [i["ticker"] for i in invs if i["tipo"] in ("acao", "fii") and i["ticker"]]
        ids_cripto = [i["ticker"] for i in invs if i["tipo"] == "cripto" and i["ticker"]]
        precos_b3 = cotacoes.buscar_acoes_fiis(tickers_b3) if tickers_b3 else {}
        precos_cripto = cotacoes.buscar_cripto(ids_cripto) if ids_cripto else {}

        ativos = []
        total_investido = 0
        total_mercado = 0
        por_tipo = {}

        for inv in invs:
            investido = _valor_investido_cents(conn, inv["id"])

            preco_atual = None
            if inv["tipo"] in ("acao", "fii") and inv["ticker"] in precos_b3:
                preco_atual = precos_b3[inv["ticker"]]
            elif inv["tipo"] == "cripto" and inv["ticker"] in precos_cripto:
                preco_atual = precos_cripto[inv["ticker"]]

            if preco_atual is not None and inv["quantidade"] > 0:
                valor_mercado_cents = int(round(inv["quantidade"] * preco_atual * 100))
            else:
                valor_mercado_cents = investido

            total_investido += investido
            total_mercado += valor_mercado_cents
            por_tipo[inv["tipo"]] = por_tipo.get(inv["tipo"], 0) + valor_mercado_cents

            rentabilidade_cents = valor_mercado_cents - investido
            ativos.append({
                **inv,
                "valor_investido_cents": investido,
                "valor_mercado_cents": valor_mercado_cents,
                "rentabilidade_cents": rentabilidade_cents,
                "rentabilidade_pct": (rentabilidade_cents / investido * 100) if investido else 0,
                "preco_atual_cents": int(round(preco_atual * 100)) if preco_atual is not None else None,
            })

        rentabilidade_total = total_mercado - total_investido
        return {
            "total_investido_cents": total_investido,
            "total_mercado_cents": total_mercado,
            "rentabilidade_cents": rentabilidade_total,
            "rentabilidade_pct": (rentabilidade_total / total_investido * 100) if total_investido else 0,
            "por_tipo": [{"tipo": k, "valor_cents": v} for k, v in por_tipo.items() if v > 0],
            "ativos": ativos,
        }
    finally:
        conn.close()
