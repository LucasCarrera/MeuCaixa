"""Contas a pagar/receber e recorrências (salário, aluguel, assinaturas...).

Uma recorrência gera contas_pagar automaticamente: materializar() roda na
abertura do app e, para cada recorrência ativa cuja proxima_data já chegou,
cria a conta a pagar e avança a data conforme a frequência — em loop, para
cobrir o caso de o app ficar dias/semanas fechado.

Pagar uma conta cria a transação de verdade (aí sim afeta o caixa) e marca
pago=1.
"""

import calendar
from datetime import date, timedelta

from .db import get_connection, agora
from .logger import get_logger

log = get_logger(__name__)


def _avancar_data(data_str, frequencia):
    d = date.fromisoformat(data_str)
    if frequencia == "semanal":
        return (d + timedelta(days=7)).isoformat()
    meses = 12 if frequencia == "anual" else 1
    mes = d.month + meses
    ano = d.year + (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia).isoformat()


def materializar():
    """Gera as contas a pagar previstas até hoje. Chamado na abertura do app."""
    hoje = date.today().isoformat()
    conn = get_connection()
    try:
        geradas = 0
        rows = conn.execute(
            "SELECT * FROM recorrencias WHERE ativo = 1 AND proxima_data <= ?", (hoje,)
        ).fetchall()
        for r in rows:
            proxima = r["proxima_data"]
            # limite de segurança: nunca gerar mais de 60 ocorrências de uma vez
            for _ in range(60):
                if proxima > hoje:
                    break
                conn.execute(
                    "INSERT INTO contas_pagar "
                    "(descricao, valor_cents, tipo, vencimento, pago, categoria_id, conta_id, recorrencia_id, criado_em) "
                    "VALUES (?,?,?,?,0,?,?,?,?)",
                    (r["descricao"], r["valor_cents"], r["tipo"], proxima,
                     r["categoria_id"], r["conta_id"], r["id"], agora()),
                )
                geradas += 1
                proxima = _avancar_data(proxima, r["frequencia"])
            conn.execute(
                "UPDATE recorrencias SET proxima_data = ? WHERE id = ?", (proxima, r["id"])
            )
        conn.commit()
        if geradas:
            log.info("%s conta(s) a pagar gerada(s) por recorrência", geradas)
        return geradas
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Recorrências
# ----------------------------------------------------------------------------
def listar_recorrencias():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT r.*, c.nome AS categoria_nome, c.icone AS categoria_icone, "
            "ct.nome AS conta_nome "
            "FROM recorrencias r "
            "LEFT JOIN categorias c ON c.id = r.categoria_id "
            "LEFT JOIN contas ct ON ct.id = r.conta_id "
            "ORDER BY r.proxima_data",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def criar_recorrencia(descricao, valor_cents, tipo, frequencia, proxima_data,
                       categoria_id=None, conta_id=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO recorrencias "
            "(descricao, valor_cents, tipo, frequencia, proxima_data, categoria_id, conta_id, ativo, criado_em) "
            "VALUES (?,?,?,?,?,?,?,1,?)",
            (descricao.strip(), int(valor_cents), tipo, frequencia, proxima_data,
             categoria_id, conta_id, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def excluir_recorrencia(recorrencia_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM recorrencias WHERE id = ?", (recorrencia_id,))
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Contas a pagar/receber
# ----------------------------------------------------------------------------
def listar_contas_pagar(incluir_pagas=False, limite=50):
    conn = get_connection()
    try:
        sql = (
            "SELECT cp.*, c.nome AS categoria_nome, c.icone AS categoria_icone "
            "FROM contas_pagar cp LEFT JOIN categorias c ON c.id = cp.categoria_id "
        )
        if not incluir_pagas:
            sql += "WHERE cp.pago = 0 "
        sql += "ORDER BY cp.vencimento LIMIT ?"
        return [dict(r) for r in conn.execute(sql, (limite,)).fetchall()]
    finally:
        conn.close()


def criar_conta_pagar(descricao, valor_cents, tipo, vencimento, categoria_id=None, conta_id=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO contas_pagar "
            "(descricao, valor_cents, tipo, vencimento, pago, categoria_id, conta_id, criado_em) "
            "VALUES (?,?,?,?,0,?,?,?)",
            (descricao.strip(), int(valor_cents), tipo, vencimento, categoria_id, conta_id, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def pagar_conta(conta_pagar_id, conta_id):
    """Efetiva a conta: cria a transação real e marca como paga."""
    conn = get_connection()
    try:
        cp = conn.execute(
            "SELECT * FROM contas_pagar WHERE id = ? AND pago = 0", (conta_pagar_id,)
        ).fetchone()
        if not cp:
            return None
        cur = conn.execute(
            "INSERT INTO transacoes "
            "(data, descricao, valor_cents, tipo, categoria_id, conta_id, observacao, criado_em) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (date.today().isoformat(), cp["descricao"], cp["valor_cents"], cp["tipo"],
             cp["categoria_id"], conta_id, "", agora()),
        )
        tid = cur.lastrowid
        conn.execute("UPDATE contas_pagar SET pago = 1 WHERE id = ?", (conta_pagar_id,))
        conn.commit()
        log.info("Conta a pagar #%s efetivada: transação #%s", conta_pagar_id, tid)
        return {"transacao_id": tid}
    finally:
        conn.close()


def excluir_conta_pagar(conta_pagar_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contas_pagar WHERE id = ?", (conta_pagar_id,))
        conn.commit()
    finally:
        conn.close()


def proximos_vencimentos(limite=5):
    return listar_contas_pagar(incluir_pagas=False, limite=limite)
