/**
 * Valor Clássico — anuncios.js
 * Tabela paginada de anúncios coletados com filtros e ordenação.
 */

let currentPage   = 1;
let currentOrder  = 'ultima_vista';
let currentDir    = 'desc';
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
  const fonte  = document.getElementById('filter-fonte').value;
  // Antes da 1ª resposta chegar, marca/modelo/ano vindos da URL ainda não
  // existem como <option> nos selects (não dá pra setar .value) — usa o
  // valor pendente pra já buscar com o recorte certo (e trazer, na mesma
  // resposta, a cascata de opções que inclui esse valor).
  const pend   = filtrosPendentesDaUrl || {};
  const marca  = document.getElementById('filter-marca').value  || pend.marca  || '';
  const modelo = document.getElementById('filter-modelo').value || pend.modelo || '';
  const ano    = document.getElementById('filter-ano').value    || pend.ano    || '';
  const ps     = document.getElementById('filter-page-size').value;

  if (q)      p.set('q',      q);
  if (fonte)  p.set('fonte',  fonte);
  if (marca)  p.set('marca',  marca);
  if (modelo) p.set('modelo', modelo);
  if (ano)    p.set('ano',    ano);
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
  const { marca, modelo, ano } = filtrosPendentesDaUrl;
  if (marca)  document.getElementById('filter-marca').value  = marca;
  if (modelo) document.getElementById('filter-modelo').value = modelo;
  if (ano)    document.getElementById('filter-ano').value    = ano;
  filtrosPendentesDaUrl = null;
}

// ── Busca / render ─────────────────────────────────────────────────────
async function buscar(page) {
  currentPage = page;
  const tbody = document.getElementById('an-tbody');
  tbody.innerHTML = '<tr><td colspan="9" class="an-empty">Carregando…</td></tr>';

  try {
    const res  = await fetch(`/admin/api/anuncios?${params(page)}`);
    const data = await res.json();

    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="9" class="an-empty an-empty--erro">${data.erro}</td></tr>`;
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
    }

    aplicarFiltrosPendentes();

    // Tabela
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="an-empty">Nenhum resultado para os filtros aplicados.</td></tr>';
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
          <td class="an-td">${escapeHtml(r.obs || '—')}</td>
          <td class="an-td an-td--num">${r.ano || '—'}</td>
          <td class="an-td an-td--num">${fmtPreco(r.preco)}</td>
          <td class="an-td an-td--data">${fmtData(r.ultima_vista)}</td>
        </tr>`;
      }).join('');
    }

    renderPaginacao(page, pages);

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
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
  tbody.innerHTML = '<tr><td colspan="3" class="an-empty">Carregando…</td></tr>';
  try {
    const res = await fetch('/admin/api/marca-modelo');
    const data = await res.json();
    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="3" class="an-empty an-empty--erro">${escapeHtml(data.erro)}</td></tr>`;
      return;
    }
    mmPares = data.pares || [];
    renderMarcaModelo();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="3" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function ordenarMarcaModelo(col) {
  if (mmOrder === col) {
    mmDir = mmDir === 'asc' ? 'desc' : 'asc';
  } else {
    mmOrder = col;
    mmDir = col === 'qtd' ? 'desc' : 'asc';
  }
  ['marca', 'modelo', 'qtd'].forEach(c => {
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
    if (mmOrder === 'qtd') return (a.qtd - b.qtd) * dir;
    return a[mmOrder].localeCompare(b[mmOrder]) * dir;
  });

  document.getElementById('mm-total').textContent =
    `${linhas.length.toLocaleString('pt-BR')} de ${mmPares.length.toLocaleString('pt-BR')} pares`;

  if (!linhas.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="an-empty">Nenhum par encontrado.</td></tr>';
    return;
  }
  tbody.innerHTML = linhas.map(p => `
    <tr>
      <td class="an-td">${escapeHtml(p.marca)}</td>
      <td class="an-td">${escapeHtml(p.modelo)}</td>
      <td class="an-td an-td--num">${p.qtd.toLocaleString('pt-BR')}</td>
    </tr>
  `).join('');
}

// ── Anúncios a verificar (quarentena: pares fora do catálogo) ───────────
let qvPares = null;
let qvMarcas = [];
let qvModelos = {};   // {MARCA: [modelos do catálogo]} — pra selecionar um já cadastrado
let qvOrder = 'qtd';
let qvDir = 'desc';

function toggleVerificar() {
  const secao = document.getElementById('qv-section');
  const abrindo = secao.classList.contains('hidden');
  secao.classList.toggle('hidden');
  document.getElementById('btn-toggle-qv').textContent =
    abrindo ? 'Esconder a verificar' : 'Anúncios a verificar';
  if (abrindo) carregarVerificar();
}

async function carregarVerificar() {
  const tbody = document.getElementById('qv-tbody');
  tbody.innerHTML = '<tr><td colspan="4" class="an-empty">Carregando…</td></tr>';
  try {
    const res = await fetch('/admin/api/anuncios-a-verificar');
    const data = await res.json();
    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="4" class="an-empty an-empty--erro">${escapeHtml(data.erro)}</td></tr>`;
      return;
    }
    qvPares = data.pares || [];
    qvMarcas = data.marcas_catalogo || [];
    qvModelos = data.modelos_catalogo || {};
    document.getElementById('qv-marcas').innerHTML =
      qvMarcas.map(m => `<option value="${escapeAttr(m)}">`).join('');
    renderVerificar();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function ordenarVerificar(col) {
  if (qvOrder === col) {
    qvDir = qvDir === 'asc' ? 'desc' : 'asc';
  } else {
    qvOrder = col;
    qvDir = col === 'qtd' ? 'desc' : 'asc';
  }
  ['marca', 'modelo', 'qtd'].forEach(c => {
    const el = document.getElementById(`qv-sort-${c}`);
    if (el) el.textContent = c === qvOrder ? (qvDir === 'asc' ? '↑' : '↓') : '';
  });
  renderVerificar();
}

