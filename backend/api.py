"""Ponte entre a interface (JavaScript) e o Python.

Cada método desta classe fica disponível no frontend como
`window.pywebview.api.nome_do_metodo(...)` e devolve dados prontos (dicts/listas)
já em REAIS, não em centavos — a interface nunca precisa saber de centavos.
"""

import os
import sys
import subprocess
from datetime import date

from . import repository as repo
from . import categorizer
from . import alerts
from . import reports
from . import llm
from . import cartoes
from . import investimentos
from . import metas
from . import recorrencias
from . import dados
from .logger import get_logger

log = get_logger(__name__)


def _cents(valor_reais):
    """Converte '1.234,56' ou 1234.56 para centavos inteiros, sem erro de float."""
    if isinstance(valor_reais, str):
        v = valor_reais.strip().replace("R$", "").replace(" ", "")
        # formato brasileiro: 1.234,56
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        valor_reais = float(v or 0)
    return int(round(float(valor_reais) * 100))


def _reais(cents):
    return round((cents or 0) / 100.0, 2)


def _num(valor):
    """Converte '0,01' ou 0.01 para float, aceitando formato brasileiro (vírgula decimal)."""
    if isinstance(valor, str):
        v = valor.strip().replace(" ", "")
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        return float(v or 0)
    return float(valor)


def _abrir_arquivo(caminho):
    try:
        if sys.platform.startswith("win"):
            os.startfile(caminho)  # noqa
        elif sys.platform == "darwin":
            subprocess.run(["open", caminho])
        else:
            subprocess.run(["xdg-open", caminho])
    except Exception:
        log.warning("Não consegui abrir o arquivo %s", caminho, exc_info=True)


