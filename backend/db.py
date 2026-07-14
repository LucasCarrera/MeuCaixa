"""Conexão e schema do banco SQLite do MeuCaixa.

Tudo em português e local-first: o arquivo do banco fica dentro da pasta data/.
Valores em dinheiro são guardados em CENTAVOS (inteiro) para nunca ter erro
de arredondamento de float. A conversão para reais acontece só na borda.
"""

import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "meucaixa.db")

# import tardio evita import circular (logger usa BASE_DIR daqui)
def _log():
    from .logger import get_logger
    return get_logger(__name__)


def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS categorias (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome              TEXT NOT NULL UNIQUE,
    tipo              TEXT NOT NULL CHECK (tipo IN ('saida', 'entrada')),
    icone             TEXT DEFAULT '💰',
    cor               TEXT DEFAULT '#1B7A5A',
    padrao            INTEGER DEFAULT 0,
    categoria_pai_id  INTEGER,
    FOREIGN KEY (categoria_pai_id) REFERENCES categorias(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS contas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                TEXT NOT NULL UNIQUE,
    tipo                TEXT NOT NULL CHECK (tipo IN ('corrente', 'poupanca', 'dinheiro', 'digital')),
    saldo_inicial_cents INTEGER NOT NULL DEFAULT 0,
    cor                 TEXT DEFAULT '#1B7A5A',
    icone               TEXT DEFAULT '💼',
    criado_em           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transacoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    data          TEXT NOT NULL,                    -- YYYY-MM-DD
    descricao     TEXT NOT NULL,
    valor_cents   INTEGER NOT NULL,                 -- sempre positivo
    tipo          TEXT NOT NULL CHECK (tipo IN ('saida', 'entrada')),
    categoria_id  INTEGER,
    conta_id      INTEGER,
    observacao    TEXT DEFAULT '',
    criado_em     TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL,
    FOREIGN KEY (conta_id) REFERENCES contas(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS transferencias (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_origem_id   INTEGER NOT NULL,
    conta_destino_id  INTEGER NOT NULL,
    valor_cents       INTEGER NOT NULL,
    data              TEXT NOT NULL,
    descricao         TEXT DEFAULT '',
    criado_em         TEXT NOT NULL,
    FOREIGN KEY (conta_origem_id) REFERENCES contas(id) ON DELETE CASCADE,
    FOREIGN KEY (conta_destino_id) REFERENCES contas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cartoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL UNIQUE,
    limite_cents    INTEGER NOT NULL DEFAULT 0,
    dia_fechamento  INTEGER NOT NULL,                 -- 1-28
    dia_vencimento  INTEGER NOT NULL,                 -- 1-28
    cor             TEXT DEFAULT '#6B4FBB',
    icone           TEXT DEFAULT '💳',
    criado_em       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compras_cartao (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    cartao_id          INTEGER NOT NULL,
    descricao          TEXT NOT NULL,
    categoria_id       INTEGER,
    valor_total_cents  INTEGER NOT NULL,
    parcelas_total     INTEGER NOT NULL DEFAULT 1,
    criado_em          TEXT NOT NULL,
    FOREIGN KEY (cartao_id) REFERENCES cartoes(id) ON DELETE CASCADE,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS parcelas_cartao (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    compra_id   INTEGER NOT NULL,
    cartao_id   INTEGER NOT NULL,
    numero      INTEGER NOT NULL,
    valor_cents INTEGER NOT NULL,
    mes_fatura  TEXT NOT NULL,                        -- YYYY-MM
    paga        INTEGER DEFAULT 0,
    FOREIGN KEY (compra_id) REFERENCES compras_cartao(id) ON DELETE CASCADE,
    FOREIGN KEY (cartao_id) REFERENCES cartoes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS investimentos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo               TEXT NOT NULL CHECK (tipo IN
                        ('renda_fixa','acao','fii','cripto','fundo','previdencia')),
    nome               TEXT NOT NULL,
    corretora          TEXT DEFAULT '',
    ticker             TEXT,                          -- símbolo B3 ou id do CoinGecko
    quantidade         REAL NOT NULL DEFAULT 0,
    preco_medio_cents  INTEGER NOT NULL DEFAULT 0,
    indexador          TEXT DEFAULT '',
    vencimento         TEXT,
    meta_id            INTEGER,                        -- vínculo opcional com uma meta (sem FK: metas é de outra fase)
    criado_em          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aportes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    investimento_id      INTEGER NOT NULL,
    valor_cents          INTEGER NOT NULL,
    quantidade_comprada  REAL,
    data                 TEXT NOT NULL,
    criado_em            TEXT NOT NULL,
    FOREIGN KEY (investimento_id) REFERENCES investimentos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recorrencias (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao     TEXT NOT NULL,
    valor_cents   INTEGER NOT NULL,
    tipo          TEXT NOT NULL CHECK (tipo IN ('saida', 'entrada')),
    frequencia    TEXT NOT NULL CHECK (frequencia IN ('semanal', 'mensal', 'anual')),
    proxima_data  TEXT NOT NULL,                    -- YYYY-MM-DD
    categoria_id  INTEGER,
    conta_id      INTEGER,
    ativo         INTEGER DEFAULT 1,
    criado_em     TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL,
    FOREIGN KEY (conta_id) REFERENCES contas(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS contas_pagar (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    descricao      TEXT NOT NULL,
    valor_cents    INTEGER NOT NULL,
    tipo           TEXT NOT NULL CHECK (tipo IN ('saida', 'entrada')),
    vencimento     TEXT NOT NULL,                   -- YYYY-MM-DD
    pago           INTEGER DEFAULT 0,
    categoria_id   INTEGER,
    conta_id       INTEGER,
    recorrencia_id INTEGER,
    criado_em      TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL,
    FOREIGN KEY (conta_id) REFERENCES contas(id) ON DELETE SET NULL,
    FOREIGN KEY (recorrencia_id) REFERENCES recorrencias(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS metas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome              TEXT NOT NULL,
    valor_alvo_cents  INTEGER NOT NULL,
    prazo             TEXT,                          -- YYYY-MM-DD
    valor_atual_cents INTEGER NOT NULL DEFAULT 0,    -- guardado manualmente (fora investimentos)
    criado_em         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orcamentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_id  INTEGER UNIQUE,                   -- NULL = orçamento geral do mês
    limite_cents  INTEGER NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS aprendizado (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chave         TEXT NOT NULL,                    -- descrição normalizada
    categoria_id  INTEGER NOT NULL,
    contador      INTEGER DEFAULT 1,
    UNIQUE (chave, categoria_id),
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ajustes (
    chave  TEXT PRIMARY KEY,
    valor  TEXT
);

CREATE TABLE IF NOT EXISTS alertas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em    TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    nivel        TEXT NOT NULL,                     -- info | atencao | perigo
    mensagem     TEXT NOT NULL,
    lido         INTEGER DEFAULT 0
);
"""

# índices que dependem de colunas migradas em bancos antigos (ver _migrar_colunas_antigas)
INDICES = """
CREATE INDEX IF NOT EXISTS idx_transacoes_data   ON transacoes(data);
CREATE INDEX IF NOT EXISTS idx_transacoes_cat    ON transacoes(categoria_id);
CREATE INDEX IF NOT EXISTS idx_transacoes_conta  ON transacoes(conta_id);
CREATE INDEX IF NOT EXISTS idx_categorias_pai    ON categorias(categoria_pai_id);
CREATE INDEX IF NOT EXISTS idx_parcelas_cartao   ON parcelas_cartao(cartao_id, mes_fatura);
CREATE INDEX IF NOT EXISTS idx_parcelas_compra   ON parcelas_cartao(compra_id);
CREATE INDEX IF NOT EXISTS idx_aportes_invest    ON aportes(investimento_id);
"""

CATEGORIAS_PADRAO = [
    # nome, tipo, ícone, cor
    ("Salário", "entrada", "💼", "#1B7A5A"),
    ("Renda extra", "entrada", "✨", "#2E9E77"),
    ("Mercado", "saida", "🛒", "#C9741E"),
    ("Alimentação/Delivery", "saida", "🍔", "#D64545"),
    ("Transporte", "saida", "🚗", "#3B6FB0"),
    ("Moradia", "saida", "🏠", "#7A5C3E"),
    ("Contas (luz, água, net)", "saida", "💡", "#E8A33D"),
    ("Saúde", "saida", "💊", "#2A9D8F"),
    ("Lazer", "saida", "🎬", "#9B59B6"),
    ("Educação", "saida", "📚", "#4A6FA5"),
    ("Assinaturas", "saida", "📺", "#8E44AD"),
    ("Outros", "saida", "📦", "#6B7772"),
]


def _colunas(conn, tabela):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({tabela})")}


def _migrar_colunas_antigas(conn):
    """Bancos criados antes da tabela 'contas' existir não têm transacoes.conta_id."""
    if "conta_id" not in _colunas(conn, "transacoes"):
        conn.execute(
            "ALTER TABLE transacoes ADD COLUMN conta_id INTEGER "
            "REFERENCES contas(id) ON DELETE SET NULL"
        )
        _log().info("Migração: coluna conta_id adicionada em transacoes")

    if "categoria_pai_id" not in _colunas(conn, "categorias"):
        conn.execute(
            "ALTER TABLE categorias ADD COLUMN categoria_pai_id INTEGER "
            "REFERENCES categorias(id) ON DELETE SET NULL"
        )
        _log().info("Migração: coluna categoria_pai_id adicionada em categorias")


def _garantir_conta_padrao(conn):
    """Na primeira vez que o app ganha suporte a contas, cria a 'Carteira'
    trazendo o saldo inicial antigo e migrando as transações órfãs pra ela."""
    tem_conta = conn.execute("SELECT COUNT(*) AS n FROM contas").fetchone()["n"] > 0
    if tem_conta:
        return
    saldo_antigo = conn.execute(
        "SELECT valor FROM ajustes WHERE chave = 'saldo_inicial_cents'"
    ).fetchone()
    saldo_cents = int(saldo_antigo["valor"]) if saldo_antigo else 0
    cur = conn.execute(
        "INSERT INTO contas (nome, tipo, saldo_inicial_cents, cor, icone, criado_em) "
        "VALUES ('Carteira', 'dinheiro', ?, '#1B7A5A', '👛', ?)",
        (saldo_cents, agora()),
    )
    conta_id = cur.lastrowid
    n = conn.execute(
        "UPDATE transacoes SET conta_id = ? WHERE conta_id IS NULL", (conta_id,)
    ).rowcount
    _log().info("Conta padrão 'Carteira' criada (id=%s), %s transação(ões) migrada(s)", conta_id, n)


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _migrar_colunas_antigas(conn)
        conn.executescript(INDICES)
        cur = conn.execute("SELECT COUNT(*) AS n FROM categorias")
        primeira_vez = cur.fetchone()["n"] == 0
        if primeira_vez:
            for nome, tipo, icone, cor in CATEGORIAS_PADRAO:
                conn.execute(
                    "INSERT INTO categorias (nome, tipo, icone, cor, padrao) VALUES (?,?,?,?,1)",
                    (nome, tipo, icone, cor),
                )
        # ajustes iniciais
        defaults = {
            "onboarding_ok": "0",
            "saldo_inicial_cents": "0",
            "piso_caixa_cents": "0",       # alerta quando caixa cai abaixo disso
            "limite_mensal_cents": "0",    # 0 = sem limite geral
            "modelo_ia": "",
            "moeda": "BRL",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO ajustes (chave, valor) VALUES (?, ?)", (k, v)
            )
        _garantir_conta_padrao(conn)
        conn.commit()
        if primeira_vez:
            _log().info("Banco criado do zero em %s, categorias padrão inseridas", DB_PATH)
        else:
            _log().debug("Banco inicializado em %s", DB_PATH)
    except Exception:
        _log().exception("Falha ao inicializar o banco em %s", DB_PATH)
        raise
    finally:
        conn.close()


def agora():
    return datetime.now().isoformat(timespec="seconds")
