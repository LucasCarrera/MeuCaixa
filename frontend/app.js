// ============================================================================
//  MeuCaixa — lógica da interface
//  Fala com o Python pela ponte window.pywebview.api
// ============================================================================

const fmt = (v) => (v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const hoje = () => new Date().toISOString().slice(0, 10);
const mesHoje = () => new Date().toISOString().slice(0, 7);

function api() { return window.pywebview.api; }
let categorias = [];
let tipoLancamento = 'saida';

// espera a ponte Python ficar pronta
window.addEventListener('pywebviewready', iniciar);
// fallback: se já estiver pronta
if (window.pywebview && window.pywebview.api) iniciar();

async function iniciar() {
  document.getElementById('mes-atual').value = mesHoje();
  document.getElementById('l-data').value = hoje();

  configurarNavegacao();
  configurarLancamento();

  categorias = await api().listar_categorias();
  preencherSelectsCategorias();

  const aj = await api().get_ajustes();
  if (!aj.onboarding_ok) mostrarOnboarding();

  atualizarStatusIA();
  await recarregarTudo();

  document.getElementById('mes-atual').addEventListener('change', recarregarTudo);
  document.getElementById('h-busca').addEventListener('input', carregarHistorico);
  document.getElementById('h-tipo').addEventListener('change', carregarHistorico);
  document.getElementById('h-categoria').addEventListener('change', carregarHistorico);
}

function mesSelecionado() { return document.getElementById('mes-atual').value || mesHoje(); }

async function recarregarTudo() {
  await carregarDashboard();
  await carregarHistorico();
  await carregarAlertas();
}

// ---------------------------------------------------------------- Navegação
function configurarNavegacao() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('ativo'));
      btn.classList.add('ativo');
      document.querySelectorAll('.view').forEach(v => v.classList.add('escondido'));
      document.getElementById('view-' + btn.dataset.view).classList.remove('escondido');
      if (btn.dataset.view === 'ajustes') carregarAjustes();
    });
  });
}

// ---------------------------------------------------------------- Dashboard
async function carregarDashboard() {
  const d = await api().get_dashboard(mesSelecionado());
  document.getElementById('hero-caixa').textContent = fmt(d.caixa);
  document.getElementById('card-entradas').textContent = fmt(d.entradas);
  document.getElementById('card-saidas').textContent = fmt(d.saidas);
  const saldoEl = document.getElementById('card-saldo');
  saldoEl.textContent = fmt(d.saldo_mes);
  saldoEl.style.color = d.saldo_mes >= 0 ? 'var(--green)' : 'var(--red)';

  const dica = document.getElementById('hero-dica');
  if (d.saldo_mes > 0) dica.textContent = `👍 Você guardou ${fmt(d.saldo_mes)} este mês.`;
  else if (d.saldo_mes < 0) dica.textContent = `⚠️ Você gastou ${fmt(-d.saldo_mes)} a mais do que recebeu.`;
  else dica.textContent = 'Comece lançando seus ganhos e gastos.';

  // gráfico de barras
  const graf = document.getElementById('grafico-categorias');
  if (!d.por_categoria.length) {
    graf.innerHTML = '<div class="vazio">Nenhum gasto neste mês ainda.</div>';
  } else {
    const max = Math.max(...d.por_categoria.map(c => c.valor));
    graf.innerHTML = d.por_categoria.map(c => `
      <div class="barra-item">
        <div class="barra-topo">
          <span class="barra-nome">${c.icone} ${c.nome}</span>
          <span class="barra-valor">${fmt(c.valor)}</span>
        </div>
        <div class="barra-trilho"><div class="barra-preench"
          style="width:${(c.valor / max * 100).toFixed(0)}%;background:${c.cor}"></div></div>
      </div>`).join('');
  }

  document.getElementById('lista-ultimas').innerHTML =
    d.ultimas.length ? d.ultimas.map(t => itemTransacao(t, false)).join('')
                     : '<div class="vazio">Sem movimentações ainda.</div>';
}

function itemTransacao(t, comExcluir = true) {
  const sinal = t.tipo === 'entrada' ? '+' : '−';
  return `
    <div class="trans-item">
      <div class="trans-icone" style="background:${t.categoria_cor}22">${t.categoria_icone}</div>
      <div class="trans-info">
        <div class="trans-desc">${escapar(t.descricao)}</div>
        <div class="trans-meta">${t.categoria_nome} · ${formatarData(t.data)}</div>
      </div>
      <div class="trans-valor ${t.tipo}">${sinal} ${fmt(t.valor)}</div>
      ${comExcluir ? `<button class="trans-excluir" onclick="excluir(${t.id})">🗑️</button>` : ''}
    </div>`;
}

