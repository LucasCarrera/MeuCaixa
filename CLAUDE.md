# MeuCaixa — contexto do projeto

App **desktop** de finanças pessoais, **local-first, offline, um usuário só**. Todo em **português do Brasil** — código, UI, mensagens, commits.

## Stack e como rodar
- **Python + pywebview** (janela desktop carregando `frontend/index.html`). Sem framework web, sem servidor.
- **SQLite local** em `data/meucaixa.db`. **Sem nuvem, sem login, sem RLS.**
- Frontend é HTML/CSS/JS puro (sem build, sem libs). Fala com o Python pela ponte `window.pywebview.api.<metodo>`.
- IA opcional via **Ollama local** (`http://localhost:11434`) — o app funciona 100% sem ela.
- Rodar: `python run.py` (venv em `.venv/`). Interpretador: `.venv/Scripts/python.exe`.
- Windows + Git Bash. Ao rodar Python no terminal use `PYTHONIOENCODING=utf-8` senão emoji quebra o console (cp1252).

## Convenções que NÃO se quebram
- **Dinheiro é sempre `int` em CENTAVOS** no backend/DB. Converte para reais só na borda (`api.py::_reais`). Entrada do usuário vem em formato BR ("1.234,56") → `api.py::_cents`. Número genérico (quantidade) → `api.py::_num`.
- **Nada de SQL fora de `repository.py` e dos módulos de domínio** — a API não faz SQL direto.
- **Migração de schema**: sem framework. Tabelas novas entram no `SCHEMA` de `db.py` (`CREATE TABLE IF NOT EXISTS`). Colunas novas em tabelas existentes vão em `_migrar_colunas_antigas(conn)` (checa `PRAGMA table_info`, faz `ALTER TABLE ADD COLUMN`). Índices ficam em `INDICES`, rodados DEPOIS da migração de colunas. Tudo idempotente.
- **Degradação graciosa**: se Ollama/cotações/rede caem, retorna vazio/None e o app segue. Ver `llm.py`, `cotacoes.py`.
- **Logging** via `logger.py` (`get_logger(__name__)`), grava em `data/logs/`. Erros que antes eram engolidos agora são logados.

## Módulos backend (`backend/`)
- `db.py` — conexão, SCHEMA, migração, `init_db()`, conta padrão "Carteira".
- `repository.py` — CRUD de contas, categorias, transações, orçamentos; `resumo_mes`/`resumo_periodo`; `caixa_atual_cents` (= soma do saldo de todas as contas).
- `api.py` — classe `Api`, ponte para o JS. Cada método público vira `window.pywebview.api.<nome>`.
- `cartoes.py` — cartões, compras parceladas, faturas, pagamento (total/parcial). Regra de fechamento: compra depois do `dia_fechamento` → 1ª parcela no mês seguinte. Fatura pode ser escolhida manualmente no lançamento. `pagamentos_fatura` guarda pagamentos parciais; limite usado = parcelas − pagamentos.
- `investimentos.py` + `cotacoes.py` — carteira, aportes (média ponderada), rentabilidade. Cotações via **brapi.dev** (ações; sem token só resolve 1 ticker/chamada e não cobre FIIs) e **CoinGecko** (cripto, id não símbolo). Cache 5 min.
- `metas.py` — metas; valor atual = guardado manual + valor de mercado dos investimentos vinculados (`meta_id`).
- `recorrencias.py` — contas a pagar/receber + recorrências. `materializar()` roda no boot (`run.py`) gerando contas previstas até hoje.
- `alerts.py` — 6 tipos de alerta (orçamento, limite mensal, piso de caixa, anomalia, fatura de cartão, conta a pagar). `avaliar()` calcula, `gravar_alertas()` deduplica e persiste no sino.
- `reports.py` — Excel (openpyxl) e PDF (reportlab), por mês ou período livre, com seção de Cartões.
- `dados.py` — exportar tudo (JSON) e apagar tudo (reset com confirmação "apagar").
- `categorizer.py` — sugestão de categoria por aprendizado + regras + IA.
- `llm.py` — Ollama: chat (`conversar`), categorização, download de modelo com progresso. `_contexto_financeiro()` dá ao assistente resumo do mês + cartões + investimentos.

## Frontend
- `index.html` (views + modais), `app.js` (lógica), `styles.css` (variáveis em `:root`, tema escuro em `[data-theme="escuro"]`).
- Views: Início, Lançar, Histórico, Cartões, Investimentos (+ Metas), Assistente, Relatórios, Ajustes.
- Padrões reusáveis: `.barra-item`/`.barra-preench` (barras e rosca via `conic-gradient`), `.trans-item`, modais `.modal-fundo`.

## Estado atual (tudo implementado e commitado)
Fases 1–9 completas + correção/exclusão de compras + (fatura escolhida, pagamento parcial, cartões no relatório, assistente com contexto de cartões/investimentos). Ver `git log`.

## Regras de trabalho aprendidas
- **NUNCA rodar teste que escreve/apaga contra `data/meucaixa.db` (banco REAL do usuário, com dados reais).** Testar SEMPRE em banco isolado: `import backend.db as db; db.DB_PATH = <tmp>` ANTES de importar api/db. (Já houve incidente corrigido via backup.)
- Verificar mudanças **na janela real** via `webview.start(callback, window)` + `window.evaluate_js(...)`, não só testes de unidade. Usar seletores inequívocos (não `btns[0]` global).
- Fazer backup (`cp data/meucaixa.db data/meucaixa.db.bak-X`) antes de qualquer migração no banco real; remover depois de validar.
- Commits e mensagens em português, sem acento nas msgs de commit (evita ruído de encoding). Terminar com a linha `Co-Authored-By` do Claude.
- Uma fase/feature por commit. Confirmar com o usuário antes de `git push` (mas ele costuma pedir push ao fim).

## Git / GitHub
- Repo público: **github.com/LucasCarrera/MeuCaixa** (usuário `LucasCarrera`, `gh` autenticado).
- `.gitignore` ignora `data/*` (exceto `.gitkeep`), `.venv/`, `__pycache__`, `.claude/settings.local.json`. **Dados pessoais nunca vão pro repo.**
- Também existe o repo de perfil `LucasCarrera/LucasCarrera` (README de perfil com cobrinha de contribuições via Action).

## Ideias/pendências mencionadas
- Nenhuma pendência aberta no momento. O spec original tinha 14 prompts (Supabase/web) adaptados para local — se o usuário pedir "próxima fase", tudo já foi feito; novas ideias são incrementais.