class Api:
    # -------------------- Dashboard --------------------
    def get_dashboard(self, mes=None):
        mes = mes or date.today().strftime("%Y-%m")
        resumo = repo.resumo_mes(mes)
        avaliados = alerts.avaliar(mes)
        # grava no sino também aqui: alertas como fatura vencendo não dependem
        # de lançar uma transação para aparecer (gravar_alertas já deduplica)
        alerts.gravar_alertas(avaliados)
        return {
            "mes": mes,
            "entradas": _reais(resumo["entradas_cents"]),
            "saidas": _reais(resumo["saidas_cents"]),
            "saldo_mes": _reais(resumo["saldo_mes_cents"]),
            "caixa": _reais(resumo["caixa_cents"]),
            "por_categoria": [
                {"nome": c["nome"], "icone": c["icone"], "cor": c["cor"],
                 "valor": _reais(c["total"])}
                for c in resumo["por_categoria"]
            ],
            "alertas": avaliados,
            "ultimas": [self._trans_view(t) for t in repo.listar_transacoes(mes=mes, limite=8)],
            "proximos_vencimentos": [
                {"id": cp["id"], "descricao": cp["descricao"], "valor": _reais(cp["valor_cents"]),
                 "tipo": cp["tipo"], "vencimento": cp["vencimento"],
                 "vencida": cp["vencimento"] < date.today().isoformat()}
                for cp in recorrencias.proximos_vencimentos()
            ],
        }

    def _trans_view(self, t):
        return {
            "id": t["id"], "data": t["data"], "descricao": t["descricao"],
            "valor": _reais(t["valor_cents"]), "tipo": t["tipo"],
            "categoria_nome": t.get("categoria_nome") or "Sem categoria",
            "categoria_icone": t.get("categoria_icone") or "📦",
            "categoria_cor": t.get("categoria_cor") or "#6B7772",
            "conta_nome": t.get("conta_nome") or "—",
            "conta_icone": t.get("conta_icone") or "💼",
            "observacao": t.get("observacao") or "",
        }

    # -------------------- Transações --------------------
    def sugerir_categoria(self, descricao):
        s = categorizer.sugerir_categoria(descricao)
        cat = next((c for c in repo.listar_categorias()
                    if c["id"] == s["categoria_id"]), None)
        return {
            "categoria_id": s["categoria_id"],
            "categoria_nome": cat["nome"] if cat else "Outros",
            "confianca": s["confianca"], "origem": s["origem"],
        }

    def adicionar_transacao(self, data_str, descricao, valor, tipo, categoria_id, conta_id=None, observacao=""):
        data_str = data_str or date.today().strftime("%Y-%m-%d")
        cents = _cents(valor)
        if cents <= 0:
            log.warning("Tentativa de lançar transação com valor inválido: %r", valor)
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        cat_id = int(categoria_id) if categoria_id else None
        cta_id = int(conta_id) if conta_id else None
        tid = repo.adicionar_transacao(data_str, descricao, cents, tipo, cat_id, cta_id, observacao)
        log.info("Transação #%s lançada: %s %s centavos (categoria=%s, conta=%s)",
                  tid, tipo, cents, cat_id, cta_id)
        # o app aprende com a escolha do usuário
        if cat_id:
            categorizer.registrar_aprendizado(descricao, cat_id)
        # avalia alertas, incluindo anomalia desta transação
        nova = {"tipo": tipo, "valor_cents": cents, "categoria_id": cat_id}
        avaliados = alerts.avaliar(data_str[:7], ultima_transacao=nova)
        alerts.gravar_alertas(avaliados)
        return {"ok": True, "id": tid, "alertas": avaliados}

    def listar_transacoes(self, mes=None, categoria_id=None, tipo=None, busca=None, conta_id=None):
        cat = int(categoria_id) if categoria_id else None
        cta = int(conta_id) if conta_id else None
        rows = repo.listar_transacoes(mes=mes, categoria_id=cat, tipo=tipo, busca=busca, conta_id=cta)
        return [self._trans_view(t) for t in rows]

    def excluir_transacao(self, trans_id):
        repo.excluir_transacao(int(trans_id))
        log.info("Transação #%s excluída", trans_id)
        return {"ok": True}

    # -------------------- Categorias --------------------
    def listar_categorias(self, tipo=None):
        return repo.listar_categorias(tipo)

    def criar_categoria(self, nome, tipo, icone="💰", cor="#1B7A5A", categoria_pai_id=None):
        if not nome.strip():
            return {"ok": False, "erro": "Dê um nome para a categoria."}
        pai_id = int(categoria_pai_id) if categoria_pai_id else None
        try:
            cid = repo.criar_categoria(nome, tipo, icone, cor, pai_id)
            log.info("Categoria #%s criada: %s (%s, pai=%s)", cid, nome, tipo, pai_id)
            return {"ok": True, "id": cid}
        except Exception:
            log.warning("Falha ao criar categoria %r (provável nome duplicado)", nome, exc_info=True)
            return {"ok": False, "erro": "Já existe uma categoria com esse nome."}

    def excluir_categoria(self, cat_id):
        repo.excluir_categoria(int(cat_id))
        log.info("Categoria #%s excluída", cat_id)
        return {"ok": True}

    # -------------------- Contas --------------------
    def listar_contas(self):
        return [
            {"id": c["id"], "nome": c["nome"], "tipo": c["tipo"],
             "saldo_inicial": _reais(c["saldo_inicial_cents"]),
             "saldo_atual": _reais(c["saldo_atual_cents"]),
             "cor": c["cor"], "icone": c["icone"]}
            for c in repo.listar_contas()
        ]

    def salvar_conta(self, nome, tipo, saldo_inicial=0, cor="#1B7A5A", icone="💼", conta_id=None):
        if not nome or not nome.strip():
            return {"ok": False, "erro": "Dê um nome para a conta."}
        cents = _cents(saldo_inicial)
        try:
            if conta_id:
                conta_id = int(conta_id)
                repo.atualizar_conta(conta_id, nome=nome, tipo=tipo,
                                      saldo_inicial_cents=cents, cor=cor, icone=icone)
                log.info("Conta #%s atualizada: %s (%s)", conta_id, nome, tipo)
                return {"ok": True, "id": conta_id}
            cid = repo.criar_conta(nome, tipo, cents, cor, icone)
            log.info("Conta #%s criada: %s (%s)", cid, nome, tipo)
            return {"ok": True, "id": cid}
        except Exception:
            log.warning("Falha ao salvar conta %r", nome, exc_info=True)
            return {"ok": False, "erro": "Já existe uma conta com esse nome."}

    def excluir_conta(self, conta_id):
        conta_id = int(conta_id)
        if len(repo.listar_contas()) <= 1:
            return {"ok": False, "erro": "Você precisa ter pelo menos uma conta."}
        if repo.conta_tem_movimentacao(conta_id):
            return {"ok": False, "erro":
                     "Essa conta tem transações ou transferências vinculadas. "
                     "Apague-as antes de remover a conta."}
        repo.excluir_conta(conta_id)
        log.info("Conta #%s excluída", conta_id)
        return {"ok": True}

    def criar_transferencia(self, conta_origem_id, conta_destino_id, valor, data_str=None, descricao=""):
        origem, destino = int(conta_origem_id), int(conta_destino_id)
        if origem == destino:
            return {"ok": False, "erro": "Escolha contas diferentes para a transferência."}
        cents = _cents(valor)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        data_str = data_str or date.today().strftime("%Y-%m-%d")
        tid = repo.criar_transferencia(origem, destino, cents, data_str, descricao)
        log.info("Transferência #%s: conta %s -> conta %s, %s centavos", tid, origem, destino, cents)
        return {"ok": True, "id": tid}

    def listar_transferencias(self):
        return [
            {"id": t["id"], "data": t["data"], "valor": _reais(t["valor_cents"]),
             "descricao": t.get("descricao") or "",
             "origem_nome": t["origem_nome"], "origem_icone": t["origem_icone"],
             "destino_nome": t["destino_nome"], "destino_icone": t["destino_icone"]}
            for t in repo.listar_transferencias()
        ]

    # -------------------- Orçamentos e ajustes --------------------
    def get_ajustes(self):
        a = repo.get_todos_ajustes()
        return {
            "onboarding_ok": a.get("onboarding_ok") == "1",
            "piso_caixa": _reais(int(a.get("piso_caixa_cents", "0"))),
            "limite_mensal": _reais(int(a.get("limite_mensal_cents", "0"))),
            "modelo_ia": a.get("modelo_ia", ""),
            "tema": a.get("tema", "claro"),
            "nome_usuario": a.get("nome_usuario", ""),
        }

    def salvar_ajustes(self, saldo_inicial=None, piso_caixa=None, limite_mensal=None,
                       modelo_ia=None, onboarding_ok=None, tema=None, nome_usuario=None):
        if saldo_inicial is not None:
            # ainda sem conta escolhida explicitamente (ex.: onboarding) -> cai na primeira conta
            contas = repo.listar_contas()
            if contas:
                repo.atualizar_conta(contas[0]["id"], saldo_inicial_cents=_cents(saldo_inicial))
        if piso_caixa is not None:
            repo.set_ajuste("piso_caixa_cents", _cents(piso_caixa))
        if limite_mensal is not None:
            repo.set_ajuste("limite_mensal_cents", _cents(limite_mensal))
        if modelo_ia is not None:
            repo.set_ajuste("modelo_ia", modelo_ia)
        if onboarding_ok is not None:
            repo.set_ajuste("onboarding_ok", "1" if onboarding_ok else "0")
        if tema is not None:
            repo.set_ajuste("tema", tema)
        if nome_usuario is not None:
            repo.set_ajuste("nome_usuario", nome_usuario.strip())
        return {"ok": True}

    def listar_orcamentos(self):
        return [
            {"categoria_id": o["categoria_id"], "categoria_nome": o.get("categoria_nome"),
             "categoria_icone": o.get("categoria_icone"), "limite": _reais(o["limite_cents"])}
            for o in repo.listar_orcamentos()
        ]

    def salvar_orcamento(self, categoria_id, limite):
        repo.salvar_orcamento(int(categoria_id), _cents(limite))
        return {"ok": True}

    # -------------------- Alertas --------------------
    def listar_alertas(self):
        return alerts.listar_alertas()

    def marcar_alertas_lidos(self):
        alerts.marcar_todos_lidos()
        return {"ok": True}

    # -------------------- Relatórios --------------------
    def exportar_excel(self, mes=None, data_inicio=None, data_fim=None):
        try:
            caminho = reports.exportar_excel(mes, data_inicio, data_fim)
        except Exception:
            log.exception("Falha ao exportar Excel (mes=%s, periodo=%s..%s)", mes, data_inicio, data_fim)
            return {"ok": False, "erro": "Não consegui gerar o Excel. Tente novamente."}
        log.info("Excel exportado: %s", caminho)
        _abrir_arquivo(caminho)
        return {"ok": True, "caminho": caminho}

    def exportar_pdf(self, mes=None, data_inicio=None, data_fim=None):
        try:
            caminho = reports.exportar_pdf(mes, data_inicio, data_fim)
        except Exception:
            log.exception("Falha ao exportar PDF (mes=%s, periodo=%s..%s)", mes, data_inicio, data_fim)
            return {"ok": False, "erro": "Não consegui gerar o PDF. Tente novamente."}
        log.info("PDF exportado: %s", caminho)
        _abrir_arquivo(caminho)
        return {"ok": True, "caminho": caminho}

    def abrir_pasta_relatorios(self):
        _abrir_arquivo(reports.REL_DIR)
        return {"ok": True}

    # -------------------- Cartões de crédito --------------------
    def listar_cartoes(self):
        return [
            {"id": c["id"], "nome": c["nome"], "limite": _reais(c["limite_cents"]),
             "dia_fechamento": c["dia_fechamento"], "dia_vencimento": c["dia_vencimento"],
             "cor": c["cor"], "icone": c["icone"],
             "limite_usado": _reais(c["limite_usado_cents"]),
             "limite_disponivel": _reais(c["limite_disponivel_cents"])}
            for c in cartoes.listar_cartoes()
        ]

    def salvar_cartao(self, nome, limite, dia_fechamento, dia_vencimento,
                      cor="#6B4FBB", icone="💳", cartao_id=None):
        if not nome or not nome.strip():
            return {"ok": False, "erro": "Dê um nome para o cartão."}
        dia_f, dia_v = int(dia_fechamento), int(dia_vencimento)
        if not (1 <= dia_f <= 28) or not (1 <= dia_v <= 28):
            return {"ok": False, "erro": "Use um dia entre 1 e 28 para fechamento/vencimento."}
        cents = _cents(limite)
        try:
            if cartao_id:
                cartao_id = int(cartao_id)
                cartoes.atualizar_cartao(cartao_id, nome=nome, limite_cents=cents,
                                          dia_fechamento=dia_f, dia_vencimento=dia_v, cor=cor, icone=icone)
                log.info("Cartão #%s atualizado: %s", cartao_id, nome)
                return {"ok": True, "id": cartao_id}
            cid = cartoes.criar_cartao(nome, cents, dia_f, dia_v, cor, icone)
            log.info("Cartão #%s criado: %s", cid, nome)
            return {"ok": True, "id": cid}
        except Exception:
            log.warning("Falha ao salvar cartão %r", nome, exc_info=True)
            return {"ok": False, "erro": "Já existe um cartão com esse nome."}

    def excluir_cartao(self, cartao_id):
        cartao_id = int(cartao_id)
        if cartoes.cartao_tem_compras(cartao_id):
            return {"ok": False, "erro":
                     "Esse cartão tem compras vinculadas. Apague-as antes de remover o cartão."}
        cartoes.excluir_cartao(cartao_id)
        log.info("Cartão #%s excluído", cartao_id)
        return {"ok": True}

    def registrar_compra_cartao(self, cartao_id, descricao, categoria_id, valor_total,
                                parcelas_total, data_compra=None):
        if not descricao or not descricao.strip():
            return {"ok": False, "erro": "Descreva a compra."}
        cents = _cents(valor_total)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        cat_id = int(categoria_id) if categoria_id else None
        compra_id = cartoes.criar_compra(int(cartao_id), descricao, cat_id, cents, parcelas_total, data_compra)
        if compra_id is None:
            return {"ok": False, "erro": "Cartão não encontrado."}
        log.info("Compra #%s registrada no cartão #%s", compra_id, cartao_id)
        return {"ok": True, "id": compra_id}

    def listar_compras_cartao(self, cartao_id):
        return [
            {"id": c["id"], "descricao": c["descricao"], "valor_total": _reais(c["valor_total_cents"]),
             "parcelas_total": c["parcelas_total"],
             "categoria_nome": c.get("categoria_nome") or "Sem categoria",
             "categoria_icone": c.get("categoria_icone") or "📦"}
            for c in cartoes.listar_compras(int(cartao_id))
        ]

    def fatura_cartao(self, cartao_id, mes=None):
        f = cartoes.fatura(int(cartao_id), mes)
        return {
            "mes": f["mes"], "total": _reais(f["total_cents"]), "paga": f["paga"],
            "parcelas": [
                {"id": p["id"], "descricao": p["descricao"], "numero": p["numero"],
                 "parcelas_total": p["parcelas_total"], "valor": _reais(p["valor_cents"]),
                 "paga": bool(p["paga"]), "categoria_nome": p.get("categoria_nome") or "Sem categoria",
                 "categoria_icone": p.get("categoria_icone") or "📦"}
                for p in f["parcelas"]
            ],
        }

    def pagar_fatura_cartao(self, cartao_id, mes, conta_id):
        r = cartoes.pagar_fatura(int(cartao_id), mes, int(conta_id))
        if r is None:
            return {"ok": False, "erro": "Não há fatura em aberto nesse mês."}
        log.info("Fatura do cartão #%s (%s) paga via conta #%s", cartao_id, mes, conta_id)
        return {"ok": True, "total": _reais(r["total_cents"])}

    # -------------------- Investimentos --------------------
    def listar_investimentos(self):
        c = investimentos.carteira()
        return {
            "total_investido": _reais(c["total_investido_cents"]),
            "total_mercado": _reais(c["total_mercado_cents"]),
            "rentabilidade": _reais(c["rentabilidade_cents"]),
            "rentabilidade_pct": round(c["rentabilidade_pct"], 2),
            "por_tipo": [{"tipo": t["tipo"], "valor": _reais(t["valor_cents"])} for t in c["por_tipo"]],
            "ativos": [
                {"id": a["id"], "tipo": a["tipo"], "nome": a["nome"], "corretora": a["corretora"],
                 "ticker": a["ticker"], "quantidade": a["quantidade"],
                 "preco_medio": _reais(a["preco_medio_cents"]),
                 "indexador": a["indexador"], "vencimento": a["vencimento"],
                 "valor_investido": _reais(a["valor_investido_cents"]),
                 "valor_mercado": _reais(a["valor_mercado_cents"]),
                 "rentabilidade": _reais(a["rentabilidade_cents"]),
                 "rentabilidade_pct": round(a["rentabilidade_pct"], 2),
                 "preco_atual": _reais(a["preco_atual_cents"]) if a["preco_atual_cents"] is not None else None}
                for a in c["ativos"]
            ],
        }

    def criar_investimento(self, tipo, nome, corretora="", ticker=None, indexador="",
                           vencimento=None, meta_id=None):
        if not nome or not nome.strip():
            return {"ok": False, "erro": "Dê um nome para o ativo."}
        mid = int(meta_id) if meta_id else None
        iid = investimentos.criar_investimento(tipo, nome, corretora, ticker or None,
                                                indexador, vencimento or None, mid)
        log.info("Investimento #%s criado: %s (%s, meta=%s)", iid, nome, tipo, mid)
        return {"ok": True, "id": iid}

    def excluir_investimento(self, investimento_id):
        investimentos.excluir_investimento(int(investimento_id))
        log.info("Investimento #%s excluído", investimento_id)
        return {"ok": True}

    def registrar_aporte(self, investimento_id, valor, quantidade_comprada=None, data_str=None):
        cents = _cents(valor)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        qtd = _num(quantidade_comprada) if quantidade_comprada else None
        investimentos.registrar_aporte(int(investimento_id), cents, qtd, data_str)
        return {"ok": True}

    # -------------------- Metas --------------------
    def listar_metas(self):
        return [
            {"id": m["id"], "nome": m["nome"], "prazo": m["prazo"],
             "valor_alvo": _reais(m["valor_alvo_cents"]),
             "valor_guardado": _reais(m["valor_atual_cents"]),
             "valor_vinculado": _reais(m["valor_vinculado_cents"]),
             "valor_total": _reais(m["valor_total_cents"]),
             "falta": _reais(m["falta_cents"]),
             "progresso_pct": round(m["progresso_pct"], 1),
             "meses_restantes": m["meses_restantes"],
             "por_mes": _reais(m["por_mes_cents"])}
            for m in metas.listar_metas()
        ]

    def criar_meta(self, nome, valor_alvo, prazo=None):
        if not nome or not nome.strip():
            return {"ok": False, "erro": "Dê um nome para a meta."}
        cents = _cents(valor_alvo)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor alvo maior que zero."}
        mid = metas.criar_meta(nome, cents, prazo or None)
        log.info("Meta #%s criada: %s", mid, nome)
        return {"ok": True, "id": mid}

    def guardar_na_meta(self, meta_id, valor):
        cents = _cents(valor)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        metas.guardar_na_meta(int(meta_id), cents)
        return {"ok": True}

    def excluir_meta(self, meta_id):
        metas.excluir_meta(int(meta_id))
        log.info("Meta #%s excluída", meta_id)
        return {"ok": True}

    # -------------------- Contas a pagar e recorrências --------------------
    def listar_contas_pagar(self):
        hoje = date.today().isoformat()
        return [
            {"id": cp["id"], "descricao": cp["descricao"], "valor": _reais(cp["valor_cents"]),
             "tipo": cp["tipo"], "vencimento": cp["vencimento"], "vencida": cp["vencimento"] < hoje,
             "categoria_nome": cp.get("categoria_nome") or "Sem categoria",
             "categoria_icone": cp.get("categoria_icone") or "📦"}
            for cp in recorrencias.listar_contas_pagar()
        ]

    def criar_conta_pagar(self, descricao, valor, tipo, vencimento, categoria_id=None):
        if not descricao or not descricao.strip():
            return {"ok": False, "erro": "Descreva a conta."}
        cents = _cents(valor)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        if not vencimento:
            return {"ok": False, "erro": "Informe o vencimento."}
        cat = int(categoria_id) if categoria_id else None
        cid = recorrencias.criar_conta_pagar(descricao, cents, tipo, vencimento, cat)
        log.info("Conta a pagar #%s criada: %s", cid, descricao)
        return {"ok": True, "id": cid}

    def pagar_conta(self, conta_pagar_id, conta_id):
        r = recorrencias.pagar_conta(int(conta_pagar_id), int(conta_id))
        if r is None:
            return {"ok": False, "erro": "Essa conta já foi paga ou não existe."}
        return {"ok": True}

    def excluir_conta_pagar(self, conta_pagar_id):
        recorrencias.excluir_conta_pagar(int(conta_pagar_id))
        return {"ok": True}

    def listar_recorrencias(self):
        return [
            {"id": r["id"], "descricao": r["descricao"], "valor": _reais(r["valor_cents"]),
             "tipo": r["tipo"], "frequencia": r["frequencia"], "proxima_data": r["proxima_data"],
             "categoria_nome": r.get("categoria_nome") or "Sem categoria",
             "conta_nome": r.get("conta_nome") or "—", "ativo": bool(r["ativo"])}
            for r in recorrencias.listar_recorrencias()
        ]

    def criar_recorrencia(self, descricao, valor, tipo, frequencia, proxima_data,
                          categoria_id=None, conta_id=None):
        if not descricao or not descricao.strip():
            return {"ok": False, "erro": "Descreva a recorrência."}
        cents = _cents(valor)
        if cents <= 0:
            return {"ok": False, "erro": "Informe um valor maior que zero."}
        if not proxima_data:
            return {"ok": False, "erro": "Informe a primeira data."}
        cat = int(categoria_id) if categoria_id else None
        cta = int(conta_id) if conta_id else None
        rid = recorrencias.criar_recorrencia(descricao, cents, tipo, frequencia, proxima_data, cat, cta)
        log.info("Recorrência #%s criada: %s (%s)", rid, descricao, frequencia)
        # se a primeira data já passou/é hoje, materializa na hora
        recorrencias.materializar()
        return {"ok": True, "id": rid}

    def excluir_recorrencia(self, recorrencia_id):
        recorrencias.excluir_recorrencia(int(recorrencia_id))
        return {"ok": True}

    # -------------------- Seus dados --------------------
    def exportar_dados(self):
        try:
            caminho = dados.exportar_tudo()
        except Exception:
            log.exception("Falha ao exportar os dados")
            return {"ok": False, "erro": "Não consegui exportar. Tente novamente."}
        _abrir_arquivo(dados.EXPORT_DIR)
        return {"ok": True, "caminho": caminho}

    def apagar_tudo(self, confirmacao):
        if (confirmacao or "").strip().lower() != "apagar":
            return {"ok": False, "erro": "Digite 'apagar' para confirmar."}
        dados.apagar_tudo()
        return {"ok": True}

    # -------------------- IA local --------------------
    def ia_status(self):
        st = llm.status()
        rec = llm.modelos_recomendados()
        return {
            "disponivel": st["disponivel"],
            "instalados": st["instalados"],
            "ram_gb": rec["ram_gb"],
            "recomendados": rec["modelos"],
            "modelo_ativo": repo.get_ajuste("modelo_ia", ""),
        }

    def ia_conversar(self, pergunta):
        return llm.conversar(pergunta)

    def baixar_modelo(self, nome):
        log.info("Usuário pediu download do modelo %s", nome)
        llm.baixar_modelo(nome)
        return {"ok": True}

    def progresso_download_modelo(self, nome):
        return llm.progresso_download(nome)
