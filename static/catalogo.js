/**
 * Valor Clássico — catálogo definitivo.
 *
 * Mostra as sete fontes de marca/modelo/versão unificadas (ver
 * src/catalog/unificado.py) e grava a curadoria de cada linha.
 *
 * São 20 mil combinações, então NADA é carregado de uma vez: a tela pede uma
 * página por vez e o servidor filtra. O resumo vem só na primeira chamada -
 * ele custa varrer o índice inteiro e não muda entre páginas.
 *
 * Todo texto de fonte externa entra por textContent, nunca innerHTML: nome de
 * modelo vem de CSV de terceiro e de anúncio, e nenhum dos dois é confiável
 * como marcação.
 */

const FMT_INT = new Intl.NumberFormat('pt-BR');

const el = (id) => document.getElementById(id);

const tbody      = el('cat-tbody');
const lista      = el('cat-lista');
const vazio      = el('cat-vazio');
const nota       = el('cat-nota');
const resumoBox  = el('cat-resumo');
const paginaInfo = el('cat-pagina-info');

const filtros = {
  busca:     el('cat-busca'),
  marca:     el('cat-marca'),
  situacao:  el('cat-situacao'),
  porPagina: el('cat-por-pagina'),
  soAnuncios: el('cat-so-anuncios'),
};

// Ordem corrente. O servidor entende "campo" e "-campo"; "relevancia" é o
// padrão e é o único que não tem coluna correspondente.
const ORDEM_PADRAO = 'relevancia';
let ordem = ORDEM_PADRAO;

let pagina = 1;
// A procedência saiu da tabela, mas continua servindo o editor: é a faixa de
// cada fonte que justifica mexer (ou não) nos anos.
let rotulosFonte = {};
let primeiraCarga = true;
// Qual linha está com o editor aberto, pela chave de origem. Guardado por
// chave e não por índice: a lista é reordenada a cada carga.
let editando = null;

/* ── Chave de origem ────────────────────────────────────────────────── */

// É por ela que a decisão volta ao servidor, e ela não muda quando a
// curadoria corrige o nome — é isso que mantém o vínculo com a fonte.
function chaveDe(l) {
  return JSON.stringify([l.marca_origem, l.modelo_origem, l.versao_origem]);
}

function rotuloVersao(v) {
  return v || '(sem versão)';
}

function faixaAnos(l) {
  if (l.ano_min == null && l.ano_max == null) return '—';
  if (l.ano_min === l.ano_max) return String(l.ano_min);
  return `${l.ano_min ?? '?'}–${l.ano_max ?? '?'}`;
}

/* ── Carga ──────────────────────────────────────────────────────────── */

function params(extra = {}) {
  const p = new URLSearchParams();
  if (filtros.busca.value.trim()) p.set('busca', filtros.busca.value.trim());
  if (filtros.marca.value)     p.set('marca', filtros.marca.value);
  if (filtros.situacao.value)  p.set('situacao', filtros.situacao.value);
  p.set('ordem', ordem);
  if (filtros.soAnuncios.checked) p.set('so_com_anuncios', '1');
  p.set('pagina', String(pagina));
  p.set('por_pagina', filtros.porPagina.value);
  Object.entries(extra).forEach(([k, v]) => p.set(k, v));
  return p;
}

async function carregar() {
  lista.classList.add('carregando');
  try {
    const p = params(primeiraCarga ? {} : { so_linhas: '1' });
    const resp = await fetch('/admin/api/catalogo?' + p.toString());
    const dados = await resp.json();
    if (dados.erro) throw new Error(dados.erro);

    if (dados.resumo) {
      rotulosFonte = dados.resumo.fontes_rotulos || {};
      montarFiltrosFixos(dados);
      renderResumo(dados.resumo);
      primeiraCarga = false;
    }
    renderTabela(dados);
  } catch (err) {
    nota.textContent = `Falha ao carregar: ${err.message}`;
  } finally {
    lista.classList.remove('carregando');
  }
}

// Só na primeira carga: é a lista completa de marcas, e recarregá-la a cada
// página faria a seleção do usuário piscar.
function montarFiltrosFixos(dados) {
  for (const m of dados.marcas || []) {
    filtros.marca.append(new Option(`${m.marca} (${FMT_INT.format(m.qtd)})`, m.marca));
  }
}

/* ── Resumo (as pílulas também filtram) ─────────────────────────────── */

function pilula(rotulo, valor, aoClicar, ativa = false) {
  const b = document.createElement('button');
  b.className = 'cat-pilula' + (ativa ? ' ativa' : '');
  b.append(document.createTextNode(rotulo + ' '));
  const forte = document.createElement('strong');
  forte.textContent = FMT_INT.format(valor);
  b.append(forte);
  if (aoClicar) b.addEventListener('click', aoClicar);
  else b.disabled = true;
  return b;
}