// ---------------------------------------------------------------- Lançamento
function configurarLancamento() {
  document.querySelectorAll('.tipo-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tipo-btn').forEach(b => b.classList.remove('ativo'));
      btn.classList.add('ativo');
      tipoLancamento = btn.dataset.tipo;
      preencherSelectsCategorias();
    });
  });

  let timer;
  document.getElementById('l-descricao').addEventListener('input', (e) => {
    clearTimeout(timer);
    const txt = e.target.value.trim();
    if (txt.length < 3) { document.getElementById('sugestao-cat').classList.add('escondido'); return; }
    timer = setTimeout(async () => {
      const s = await api().sugerir_categoria(txt);
      const box = document.getElementById('sugestao-cat');
      box.classList.remove('escondido');
      box.innerHTML = `💡 Parece <b>${s.categoria_nome}</b>. <a href="#" onclick="aplicarSugestao(${s.categoria_id});return false;" style="color:var(--green)">usar</a>`;
    }, 350);
  });
}

function aplicarSugestao(catId) {
  document.getElementById('l-categoria').value = catId;
  document.getElementById('sugestao-cat').classList.add('escondido');
}

function preencherSelectsCategorias() {
  const doTipo = categorias.filter(c => c.tipo === tipoLancamento);
  const sel = document.getElementById('l-categoria');
  sel.innerHTML = doTipo.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');

  const hSel = document.getElementById('h-categoria');
  const atual = hSel.value;
  hSel.innerHTML = '<option value="">Todas as categorias</option>' +
    categorias.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');
  hSel.value = atual;
}

async function salvarTransacao() {
  const valor = document.getElementById('l-valor').value;
  const desc = document.getElementById('l-descricao').value.trim();
  const cat = document.getElementById('l-categoria').value;
  const data = document.getElementById('l-data').value || hoje();
  const obs = document.getElementById('l-obs').value;
  if (!desc) return toast('Escreva com o que foi.');
  if (!valor) return toast('Informe o valor.');

  const r = await api().adicionar_transacao(data, desc, valor, tipoLancamento, cat, obs);
  if (!r.ok) return toast(r.erro || 'Não deu para salvar.');

  document.getElementById('l-valor').value = '';
  document.getElementById('l-descricao').value = '';
  document.getElementById('l-obs').value = '';
  document.getElementById('sugestao-cat').classList.add('escondido');
  toast('✅ Salvo!');
  if (r.alertas && r.alertas.length) setTimeout(() => mostrarAlertas(), 500);
  await recarregarTudo();

  // volta para o início
  document.querySelector('.nav-item[data-view="inicio"]').click();
}

async function excluir(id) {
  await api().excluir_transacao(id);
  toast('Removido.');
  await recarregarTudo();
}

// ---------------------------------------------------------------- Histórico
async function carregarHistorico() {
  const busca = document.getElementById('h-busca').value;
  const tipo = document.getElementById('h-tipo').value;
  const cat = document.getElementById('h-categoria').value;
  const rows = await api().listar_transacoes(mesSelecionado(), cat, tipo, busca);
  document.getElementById('lista-historico').innerHTML =
    rows.length ? rows.map(t => itemTransacao(t, true)).join('')
                : '<div class="vazio">Nada encontrado para este filtro.</div>';
}

// ---------------------------------------------------------------- Alertas
async function carregarAlertas() {
  const lista = await api().listar_alertas();
  const naoLidos = lista.filter(a => !a.lido).length;
  const badge = document.getElementById('badge-alertas');
  if (naoLidos > 0) { badge.textContent = naoLidos; badge.classList.remove('escondido'); }
  else badge.classList.add('escondido');
}

async function mostrarAlertas() {
  const lista = await api().listar_alertas();
  const box = document.getElementById('lista-alertas');
  box.innerHTML = lista.length
    ? lista.map(a => `<div class="alerta-item ${a.nivel}"><span>${escapar(a.mensagem)}</span></div>`).join('')
    : '<div class="vazio">Nenhum aviso por enquanto. Tudo em ordem! 🌿</div>';
  document.getElementById('modal-alertas').classList.remove('escondido');
  await api().marcar_alertas_lidos();
  carregarAlertas();
}
function fecharAlertas() { document.getElementById('modal-alertas').classList.add('escondido'); }