function renderVerificar() {
  const tbody = document.getElementById('qv-tbody');
  if (qvPares === null) return;

  const termo = document.getElementById('qv-busca').value.trim().toUpperCase();
  let linhas = termo
    ? qvPares.filter(p => p.marca.includes(termo) || (p.modelo || '').includes(termo))
    : qvPares.slice();

  linhas.sort((a, b) => {
    const dir = qvDir === 'asc' ? 1 : -1;
    if (qvOrder === 'qtd') return (a.qtd - b.qtd) * dir;
    return String(a[qvOrder]).localeCompare(String(b[qvOrder])) * dir;
  });

  const totalAnuncios = qvPares.reduce((s, p) => s + p.qtd, 0);
  document.getElementById('qv-total').textContent =
    `${linhas.length.toLocaleString('pt-BR')} de ${qvPares.length.toLocaleString('pt-BR')} pares · ${totalAnuncios.toLocaleString('pt-BR')} anúncios`;

  if (!linhas.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="an-empty">Nenhum par a verificar.</td></tr>';
    return;
  }
  tbody.innerHTML = linhas.map(p => `
    <tr data-marca="${escapeAttr(p.marca)}" data-modelo="${escapeAttr(p.modelo || '')}">
      <td class="an-td">${escapeHtml(p.marca)}</td>
      <td class="an-td">${escapeHtml(p.modelo || '—')}</td>
      <td class="an-td an-td--num"><button class="qv-count" onclick="verAnunciosDoPar(this)" title="Ver os anúncios deste par">${p.qtd.toLocaleString('pt-BR')}</button></td>
      <td class="an-td qv-fix">
        <input class="an-filter-input qv-in-marca" list="qv-marcas" value="${escapeAttr(p.marca)}" placeholder="marca" oninput="atualizarModelosLinha(this)" />
        <select class="an-filter-select qv-sel-modelo" onchange="aoSelecionarModelo(this)" title="Selecionar um modelo já cadastrado desta marca">${opcoesModeloSelect(p.marca)}</select>
        <input class="an-filter-input qv-in-modelo" value="${escapeAttr(p.modelo || '')}" placeholder="ou digite um modelo novo" />
        <button class="btn btn-primary btn-sm" onclick="corrigirPar(this)">Corrigir</button>
        <button class="btn btn-outline btn-sm" onclick="adicionarCatalogo(this)" title="O par já está correto — cadastra no catálogo (suplemento manual)">Ao catálogo</button>
        <button class="btn btn-danger btn-sm" onclick="excluirPar(this)" title="O veículo não pertence ao acervo — apaga todos os anúncios deste par">Excluir</button>
        <span class="qv-msg"></span>
      </td>
    </tr>
  `).join('');
}