function renderResumo(r) {
  resumoBox.replaceChildren();
  const s = r.por_situacao;
  resumoBox.append(pilula('Combinações', r.total, null));
  resumoBox.append(pilula('Marcas', r.marcas, null));

  const porSituacao = [['Pendentes', 'pendente'], ['Confirmadas', 'confirmado'],
                       ['Descartadas', 'descartado']];
  for (const [rotulo, chave] of porSituacao) {
    resumoBox.append(pilula(rotulo, s[chave], () => {
      filtros.situacao.value = filtros.situacao.value === chave ? '' : chave;
      reiniciar();
    }, filtros.situacao.value === chave));
  }

  resumoBox.append(pilula('Aparecem em anúncios', r.com_anuncios, () => {
    filtros.soAnuncios.checked = !filtros.soAnuncios.checked;
    reiniciar();
  }, filtros.soAnuncios.checked));
}

/* ── Ordenação ──────────────────────────────────────────────────────── */

/**
 * Clique no cabeçalho: primeiro clique ordena crescente, o segundo inverte,
 * o terceiro volta ao padrão. O terceiro estado existe pra dar saída — sem
 * ele, escolher uma coluna por engano prenderia a lista nela.
 */
function alternarOrdem(campo) {
  if (ordem === campo) ordem = '-' + campo;
  else if (ordem === '-' + campo) ordem = ORDEM_PADRAO;
  else ordem = campo;
  reiniciar();
}

// Setas e destaque saem do estado, não do clique: assim o botão "Ordem
// padrão" também limpa a indicação, sem precisar saber quem estava ativo.
function pintarCabecalhos() {
  const campo = ordem.startsWith('-') ? ordem.slice(1) : ordem;
  const dir = ordem.startsWith('-') ? 'desc' : 'asc';
  for (const b of document.querySelectorAll('.cat-ord')) {
    const th = b.closest('th');
    if (b.dataset.ordem === campo) {
      b.dataset.dir = dir;
      th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
    } else {
      delete b.dataset.dir;
      th.removeAttribute('aria-sort');
    }
  }
}

/* ── Tabela ─────────────────────────────────────────────────────────── */

function celula(texto, classe) {
  const td = document.createElement('td');
  if (classe) td.className = classe;
  td.textContent = texto;
  return td;
}

function botao(rotulo, classe, aoClicar, titulo) {
  const b = document.createElement('button');
  b.className = 'cat-btn ' + classe;
  b.textContent = rotulo;
  if (titulo) b.title = titulo;
  b.addEventListener('click', aoClicar);
  return b;
}

function celulaAcoes(l) {
  const td = document.createElement('td');
  const caixa = document.createElement('div');
  caixa.className = 'cat-acoes';

  caixa.append(botao('Editar', '', () => alternarEditor(l),
                     'Corrigir nome ou ajustar a faixa de anos'));

  if (l.situacao !== 'confirmado') {
    caixa.append(botao('Confirmar', 'cat-btn--ok',
                       () => decidir(l, { situacao: 'confirmado' }),
                       'Entra no catálogo definitivo como está'));
  }
  if (l.situacao !== 'descartado') {
    caixa.append(botao('Descartar', 'cat-btn--no',
                       () => decidir(l, { situacao: 'descartado' }),
                       'Não é um carro válido pro catálogo'));
  }
  if (l.situacao !== 'pendente') {
    caixa.append(botao('Reabrir', '', () => decidir(l, { situacao: 'pendente' }),
                       'Desfaz a decisão e volta pra fila'));
  }
  td.append(caixa);
  return td;
}

function renderTabela(dados) {
  pintarCabecalhos();
  tbody.replaceChildren();
  const linhas = dados.linhas || [];
  vazio.classList.toggle('hidden', linhas.length > 0);

  for (const l of linhas) {
    const tr = document.createElement('tr');
    tr.className = l.situacao;
    tr.append(celula(l.marca, 'cat-nome'));
    tr.append(celula(l.modelo, 'cat-nome'));

    const tdVersao = document.createElement('td');
    tdVersao.textContent = rotuloVersao(l.versao);
    if (!l.versao) tdVersao.className = 'cat-sem-versao';
    tr.append(tdVersao);

    tr.append(celula(faixaAnos(l), 'cat-num'));
    tr.append(celulaAcoes(l));
    tbody.append(tr);

    if (editando === chaveDe(l)) tbody.append(linhaEditor(l));
  }

  const total = dados.total || 0;
  const de = total ? (dados.pagina - 1) * dados.por_pagina + 1 : 0;
  const ate = Math.min(dados.pagina * dados.por_pagina, total);
  nota.textContent = total
    ? `Mostrando ${FMT_INT.format(de)}–${FMT_INT.format(ate)} de ${FMT_INT.format(total)} combinações.`
    : '';
  paginaInfo.textContent = `Página ${FMT_INT.format(dados.pagina)} de ${FMT_INT.format(dados.paginas)}`;
  el('cat-anterior').disabled = dados.pagina <= 1;
  el('cat-proxima').disabled = dados.pagina >= dados.paginas;
}

/* ── Editor inline ──────────────────────────────────────────────────── */

function alternarEditor(l) {
  editando = editando === chaveDe(l) ? null : chaveDe(l);
  carregar();
}

