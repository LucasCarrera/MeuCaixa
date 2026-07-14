"""Categorização automática das transações.

Estratégia em camadas (da mais confiável para a menos):
1. Aprendizado: se o usuário já classificou algo parecido antes, usa isso.
2. Regras: palavras-chave comuns do dia a dia brasileiro.
3. IA local (opcional): se o Ollama estiver rodando, o modelo escolhe entre
   as categorias existentes. Se não estiver, simplesmente pulamos esta etapa.

Nunca trava: o pior caso é sugerir "Outros" com confiança baixa.
"""

import re
import unicodedata
from .db import get_connection
from .logger import get_logger

log = get_logger(__name__)

# Palavras-chave -> nome de categoria padrão.
REGRAS = {
    "Mercado": ["mercado", "supermerc", "atacad", "hortifruti", "sacolao", "assai",
                "carrefour", "pao de acucar", "extra", "big", "dia ", "feira"],
    "Alimentação/Delivery": ["ifood", "rappi", "delivery", "restaurante", "lanche",
                             "lanchonete", "padaria", "pizza", "burguer", "burger",
                             "mc donalds", "mcdonald", "bk", "subway", "bar ", "cafe",
                             "acai", "sorveteria"],
    "Transporte": ["uber", "99 ", "99app", "taxi", "onibus", "metro", "gasolina",
                   "posto", "combustivel", "alcool", "etanol", "estacionamento",
                   "pedagio", "passagem", "bilhete unico"],
    "Moradia": ["aluguel", "condominio", "iptu", "imobiliaria"],
    "Contas (luz, água, net)": ["luz", "energia", "enel", "cemig", "copel", "agua",
                                "sabesp", "saneamento", "internet", "banda larga", "vivo",
                                "claro", "tim", "telefone", "gas", "comgas"],
    "Saúde": ["farmacia", "drogaria", "drogasil", "pacheco", "raia", "hospital",
              "clinica", "medico", "dentista", "consulta", "exame", "plano de saude",
              "unimed", "amil"],
    "Lazer": ["cinema", "show", "ingresso", "viagem", "hotel", "airbnb", "parque",
              "balada", "festa", "jogo"],
    "Educação": ["escola", "faculdade", "curso", "livro", "livraria", "mensalidade",
                 "material escolar", "udemy", "alura"],
    "Assinaturas": ["netflix", "spotify", "amazon prime", "disney", "hbo", "max ",
                    "youtube premium", "globoplay", "deezer", "assinatura", "apple"],
    "Salário": ["salario", "pagamento", "holerite", "provento"],
    "Renda extra": ["freela", "freelance", "bico", "venda", "pix recebido", "recebimento"],
}


def normalizar(texto):
    txt = unicodedata.normalize("NFKD", texto.lower())
    txt = txt.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", txt).strip()


def _mapa_categorias():
    conn = get_connection()
    try:
        return {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM categorias")}
    finally:
        conn.close()


def _por_aprendizado(desc_norm, mapa):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT categoria_id, chave, contador FROM aprendizado ORDER BY contador DESC"
        ).fetchall()
        for r in rows:
            chave = r["chave"]
            # match se a chave aprendida aparece na descrição (ou vice-versa)
            if chave and (chave in desc_norm or desc_norm in chave):
                return r["categoria_id"], 0.95, "aprendizado"
        return None
    finally:
        conn.close()


def _casa(palavra, texto):
    """Casa a palavra-chave respeitando limites de palavra.

    Assim 'net' casa 'net claro' mas NÃO casa dentro de 'netflix'.
    """
    p = normalizar(palavra)
    return re.search(r"\b" + re.escape(p) + r"\b", texto) is not None


def _por_regras(desc_norm, mapa):
    for nome_cat, palavras in REGRAS.items():
        for p in palavras:
            if _casa(p, desc_norm):
                cat_id = mapa.get(nome_cat)
                if cat_id:
                    return cat_id, 0.8, "regra"
    return None


def sugerir_categoria(descricao, usar_ia=True):
    """Retorna dict {categoria_id, confianca, origem} ou categoria 'Outros'."""
    mapa = _mapa_categorias()
    desc_norm = normalizar(descricao)

    for tentativa in (_por_aprendizado(desc_norm, mapa), _por_regras(desc_norm, mapa)):
        if tentativa:
            cat_id, conf, origem = tentativa
            return {"categoria_id": cat_id, "confianca": conf, "origem": origem}

    if usar_ia:
        try:
            from .llm import categorizar_com_ia
            cat_id = categorizar_com_ia(descricao)
            if cat_id:
                return {"categoria_id": cat_id, "confianca": 0.7, "origem": "ia"}
        except Exception:
            log.debug("IA indisponível para sugerir categoria, seguindo com o fallback", exc_info=True)

    return {"categoria_id": mapa.get("Outros"), "confianca": 0.3, "origem": "padrao"}


def registrar_aprendizado(descricao, categoria_id):
    """Chamado quando o usuário confirma/corrige uma categoria — o app aprende."""
    chave = normalizar(descricao)
    if not chave or not categoria_id:
        return
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO aprendizado (chave, categoria_id, contador) VALUES (?, ?, 1) "
            "ON CONFLICT(chave, categoria_id) DO UPDATE SET contador = contador + 1",
            (chave, categoria_id),
        )
        conn.commit()
    finally:
        conn.close()
