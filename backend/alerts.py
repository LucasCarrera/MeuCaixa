"""Motor de alertas.

Verifica quatro situações e devolve uma lista de avisos em linguagem simples:
1. Estourou o orçamento de uma categoria (ou está quase).
2. Passou do limite geral de gastos do mês.
3. O caixa caiu abaixo do piso que o usuário definiu.
4. Um gasto isolado fugiu muito do padrão daquela categoria.

Os níveis são: info | atencao | perigo.
"""

from datetime import date
from statistics import median
from .db import get_connection, agora
from . import repository as repo
from .logger import get_logger

log = get_logger(__name__)


def _reais(cents):
    return cents / 100.0


def _fmt(cents):
    return f"R$ {_reais(cents):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _gasto_categoria_mes(categoria_id, mes):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(valor_cents),0) AS t FROM transacoes "
            "WHERE tipo='saida' AND categoria_id=? AND substr(data,1,7)=?",
            (categoria_id, mes),
        ).fetchone()
        return row["t"]
    finally:
        conn.close()


def avaliar(mes=None, ultima_transacao=None):
    """Retorna lista de alertas. Não grava nada — quem decide gravar é a API."""
    mes = mes or date.today().strftime("%Y-%m")
    alertas = []

    resumo = repo.resumo_mes(mes)
    ajustes = repo.get_todos_ajustes()

    # 1. Orçamentos por categoria
    for orc in repo.listar_orcamentos():
        if not orc["categoria_id"]:
            continue
        gasto = _gasto_categoria_mes(orc["categoria_id"], mes)
        limite = orc["limite_cents"]
        if limite <= 0:
            continue
        pct = gasto / limite
        nome = orc["categoria_nome"]
        if pct >= 1.0:
            alertas.append({
                "tipo": "orcamento",
                "nivel": "perigo",
                "mensagem": f"Você estourou o limite de {nome}: gastou {_fmt(gasto)} "
                            f"de {_fmt(limite)} previstos neste mês.",
            })
        elif pct >= 0.8:
            alertas.append({
                "tipo": "orcamento",
                "nivel": "atencao",
                "mensagem": f"Atenção: já usou {int(pct*100)}% do limite de {nome} "
                            f"({_fmt(gasto)} de {_fmt(limite)}).",
            })

    # 2. Limite geral do mês
    limite_mensal = int(ajustes.get("limite_mensal_cents", "0"))
    if limite_mensal > 0:
        saidas = resumo["saidas_cents"]
        pct = saidas / limite_mensal
        if pct >= 1.0:
            alertas.append({
                "tipo": "limite_mensal",
                "nivel": "perigo",
                "mensagem": f"Seus gastos do mês ({_fmt(saidas)}) passaram do limite "
                            f"que você definiu ({_fmt(limite_mensal)}).",
            })
        elif pct >= 0.85:
            alertas.append({
                "tipo": "limite_mensal",
                "nivel": "atencao",
                "mensagem": f"Você já gastou {int(pct*100)}% do seu limite do mês. "
                            f"Pé no freio pelos próximos dias.",
            })

    # 3. Piso de caixa
    piso = int(ajustes.get("piso_caixa_cents", "0"))
    caixa = resumo["caixa_cents"]
    if piso > 0 and caixa < piso:
        alertas.append({
            "tipo": "piso_caixa",
            "nivel": "perigo",
            "mensagem": f"Seu caixa está em {_fmt(caixa)}, abaixo da reserva mínima "
                        f"de {_fmt(piso)} que você definiu.",
        })

    # 4. Gasto fora do padrão (só para a última transação, se informada)
    if ultima_transacao and ultima_transacao.get("tipo") == "saida":
        anomalia = _detectar_anomalia(ultima_transacao)
        if anomalia:
            alertas.append(anomalia)

    return alertas


def _detectar_anomalia(trans):
    """Compara o gasto com o histórico da mesma categoria."""
    cat_id = trans.get("categoria_id")
    valor = trans.get("valor_cents", 0)
    if not cat_id or valor <= 0:
        return None
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT valor_cents FROM transacoes "
            "WHERE tipo='saida' AND categoria_id=? ORDER BY id DESC LIMIT 30",
            (cat_id,),
        ).fetchall()
    finally:
        conn.close()
    valores = [r["valor_cents"] for r in rows if r["valor_cents"] != valor]
    if len(valores) < 5:
        return None  # histórico insuficiente para julgar
    tipico = median(valores)
    if tipico > 0 and valor > tipico * 2.5:
        return {
            "tipo": "anomalia",
            "nivel": "atencao",
            "mensagem": f"Este gasto de {_fmt(valor)} está bem acima do seu normal "
                        f"nessa categoria (perto de {_fmt(int(tipico))}). Foi proposital?",
        }
    return None


def gravar_alertas(alertas):
    """Persiste os alertas para o sino de notificações.

    Evita duplicar: se a MESMA mensagem já existe e ainda não foi lida,
    não grava de novo (senão o mesmo aviso apareceria a cada lançamento).
    """
    if not alertas:
        return
    conn = get_connection()
    try:
        gravados = 0
        for a in alertas:
            existe = conn.execute(
                "SELECT 1 FROM alertas WHERE mensagem = ? AND lido = 0 LIMIT 1",
                (a["mensagem"],),
            ).fetchone()
            if existe:
                continue
            conn.execute(
                "INSERT INTO alertas (criado_em, tipo, nivel, mensagem) VALUES (?,?,?,?)",
                (agora(), a["tipo"], a["nivel"], a["mensagem"]),
            )
            gravados += 1
        conn.commit()
        if gravados:
            log.info("%s novo(s) alerta(s) gravado(s)", gravados)
    finally:
        conn.close()


def listar_alertas(limite=20):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM alertas ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def marcar_todos_lidos():
    conn = get_connection()
    try:
        conn.execute("UPDATE alertas SET lido = 1 WHERE lido = 0")
        conn.commit()
    finally:
        conn.close()
