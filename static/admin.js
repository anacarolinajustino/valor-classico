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
async function coletarTodos() {
  const btn = document.getElementById('btn-coletar-todos');
  btn.disabled = true;
  btn.textContent = 'Coletando…';

  // Marca todos os cards como "em fila"
  document.querySelectorAll('.admin-source-status').forEach(el => {
    el.textContent = '⏳';
    el.className = 'admin-source-status admin-source-status--loading';
  });
  document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = true);

  log('Iniciando coleta de <strong>todas as fontes</strong>…');

  try {
    const res  = await fetch('/admin/api/coletar-todos', { method: 'POST' });
    const data = await res.json();

    if (!res.ok) throw new Error(data.erro || `HTTP ${res.status}`);

    (data.resultados || []).forEach(r => {
      const status = document.getElementById(`status-${r.fonte}`);
      if (!status) return;
      if (r.ok) {
        const m = r.metricas || {};
        const db = r.resultado || {};
        status.textContent = '✓';
        status.className = 'admin-source-status admin-source-status--ok';
        log(
          `<strong>${r.fonte}</strong> — ${db.novos ?? '?'} novos · ${m.anuncios_validos ?? '?'} anúncios · ${m.tempo_total_s ?? '?'}s`,
          'ok',
        );
      } else {
        status.textContent = '✗';
        status.className = 'admin-source-status admin-source-status--erro';
        log(`Erro em <strong>${r.fonte}</strong>: ${r.erro}`, 'erro');
      }
    });

    log(`Coleta concluída. Total novos: <strong>${data.total_novos ?? 0}</strong>`, 'ok');
    await carregarStatus();

  } catch (err) {
    log(`Erro ao coletar todos: ${err.message}`, 'erro');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Coletar todos';
    document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = false);
  }
}

// ── Init ───────────────────────────────────────
carregarStatus();
