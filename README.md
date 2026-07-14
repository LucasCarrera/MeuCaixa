# 🌱 MeuCaixa

Controle financeiro pessoal **local-first**: seus dados ficam só no seu computador,
num banco SQLite. Feito para quem **não entende de finanças nem de tecnologia**
começar a usar em minutos.

- ✅ Lançar ganhos e gastos em 2 toques
- 🤖 **Categorização automática** (aprende com o seu uso)
- 💬 **Assistente com IA local** (via Ollama) que conversa sobre o seu dinheiro
- 🔔 **Alertas** de orçamento estourado, limite do mês e reserva mínima (piso de caixa)
- 📄 **Relatórios em PDF e Excel**
- 🔒 Nada sai da sua máquina

---

## Como rodar (Windows)

### 1. Instale o Python 3.10+
Baixe em [python.org](https://www.python.org/downloads/). Na instalação, marque
**"Add Python to PATH"**.

### 2. Instale as dependências
Abra o **Prompt de Comando** dentro da pasta do projeto e rode:

```bat
pip install -r requirements.txt
```

### 3. Abra o app

```bat
python run.py
```

Uma janela vai abrir. Na primeira vez, um pequeno passo a passo te ajuda a começar.

> No Windows 10/11 o app usa o WebView2 (Edge), que já vem instalado. Não precisa de navegador extra.

---

## Ativar a IA local (opcional)

O app funciona 100% sem IA. Para ligar o **assistente que conversa**:

1. Instale o **Ollama** em [ollama.com](https://ollama.com) e abra o programa.
2. Baixe um modelo (escolha conforme seu PC). No Prompt de Comando:
   ```bat
   ollama pull llama3.2:3b
   ```
   - PC simples: `llama3.2:1b` ou `qwen2.5:0.5b`
   - PC comum (8GB): `llama3.2:3b` *(recomendado)*
   - PC bom (16GB+): `qwen2.5:7b`
3. No MeuCaixa, vá em **Ajustes → IA local** e clique em **"Usar este"** no modelo baixado.

Pronto: a aba **Assistente** passa a responder sobre os seus gastos.

---

## Estrutura do projeto

```
MeuCaixa/
├── run.py                 # abre a janela do app
├── requirements.txt
├── backend/
│   ├── db.py              # banco SQLite + schema
│   ├── repository.py      # acesso a dados e resumos
│   ├── categorizer.py     # categorização (regras + aprendizado + IA)
│   ├── alerts.py          # motor de alertas
│   ├── reports.py         # relatórios PDF e Excel
│   ├── llm.py             # integração com Ollama (IA local)
│   └── api.py             # ponte com a interface
├── frontend/
│   ├── index.html         # telas
│   ├── styles.css         # visual
│   └── app.js             # interações
└── data/                  # criado ao rodar (banco + relatórios)
```

Os relatórios são salvos em `data/relatorios/`.

---

## Notas de segurança

- Tudo é local: nenhum dado é enviado para a internet.
- Valores em dinheiro são guardados em **centavos (inteiro)** para nunca ter erro de arredondamento.
- Faça backup copiando o arquivo `data/meucaixa.db`.
