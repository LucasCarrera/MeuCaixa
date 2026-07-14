"""Integração com a IA local (Ollama).

O app funciona 100% sem IA — a IA é um bônus. Todas as funções aqui degradam
com elegância: se o Ollama não estiver rodando, retornam None ou uma mensagem
amigável, e o resto do app continua normal.

O Ollama expõe uma API HTTP em http://localhost:11434. Usamos requests direto
para não depender de bibliotecas extras.
"""

import json
import threading

import requests

from . import repository as repo
from .logger import get_logger

log = get_logger(__name__)

OLLAMA_URL = "http://localhost:11434"
TIMEOUT_CURTO = 3
TIMEOUT_CHAT = 120

# progresso dos downloads de modelo em andamento, por nome do modelo
_progresso = {}
_progresso_lock = threading.Lock()


# ----------------------------------------------------------------------------
# Descoberta de hardware e modelos (para o usuário escolher)
# ----------------------------------------------------------------------------
def memoria_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return None


def modelos_recomendados():
    """Sugere modelos por faixa de RAM. O usuário escolhe qual usar/baixar."""
    ram = memoria_gb() or 8
    catalogo = [
        {"nome": "qwen2.5:0.5b", "rotulo": "Ultra leve (roda em quase tudo)", "min_ram": 2},
        {"nome": "llama3.2:1b",  "rotulo": "Leve",                            "min_ram": 4},
        {"nome": "llama3.2:3b",  "rotulo": "Equilibrado (recomendado)",       "min_ram": 8},
        {"nome": "qwen2.5:7b",   "rotulo": "Esperto (precisa de PC bom)",     "min_ram": 16},
    ]
    for m in catalogo:
        m["cabe"] = ram >= m["min_ram"]
        m["recomendado"] = (m["nome"] == "llama3.2:3b" and ram >= 8) or \
                           (m["nome"] == "llama3.2:1b" and 4 <= ram < 8) or \
                           (m["nome"] == "qwen2.5:0.5b" and ram < 4)
    return {"ram_gb": ram, "modelos": catalogo}


