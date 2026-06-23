/**
 * Valor Clássico — admin.js
 * Carrega o status do banco e gerencia coletas por fonte.
 */

const logEl = document.getElementById('admin-log');

// ── Log ────────────────────────────────────────
function log(msg, tipo = 'info') {
  const placeholder = logEl.querySelector('.admin-log-placeholder');
  if (placeholder) placeholder.remove();

  const line = document.createElement('div');
  line.className = `admin-log-line admin-log-line--${tipo}`;

  const ts = new Date().toLocaleTimeString('pt-BR');
  line.innerHTML = `<span class="admin-log-ts">${ts}</span> ${msg}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
  logEl.innerHTML = '<p class="admin-log-placeholder">Nenhuma coleta iniciada nesta sessão.</p>';
}

// ── Status do banco ────────────────────────────
async function carregarStatus() {
  try {
    const res  = await fetch('/admin/api/status');
    const data = await res.json();

    document.getElementById('stat-total').textContent  = (data.total_anuncios ?? 0).toLocaleString('pt-BR');
    document.getElementById('stat-fontes').textContent = (data.por_fonte || []).length;

    // Última atualização: a mais recente de todas as fontes
    const datas = (data.por_fonte || []).map(f => f.last_update).filter(Boolean);
    document.getElementById('stat-ultima').textContent =
      datas.length ? datas.sort().reverse()[0].slice(0, 10) : '—';

    // Tabela de fontes com dados
    const tbody = document.getElementById('admin-fonte-tbody');
    tbody.innerHTML = '';
    (data.por_fonte || []).forEach(f => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="admin-fonte-nome">${f.fonte}</td>
        <td>${(f.count || 0).toLocaleString('pt-BR')}</td>
        <td>${f.last_update ? f.last_update.slice(0, 10) : '—'}</td>
      `;
      tbody.appendChild(tr);
    });
    if ((data.por_fonte || []).length > 0) {
      document.getElementById('admin-fonte-lista').style.display = '';
    }

    // Grade de fontes para coleta
    renderSourceGrid(data.connectors || []);

  } catch (err) {
    console.error(err);
    log('Erro ao carregar status do banco.', 'erro');
  }
}

// ── Grade de fontes ────────────────────────────
function renderSourceGrid(connectors) {
  const grid = document.getElementById('admin-source-grid');
  grid.innerHTML = '';

  if (!connectors.length) {
    grid.innerHTML = '<p class="admin-loading-text">Nenhuma fonte configurada.</p>';
    return;
  }

  connectors.forEach(fonte => {
    const card = document.createElement('div');
    card.className = 'admin-source-card';
    card.id = `card-${fonte}`;

    card.innerHTML = `
      <div class="admin-source-info">
        <span class="admin-source-nome">${fonte}</span>
        <span class="admin-source-status" id="status-${fonte}"></span>
      </div>
      <button class="btn btn-outline btn-sm admin-btn-coletar"
              id="btn-${fonte}"
              onclick="coletar('${fonte}')">
        Coletar
      </button>
    `;
    grid.appendChild(card);
  });
}

// ── Coleta ─────────────────────────────────────
async function coletar(fonte) {
  const btn    = document.getElementById(`btn-${fonte}`);
  const status = document.getElementById(`status-${fonte}`);

  btn.disabled = true;
  btn.textContent = 'Coletando…';
  status.textContent = '⏳';
  status.className = 'admin-source-status admin-source-status--loading';

  log(`Iniciando coleta: <strong>${fonte}</strong>…`);

  try {
    const res  = await fetch('/admin/api/coletar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fonte }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.erro || `HTTP ${res.status}`);
    }

    const m = data.metricas || {};
    const r = data.resultado || {};
    status.textContent = '✓';
    status.className = 'admin-source-status admin-source-status--ok';

    log(
      `<strong>${fonte}</strong> — ${r.novos ?? '?'} novos, ${r.atualizados ?? '?'} atualizados · `
      + `${m.paginas_listagem ?? '?'} páginas · ${m.tempo_total_s ?? '?'}s`,
      'ok',
    );

    // Recarrega status após coleta
    await carregarStatus();

  } catch (err) {
    status.textContent = '✗';
    status.className = 'admin-source-status admin-source-status--erro';
    log(`Erro em <strong>${fonte}</strong>: ${err.message}`, 'erro');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Coletar';
  }
}

// ── Coletar todos ──────────────────────────────
// Chama coletar(fonte) sequencialmente para cada fonte, evitando timeout
// de requisição única longa no servidor.
async function coletarTodos() {
  const btn = document.getElementById('btn-coletar-todos');
  btn.disabled = true;
  btn.textContent = 'Coletando…';
  document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = true);

  // Coleta lista de fontes dos cards já renderizados
  const fontes = Array.from(document.querySelectorAll('.admin-source-card'))
    .map(card => card.id.replace('card-', ''))
    .filter(Boolean);

  if (!fontes.length) {
    log('Nenhuma fonte carregada. Aguarde o status carregar.', 'erro');
    btn.disabled = false;
    btn.textContent = 'Coletar todos';
    document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = false);
    return;
  }

  log(`Iniciando coleta de <strong>${fontes.length} fontes</strong> em sequência…`);
  let totalNovos = 0;

  for (const fonte of fontes) {
    await coletar(fonte);
    // coletar() já loga e atualiza o status do card individualmente
    // Pequena pausa entre fontes para não sobrecarregar o servidor
    await new Promise(r => setTimeout(r, 500));
  }

  log(`Coleta de todas as fontes concluída.`, 'ok');
  btn.disabled = false;
  btn.textContent = 'Coletar todos';
  document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = false);
}

// ── Init ───────────────────────────────────────
carregarStatus();
