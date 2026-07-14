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


def opcoes_fatura(cartao_id, data_compra=None, quantidade=15):
    """Lista de faturas candidatas para o usuário escolher ao lançar uma compra.

    Cada item traz o mês da fatura, seu vencimento e se é a sugestão automática
    (a que o cálculo por data+fechamento indicaria). A UI pré-seleciona a sugerida.
    """
    conn = get_connection()
    try:
        cartao = conn.execute(
            "SELECT dia_fechamento, dia_vencimento FROM cartoes WHERE id = ?", (cartao_id,)
        ).fetchone()
    finally:
        conn.close()
    if not cartao:
        return []
    data_compra = data_compra or date.today().strftime("%Y-%m-%d")
    sugerido = _mes_fatura_inicial(data_compra, cartao["dia_fechamento"])
    # começa a lista um mês antes da sugerida, pra permitir "jogar pra fatura atual"
    inicio = _somar_mes(sugerido, -1)
    opcoes = []
    for i in range(quantidade):
        mes = _somar_mes(inicio, i)
        opcoes.append({
            "mes_fatura": mes,
            "vencimento": data_vencimento_fatura(mes, cartao["dia_vencimento"]),
            "sugerido": mes == sugerido,
        })
    return opcoes


# ----------------------------------------------------------------------------
# Cartões
# ----------------------------------------------------------------------------
def listar_cartoes():
    conn = get_connection()
    try:
        cartoes = [dict(r) for r in conn.execute("SELECT * FROM cartoes ORDER BY criado_em")]
        for c in cartoes:
            # limite usado = tudo que já foi comprado - tudo que já foi pago (inclusive parcial)
            comprado = conn.execute(
                "SELECT COALESCE(SUM(valor_cents),0) AS t FROM parcelas_cartao WHERE cartao_id=?",
                (c["id"],),
            ).fetchone()["t"]
            pago = conn.execute(
                "SELECT COALESCE(SUM(valor_cents),0) AS t FROM pagamentos_fatura WHERE cartao_id=?",
                (c["id"],),
            ).fetchone()["t"]
            usado = comprado - pago
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
def _gerar_parcelas(conn, compra_id, cartao_id, valor_total_cents, parcelas_total, mes_inicial):
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


def criar_compra(cartao_id, descricao, categoria_id, valor_total_cents, parcelas_total,
                 data_compra=None, mes_fatura=None):
    """Registra uma compra. Se mes_fatura for informado, a 1ª parcela cai nele;
    senão, calcula pelo dia de fechamento a partir da data da compra."""
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
        mes_inicial = mes_fatura or _mes_fatura_inicial(data_compra, cartao["dia_fechamento"])

        cur = conn.execute(
            "INSERT INTO compras_cartao "
            "(cartao_id, descricao, categoria_id, valor_total_cents, parcelas_total, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (cartao_id, descricao.strip(), categoria_id, valor_total_cents, parcelas_total, agora()),
        )
        compra_id = cur.lastrowid
        _gerar_parcelas(conn, compra_id, cartao_id, valor_total_cents, parcelas_total, mes_inicial)
        conn.commit()
        log.info("Compra #%s no cartão #%s: %s centavos em %sx (1ª fatura %s)",
                  compra_id, cartao_id, valor_total_cents, parcelas_total, mes_inicial)
        return compra_id
    finally:
        conn.close()


def compra_bloqueada_por_pagamento(compra_id):
    """True se alguma fatura que contém parcela desta compra já recebeu pagamento
    (total ou parcial). Nesse caso a compra não pode mais ser editada/excluída,
    para não bagunçar a contabilidade do que já saiu do caixa."""
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM pagamentos_fatura pf "
            "WHERE pf.cartao_id = (SELECT cartao_id FROM compras_cartao WHERE id = ?) "
            "AND pf.mes_fatura IN (SELECT mes_fatura FROM parcelas_cartao WHERE compra_id = ?)",
            (compra_id, compra_id),
        ).fetchone()["n"]
        return n > 0
    finally:
        conn.close()


