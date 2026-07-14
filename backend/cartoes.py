"""Cartões de crédito: compras parceladas, faturas e limite.

Uma compra parcelada vira N linhas em parcelas_cartao, uma por mês de fatura.
A compra só afeta o caixa quando a fatura é paga (pagar_fatura cria a
transação de verdade). Até lá, ela só consome limite do cartão.

Regra de fechamento: se o dia da compra for depois do dia de fechamento do
cartão, a 1ª parcela cai na fatura do mês seguinte; senão, na do mesmo mês.
A fatura de um mês de referência X vence no mês seguinte (X+1), no dia de
vencimento do cartão — como na maioria dos cartões reais.
"""

from datetime import date

from .db import get_connection, agora
from .logger import get_logger

log = get_logger(__name__)


# ----------------------------------------------------------------------------
# Datas de fatura
# ----------------------------------------------------------------------------
def _somar_mes(ano_mes, n):
    ano, mes = map(int, ano_mes.split("-"))
    mes += n
    ano += (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    return f"{ano:04d}-{mes:02d}"


def _mes_fatura_inicial(data_compra_str, dia_fechamento):
    dia = int(data_compra_str[8:10])
    ym = data_compra_str[:7]
    return _somar_mes(ym, 1) if dia > dia_fechamento else ym


def data_vencimento_fatura(mes_fatura, dia_vencimento):
    return f"{_somar_mes(mes_fatura, 1)}-{int(dia_vencimento):02d}"


# ----------------------------------------------------------------------------
# Cartões
# ----------------------------------------------------------------------------
def listar_cartoes():
    conn = get_connection()
    try:
        cartoes = [dict(r) for r in conn.execute("SELECT * FROM cartoes ORDER BY criado_em")]
        for c in cartoes:
            usado = conn.execute(
                "SELECT COALESCE(SUM(valor_cents),0) AS t FROM parcelas_cartao WHERE cartao_id=? AND paga=0",
                (c["id"],),
            ).fetchone()["t"]
            c["limite_usado_cents"] = usado
            c["limite_disponivel_cents"] = c["limite_cents"] - usado
        return cartoes
    finally:
        conn.close()


def criar_cartao(nome, limite_cents, dia_fechamento, dia_vencimento, cor="#6B4FBB", icone="💳"):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO cartoes (nome, limite_cents, dia_fechamento, dia_vencimento, cor, icone, criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (nome.strip(), int(limite_cents), int(dia_fechamento), int(dia_vencimento), cor, icone, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def atualizar_cartao(cartao_id, nome=None, limite_cents=None, dia_fechamento=None,
                      dia_vencimento=None, cor=None, icone=None):
    conn = get_connection()
    try:
        campos, valores = [], []
        if nome is not None:
            campos.append("nome = ?"); valores.append(nome.strip())
        if limite_cents is not None:
            campos.append("limite_cents = ?"); valores.append(int(limite_cents))
        if dia_fechamento is not None:
            campos.append("dia_fechamento = ?"); valores.append(int(dia_fechamento))
        if dia_vencimento is not None:
            campos.append("dia_vencimento = ?"); valores.append(int(dia_vencimento))
        if cor is not None:
            campos.append("cor = ?"); valores.append(cor)
        if icone is not None:
            campos.append("icone = ?"); valores.append(icone)
        if not campos:
            return
        valores.append(cartao_id)
        conn.execute(f"UPDATE cartoes SET {', '.join(campos)} WHERE id = ?", valores)
        conn.commit()
    finally:
        conn.close()


def cartao_tem_compras(cartao_id):
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM compras_cartao WHERE cartao_id = ?", (cartao_id,)
        ).fetchone()["n"]
        return n > 0
    finally:
        conn.close()


def excluir_cartao(cartao_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM cartoes WHERE id = ?", (cartao_id,))
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Compras parceladas
# ----------------------------------------------------------------------------
def criar_compra(cartao_id, descricao, categoria_id, valor_total_cents, parcelas_total, data_compra=None):
    data_compra = data_compra or date.today().strftime("%Y-%m-%d")
    parcelas_total = max(1, int(parcelas_total))
    valor_total_cents = int(valor_total_cents)
    conn = get_connection()
    try:
        cartao = conn.execute(
            "SELECT dia_fechamento FROM cartoes WHERE id = ?", (cartao_id,)
        ).fetchone()
        if not cartao:
            return None
        mes_inicial = _mes_fatura_inicial(data_compra, cartao["dia_fechamento"])

        cur = conn.execute(
            "INSERT INTO compras_cartao "
            "(cartao_id, descricao, categoria_id, valor_total_cents, parcelas_total, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (cartao_id, descricao.strip(), categoria_id, valor_total_cents, parcelas_total, agora()),
        )
        compra_id = cur.lastrowid

        base = valor_total_cents // parcelas_total
        resto = valor_total_cents - base * parcelas_total
        for i in range(parcelas_total):
            valor = base + resto if i == parcelas_total - 1 else base
            mes_fatura = _somar_mes(mes_inicial, i)
            conn.execute(
                "INSERT INTO parcelas_cartao (compra_id, cartao_id, numero, valor_cents, mes_fatura, paga) "
                "VALUES (?,?,?,?,?,0)",
                (compra_id, cartao_id, i + 1, valor, mes_fatura),
            )
        conn.commit()
        log.info("Compra #%s no cartão #%s: %s centavos em %sx (1ª fatura %s)",
                  compra_id, cartao_id, valor_total_cents, parcelas_total, mes_inicial)
        return compra_id
    finally:
        conn.close()


def listar_compras(cartao_id, limite=30):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT cc.*, c.nome AS categoria_nome, c.icone AS categoria_icone "
            "FROM compras_cartao cc LEFT JOIN categorias c ON c.id = cc.categoria_id "
            "WHERE cc.cartao_id = ? ORDER BY cc.criado_em DESC LIMIT ?",
            (cartao_id, limite),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Fatura
# ----------------------------------------------------------------------------
def fatura(cartao_id, mes=None):
    mes = mes or date.today().strftime("%Y-%m")
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT pc.*, cc.descricao, cc.categoria_id, cc.parcelas_total, "
            "c.nome AS categoria_nome, c.icone AS categoria_icone "
            "FROM parcelas_cartao pc "
            "JOIN compras_cartao cc ON cc.id = pc.compra_id "
            "LEFT JOIN categorias c ON c.id = cc.categoria_id "
            "WHERE pc.cartao_id = ? AND pc.mes_fatura = ? "
            "ORDER BY cc.criado_em, pc.numero",
            (cartao_id, mes),
        ).fetchall()
        total = sum(r["valor_cents"] for r in rows)
        paga = all(r["paga"] for r in rows) if rows else False
        return {"mes": mes, "total_cents": total, "paga": paga, "parcelas": [dict(r) for r in rows]}
    finally:
        conn.close()


def proxima_fatura_em_aberto(cartao_id):
    """Menor mes_fatura com parcela ainda não paga — a próxima a vencer."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MIN(mes_fatura) AS mes FROM parcelas_cartao WHERE cartao_id = ? AND paga = 0",
            (cartao_id,),
        ).fetchone()
        return row["mes"]
    finally:
        conn.close()


def pagar_fatura(cartao_id, mes, conta_id):
    """Cria a transação real de saída (a fatura afetando o caixa) e marca as parcelas do mês como pagas."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(valor_cents),0) AS total FROM parcelas_cartao "
            "WHERE cartao_id = ? AND mes_fatura = ? AND paga = 0",
            (cartao_id, mes),
        ).fetchone()
        total = row["total"]
        if total <= 0:
            return None
        cartao = conn.execute("SELECT nome FROM cartoes WHERE id = ?", (cartao_id,)).fetchone()
        cur = conn.execute(
            "INSERT INTO transacoes "
            "(data, descricao, valor_cents, tipo, categoria_id, conta_id, observacao, criado_em) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (date.today().strftime("%Y-%m-%d"), f"Fatura {cartao['nome']} ({mes})",
             total, "saida", None, conta_id, "", agora()),
        )
        tid = cur.lastrowid
        conn.execute(
            "UPDATE parcelas_cartao SET paga = 1 WHERE cartao_id = ? AND mes_fatura = ? AND paga = 0",
            (cartao_id, mes),
        )
        conn.commit()
        log.info("Fatura do cartão #%s (%s) paga: transação #%s, %s centavos", cartao_id, mes, tid, total)
        return {"transacao_id": tid, "total_cents": total}
    finally:
        conn.close()