function campo(rotulo, valor, tipo = 'text') {
  const label = document.createElement('label');
  label.append(document.createTextNode(rotulo));
  const input = document.createElement('input');
  input.type = tipo;
  input.value = valor ?? '';
  if (tipo === 'number') { input.min = '1900'; input.max = '2100'; }
  label.append(input);
  return { label, input };
}

function linhaEditor(l) {
  const tr = document.createElement('tr');
  tr.className = 'cat-editor';
  const td = document.createElement('td');
  td.colSpan = 5;

  const campos = document.createElement('div');
  campos.className = 'cat-editor-campos';
  const marca  = campo('Marca', l.marca);
  const modelo = campo('Modelo', l.modelo);
  const versao = campo('Versão', l.versao);
  const anoMin = campo('Ano inicial', l.ano_min, 'number');
  const anoMax = campo('Ano final', l.ano_max, 'number');
  [marca, modelo, versao, anoMin, anoMax].forEach(c => campos.append(c.label));

  const erro = document.createElement('p');
  erro.className = 'cat-editor-erro hidden';

  const salvar = botao('Salvar e confirmar', 'cat-btn--ok', async () => {
    erro.classList.add('hidden');
    try {
      await decidir(l, {
        situacao: 'confirmado',
        marca: marca.input.value.trim(),
        modelo: modelo.input.value.trim(),
        // String vazia é valor legítimo aqui ("esta linha é o modelo sem
        // versão"), então vai como está, sem virar null.
        versao: versao.input.value.trim(),
        ano_min: anoMin.input.value,
        ano_max: anoMax.input.value,
      });
    } catch (err) {
      erro.textContent = err.message;
      erro.classList.remove('hidden');
    }
  });
  const cancelar = botao('Cancelar', '', () => { editando = null; carregar(); });

  const acoes = document.createElement('div');
  acoes.className = 'cat-acoes';
  acoes.style.marginTop = '.6rem';
  acoes.append(salvar, cancelar);

  // O que cada fonte diz, à vista de quem está editando: é a informação que
  // justifica mexer (ou não) na faixa.
  const detalhe = document.createElement('p');
  detalhe.className = 'cat-editor-fontes';
  const partes = l.fontes.map(f => {
    const [a1, a2] = l.anos_por_fonte[f] || [null, null];
    return `${rotulosFonte[f] || f}: ${(a1 || a2) ? `${a1 ?? '?'}–${a2 ?? '?'}` : 'sem anos'}`;
  });
  detalhe.textContent = 'Origem — ' + [
    `${l.marca_origem} ${l.modelo_origem} ${rotuloVersao(l.versao_origem)}`,
    ...partes,
  ].join(' · ');

  td.append(campos, acoes, erro, detalhe);
  tr.append(td);
  return tr;
}

/* ── Decisão ────────────────────────────────────────────────────────── */

async function decidir(l, dados) {
  const corpo = {
    marca_origem: l.marca_origem,
    modelo_origem: l.modelo_origem,
    versao_origem: l.versao_origem,
    ...dados,
  };
  const resp = await fetch('/admin/api/catalogo-decidir', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  });
  const r = await resp.json();
  if (r.erro) throw new Error(r.erro);

  editando = null;
  // Recarrega com resumo: as contagens de pendente/confirmado mudaram, e uma
  // tela que não as atualiza faz parecer que o clique não pegou.
  primeiraCargaResumo();
  return r;
}

// Força o resumo a vir de novo sem repopular os <select> (que já estão
// montados e guardam a escolha do usuário).
async function primeiraCargaResumo() {
  lista.classList.add('carregando');
  try {
    const resp = await fetch('/admin/api/catalogo?' + params().toString());
    const dados = await resp.json();
    if (dados.erro) throw new Error(dados.erro);
    if (dados.resumo) renderResumo(dados.resumo);
    renderTabela(dados);
  } catch (err) {
    nota.textContent = `Falha ao recarregar: ${err.message}`;
  } finally {
    lista.classList.remove('carregando');
  }
}

/* ── Wiring ─────────────────────────────────────────────────────────── */

function reiniciar() {
  pagina = 1;
  editando = null;
  carregar();
}

let debounce;
filtros.busca.addEventListener('input', () => {
  clearTimeout(debounce);
  debounce = setTimeout(reiniciar, 300);
});
['marca', 'situacao', 'porPagina', 'soAnuncios'].forEach(k =>
  filtros[k].addEventListener('change', reiniciar));

for (const b of document.querySelectorAll('.cat-ord')) {
  b.addEventListener('click', () => alternarOrdem(b.dataset.ordem));
}
el('cat-ordem-padrao').addEventListener('click', () => {
  ordem = ORDEM_PADRAO;
  reiniciar();
});

el('cat-anterior').addEventListener('click', () => { pagina--; editando = null; carregar(); });
el('cat-proxima').addEventListener('click', () => { pagina++; editando = null; carregar(); });

el('cat-exportar').addEventListener('change', (ev) => {
  const situacao = ev.target.value;
  if (!situacao) return;
  window.location = `/admin/api/exportar-catalogo?situacao=${situacao}`;
  ev.target.value = '';
});

carregar();
