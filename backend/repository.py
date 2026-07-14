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
    conn = get_connection()
    try:
        if tipo:
            rows = conn.execute(
                "SELECT * FROM categorias WHERE tipo = ? ORDER BY nome", (tipo,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM categorias ORDER BY tipo DESC, nome").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def criar_categoria(nome, tipo, icone="💰", cor="#1B7A5A"):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO categorias (nome, tipo, icone, cor, padrao) VALUES (?,?,?,?,0)",
            (nome.strip(), tipo, icone, cor),
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
# Transações
# ----------------------------------------------------------------------------
def adicionar_transacao(data_str, descricao, valor_cents, tipo, categoria_id, observacao=""):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO transacoes (data, descricao, valor_cents, tipo, categoria_id, observacao, criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (data_str, descricao.strip(), int(valor_cents), tipo, categoria_id, observacao, agora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_transacoes(mes=None, categoria_id=None, tipo=None, busca=None, limite=None):
    conn = get_connection()
    try:
        sql = (
            "SELECT t.*, c.nome AS categoria_nome, c.icone AS categoria_icone, c.cor AS categoria_cor "
            "FROM transacoes t LEFT JOIN categorias c ON c.id = t.categoria_id WHERE 1=1"
        )
        params = []
        if mes:
            sql += " AND substr(t.data, 1, 7) = ?"
            params.append(mes)
        if categoria_id:
            sql += " AND t.categoria_id = ?"
            params.append(categoria_id)
        if tipo:
            sql += " AND t.tipo = ?"
            params.append(tipo)
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
    """Saldo total acumulado = saldo inicial + entradas - saídas de todos os tempos."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor_cents ELSE 0 END),0) AS ent, "
            "COALESCE(SUM(CASE WHEN tipo='saida'   THEN valor_cents ELSE 0 END),0) AS sai "
            "FROM transacoes"
        ).fetchone()
        inicial = int(get_ajuste("saldo_inicial_cents", "0"))
        return inicial + row["ent"] - row["sai"]
    finally:
        conn.close()


def resumo_mes(mes=None):
    """Retorna totais do mês e quebra por categoria (só saídas)."""
    mes = mes or _mes_atual()
    conn = get_connection()
    try:
        tot = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor_cents ELSE 0 END),0) AS entradas, "
            "COALESCE(SUM(CASE WHEN tipo='saida'   THEN valor_cents ELSE 0 END),0) AS saidas "
            "FROM transacoes WHERE substr(data,1,7) = ?",
            (mes,),
        ).fetchone()

        por_cat = conn.execute(
            "SELECT c.id, c.nome, c.icone, c.cor, SUM(t.valor_cents) AS total "
            "FROM transacoes t JOIN categorias c ON c.id = t.categoria_id "
            "WHERE t.tipo='saida' AND substr(t.data,1,7) = ? "
            "GROUP BY c.id ORDER BY total DESC",
            (mes,),
        ).fetchall()

        entradas = tot["entradas"]
        saidas = tot["saidas"]
        return {
            "mes": mes,
            "entradas_cents": entradas,
            "saidas_cents": saidas,
            "saldo_mes_cents": entradas - saidas,
            "caixa_cents": caixa_atual_cents(),
            "por_categoria": [dict(r) for r in por_cat],
        }
    finally:
        conn.close()