// ---------------------------------------------------------------- Relatórios
async function exportar(tipo) {
  toast('Gerando relatório...');
  const r = tipo === 'pdf' ? await api().exportar_pdf(mesSelecionado())
                           : await api().exportar_excel(mesSelecionado());
  if (r.ok) toast('✅ Pronto! O arquivo foi aberto.');
}

// ---------------------------------------------------------------- Assistente
async function enviarChat() {
  const input = document.getElementById('chat-input');
  const txt = input.value.trim();
  if (!txt) return;
  input.value = '';
  const box = document.getElementById('chat-mensagens');
  box.insertAdjacentHTML('beforeend', `<div class="msg user">${escapar(txt)}</div>`);
  box.insertAdjacentHTML('beforeend', `<div class="msg bot pensando" id="pensando">pensando...</div>`);
  box.scrollTop = box.scrollHeight;

  const r = await api().ia_conversar(txt);
  document.getElementById('pensando').remove();
  box.insertAdjacentHTML('beforeend', `<div class="msg bot">${escapar(r.resposta)}</div>`);
  box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- Ajustes
async function carregarAjustes() {
  const aj = await api().get_ajustes();
  document.getElementById('a-saldo').value = aj.saldo_inicial ? aj.saldo_inicial.toFixed(2).replace('.', ',') : '';
  document.getElementById('a-piso').value = aj.piso_caixa ? aj.piso_caixa.toFixed(2).replace('.', ',') : '';
  document.getElementById('a-limite').value = aj.limite_mensal ? aj.limite_mensal.toFixed(2).replace('.', ',') : '';

  // orçamentos
  const orcs = await api().listar_orcamentos();
  const mapaOrc = {};
  orcs.forEach(o => mapaOrc[o.categoria_id] = o.limite);
  const box = document.getElementById('lista-orcamentos');
  box.innerHTML = categorias.filter(c => c.tipo === 'saida').map(c => `
    <div class="orc-item">
      <span class="orc-nome">${c.icone} ${c.nome}</span>
      <div class="campo-moeda pequeno" style="width:130px"><span>R$</span>
        <input type="text" inputmode="decimal" data-cat="${c.id}"
          value="${mapaOrc[c.id] ? mapaOrc[c.id].toFixed(2).replace('.', ',') : ''}"
          placeholder="sem limite" onchange="salvarOrcamento(${c.id}, this.value)"></div>
    </div>`).join('');

  // categorias
  document.getElementById('lista-categorias').innerHTML = categorias.map(c => `
    <span class="chip">${c.icone} ${c.nome}
      ${c.padrao ? '' : `<button onclick="removerCategoria(${c.id})">✕</button>`}</span>`).join('');

  carregarConfigIA();
}

async function salvarAjustesGerais() {
  await api().salvar_ajustes(
    document.getElementById('a-saldo').value || '0',
    document.getElementById('a-piso').value || '0',
    document.getElementById('a-limite').value || '0'
  );
  toast('✅ Ajustes salvos.');
  recarregarTudo();
}
async function salvarOrcamento(catId, valor) {
  await api().salvar_orcamento(catId, valor || '0');
  toast('Limite atualizado.');
}
async function criarCategoria() {
  const nome = document.getElementById('nc-nome').value.trim();
  const tipo = document.getElementById('nc-tipo').value;
  if (!nome) return toast('Dê um nome.');
  const r = await api().criar_categoria(nome, tipo);
  if (!r.ok) return toast(r.erro);
  document.getElementById('nc-nome').value = '';
  categorias = await api().listar_categorias();
  preencherSelectsCategorias();
  carregarAjustes();
  toast('✅ Categoria criada.');
}
async function removerCategoria(id) {
  await api().excluir_categoria(id);
  categorias = await api().listar_categorias();
  preencherSelectsCategorias();
  carregarAjustes();
}

// ---------------------------------------------------------------- IA config
let downloadsModelo = {};
let downloadInterval = null;

async function atualizarStatusIA() {
  const st = await api().ia_status();
  const badge = document.getElementById('ia-badge');
  badge.classList.toggle('ligada', st.disponivel);
  badge.classList.toggle('desligada', !st.disponivel);
}

async function carregarConfigIA() {
  const st = await api().ia_status();
  const box = document.getElementById('ia-config');
  const statusTxt = st.disponivel
    ? `<div class="ia-status-txt on">✅ Ollama conectado. Memória detectada: ${st.ram_gb} GB.</div>`
    : `<div class="ia-status-txt off">⚠️ Ollama não encontrado. Instale em <span class="mono">ollama.com</span> e abra o programa para ativar o chat.</div>`;

  const modelos = st.recomendados.map(m => {
    const instalado = st.instalados.some(i => i.startsWith(m.nome));
    const ativo = st.modelo_ativo === m.nome;
    const dl = downloadsModelo[m.nome];

    let acao;
    if (dl && dl.rodando) {
      acao = `<div class="barra-item" style="width:160px">
        <div class="barra-topo"><span class="barra-nome">Baixando...</span>
          <span class="barra-valor">${dl.percentual}%</span></div>
        <div class="barra-trilho"><div class="barra-preench"
          style="width:${dl.percentual}%;background:var(--green)"></div></div>
      </div>`;
    } else if (!instalado) {
      acao = `<button class="btn-medio" style="margin:0" onclick="baixarModelo('${m.nome}')">
        Baixar e usar</button>`;
    } else {
      acao = `<button class="btn-medio" style="margin:0" onclick="escolherModelo('${m.nome}')">
        ${ativo ? 'Em uso' : 'Usar este'}</button>`;
    }

    return `<div class="modelo-card ${ativo ? 'sel' : ''}">
      <div class="modelo-info">
        <b>${m.rotulo}</b>
        <small><span class="mono">${m.nome}</span> · precisa ~${m.min_ram}GB
          ${m.cabe ? '' : '· pesado pra sua máquina'} ${instalado ? '· ✅ instalado' : ''}</small>
      </div>
      ${acao}
    </div>`;
  }).join('');

  box.innerHTML = statusTxt +
    `<p class="sub" style="margin:12px 0 4px">Escolha o modelo conforme seu computador:</p>` +
    modelos;
}

async function escolherModelo(nome) {
  await api().salvar_ajustes(null, null, null, nome);
  toast('Modelo escolhido: ' + nome);
  carregarConfigIA();
  atualizarStatusIA();
}

async function baixarModelo(nome) {
  await api().baixar_modelo(nome);
  downloadsModelo[nome] = { rodando: true, concluido: false, erro: null, percentual: 0 };
  toast('Baixando ' + nome + '... isso pode levar alguns minutos.');
  carregarConfigIA();
  if (!downloadInterval) downloadInterval = setInterval(atualizarDownloadsModelo, 1500);
}

async function atualizarDownloadsModelo() {
  let algumRodando = false;
  for (const nome of Object.keys(downloadsModelo)) {
    const p = await api().progresso_download_modelo(nome);
    if (p.concluido) {
      delete downloadsModelo[nome];
      toast('✅ Modelo baixado: ' + nome);
      await escolherModelo(nome);
      continue;
    }
    if (!p.rodando && p.erro) {
      delete downloadsModelo[nome];
      toast('⚠️ Não consegui baixar ' + nome + '.');
      continue;
    }
    downloadsModelo[nome] = p;
    algumRodando = true;
  }
  carregarConfigIA();
  if (!algumRodando && downloadInterval) {
    clearInterval(downloadInterval);
    downloadInterval = null;
  }
}

// ---------------------------------------------------------------- Onboarding
const ob = {
  passo: 1,
  mostrar() { document.getElementById('onboarding').classList.remove('escondido'); },
  ir(n) {
    document.querySelectorAll('.ob-passo').forEach(p => p.classList.add('escondido'));
    document.querySelector(`.ob-passo[data-passo="${n}"]`).classList.remove('escondido');
    this.passo = n;
  },
  proximo() { this.ir(this.passo + 1); },
  async finalizar() {
    await api().salvar_ajustes(
      document.getElementById('ob-saldo').value || '0',
      document.getElementById('ob-piso').value || '0',
      document.getElementById('ob-limite').value || '0',
      null, true
    );
    document.getElementById('onboarding').classList.add('escondido');
    toast('🌱 Tudo pronto! Bem-vindo.');
    recarregarTudo();
  }
};
function mostrarOnboarding() { ob.ir(1); ob.mostrar(); }

// ---------------------------------------------------------------- Utilitários
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.remove('escondido');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add('escondido'), 2600);
}
function escapar(s) {
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}
function formatarData(iso) {
  const [a, m, d] = iso.split('-');
  return `${d}/${m}`;
}