// Opções do <select> de modelos já cadastrados da marca (vazio se a marca não
// está no catálogo — a usuária ajusta a marca primeiro e o select repopula).
function opcoesModeloSelect(marca) {
  const modelos = qvModelos[(marca || '').trim().toUpperCase()] || [];
  const cabeca = modelos.length
    ? '<option value="">— modelo cadastrado —</option>'
    : '<option value="">— marca sem modelos no catálogo —</option>';
  return cabeca + modelos.map(m => `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`).join('');
}

// Escolher um modelo cadastrado preenche o campo de modelo (que o Corrigir usa).
function aoSelecionarModelo(sel) {
  if (!sel.value) return;
  sel.closest('tr').querySelector('.qv-in-modelo').value = sel.value;
}

// Ao trocar a marca, repopula o select com os modelos daquela marca.
function atualizarModelosLinha(inp) {
  const sel = inp.closest('tr').querySelector('.qv-sel-modelo');
  if (sel) sel.innerHTML = opcoesModeloSelect(inp.value);
}

async function corrigirPar(btn) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.qv-msg');
  const marcaNova  = tr.querySelector('.qv-in-marca').value.trim();
  const modeloNova = tr.querySelector('.qv-in-modelo').value.trim();
  const payload = {
    marca:  tr.dataset.marca,
    modelo: tr.dataset.modelo,
    marca_nova:  marcaNova,
    modelo_nova: modeloNova,
  };
  btn.disabled = true;
  msg.className = 'qv-msg';
  msg.textContent = 'Salvando…';
  try {
    const res = await fetch('/admin/api/corrigir-marca-modelo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.erro) {
      msg.className = 'qv-msg qv-msg--erro';
      msg.textContent = data.erro;
      btn.disabled = false;
      return;
    }
    // Correção invalida a lista de "todos os modelos" (cache) — recarrega ao reabrir.
    mmPares = null;
    if (data.no_catalogo) {
      msg.className = 'qv-msg qv-msg--ok';
      msg.textContent = `✓ ${data.atualizados} → catálogo`;
      // Saiu da quarentena: remove o par do estado local e re-renderiza.
      qvPares = qvPares.filter(p => !(p.marca === tr.dataset.marca && (p.modelo || '') === tr.dataset.modelo));
      setTimeout(renderVerificar, 900);
    } else {
      // Gravado, mas o par corrigido ainda não está no catálogo — recarrega
      // do servidor pra refletir a fusão/renomeação e continua na lista.
      msg.className = 'qv-msg qv-msg--aviso';
      msg.textContent = `✓ ${data.atualizados} (ainda fora do catálogo)`;
      setTimeout(carregarVerificar, 900);
    }
  } catch (err) {
    msg.className = 'qv-msg qv-msg--erro';
    msg.textContent = `Erro: ${err.message}`;
    btn.disabled = false;
  }
}