def atualizar_compra(compra_id, descricao, categoria_id, valor_total_cents, parcelas_total,
                     mes_fatura=None):
    """Corrige uma compra lançada errada, regenerando as parcelas.

    Só permitido enquanto NENHUMA fatura da compra tem pagamento (ver
    compra_bloqueada_por_pagamento): depois de pagar (total ou parcial), a
    transação real já saiu do caixa e alterar a compra deixaria a
    contabilidade inconsistente. Se mes_fatura for informado, move a compra
    para essa fatura; senão mantém a fatura inicial original.
    """
    parcelas_total = max(1, int(parcelas_total))
    valor_total_cents = int(valor_total_cents)
    conn = get_connection()
    try:
        compra = conn.execute(
            "SELECT * FROM compras_cartao WHERE id = ?", (compra_id,)
        ).fetchone()
        if not compra:
            return False
        mes_inicial = mes_fatura or conn.execute(
            "SELECT MIN(mes_fatura) AS m FROM parcelas_cartao WHERE compra_id = ?", (compra_id,)
        ).fetchone()["m"]
        conn.execute(
            "UPDATE compras_cartao SET descricao = ?, categoria_id = ?, "
            "valor_total_cents = ?, parcelas_total = ? WHERE id = ?",
            (descricao.strip(), categoria_id, valor_total_cents, parcelas_total, compra_id),
        )
        conn.execute("DELETE FROM parcelas_cartao WHERE compra_id = ?", (compra_id,))
        _gerar_parcelas(conn, compra_id, compra["cartao_id"], valor_total_cents,
                        parcelas_total, mes_inicial)
        conn.commit()
        log.info("Compra #%s corrigida: %s centavos em %sx (fatura %s)",
                 compra_id, valor_total_cents, parcelas_total, mes_inicial)
        return True
    finally:
        conn.close()


def excluir_compra(compra_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM compras_cartao WHERE id = ?", (compra_id,))
        conn.commit()
        log.info("Compra #%s excluída (parcelas removidas em cascata)", compra_id)
    finally:
        conn.close()


def listar_compras(cartao_id, limite=30):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT cc.*, c.nome AS categoria_nome, c.icone AS categoria_icone, "
            "(SELECT MIN(mes_fatura) FROM parcelas_cartao WHERE compra_id = cc.id) AS mes_fatura "
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
        pago = conn.execute(
            "SELECT COALESCE(SUM(valor_cents),0) AS t FROM pagamentos_fatura "
            "WHERE cartao_id = ? AND mes_fatura = ?",
            (cartao_id, mes),
        ).fetchone()["t"]
        aberto = max(0, total - pago)
        paga = total > 0 and aberto == 0
        return {
            "mes": mes, "total_cents": total, "pago_cents": pago, "aberto_cents": aberto,
            "paga": paga, "parcelas": [dict(r) for r in rows],
        }
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


def pagar_fatura(cartao_id, mes, conta_id, valor_cents=None):
    """Paga a fatura, no todo ou em parte.

    Cria a transação real de saída (afeta o caixa) pelo valor pago e registra
    o pagamento. Se `valor_cents` for None ou >= o que está em aberto, quita a
    fatura inteira; se for menor, é um pagamento parcial e o restante continua
    em aberto na mesma fatura. Quando a fatura fica totalmente quitada, as
    parcelas do mês são marcadas como pagas.
    """
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(valor_cents),0) AS t FROM parcelas_cartao "
            "WHERE cartao_id = ? AND mes_fatura = ?",
            (cartao_id, mes),
        ).fetchone()["t"]
        ja_pago = conn.execute(
            "SELECT COALESCE(SUM(valor_cents),0) AS t FROM pagamentos_fatura "
            "WHERE cartao_id = ? AND mes_fatura = ?",
            (cartao_id, mes),
        ).fetchone()["t"]
        aberto = total - ja_pago
        if aberto <= 0:
            return None

        valor = aberto if valor_cents is None else min(int(valor_cents), aberto)
        if valor <= 0:
            return None

        cartao = conn.execute("SELECT nome FROM cartoes WHERE id = ?", (cartao_id,)).fetchone()
        parcial = valor < aberto
        rotulo = "parcial " if parcial else ""
        cur = conn.execute(
            "INSERT INTO transacoes "
            "(data, descricao, valor_cents, tipo, categoria_id, conta_id, observacao, criado_em) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (date.today().strftime("%Y-%m-%d"),
             f"Pagamento {rotulo}fatura {cartao['nome']} ({mes})",
             valor, "saida", None, conta_id, "", agora()),
        )
        tid = cur.lastrowid
        conn.execute(
            "INSERT INTO pagamentos_fatura "
            "(cartao_id, mes_fatura, valor_cents, conta_id, transacao_id, data, criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (cartao_id, mes, valor, conta_id, tid, date.today().strftime("%Y-%m-%d"), agora()),
        )
        if not parcial:
            conn.execute(
                "UPDATE parcelas_cartao SET paga = 1 WHERE cartao_id = ? AND mes_fatura = ?",
                (cartao_id, mes),
            )
        conn.commit()
        log.info("Fatura do cartão #%s (%s) paga (%s%s centavos, transação #%s)",
                 cartao_id, mes, "parcial " if parcial else "", valor, tid)
        return {"transacao_id": tid, "valor_cents": valor, "aberto_restante_cents": aberto - valor}
    finally:
        conn.close()
