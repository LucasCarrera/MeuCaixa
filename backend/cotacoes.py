"""Cotações de ações, FIIs e cripto — chamadas diretas a APIs públicas.

Sem chave de API (tier gratuito de cada serviço). Cache em memória de
alguns minutos pra não estourar limite de requisições. Se a API falhar ou
o usuário estiver offline, degrada silenciosamente: a carteira perde só o
preço "ao vivo" e passa a usar o preço médio do ativo.

Limitação conhecida da brapi.dev sem token: só resolve UM ticker por
chamada (várias tickers numa só chamada exige token) e FIIs (ex.: MXRF11)
não respondem sem token — só ações simples (PETR4, VALE3...). Por isso
buscamos ticker por ticker, e um FII sem cotação simplesmente fica sem
"preço ao vivo" (usa o preço médio), sem quebrar a carteira.
"""

import time

import requests

from .logger import get_logger

log = get_logger(__name__)

BRAPI_URL = "https://brapi.dev/api/quote"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
TIMEOUT = 5
CACHE_TTL = 300  # 5 minutos

_cache = {}  # chave -> (timestamp, valor)


def _cache_get(chave):
    item = _cache.get(chave)
    if item and time.time() - item[0] < CACHE_TTL:
        return item[1]
    return None


def _cache_set(chave, valor):
    _cache[chave] = (time.time(), valor)


def buscar_acoes_fiis(tickers):
    """Retorna {ticker: preco_atual} para ações/FIIs via brapi.dev.

    Uma chamada por ticker (sem token só aceita 1 por vez). Tickers sem
    cotação disponível (ex.: a maioria dos FIIs sem token) simplesmente
    não aparecem no resultado.
    """
    tickers = sorted({t.upper() for t in tickers if t})
    precos = {}
    for t in tickers:
        cache = _cache_get(f"acao:{t}")
        if cache is not None:
            precos[t] = cache
            continue
        try:
            r = requests.get(f"{BRAPI_URL}/{t}", timeout=TIMEOUT)
            r.raise_for_status()
            resultados = r.json().get("results", [])
            preco = resultados[0].get("regularMarketPrice") if resultados else None
            if preco is not None:
                precos[t] = preco
                _cache_set(f"acao:{t}", preco)
        except Exception:
            log.debug("Sem cotação para %s na brapi.dev", t, exc_info=True)
    return precos


def buscar_cripto(ids_coingecko):
    """Retorna {id: preco_brl} para criptomoedas via CoinGecko (id, não símbolo)."""
    ids = sorted({i.lower() for i in ids_coingecko if i})
    if not ids:
        return {}
    chave = "cripto:" + ",".join(ids)
    cache = _cache_get(chave)
    if cache is not None:
        return cache
    try:
        r = requests.get(
            COINGECKO_URL, params={"ids": ",".join(ids), "vs_currencies": "brl"}, timeout=TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        precos = {i: data[i]["brl"] for i in ids if i in data and "brl" in data[i]}
    except Exception:
        log.debug("Falha ao buscar cotações de cripto na CoinGecko", exc_info=True)
        return {}
    _cache_set(chave, precos)
    return precos