async function verAnunciosDoPar(btn) {
  // Expande/colapsa uma linha de detalhe com os anúncios do par, logo abaixo.
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
  detail.innerHTML = '<td colspan="4" class="qv-detail-cell">Carregando…</td>';
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
    cell.innerHTML = `
      <div class="qv-detail-wrap">
        <table class="qv-detail-table">
          <thead>
            <tr><th>Fonte</th><th>Título</th><th class="an-th--num">Ano</th><th class="an-th--num">Preço</th><th>Versão</th><th>Obs</th></tr>
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
                <td>${escapeHtml(r.obs || '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    cell.innerHTML = `<span class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</span>`;
  }
}

async function adicionarCatalogo(btn) {
  // Cadastra o par ATUAL da linha no catálogo — pro caso em que a marca/modelo
  // já estão certos e só faltava estar no catálogo consagrado. (Se precisar
  // ajustar a grafia antes, use "Corrigir"; o par corrigido reaparece e aí sim
  // "Ao catálogo".)
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.qv-msg');
  const marca  = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  if (!modelo) {
    msg.className = 'qv-msg qv-msg--erro';
    msg.textContent = 'Sem modelo — use "Corrigir" antes.';
    return;
  }
  btn.disabled = true;
  msg.className = 'qv-msg';
  msg.textContent = 'Adicionando…';
  try {
    const res = await fetch('/admin/api/adicionar-ao-catalogo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ marca, modelo }),
    });
    const data = await res.json();
    if (data.erro) {
      msg.className = 'qv-msg qv-msg--erro';
      msg.textContent = data.erro;
      btn.disabled = false;
      return;
    }
    mmPares = null;  // "todos os modelos" muda de contagem/pertencimento
    msg.className = 'qv-msg qv-msg--ok';
    const faixa = (data.ano_min && data.ano_max) ? ` (${data.ano_min}–${data.ano_max})` : '';
    msg.textContent = data.ja_existia ? '✓ já no catálogo' : `✓ no catálogo${faixa}`;
    // Saiu da quarentena: remove do estado local e re-renderiza.
    qvPares = qvPares.filter(p => !(p.marca === marca && (p.modelo || '') === modelo));
    setTimeout(renderVerificar, 900);
  } catch (err) {
    msg.className = 'qv-msg qv-msg--erro';
    msg.textContent = `Erro: ${err.message}`;
    btn.disabled = false;
  }
}

async function excluirPar(btn) {
  // Apaga TODOS os anúncios do par — pro caso em que o veículo nem pertence ao
  // acervo (ex.: um VW T-Cross que entrou por ano forjado no título). Ação
  // destrutiva e irreversível: confirma antes.
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.qv-msg');
  const marca  = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const qtd = tr.querySelector('.qv-count')?.textContent?.trim() || '?';
  const nome = `${marca} ${modelo || '(sem modelo)'}`.trim();
  if (!confirm(`Apagar definitivamente ${qtd} anúncio(s) de "${nome}"?\n\nUse esta opção só quando o veículo não pertence ao acervo. Não dá pra desfazer.`)) {
    return;
  }
  btn.disabled = true;
  msg.className = 'qv-msg';
  msg.textContent = 'Excluindo…';
  try {
    const res = await fetch('/admin/api/excluir-marca-modelo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ marca, modelo }),
    });
    const data = await res.json();
    if (data.erro) {
      msg.className = 'qv-msg qv-msg--erro';
      msg.textContent = data.erro;
      btn.disabled = false;
      return;
    }
    mmPares = null;  // "todos os modelos" muda de contagem
    msg.className = 'qv-msg qv-msg--ok';
    msg.textContent = `✓ ${data.excluidos} apagado(s)`;
    // Sumiu do banco: remove do estado local e re-renderiza.
    qvPares = qvPares.filter(p => !(p.marca === marca && (p.modelo || '') === modelo));
    setTimeout(renderVerificar, 900);
  } catch (err) {
    msg.className = 'qv-msg qv-msg--erro';
    msg.textContent = `Erro: ${err.message}`;
    btn.disabled = false;
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
  document.getElementById('filter-ano').value = '';
  buscar(1);
});
document.getElementById('filter-modelo')?.addEventListener('change', () => {
  document.getElementById('filter-ano').value = '';
  buscar(1);
});
document.getElementById('filter-ano')?.addEventListener('change', () => buscar(1));

// ── Init ───────────────────────────────────────────────────────────────
/**
 * Lê marca/modelo/ano da query string (ex.: link "ver anúncios" do
 * dashboard: /admin/anuncios?marca=Volkswagen&modelo=Fusca) — os valores só
 * são aplicados aos selects depois que a 1ª busca traz as opções (são
 * dropdowns agora, não dá pra setar .value antes da <option> existir).
 * "q" é texto livre, pode ser pré-preenchido direto.
 */
function lerFiltrosDaUrl() {
  const urlParams = new URLSearchParams(window.location.search);
  const q = urlParams.get('q');
  if (q) document.getElementById('filter-q').value = q;

  const marca = urlParams.get('marca');
  const modelo = urlParams.get('modelo');
  const ano = urlParams.get('ano');
  if (marca || modelo || ano) filtrosPendentesDaUrl = { marca, modelo, ano };
}

lerFiltrosDaUrl();
atualizarIconesSort();
buscar(1);
