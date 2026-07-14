"""Camada de acesso a dados: transações, categorias, orçamentos, ajustes.

Regra de ouro: nada de SQL espalhado pela aplicação. Tudo passa por aqui.
Dinheiro entra e sai desta camada em CENTAVOS (int).
"""

from datetime import date
from .db import get_connection, agora


# ----------------------------------------------------------------------------
# Ajustes (configurações do usuário)
# ----------------------------------------------------------------------------
def get_ajuste(chave, padrao=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT valor FROM ajustes WHERE chave = ?", (chave,)).fetchone()
        return row["valor"] if row else padrao
    finally:
        conn.close()


def set_ajuste(chave, valor):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ajustes (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, str(valor)),
        )
        conn.commit()
    finally:
        conn.close()


def get_todos_ajustes():
    conn = get_connection()
    try:
        return {r["chave"]: r["valor"] for r in conn.execute("SELECT chave, valor FROM ajustes")}
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Categorias
# ----------------------------------------------------------------------------
def listar_categorias(tipo=None):
    """Retorna categorias ordenadas com cada subcategoria logo após seu pai."""
    conn = get_connection()
    try:
        sql = (
            "SELECT c.*, p.nome AS pai_nome FROM categorias c "
            "LEFT JOIN categorias p ON p.id = c.categoria_pai_id"
        )
        params = []
        if tipo:
            sql += " WHERE c.tipo = ?"
            params.append(tipo)
        sql += " ORDER BY c.tipo DESC, COALESCE(p.nome, c.nome), (c.categoria_pai_id IS NOT NULL), c.nome"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def criar_categoria(nome, tipo, icone="💰", cor="#1B7A5A", categoria_pai_id=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO categorias (nome, tipo, icone, cor, padrao, categoria_pai_id) "
            "VALUES (?,?,?,?,0,?)",
            (nome.strip(), tipo, icone, cor, categoria_pai_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def excluir_categoria(cat_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM categorias WHERE id = ? AND padrao = 0", (cat_id,))
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Contas
# ----------------------------------------------------------------------------
_SALDO_ATUAL_SQL = (
    "c.saldo_inicial_cents"
    "  + COALESCE((SELECT SUM(CASE WHEN t.tipo='entrada' THEN t.valor_cents ELSE -t.valor_cents END)"
    "              FROM transacoes t WHERE t.conta_id = c.id), 0)"
    "  - COALESCE((SELECT SUM(valor_cents) FROM transferencias WHERE conta_origem_id = c.id), 0)"
    "  + COALESCE((SELECT SUM(valor_cents) FROM transferencias WHERE conta_destino_id = c.id), 0)"
)


def listar_contas():
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT c.*, ({_SALDO_ATUAL_SQL}) AS saldo_atual_cents FROM contas c ORDER BY c.criado_em"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def criar_conta(nome, tipo, saldo_inicial_cents=0, cor="#1B7A5A", icone="💼"):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO contas (nome, tipo, saldo_inicial_cents, cor, icone, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (nome.strip(), tipo, int(saldo_inicial_cents), cor, icone, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def atualizar_conta(conta_id, nome=None, tipo=None, saldo_inicial_cents=None, cor=None, icone=None):
    conn = get_connection()
    try:
        campos, valores = [], []
        if nome is not None:
            campos.append("nome = ?"); valores.append(nome.strip())
        if tipo is not None:
            campos.append("tipo = ?"); valores.append(tipo)
        if saldo_inicial_cents is not None:
            campos.append("saldo_inicial_cents = ?"); valores.append(int(saldo_inicial_cents))
        if cor is not None:
            campos.append("cor = ?"); valores.append(cor)
        if icone is not None:
            campos.append("icone = ?"); valores.append(icone)
        if not campos:
            return
        valores.append(conta_id)
        conn.execute(f"UPDATE contas SET {', '.join(campos)} WHERE id = ?", valores)
        conn.commit()
    finally:
        conn.close()


def conta_tem_movimentacao(conta_id):
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM transacoes WHERE conta_id = ?", (conta_id,)
        ).fetchone()["n"]
        m = conn.execute(
            "SELECT COUNT(*) AS n FROM transferencias WHERE conta_origem_id = ? OR conta_destino_id = ?",
            (conta_id, conta_id),
        ).fetchone()["n"]
        return (n + m) > 0
    finally:
        conn.close()


def excluir_conta(conta_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contas WHERE id = ?", (conta_id,))
        conn.commit()
    finally:
        conn.close()


def criar_transferencia(conta_origem_id, conta_destino_id, valor_cents, data_str, descricao=""):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO transferencias "
            "(conta_origem_id, conta_destino_id, valor_cents, data, descricao, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (conta_origem_id, conta_destino_id, int(valor_cents), data_str, descricao, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_transferencias(limite=30):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT tr.*, "
            "co.nome AS origem_nome, co.icone AS origem_icone, "
            "cd.nome AS destino_nome, cd.icone AS destino_icone "
            "FROM transferencias tr "
            "JOIN contas co ON co.id = tr.conta_origem_id "
            "JOIN contas cd ON cd.id = tr.conta_destino_id "
            "ORDER BY tr.data DESC, tr.id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Transações
# ----------------------------------------------------------------------------
def adicionar_transacao(data_str, descricao, valor_cents, tipo, categoria_id, conta_id=None, observacao=""):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO transacoes "
            "(data, descricao, valor_cents, tipo, categoria_id, conta_id, observacao, criado_em) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (data_str, descricao.strip(), int(valor_cents), tipo, categoria_id, conta_id, observacao, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_transacoes(mes=None, categoria_id=None, tipo=None, busca=None, conta_id=None,
                       data_inicio=None, data_fim=None, limite=None):
    conn = get_connection()
    try:
        sql = (
            "SELECT t.*, c.nome AS categoria_nome, c.icone AS categoria_icone, c.cor AS categoria_cor, "
            "ct.nome AS conta_nome, ct.icone AS conta_icone "
            "FROM transacoes t "
            "LEFT JOIN categorias c ON c.id = t.categoria_id "
            "LEFT JOIN contas ct ON ct.id = t.conta_id WHERE 1=1"
        )
        params = []
        if mes:
            sql += " AND substr(t.data, 1, 7) = ?"
            params.append(mes)
        if data_inicio:
            sql += " AND t.data >= ?"
            params.append(data_inicio)
        if data_fim:
            sql += " AND t.data <= ?"
            params.append(data_fim)
        if categoria_id:
            sql += " AND t.categoria_id = ?"
            params.append(categoria_id)
        if tipo:
            sql += " AND t.tipo = ?"
            params.append(tipo)
        if conta_id:
            sql += " AND t.conta_id = ?"
            params.append(conta_id)
        if busca:
            sql += " AND lower(t.descricao) LIKE ?"
            params.append(f"%{busca.lower()}%")
        sql += " ORDER BY t.data DESC, t.id DESC"
        if limite:
            sql += f" LIMIT {int(limite)}"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def excluir_transacao(trans_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM transacoes WHERE id = ?", (trans_id,))
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Orçamentos (limites por categoria)
# ----------------------------------------------------------------------------
def listar_orcamentos():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT o.*, c.nome AS categoria_nome, c.icone AS categoria_icone "
            "FROM orcamentos o LEFT JOIN categorias c ON c.id = o.categoria_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def salvar_orcamento(categoria_id, limite_cents):
    conn = get_connection()
    try:
        if limite_cents <= 0:
            conn.execute("DELETE FROM orcamentos WHERE categoria_id = ?", (categoria_id,))
        else:
            conn.execute(
                "INSERT INTO orcamentos (categoria_id, limite_cents) VALUES (?, ?) "
                "ON CONFLICT(categoria_id) DO UPDATE SET limite_cents = excluded.limite_cents",
                (categoria_id, int(limite_cents)),
            )
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Resumos financeiros
# ----------------------------------------------------------------------------
def _mes_atual():
    return date.today().strftime("%Y-%m")


def caixa_atual_cents():
    """Patrimônio total = soma do saldo atual de todas as contas.

    Transferências entre contas não entram aqui como ganho/perda: saem de uma
    conta e entram em outra, então se cancelam na soma total (só mudam a
    distribuição entre contas).
    """
    conn = get_connection()
    try:
        row = conn.execute(f"SELECT COALESCE(SUM({_SALDO_ATUAL_SQL}), 0) AS total FROM contas c").fetchone()
        return row["total"]
    finally:
        conn.close()


def resumo_mes(mes=None):
    """Retorna totais do mês e quebra por categoria (só saídas)."""
    mes = mes or _mes_atual()
    resumo = resumo_periodo(f"{mes}-01", f"{mes}-31")
    resumo["mes"] = mes
    return resumo


def resumo_periodo(data_inicio, data_fim):
    """Como resumo_mes, mas para um intervalo de datas qualquer (inclusive)."""
    conn = get_connection()
    try:
        tot = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor_cents ELSE 0 END),0) AS entradas, "
            "COALESCE(SUM(CASE WHEN tipo='saida'   THEN valor_cents ELSE 0 END),0) AS saidas "
            "FROM transacoes WHERE data BETWEEN ? AND ?",
            (data_inicio, data_fim),
        ).fetchone()

        por_cat = conn.execute(
            "SELECT c.id, c.nome, c.icone, c.cor, SUM(t.valor_cents) AS total "
            "FROM transacoes t JOIN categorias c ON c.id = t.categoria_id "
            "WHERE t.tipo='saida' AND t.data BETWEEN ? AND ? "
            "GROUP BY c.id ORDER BY total DESC",
            (data_inicio, data_fim),
        ).fetchall()

        entradas = tot["entradas"]
        saidas = tot["saidas"]
        return {
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "entradas_cents": entradas,
            "saidas_cents": saidas,
            "saldo_mes_cents": entradas - saidas,
            "caixa_cents": caixa_atual_cents(),
            "por_categoria": [dict(r) for r in por_cat],
        }
    finally:
        conn.close()
