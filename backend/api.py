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
        # só avalia para exibir; a gravação no sino acontece ao lançar transações
        avaliados = alerts.avaliar(mes)
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

    def criar_categoria(self, nome, tipo, icone="💰", cor="#1B7A5A"):
        if not nome.strip():
            return {"ok": False, "erro": "Dê um nome para a categoria."}
        try:
            cid = repo.criar_categoria(nome, tipo, icone, cor)
            log.info("Categoria #%s criada: %s (%s)", cid, nome, tipo)
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
        }

    def salvar_ajustes(self, saldo_inicial=None, piso_caixa=None, limite_mensal=None,
                       modelo_ia=None, onboarding_ok=None):
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
    def exportar_excel(self, mes=None):
        try:
            caminho = reports.exportar_excel(mes)
        except Exception:
            log.exception("Falha ao exportar Excel do mês %s", mes)
            return {"ok": False, "erro": "Não consegui gerar o Excel. Tente novamente."}
        log.info("Excel exportado: %s", caminho)
        _abrir_arquivo(caminho)
        return {"ok": True, "caminho": caminho}

    def exportar_pdf(self, mes=None):
        try:
            caminho = reports.exportar_pdf(mes)
        except Exception:
            log.exception("Falha ao exportar PDF do mês %s", mes)
            return {"ok": False, "erro": "Não consegui gerar o PDF. Tente novamente."}
        log.info("PDF exportado: %s", caminho)
        _abrir_arquivo(caminho)
        return {"ok": True, "caminho": caminho}

    def abrir_pasta_relatorios(self):
        _abrir_arquivo(reports.REL_DIR)
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