def status():
    """Diz se o Ollama está no ar e quais modelos já estão instalados."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=TIMEOUT_CURTO)
        r.raise_for_status()
        instalados = [m["name"] for m in r.json().get("models", [])]
        return {"disponivel": True, "instalados": instalados}
    except Exception as e:
        log.debug("Ollama indisponível em %s: %s", OLLAMA_URL, e)
        return {"disponivel": False, "instalados": []}


def _modelo_ativo():
    escolhido = repo.get_ajuste("modelo_ia", "")
    st = status()
    if escolhido:
        if st["instalados"] and escolhido not in st["instalados"]:
            log.warning(
                "Modelo configurado (%s) não está instalado no Ollama; instalados: %s",
                escolhido, st["instalados"],
            )
        return escolhido
    return st["instalados"][0] if st["instalados"] else None


# ----------------------------------------------------------------------------
# Download de modelos (baixa em thread separada; a UI consulta o progresso)
# ----------------------------------------------------------------------------
def baixar_modelo(nome):
    """Inicia o download do modelo em segundo plano. Não bloqueia."""
    with _progresso_lock:
        if _progresso.get(nome, {}).get("rodando"):
            return  # já está baixando esse modelo
        _progresso[nome] = {"rodando": True, "concluido": False, "erro": None,
                             "percentual": 0, "status": "iniciando"}
    threading.Thread(target=_baixar_modelo_thread, args=(nome,), daemon=True).start()


def _baixar_modelo_thread(nome):
    log.info("Iniciando download do modelo %s", nome)
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": nome, "stream": True},
            stream=True,
            timeout=None,
        ) as r:
            r.raise_for_status()
            for linha in r.iter_lines():
                if not linha:
                    continue
                info = json.loads(linha)
                if info.get("error"):
                    raise RuntimeError(info["error"])
                total = info.get("total") or 0
                completo = info.get("completed") or 0
                pct = int(completo / total * 100) if total else 0
                with _progresso_lock:
                    _progresso[nome] = {
                        "rodando": True, "concluido": False, "erro": None,
                        "percentual": pct, "status": info.get("status", ""),
                    }
        with _progresso_lock:
            _progresso[nome] = {"rodando": False, "concluido": True, "erro": None,
                                 "percentual": 100, "status": "concluído"}
        log.info("Modelo %s baixado com sucesso", nome)
    except Exception as e:
        with _progresso_lock:
            _progresso[nome] = {"rodando": False, "concluido": False,
                                 "erro": str(e), "percentual": 0, "status": "erro"}
        log.warning("Falha ao baixar o modelo %s", nome, exc_info=True)


def progresso_download(nome):
    with _progresso_lock:
        return dict(_progresso.get(nome, {
            "rodando": False, "concluido": False, "erro": None,
            "percentual": 0, "status": "",
        }))


# ----------------------------------------------------------------------------
# Chamada base
# ----------------------------------------------------------------------------
def _gerar(system, prompt, modelo=None, timeout=TIMEOUT_CHAT):
    modelo = modelo or _modelo_ativo()
    if not modelo:
        return None
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": modelo,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
    except Exception:
        log.warning("Falha ao chamar o modelo %s no Ollama", modelo, exc_info=True)
        return None


# ----------------------------------------------------------------------------
# Categorização assistida por IA
# ----------------------------------------------------------------------------
def categorizar_com_ia(descricao):
    """Pede para o modelo escolher UMA categoria existente. Retorna o id ou None."""
    categorias = repo.listar_categorias()
    if not categorias:
        return None
    nomes = [c["nome"] for c in categorias]
    system = (
        "Você classifica gastos e receitas em categorias. Responda APENAS com o nome "
        "exato de uma categoria da lista, sem explicação, sem pontuação extra."
    )
    prompt = (
        f"Categorias possíveis: {', '.join(nomes)}.\n"
        f"Classifique isto: \"{descricao}\".\n"
        f"Responda só com o nome da categoria."
    )
    resposta = _gerar(system, prompt, timeout=20)
    if not resposta:
        return None
    resposta = resposta.strip().strip('".')
    for c in categorias:
        if c["nome"].lower() == resposta.lower():
            return c["id"]
    # tentativa mais frouxa: contém
    for c in categorias:
        if c["nome"].lower() in resposta.lower():
            return c["id"]
    return None


# ----------------------------------------------------------------------------
# Chat / assistente financeiro
# ----------------------------------------------------------------------------
def _fmt(cents):
    return f"R$ {cents/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _contexto_financeiro():
    """Monta um retrato compacto das finanças para o modelo responder com base em dados reais."""
    resumo = repo.resumo_mes()
    linhas = [
        f"Mês de referência: {resumo['mes']}.",
        f"Entradas do mês: {_fmt(resumo['entradas_cents'])}.",
        f"Saídas do mês: {_fmt(resumo['saidas_cents'])}.",
        f"Saldo do mês: {_fmt(resumo['saldo_mes_cents'])}.",
        f"Dinheiro em caixa hoje: {_fmt(resumo['caixa_cents'])}.",
    ]
    if resumo["por_categoria"]:
        linhas.append("Onde mais gastou este mês:")
        for c in resumo["por_categoria"][:6]:
            linhas.append(f"  - {c['nome']}: {_fmt(c['total'])}")
    return "\n".join(linhas)


def conversar(pergunta, modelo=None):
    """Responde à pergunta do usuário usando os dados reais dele como contexto."""
    if not status()["disponivel"]:
        return {
            "ok": False,
            "resposta": "A IA local (Ollama) não está rodando. Abra o Ollama e escolha "
                        "um modelo nos Ajustes para conversar com o assistente.",
        }
    system = (
        "Você é o assistente financeiro do app MeuCaixa. Fale português do Brasil, "
        "de forma simples, calorosa e curta, para uma pessoa que não entende de finanças. "
        "Use só os dados fornecidos; se faltar informação, diga com honestidade. "
        "Nunca invente números. Você não é um consultor licenciado: para decisões grandes "
        "(investir, financiar), sugira procurar um profissional. Dê dicas práticas do dia a dia."
    )
    prompt = (
        f"Dados atuais do usuário:\n{_contexto_financeiro()}\n\n"
        f"Pergunta do usuário: {pergunta}"
    )
    resposta = _gerar(system, prompt, modelo=modelo)
    if resposta is None:
        return {"ok": False, "resposta": "Não consegui falar com a IA agora. Tente de novo."}
    return {"ok": True, "resposta": resposta}
