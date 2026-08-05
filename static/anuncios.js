/**
 * Valor Clássico — anuncios.js
 * Tabela paginada de anúncios coletados com filtros e ordenação.
 */

let currentPage   = 1;
let currentOrder  = 'ultima_vista';
let currentDir    = 'desc';
// Sentinela de "sem versão informada" no filtro de versão (a API traduz —
// ver _arg_versao() no app.py). Precisa ser um valor distinto de '', que já
// significa "todas as versões" no <select>.
const VERSAO_SEM = '__sem__';
// Filtros vindos da URL (ex.: link "ver anúncios" do dashboard) que ainda
// não foram aplicados aos selects — eles só existem depois da 1ª resposta
// da API (ver aplicarFiltrosPendentes()).
let filtrosPendentesDaUrl = null;

// ── Helpers de formatação ──────────────────────────────────────────────
function fmtPreco(val) {
  if (val == null) return '—';
  return 'R$ ' + Number(val).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fmtData(val) {
  if (!val) return '—';
  return val.slice(0, 10);
}

/**
 * Repopula um <select> preservando a seleção atual, se ela ainda existir
 * na nova lista (senão o navegador recai pro placeholder).
 */
function popularSelect(select, itens, { valorFn, rotuloFn, placeholder }) {
  const atual = select.value;
  select.replaceChildren();
  const optPlaceholder = document.createElement('option');
  optPlaceholder.value = '';
  optPlaceholder.textContent = placeholder;
  select.append(optPlaceholder);
  for (const item of itens) {
    const opt = document.createElement('option');
    opt.value = valorFn(item);
    opt.textContent = rotuloFn(item);
    select.append(opt);
  }
  if (itens.some((item) => valorFn(item) === atual)) select.value = atual;
}

// ── Filtros ────────────────────────────────────────────────────────────
function params(page) {
  const p = new URLSearchParams();
  const q      = document.getElementById('filter-q').value.trim();
  const fonte  = document.getElementById('filter-fonte').value || (filtrosPendentesDaUrl || {}).fonte || '';
  // Antes da 1ª resposta chegar, marca/modelo/ano vindos da URL ainda não
  // existem como <option> nos selects (não dá pra setar .value) — usa o
  // valor pendente pra já buscar com o recorte certo (e trazer, na mesma
  // resposta, a cascata de opções que inclui esse valor).
  const pend   = filtrosPendentesDaUrl || {};
  const marca  = document.getElementById('filter-marca').value  || pend.marca  || '';
  const modelo = document.getElementById('filter-modelo').value || pend.modelo || '';
  const ano    = document.getElementById('filter-ano').value    || pend.ano    || '';
  const versao = document.getElementById('filter-versao').value || pend.versao || '';
  const geracao = document.getElementById('filter-geracao').value || pend.geracao || '';
  const ps     = document.getElementById('filter-page-size').value;

  if (q)      p.set('q',      q);
  if (fonte)  p.set('fonte',  fonte);
  if (marca)  p.set('marca',  marca);
  if (modelo) p.set('modelo', modelo);
  if (ano)    p.set('ano',    ano);
  if (versao) p.set('versao', versao);
  if (geracao) p.set('geracao', geracao);
  p.set('order_by',  currentOrder);
  p.set('order_dir', currentDir);
  p.set('page',      page);
  p.set('page_size', ps);
  return p;
}

function limparFiltros() {
  document.getElementById('filter-q').value      = '';
  document.getElementById('filter-fonte').value  = '';
  document.getElementById('filter-marca').value  = '';
  document.getElementById('filter-modelo').value = '';
  document.getElementById('filter-versao').value = '';
  document.getElementById('filter-geracao').value = '';
  document.getElementById('filter-ano').value    = '';
  buscar(1);
}

// ── Ordenação ──────────────────────────────────────────────────────────
function ordenar(col) {
  if (currentOrder === col) {
    currentDir = currentDir === 'asc' ? 'desc' : 'asc';
  } else {
    currentOrder = col;
    currentDir   = col === 'ultima_vista' ? 'desc' : 'asc';
  }
  atualizarIconesSort();
  buscar(currentPage);
}

function atualizarIconesSort() {
  const cols = ['fonte', 'marca', 'modelo', 'ano', 'preco', 'ultima_vista'];
  cols.forEach(col => {
    const el = document.getElementById(`sort-${col}`);
    if (!el) return;
    if (col === currentOrder) {
      el.textContent = currentDir === 'asc' ? '↑' : '↓';
    } else {
      el.textContent = '';
    }
  });
}

/**
 * Aplica marca/modelo/ano vindos da URL (ex.: link do dashboard) assim que
 * as opções existirem nos selects — antes disso, setar .value é um no-op
 * silencioso (a <option> ainda não existe no DOM).
 */
function aplicarFiltrosPendentes() {
  if (!filtrosPendentesDaUrl) return;
  const { marca, modelo, ano, versao, geracao, fonte } = filtrosPendentesDaUrl;
  if (marca)  document.getElementById('filter-marca').value  = marca;
  if (modelo) document.getElementById('filter-modelo').value = modelo;
  if (ano)    document.getElementById('filter-ano').value    = ano;
  if (versao) document.getElementById('filter-versao').value = versao;
  if (geracao) document.getElementById('filter-geracao').value = geracao;
  if (fonte)  document.getElementById('filter-fonte').value  = fonte;
  filtrosPendentesDaUrl = null;
}

// ── Busca / render ─────────────────────────────────────────────────────
async function buscar(page) {
  currentPage = page;
  const tbody = document.getElementById('an-tbody');
  tbody.innerHTML = '<tr><td colspan="11" class="an-empty">Carregando…</td></tr>';

  try {
    const res  = await fetch(`/admin/api/anuncios?${params(page)}`);
    const data = await res.json();

    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="11" class="an-empty an-empty--erro">${data.erro}</td></tr>`;
      return;
    }

    const total    = data.total    || 0;
    const pages    = data.pages    || 1;
    const pageSize = data.page_size || 50;
    const rows     = data.rows     || [];

    // Sumário
    const inicio = (page - 1) * pageSize + 1;
    const fim    = Math.min(page * pageSize, total);
    document.getElementById('an-total').textContent =
      total > 0
        ? `${total.toLocaleString('pt-BR')} anúncios — exibindo ${inicio}–${fim}`
        : 'Nenhum anúncio encontrado.';

    // Fonte: lista fixa (não depende dos outros filtros)
    if (data.fontes_disponiveis) {
      popularSelect(document.getElementById('filter-fonte'), data.fontes_disponiveis, {
        valorFn: (f) => f,
        rotuloFn: (f) => f,
        placeholder: 'Todas',
      });
    }

    // Marca/modelo/ano: opções em cascata, contadas sob os outros filtros
    // ativos (mesmo estilo faceta do dashboard)
    if (data.opcoes) {
      const filtroMarca  = document.getElementById('filter-marca');
      const filtroModelo = document.getElementById('filter-modelo');
      const filtroAno    = document.getElementById('filter-ano');

      popularSelect(filtroMarca, data.opcoes.marca, {
        valorFn: (x) => x.marca,
        rotuloFn: (x) => `${x.marca} (${x.qtd.toLocaleString('pt-BR')})`,
        placeholder: 'Todas',
      });

      // Antes de aplicarFiltrosPendentes() rodar, filtroMarca.value ainda
      // pode estar vazio mesmo com uma marca "efetiva" vinda da URL — sem
      // considerar o pendente aqui, o select de modelo ficaria travado
      // desabilitado na 1ª carga de um link com marca+modelo já setados.
      const temMarca = Boolean(filtroMarca.value || filtrosPendentesDaUrl?.marca);
      filtroModelo.disabled = !temMarca;
      popularSelect(filtroModelo, data.opcoes.modelo, {
        valorFn: (x) => x.modelo,
        rotuloFn: (x) => `${x.modelo} (${x.qtd.toLocaleString('pt-BR')})`,
        placeholder: temMarca ? 'Todos' : 'Selecione uma marca',
      });

      popularSelect(filtroAno, data.opcoes.ano, {
        valorFn: (x) => String(x.ano),
        rotuloFn: (x) => `${x.ano} (${x.qtd.toLocaleString('pt-BR')})`,
        placeholder: 'Todos',
      });

      // Versão é cascata de modelo (a mesma "1.6 8V GASOLINA" existe em
      // modelos diferentes) e tem o balde "sem versão informada", que a
      // string vazia não distingue de "todas" — daí o sentinela VERSAO_SEM.
      const filtroVersao = document.getElementById('filter-versao');
      const temModelo = Boolean(filtroModelo.value || filtrosPendentesDaUrl?.modelo);
      filtroVersao.disabled = !temModelo;
      popularSelect(filtroVersao, data.opcoes.versao || [], {
        valorFn: (x) => x.versao || VERSAO_SEM,
        rotuloFn: (x) => `${x.versao || 'Sem versão informada'} (${x.qtd.toLocaleString('pt-BR')})`,
        placeholder: temModelo ? 'Todas' : 'Selecione um modelo',
      });

      // Geração: mesma cascata da versão, mas o seletor só aparece nos
      // modelos que TÊM geração (Gol, Parati, Saveiro...) — na maioria dos
      // clássicos ele seria um dropdown de uma opção só.
      const filtroGeracao = document.getElementById('filter-geracao');
      const opcoesGeracao = data.opcoes.geracao || [];
      const grupoGeracao = document.getElementById('filter-geracao-group');
      const temGeracao = temModelo && opcoesGeracao.length > 0;
      grupoGeracao.classList.toggle('hidden', !temGeracao);
      filtroGeracao.disabled = !temGeracao;
      popularSelect(filtroGeracao, opcoesGeracao, {
        valorFn: (x) => x.geracao || VERSAO_SEM,
        rotuloFn: (x) => `Geração ${x.geracao} (${x.qtd.toLocaleString('pt-BR')})`,
        placeholder: 'Todas',
      });
    }

    aplicarFiltrosPendentes();

    // Tabela
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="11" class="an-empty">Nenhum resultado para os filtros aplicados.</td></tr>';
    } else {
      tbody.innerHTML = rows.map(r => {
        const linkTitulo = r.url
          ? `<a href="${escapeAttr(r.url)}" target="_blank" rel="noopener" class="an-link">${escapeHtml(r.titulo || '—')}</a>`
          : escapeHtml(r.titulo || '—');
        return `<tr>
          <td class="an-td an-td--fonte"><span class="an-badge-fonte">${escapeHtml(r.fonte || '')}</span></td>
          <td class="an-td an-td--titulo">${linkTitulo}</td>
          <td class="an-td">${escapeHtml(r.marca || '—')}</td>
          <td class="an-td">${escapeHtml(r.modelo || '—')}</td>
          <td class="an-td">${escapeHtml(r.versao || '—')}</td>
          <td class="an-td">${escapeHtml(r.geracao || '—')}</td>
          <td class="an-td">${escapeHtml(r.motor || '—')}</td>
          <td class="an-td">${escapeHtml(r.obs || '—')}</td>
          <td class="an-td an-td--num">${r.ano || '—'}</td>
          <td class="an-td an-td--num">${fmtPreco(r.preco)}</td>
          <td class="an-td an-td--data">${fmtData(r.ultima_vista)}</td>
        </tr>`;
      }).join('');
    }

    renderPaginacao(page, pages);

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="11" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// ── Paginação ──────────────────────────────────────────────────────────
function renderPaginacao(page, pages) {
  const el = document.getElementById('an-pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }

  const MAX_BTN = 7;
  let btns = [];

  if (pages <= MAX_BTN) {
    btns = Array.from({ length: pages }, (_, i) => i + 1);
  } else {
    btns = [1];
    let start = Math.max(2, page - 2);
    let end   = Math.min(pages - 1, page + 2);
    if (start > 2)        btns.push('…');
    for (let i = start; i <= end; i++) btns.push(i);
    if (end < pages - 1)  btns.push('…');
    btns.push(pages);
  }

  el.innerHTML = btns.map(b => {
    if (b === '…') return `<span class="an-page-ellipsis">…</span>`;
    const active = b === page ? ' an-page-btn--active' : '';
    return `<button class="an-page-btn${active}" onclick="buscar(${b})">${b}</button>`;
  }).join('');
}

// ── Marca/modelo sem cascata (revisão de qualidade de dado) ─────────────
// Lista plana de todos os pares (marca, modelo) distintos, carregada uma
// vez e filtrada/ordenada no navegador — ao contrário da tabela principal,
// não precisa ir ao servidor a cada busca (são ~1 mil linhas, leve).
let mmPares = null;
let mmOrder = 'marca';
let mmDir = 'asc';

function toggleMarcaModelo() {
  const secao = document.getElementById('mm-section');
  const abrindo = secao.classList.contains('hidden');
  secao.classList.toggle('hidden');
  document.getElementById('btn-toggle-mm').textContent =
    abrindo ? 'Esconder todos os modelos' : 'Ver todos os modelos encontrados';
  if (abrindo && mmPares === null) carregarMarcaModelo();
}

async function carregarMarcaModelo() {
  const tbody = document.getElementById('mm-tbody');
  tbody.innerHTML = '<tr><td colspan="4" class="an-empty">Carregando…</td></tr>';
  try {
    const res = await fetch('/admin/api/marca-modelo');
    const data = await res.json();
    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="4" class="an-empty an-empty--erro">${escapeHtml(data.erro)}</td></tr>`;
      return;
    }
    mmPares = data.pares || [];
    renderMarcaModelo();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function ordenarMarcaModelo(col) {
  if (mmOrder === col) {
    mmDir = mmDir === 'asc' ? 'desc' : 'asc';
  } else {
    mmOrder = col;
    mmDir = (col === 'qtd' || col === 'versoes') ? 'desc' : 'asc';
  }
  ['marca', 'modelo', 'qtd', 'versoes'].forEach(c => {
    const el = document.getElementById(`mm-sort-${c}`);
    if (el) el.textContent = c === mmOrder ? (mmDir === 'asc' ? '↑' : '↓') : '';
  });
  renderMarcaModelo();
}

function renderMarcaModelo() {
  const tbody = document.getElementById('mm-tbody');
  if (mmPares === null) return;

  const termo = document.getElementById('mm-busca').value.trim().toUpperCase();
  const min = parseInt(document.getElementById('mm-min-anuncios').value, 10) || 0;
  let linhas = termo
    ? mmPares.filter(p => p.marca.includes(termo) || p.modelo.includes(termo))
    : mmPares.slice();
  if (min > 1) linhas = linhas.filter(p => p.qtd >= min);

  linhas.sort((a, b) => {
    const dir = mmDir === 'asc' ? 1 : -1;
    if (mmOrder === 'qtd')     return (a.qtd - b.qtd) * dir;
    if (mmOrder === 'versoes') return ((a.versoes || 0) - (b.versoes || 0)) * dir;
    return a[mmOrder].localeCompare(b[mmOrder]) * dir;
  });

  document.getElementById('mm-total').textContent =
    `${linhas.length.toLocaleString('pt-BR')} de ${mmPares.length.toLocaleString('pt-BR')} pares`;

  if (!linhas.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="an-empty">Nenhum par encontrado.</td></tr>';
    return;
  }
  // As duas contagens são botões: a de anúncios abre o grupo daquele par
  // (mesmo detalhe usado na quarentena), a de versões abre os recortes
  // (versão, geração) — e de lá dá pra descer até os anúncios de cada um.
  tbody.innerHTML = linhas.map(p => `
    <tr data-marca="${escapeAttr(p.marca)}" data-modelo="${escapeAttr(p.modelo || '')}">
      <td class="an-td">${escapeHtml(p.marca)}</td>
      <td class="an-td">${escapeHtml(p.modelo)}</td>
      <td class="an-td an-td--num"><button class="qv-count" onclick="verAnunciosDoPar(this)" title="Ver os anúncios deste par">${p.qtd.toLocaleString('pt-BR')}</button></td>
      <td class="an-td an-td--num">${
        p.versoes
          ? `<button class="qv-count" onclick="verVersoesDoPar(this)" title="Ver as versões deste par">${p.versoes.toLocaleString('pt-BR')}</button>`
          : '<span class="an-muted">—</span>'
      }</td>
    </tr>
  `).join('');
}

// Detalhe de VERSÕES de um par (nível intermediário entre o par e os
// anúncios): cada linha é um recorte (versão, geração), com a contagem de
// novo clicável pra abrir os anúncios daquele recorte específico.
async function verVersoesDoPar(btn) {
  const tr = btn.closest('tr');
  const existente = tr.nextElementSibling;
  if (existente && existente.classList.contains('qv-detail')) {
    existente.remove();
    return;
  }
  const marca  = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const detail = document.createElement('tr');
  detail.className = 'qv-detail';
  detail.innerHTML = `<td colspan="${tr.children.length}" class="qv-detail-cell">Carregando…</td>`;
  tr.after(detail);
  const cell = detail.firstElementChild;
  try {
    const url = `/admin/api/versoes-do-par?marca=${encodeURIComponent(marca)}&modelo=${encodeURIComponent(modelo)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.erro) {
      cell.innerHTML = `<span class="an-empty an-empty--erro">${escapeHtml(data.erro)}</span>`;
      return;
    }
    const rows = data.rows || [];
    if (!rows.length) {
      cell.textContent = 'Nenhuma versão.';
      return;
    }
    cell.innerHTML = `
      <div class="qv-detail-wrap">
        <table class="qv-detail-table">
          <thead>
            <tr>
              <th>Versão</th><th>Geração</th><th class="an-th--num">Anúncios</th>
              <th class="an-th--num">Média</th><th class="an-th--num">Anos</th><th>Motor</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr data-marca="${escapeAttr(marca)}" data-modelo="${escapeAttr(modelo)}"
                  data-versao="${escapeAttr(r.versao)}" data-geracao="${escapeAttr(r.geracao)}">
                <td>${r.versao ? escapeHtml(r.versao) : '<span class="an-muted">sem versão informada</span>'}</td>
                <td>${r.geracao ? escapeHtml(r.geracao) : '—'}</td>
                <td class="an-td--num"><button class="qv-count" onclick="verAnunciosDaVersao(this)" title="Ver os anúncios desta versão">${r.qtd.toLocaleString('pt-BR')}</button></td>
                <td class="an-td--num">${r.com_preco ? fmtPreco(r.preco_medio) : '—'}</td>
                <td class="an-td--num">${fmtFaixaAnos(r.ano_min, r.ano_max)}</td>
                <td>${escapeHtml(r.motores || '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    cell.innerHTML = `<span class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</span>`;
  }
}

function fmtFaixaAnos(min, max) {
  if (!min && !max) return '—';
  return min === max ? String(min) : `${min}–${max}`;
}

// Anúncios de um recorte (versão, geração) — o nível mais fundo da consulta,
// aberto a partir da tabela de versões.
async function verAnunciosDaVersao(btn) {
  const tr = btn.closest('tr');
  const existente = tr.nextElementSibling;
  if (existente && existente.classList.contains('qv-subdetail')) {
    existente.remove();
    return;
  }
  const { marca, modelo, versao, geracao } = tr.dataset;
  const detail = document.createElement('tr');
  detail.className = 'qv-subdetail';
  detail.innerHTML = `<td colspan="${tr.children.length}" class="qv-detail-cell">Carregando…</td>`;
  tr.after(detail);
  const cell = detail.firstElementChild;
  try {
    // '' significa "sem o campo informado" na API — o sentinela distingue
    // isso de "não filtrar" (ver _arg_versao/_arg_geracao no app.py).
    const p = new URLSearchParams({ marca, modelo });
    p.set('versao', versao || VERSAO_SEM);
    p.set('geracao', geracao || VERSAO_SEM);
    const res = await fetch(`/admin/api/anuncios-do-par?${p.toString()}`);
    const data = await res.json();
    if (data.erro) {
      cell.innerHTML = `<span class="an-empty an-empty--erro">${escapeHtml(data.erro)}</span>`;
      return;
    }
    const rows = data.rows || [];
    if (!rows.length) {
      cell.textContent = 'Nenhum anúncio.';
      return;
    }
    const total = parseInt((btn.textContent || '').replace(/\D/g, ''), 10) || rows.length;
    const parcial = rows.length < total;
    const link = `/admin/anuncios?${p.toString()}`;
    cell.innerHTML = `
      <p class="qv-detail-nota">${
        parcial
          ? `Mostrando ${rows.length.toLocaleString('pt-BR')} dos ${total.toLocaleString('pt-BR')} anúncios deste recorte (os de ano mais antigo primeiro). `
          : ''
      }<a class="btn btn-outline btn-sm" href="${escapeAttr(link)}">Ver na lista completa</a></p>
      <div class="qv-detail-wrap">
        <table class="qv-detail-table">
          <thead>
            <tr><th>Fonte</th><th>Título</th><th class="an-th--num">Ano</th><th class="an-th--num">Preço</th><th>Motor</th><th>Obs</th></tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${escapeHtml(r.fonte || '—')}</td>
                <td>${r.url
                    ? `<a href="${escapeAttr(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.titulo || '(sem título)')}</a>`
                    : escapeHtml(r.titulo || '(sem título)')}</td>
                <td class="an-td--num">${r.ano || '—'}</td>
                <td class="an-td--num">${fmtPreco(r.preco)}</td>
                <td>${escapeHtml(r.motor || '—')}</td>
                <td>${escapeHtml(r.obs || '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    cell.innerHTML = `<span class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</span>`;
  }
}


function filtrarPorPar(btn) {
  // Manda o par pros filtros da tabela principal — é lá que o grupo inteiro é
  // consultável (paginado, ordenável), sem o corte de 300 do detalhe. Reusa o
  // mesmo caminho dos links vindos da URL: os <option> de modelo só existem
  // depois da resposta, então o par vai como filtro pendente.
  const tr = btn.closest('tr');
  document.getElementById('filter-q').value      = '';
  document.getElementById('filter-fonte').value  = '';
  document.getElementById('filter-versao').value = '';
  document.getElementById('filter-ano').value    = '';
  filtrosPendentesDaUrl = { marca: tr.dataset.marca, modelo: tr.dataset.modelo };
  buscar(1);
  document.getElementById('an-table').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function verAnunciosDoPar(btn) {
  // Expande/colapsa uma linha de detalhe com os anúncios do par, logo abaixo.
  // Serve as duas tabelas de pares (quarentena e "todas as marcas e modelos"),
  // que têm número de colunas diferente — daí o colspan calculado.
  const tr = btn.closest('tr');
  const existente = tr.nextElementSibling;
  if (existente && existente.classList.contains('qv-detail')) {
    existente.remove();
    return;
  }
  const marca  = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const detail = document.createElement('tr');
  detail.className = 'qv-detail';
  detail.dataset.marca  = marca;
  detail.dataset.modelo = modelo;
  detail.innerHTML = `<td colspan="${tr.children.length}" class="qv-detail-cell">Carregando…</td>`;
  tr.after(detail);
  const cell = detail.firstElementChild;
  try {
    const url = `/admin/api/anuncios-do-par?marca=${encodeURIComponent(marca)}&modelo=${encodeURIComponent(modelo)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.erro) {
      cell.innerHTML = `<span class="an-empty an-empty--erro">${escapeHtml(data.erro)}</span>`;
      return;
    }
    const rows = data.rows || [];
    if (!rows.length) {
      cell.textContent = 'Nenhum anúncio.';
      return;
    }
    // O servidor corta em 300 (`listar_anuncios_do_par`) e ordena por ano; em par
    // gordo (FUSCA tem milhares) o grupo é uma amostra — diz isso em vez de fingir
    // que é tudo, e oferece a tabela principal (paginada) pra ver o grupo inteiro.
    const total = parseInt((btn.textContent || '').replace(/\D/g, ''), 10) || rows.length;
    const parcial = rows.length < total;
    const verTodos = modelo
      ? '<button class="btn btn-outline btn-sm" onclick="filtrarPorPar(this)">Ver na lista completa</button>'
      : '';
    const legenda = (parcial || verTodos)
      ? `<p class="qv-detail-nota">${
          parcial
            ? `Mostrando ${rows.length.toLocaleString('pt-BR')} dos ${total.toLocaleString('pt-BR')} anúncios deste par (os de ano mais antigo primeiro). `
            : ''
        }${verTodos}</p>`
      : '';
    cell.innerHTML = `
      ${legenda}
      <div class="qv-detail-wrap">
        <table class="qv-detail-table">
          <thead>
            <tr><th>Fonte</th><th>Título</th><th class="an-th--num">Ano</th><th class="an-th--num">Preço</th><th>Versão</th><th>Geração</th><th>Motor</th><th>Obs</th></tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${escapeHtml(r.fonte || '—')}</td>
                <td>${r.url
                    ? `<a href="${escapeAttr(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.titulo || '(sem título)')}</a>`
                    : escapeHtml(r.titulo || '(sem título)')}</td>
                <td class="an-td--num">${r.ano || '—'}</td>
                <td class="an-td--num">${fmtPreco(r.preco)}</td>
                <td>${escapeHtml(r.versao || '—')}</td>
                <td>${escapeHtml(r.geracao || '—')}</td>
                <td>${escapeHtml(r.motor || '—')}</td>
                <td>${escapeHtml(r.obs || '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    cell.innerHTML = `<span class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</span>`;
  }
}


// ── XSS helpers ────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function escapeAttr(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Enter no campo de busca livre ────────────────────────────────────────
document.getElementById('filter-q')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') buscar(1);
});

// ── Dropdowns buscam assim que trocam (fonte/marca/modelo/ano) ──────────
// Trocar marca invalida o modelo escolhido (cascata); trocar modelo
// invalida o ano só no sentido de re-facetar as opções, não precisa zerar.
document.getElementById('filter-fonte')?.addEventListener('change', () => buscar(1));
document.getElementById('filter-marca')?.addEventListener('change', () => {
  document.getElementById('filter-modelo').value = '';
  document.getElementById('filter-versao').value = '';
  document.getElementById('filter-ano').value = '';
  buscar(1);
});
document.getElementById('filter-modelo')?.addEventListener('change', () => {
  document.getElementById('filter-versao').value = '';   // versão é cascata de modelo
  document.getElementById('filter-geracao').value = '';  // geração idem
  document.getElementById('filter-ano').value = '';
  buscar(1);
});
document.getElementById('filter-versao')?.addEventListener('change', () => buscar(1));
document.getElementById('filter-geracao')?.addEventListener('change', () => buscar(1));
document.getElementById('filter-ano')?.addEventListener('change', () => buscar(1));

// ── Init ───────────────────────────────────────────────────────────────
/**
 * Lê marca/modelo/versão/geração/ano/fonte da query string (ex.: link "ver anúncios"
 * do dashboard ou da calculadora de média:
 * /admin/anuncios?marca=Volkswagen&modelo=Fusca&versao=1.6%208V...) — os
 * valores só são aplicados aos selects depois que a 1ª busca traz as opções
 * (são dropdowns, não dá pra setar .value antes da <option> existir).
 * "q" é texto livre, pode ser pré-preenchido direto.
 */
function lerFiltrosDaUrl() {
  const urlParams = new URLSearchParams(window.location.search);
  const q = urlParams.get('q');
  if (q) document.getElementById('filter-q').value = q;

  const marca = urlParams.get('marca');
  const modelo = urlParams.get('modelo');
  const ano = urlParams.get('ano');
  const versao = urlParams.get('versao');
  const geracao = urlParams.get('geracao');
  const fonte = urlParams.get('fonte');
  if (marca || modelo || ano || versao || geracao || fonte) {
    filtrosPendentesDaUrl = { marca, modelo, ano, versao, geracao, fonte };
  }
}

lerFiltrosDaUrl();
atualizarIconesSort();
buscar(1);
