// ============================================================================
//  MeuCaixa — lógica da interface
//  Fala com o Python pela ponte window.pywebview.api
// ============================================================================

const fmt = (v) => (v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const hoje = () => new Date().toISOString().slice(0, 10);
const mesHoje = () => new Date().toISOString().slice(0, 7);

function api() { return window.pywebview.api; }
let categorias = [];
let contas = [];
let tipoLancamento = 'saida';

const TIPOS_CONTA = { corrente: 'Conta corrente', poupanca: 'Poupança', dinheiro: 'Dinheiro', digital: 'Conta digital' };

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

  contas = await api().listar_contas();
  preencherSelectsConta();

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
      if (btn.dataset.view === 'cartoes') carregarCartoes();
      if (btn.dataset.view === 'investimentos') carregarInvestimentos();
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
        <div class="trans-meta">${t.categoria_nome} · ${t.conta_icone} ${t.conta_nome} · ${formatarData(t.data)}</div>
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

function rotuloCategoria(c) {
  return `${c.categoria_pai_id ? '— ' : ''}${c.icone} ${c.nome}`;
}

function preencherSelectsCategorias() {
  const doTipo = categorias.filter(c => c.tipo === tipoLancamento);
  const sel = document.getElementById('l-categoria');
  sel.innerHTML = doTipo.map(c => `<option value="${c.id}">${rotuloCategoria(c)}</option>`).join('');

  const hSel = document.getElementById('h-categoria');
  const atual = hSel.value;
  hSel.innerHTML = '<option value="">Todas as categorias</option>' +
    categorias.map(c => `<option value="${c.id}">${rotuloCategoria(c)}</option>`).join('');
  hSel.value = atual;
}

function preencherSelectsConta() {
  const opcoes = contas.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');
  const sel = document.getElementById('l-conta');
  if (sel) sel.innerHTML = opcoes;
}

async function salvarTransacao() {
  const valor = document.getElementById('l-valor').value;
  const desc = document.getElementById('l-descricao').value.trim();
  const cat = document.getElementById('l-categoria').value;
  const conta = document.getElementById('l-conta').value;
  const data = document.getElementById('l-data').value || hoje();
  const obs = document.getElementById('l-obs').value;
  if (!desc) return toast('Escreva com o que foi.');
  if (!valor) return toast('Informe o valor.');

  const r = await api().adicionar_transacao(data, desc, valor, tipoLancamento, cat, conta, obs);
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
  document.getElementById('a-piso').value = aj.piso_caixa ? aj.piso_caixa.toFixed(2).replace('.', ',') : '';
  document.getElementById('a-limite').value = aj.limite_mensal ? aj.limite_mensal.toFixed(2).replace('.', ',') : '';

  await carregarContas();

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
    <span class="chip">${c.categoria_pai_id ? '↳ ' : ''}${c.icone} ${c.nome}
      ${c.padrao ? '' : `<button onclick="removerCategoria(${c.id})">✕</button>`}</span>`).join('');

  atualizarSelectPaiCategoria();
  carregarConfigIA();
}

function atualizarSelectPaiCategoria() {
  const tipo = document.getElementById('nc-tipo').value;
  const raizes = categorias.filter(c => c.tipo === tipo && !c.categoria_pai_id);
  document.getElementById('nc-pai').innerHTML =
    '<option value="">Subcategoria de (opcional)</option>' +
    raizes.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');
}

async function salvarAjustesGerais() {
  await api().salvar_ajustes(
    null,
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
  const pai = document.getElementById('nc-pai').value || null;
  if (!nome) return toast('Dê um nome.');
  const r = await api().criar_categoria(nome, tipo, '💰', '#1B7A5A', pai);
  if (!r.ok) return toast(r.erro);
  document.getElementById('nc-nome').value = '';
  document.getElementById('nc-pai').value = '';
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

// ---------------------------------------------------------------- Contas
async function carregarContas() {
  contas = await api().listar_contas();
  preencherSelectsConta();

  document.getElementById('lista-contas').innerHTML = contas.map(c => `
    <div class="conta-item">
      <span class="conta-icone">${c.icone}</span>
      <div class="conta-info">
        <div class="conta-nome">${escapar(c.nome)}</div>
        <div class="conta-tipo">${TIPOS_CONTA[c.tipo] || c.tipo}</div>
      </div>
      <div class="conta-saldo">${fmt(c.saldo_atual)}</div>
      <button class="trans-excluir" onclick="abrirModalConta(${c.id})">✏️</button>
      <button class="trans-excluir" onclick="removerConta(${c.id})">🗑️</button>
    </div>`).join('');
}

function abrirModalConta(id) {
  const c = id ? contas.find(c => c.id === id) : null;
  document.getElementById('mc-titulo').textContent = c ? 'Editar conta' : 'Nova conta';
  document.getElementById('mc-id').value = c ? c.id : '';
  document.getElementById('mc-nome').value = c ? c.nome : '';
  document.getElementById('mc-tipo').value = c ? c.tipo : 'corrente';
  document.getElementById('mc-saldo').value = c ? c.saldo_inicial.toFixed(2).replace('.', ',') : '';
  document.getElementById('modal-conta').classList.remove('escondido');
}
function fecharModalConta() { document.getElementById('modal-conta').classList.add('escondido'); }

async function salvarContaModal() {
  const id = document.getElementById('mc-id').value || null;
  const nome = document.getElementById('mc-nome').value.trim();
  const tipo = document.getElementById('mc-tipo').value;
  const saldo = document.getElementById('mc-saldo').value || '0';
  if (!nome) return toast('Dê um nome pra conta.');

  const r = await api().salvar_conta(nome, tipo, saldo, '#1B7A5A', '💼', id);
  if (!r.ok) return toast(r.erro || 'Não deu para salvar.');
  fecharModalConta();
  toast('✅ Conta salva.');
  await carregarContas();
  await recarregarTudo();
}

async function removerConta(id) {
  const r = await api().excluir_conta(id);
  if (!r.ok) return toast(r.erro);
  toast('Conta removida.');
  await carregarContas();
  await recarregarTudo();
}

function abrirModalTransferencia() {
  const opcoes = contas.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');
  document.getElementById('tr-origem').innerHTML = opcoes;
  document.getElementById('tr-destino').innerHTML = opcoes;
  document.getElementById('tr-valor').value = '';
  document.getElementById('tr-data').value = hoje();
  document.getElementById('modal-transferencia').classList.remove('escondido');
}
function fecharModalTransferencia() { document.getElementById('modal-transferencia').classList.add('escondido'); }

async function confirmarTransferencia() {
  const origem = document.getElementById('tr-origem').value;
  const destino = document.getElementById('tr-destino').value;
  const valor = document.getElementById('tr-valor').value;
  const data = document.getElementById('tr-data').value || hoje();
  if (!valor) return toast('Informe o valor.');

  const r = await api().criar_transferencia(origem, destino, valor, data);
  if (!r.ok) return toast(r.erro || 'Não deu para transferir.');
  fecharModalTransferencia();
  toast('✅ Transferência feita.');
  await carregarContas();
  await recarregarTudo();
}

// ---------------------------------------------------------------- Cartões
let cartoesCache = [];

async function carregarCartoes() {
  cartoesCache = await api().listar_cartoes();
  const mes = mesHoje();
  const box = document.getElementById('lista-cartoes');

  if (!cartoesCache.length) {
    box.innerHTML = '<div class="card"><div class="vazio">Nenhum cartão cadastrado ainda.</div></div>';
    return;
  }

  const partes = await Promise.all(cartoesCache.map(async c => {
    const fat = await api().fatura_cartao(c.id, mes);
    const pctLimite = c.limite > 0 ? Math.min(100, (c.limite_usado / c.limite) * 100) : 0;
    const corBarra = c.limite_usado > c.limite ? 'var(--red)' : c.cor;

    const parcelasHtml = fat.parcelas.length
      ? fat.parcelas.map(p => `
          <div class="trans-item">
            <div class="trans-icone" style="background:${c.cor}22">${p.categoria_icone}</div>
            <div class="trans-info">
              <div class="trans-desc">${escapar(p.descricao)}</div>
              <div class="trans-meta">${p.categoria_nome} · parcela ${p.numero}/${p.parcelas_total}</div>
            </div>
            <div class="trans-valor saida">${fmt(p.valor)}</div>
          </div>`).join('')
      : '<div class="vazio">Nenhuma compra nessa fatura.</div>';

    return `
      <div class="card">
        <div class="cartao-topo">
          <span class="cartao-icone">${c.icone}</span>
          <div class="cartao-info">
            <h3>${escapar(c.nome)}</h3>
            <small>Fecha dia ${c.dia_fechamento} · Vence dia ${c.dia_vencimento}</small>
          </div>
          <div class="cartao-acoes">
            <button onclick="abrirModalCartao(${c.id})">✏️</button>
            <button onclick="removerCartao(${c.id})">🗑️</button>
          </div>
        </div>

        <div class="barra-item">
          <div class="barra-topo">
            <span class="barra-nome">Limite usado</span>
            <span class="barra-valor">${fmt(c.limite_usado)} de ${fmt(c.limite)}</span>
          </div>
          <div class="barra-trilho"><div class="barra-preench"
            style="width:${pctLimite}%;background:${corBarra}"></div></div>
        </div>

        <div class="cartao-fatura-titulo">Fatura de ${formatarMes(mes)}</div>
        <div class="lista-trans">${parcelasHtml}</div>

        <div class="cartao-rodape">
          <b>Total da fatura: ${fmt(fat.total)}</b>
          <div style="display:flex; gap:8px">
            <button class="btn-medio" style="margin:0" onclick="abrirModalCompraCartao(${c.id})">➕ Nova compra</button>
            ${!fat.paga && fat.total > 0
              ? `<button class="btn-medio" style="margin:0" onclick="abrirModalPagarFatura(${c.id}, '${mes}', ${fat.total})">Pagar fatura</button>`
              : ''}
          </div>
        </div>
      </div>`;
  }));

  box.innerHTML = partes.join('');
}

function formatarMes(ym) {
  const [ano, mes] = ym.split('-');
  const nomes = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  return `${nomes[parseInt(mes, 10)]}/${ano}`;
}

function abrirModalCartao(id) {
  const c = id ? cartoesCache.find(c => c.id === id) : null;
  document.getElementById('mca-titulo').textContent = c ? 'Editar cartão' : 'Novo cartão';
  document.getElementById('mca-id').value = c ? c.id : '';
  document.getElementById('mca-nome').value = c ? c.nome : '';
  document.getElementById('mca-limite').value = c ? c.limite.toFixed(2).replace('.', ',') : '';
  document.getElementById('mca-fechamento').value = c ? c.dia_fechamento : 1;
  document.getElementById('mca-vencimento').value = c ? c.dia_vencimento : 10;
  document.getElementById('modal-cartao').classList.remove('escondido');
}
function fecharModalCartao() { document.getElementById('modal-cartao').classList.add('escondido'); }

async function salvarCartaoModal() {
  const id = document.getElementById('mca-id').value || null;
  const nome = document.getElementById('mca-nome').value.trim();
  const limite = document.getElementById('mca-limite').value || '0';
  const fechamento = document.getElementById('mca-fechamento').value;
  const vencimento = document.getElementById('mca-vencimento').value;
  if (!nome) return toast('Dê um nome pro cartão.');

  const r = await api().salvar_cartao(nome, limite, fechamento, vencimento, '#6B4FBB', '💳', id);
  if (!r.ok) return toast(r.erro || 'Não deu para salvar.');
  fecharModalCartao();
  toast('✅ Cartão salvo.');
  await carregarCartoes();
}

async function removerCartao(id) {
  const r = await api().excluir_cartao(id);
  if (!r.ok) return toast(r.erro);
  toast('Cartão removido.');
  await carregarCartoes();
}

function abrirModalCompraCartao(cartaoId) {
  document.getElementById('mcc-cartao-id').value = cartaoId;
  document.getElementById('mcc-descricao').value = '';
  document.getElementById('mcc-valor').value = '';
  document.getElementById('mcc-parcelas').value = 1;
  document.getElementById('mcc-data').value = hoje();
  const doTipoSaida = categorias.filter(c => c.tipo === 'saida');
  document.getElementById('mcc-categoria').innerHTML =
    doTipoSaida.map(c => `<option value="${c.id}">${rotuloCategoria(c)}</option>`).join('');
  document.getElementById('modal-compra-cartao').classList.remove('escondido');
}
function fecharModalCompraCartao() { document.getElementById('modal-compra-cartao').classList.add('escondido'); }

async function confirmarCompraCartao() {
  const cartaoId = document.getElementById('mcc-cartao-id').value;
  const descricao = document.getElementById('mcc-descricao').value.trim();
  const categoria = document.getElementById('mcc-categoria').value;
  const valor = document.getElementById('mcc-valor').value;
  const parcelas = document.getElementById('mcc-parcelas').value || 1;
  const data = document.getElementById('mcc-data').value || hoje();
  if (!descricao) return toast('Descreva a compra.');
  if (!valor) return toast('Informe o valor.');

  const r = await api().registrar_compra_cartao(cartaoId, descricao, categoria, valor, parcelas, data);
  if (!r.ok) return toast(r.erro || 'Não deu para registrar.');
  fecharModalCompraCartao();
  toast('✅ Compra registrada.');
  await carregarCartoes();
}

function abrirModalPagarFatura(cartaoId, mes, totalReais) {
  document.getElementById('mpf-cartao-id').value = cartaoId;
  document.getElementById('mpf-mes').value = mes;
  document.getElementById('mpf-resumo').textContent =
    `Total da fatura de ${formatarMes(mes)}: ${fmt(totalReais)}`;
  document.getElementById('mpf-conta').innerHTML =
    contas.map(c => `<option value="${c.id}">${c.icone} ${c.nome}</option>`).join('');
  document.getElementById('modal-pagar-fatura').classList.remove('escondido');
}
function fecharModalPagarFatura() { document.getElementById('modal-pagar-fatura').classList.add('escondido'); }

async function confirmarPagarFatura() {
  const cartaoId = document.getElementById('mpf-cartao-id').value;
  const mes = document.getElementById('mpf-mes').value;
  const conta = document.getElementById('mpf-conta').value;

  const r = await api().pagar_fatura_cartao(cartaoId, mes, conta);
  if (!r.ok) return toast(r.erro || 'Não deu para pagar a fatura.');
  fecharModalPagarFatura();
  toast('✅ Fatura paga.');
  await carregarCartoes();
  await carregarContas();
  await recarregarTudo();
}

// ---------------------------------------------------------------- Investimentos
let investimentosCache = [];

const TIPOS_INVEST = {
  renda_fixa:  { label: 'Renda fixa',  cor: '#1B7A5A', icone: '🏦' },
  acao:        { label: 'Ações',       cor: '#3B6FB0', icone: '📈' },
  fii:         { label: 'FIIs',        cor: '#C9741E', icone: '🏢' },
  cripto:      { label: 'Cripto',      cor: '#8E44AD', icone: '₿' },
  fundo:       { label: 'Fundos',      cor: '#2A9D8F', icone: '📊' },
  previdencia: { label: 'Previdência', cor: '#6B7772', icone: '🛡️' },
};

async function carregarInvestimentos() {
  const c = await api().listar_investimentos();
  investimentosCache = c.ativos;

  document.getElementById('inv-total-investido').textContent = fmt(c.total_investido);
  document.getElementById('inv-total-mercado').textContent = fmt(c.total_mercado);
  const rentEl = document.getElementById('inv-rentabilidade');
  const sinalRent = c.rentabilidade >= 0 ? '+' : '';
  rentEl.textContent = `${sinalRent}${fmt(c.rentabilidade)} (${sinalRent}${c.rentabilidade_pct}%)`;
  rentEl.style.color = c.rentabilidade >= 0 ? 'var(--green)' : 'var(--red)';

  document.getElementById('inv-rosca').innerHTML = renderRosca(c.por_tipo, c.total_mercado);

  const lista = document.getElementById('lista-investimentos');
  lista.innerHTML = c.ativos.length ? c.ativos.map(a => {
    const info = TIPOS_INVEST[a.tipo] || { label: a.tipo, icone: '💰' };
    const sinal = a.rentabilidade >= 0 ? '+' : '';
    return `
      <div class="ativo-item">
        <div class="ativo-icone">${info.icone}</div>
        <div class="ativo-info">
          <div class="ativo-nome">${escapar(a.nome)}</div>
          <div class="ativo-meta">${info.label}${a.corretora ? ' · ' + escapar(a.corretora) : ''}${a.ticker ? ' · ' + escapar(a.ticker) : ''}</div>
        </div>
        <div class="ativo-valores">
          <div class="valor">${fmt(a.valor_mercado)}</div>
          <div class="ativo-rent ${a.rentabilidade >= 0 ? 'pos' : 'neg'}">${sinal}${fmt(a.rentabilidade)} (${sinal}${a.rentabilidade_pct}%)</div>
        </div>
        <div class="ativo-acoes">
          <button onclick="abrirModalAporte(${a.id})">💰</button>
          <button onclick="removerInvestimento(${a.id})">🗑️</button>
        </div>
      </div>`;
  }).join('') : '<div class="vazio">Nenhum ativo cadastrado ainda.</div>';
}

function renderRosca(porTipo, total) {
  if (!total || !porTipo.length) return '<div class="vazio">Sem investimentos ainda.</div>';
  let acc = 0;
  const trechos = porTipo.map(p => {
    const cor = (TIPOS_INVEST[p.tipo] || {}).cor || '#6B7772';
    const pct = p.valor / total * 100;
    const trecho = `${cor} ${acc}% ${acc + pct}%`;
    acc += pct;
    return trecho;
  }).join(', ');
  const legenda = porTipo.map(p => {
    const info = TIPOS_INVEST[p.tipo] || { label: p.tipo, cor: '#6B7772' };
    return `<div><span class="rosca-dot" style="background:${info.cor}"></span>${info.label} · ${fmt(p.valor)}</div>`;
  }).join('');
  return `
    <div class="rosca-wrap">
      <div class="rosca" style="background: conic-gradient(${trechos})"></div>
      <div class="rosca-legenda">${legenda}</div>
    </div>`;
}

function abrirModalInvestimento() {
  document.getElementById('mi-tipo').value = 'renda_fixa';
  document.getElementById('mi-nome').value = '';
  document.getElementById('mi-corretora').value = '';
  document.getElementById('mi-ticker').value = '';
  document.getElementById('mi-indexador').value = '';
  document.getElementById('modal-investimento').classList.remove('escondido');
}
function fecharModalInvestimento() { document.getElementById('modal-investimento').classList.add('escondido'); }

async function salvarInvestimentoModal() {
  const tipo = document.getElementById('mi-tipo').value;
  const nome = document.getElementById('mi-nome').value.trim();
  const corretora = document.getElementById('mi-corretora').value.trim();
  const ticker = document.getElementById('mi-ticker').value.trim();
  const indexador = document.getElementById('mi-indexador').value.trim();
  if (!nome) return toast('Dê um nome pro ativo.');

  const r = await api().criar_investimento(tipo, nome, corretora, ticker || null, indexador);
  if (!r.ok) return toast(r.erro || 'Não deu para criar.');
  fecharModalInvestimento();
  toast('✅ Ativo criado.');
  await carregarInvestimentos();
}

async function removerInvestimento(id) {
  await api().excluir_investimento(id);
  toast('Ativo removido.');
  await carregarInvestimentos();
}

function abrirModalAporte(investimentoId) {
  document.getElementById('ma-investimento-id').value = investimentoId;
  document.getElementById('ma-valor').value = '';
  document.getElementById('ma-quantidade').value = '';
  document.getElementById('ma-data').value = hoje();
  document.getElementById('modal-aporte').classList.remove('escondido');
}
function fecharModalAporte() { document.getElementById('modal-aporte').classList.add('escondido'); }

async function confirmarAporte() {
  const id = document.getElementById('ma-investimento-id').value;
  const valor = document.getElementById('ma-valor').value;
  const quantidade = document.getElementById('ma-quantidade').value;
  const data = document.getElementById('ma-data').value || hoje();
  if (!valor) return toast('Informe o valor aportado.');

  const r = await api().registrar_aporte(id, valor, quantidade || null, data);
  if (!r.ok) return toast(r.erro || 'Não deu para registrar.');
  fecharModalAporte();
  toast('✅ Aporte registrado.');
  await carregarInvestimentos();
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
