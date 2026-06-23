/**
 * Valor Clássico — anuncios.js
 * Tabela paginada de anúncios coletados com filtros e ordenação.
 */

let currentPage   = 1;
let currentOrder  = 'ultima_vista';
let currentDir    = 'desc';

// ── Helpers de formatação ──────────────────────────────────────────────
function fmtPreco(val) {
  if (val == null) return '—';
  return 'R$ ' + Number(val).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fmtData(val) {
  if (!val) return '—';
  return val.slice(0, 10);
}

// ── Filtros ────────────────────────────────────────────────────────────
function params(page) {
  const p = new URLSearchParams();
  const q      = document.getElementById('filter-q').value.trim();
  const fonte  = document.getElementById('filter-fonte').value;
  const marca  = document.getElementById('filter-marca').value.trim();
  const modelo = document.getElementById('filter-modelo').value.trim();
  const ano    = document.getElementById('filter-ano').value.trim();
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

// ── Carregar fontes para o select ──────────────────────────────────────
async function carregarFontes() {
  try {
    const res  = await fetch('/admin/api/anuncios?page=1&page_size=10');
    const data = await res.json();
    const sel  = document.getElementById('filter-fonte');
    (data.fontes_disponiveis || []).forEach(f => {
      const opt = document.createElement('option');
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

// ── Busca / render ─────────────────────────────────────────────────────
async function buscar(page) {
  currentPage = page;
  const tbody = document.getElementById('an-tbody');
  tbody.innerHTML = '<tr><td colspan="7" class="an-empty">Carregando…</td></tr>';

  try {
    const res  = await fetch(`/admin/api/anuncios?${params(page)}`);
    const data = await res.json();

    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="7" class="an-empty an-empty--erro">${data.erro}</td></tr>`;
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

    // Atualiza fontes disponíveis no select (uma vez que chegam)
    if (data.fontes_disponiveis && data.fontes_disponiveis.length) {
      const sel = document.getElementById('filter-fonte');
      const current = sel.value;
      // Preserva seleção atual
      while (sel.options.length > 1) sel.remove(1);
      data.fontes_disponiveis.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f;
        opt.textContent = f;
        if (f === current) opt.selected = true;
        sel.appendChild(opt);
      });
    }

    // Tabela
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="an-empty">Nenhum resultado para os filtros aplicados.</td></tr>';
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
          <td class="an-td an-td--num">${r.ano || '—'}</td>
          <td class="an-td an-td--num">${fmtPreco(r.preco)}</td>
          <td class="an-td an-td--data">${fmtData(r.ultima_vista)}</td>
        </tr>`;
      }).join('');
    }

    renderPaginacao(page, pages);

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
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

// ── Enter nos inputs ───────────────────────────────────────────────────
['filter-q', 'filter-marca', 'filter-modelo', 'filter-ano'].forEach(id => {
  document.getElementById(id)?.addEventListener('keydown', e => {
    if (e.key === 'Enter') buscar(1);
  });
});

// ── Init ───────────────────────────────────────────────────────────────
atualizarIconesSort();
buscar(1);
