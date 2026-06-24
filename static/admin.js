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

// ── Helpers de progresso por card ──────────────
function setCardEstado(fonte, estado, mensagem = '') {
  const card = document.getElementById(`card-${fonte}`);
  if (!card) return;
  card.classList.remove('admin-source-card--loading', 'admin-source-card--ok', 'admin-source-card--erro');
  if (estado) card.classList.add(`admin-source-card--${estado}`);

  const msg = document.getElementById(`progmsg-${fonte}`);
  if (msg) msg.textContent = mensagem;
}

// ── Status do banco ────────────────────────────
async function carregarStatus() {
  try {
    const res  = await fetch('/admin/api/status');
    const data = await res.json();

    document.getElementById('stat-total').textContent  = (data.total_anuncios ?? 0).toLocaleString('pt-BR');
    document.getElementById('stat-fontes').textContent = (data.por_fonte || []).length;

    const datas = (data.por_fonte || []).map(f => f.last_update).filter(Boolean);
    document.getElementById('stat-ultima').textContent =
      datas.length ? datas.sort().reverse()[0].slice(0, 10) : '—';

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

  // Ativas primeiro, inativas ao final
  const sorted = [...connectors].sort((a, b) => {
    const aAtivo = typeof a === 'object' ? a.ativo : true;
    const bAtivo = typeof b === 'object' ? b.ativo : true;
    if (aAtivo === bAtivo) return 0;
    return aAtivo ? -1 : 1;
  });

  sorted.forEach(item => {
    const fonte = typeof item === 'object' ? item.nome : item;
    const ativo = typeof item === 'object' ? item.ativo : true;

    const card = document.createElement('div');
    card.className = 'admin-source-card' + (ativo ? '' : ' admin-source-card--inativa');
    card.id = `card-${fonte}`;
    card.dataset.ativo = ativo ? 'true' : 'false';

    card.innerHTML = `
      <div class="admin-source-top">
        <div class="admin-source-info">
          <span class="admin-source-nome">${fonte}</span>
          ${ativo ? '' : '<span class="admin-badge-inativa">inativa</span>'}
        </div>
        <button class="btn btn-outline btn-sm admin-btn-coletar"
                id="btn-${fonte}"
                onclick="coletar('${fonte}')">
          Coletar
        </button>
      </div>
      <div class="admin-progress-wrap">
        <div class="admin-progress-bar" id="prog-${fonte}"></div>
      </div>
      <div class="admin-progress-msg" id="progmsg-${fonte}"></div>
    `;
    grid.appendChild(card);
  });
}

// ── Polling de tarefa assíncrona ───────────────
async function _pollTask(taskId, fonte) {
  const MAX_MS = 10 * 60 * 1000;  // 10 minutos
  const INTERVAL_MS = 2000;
  const started = Date.now();

  while (Date.now() - started < MAX_MS) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const res = await fetch(`/admin/api/coletar-status/${taskId}`);
    const data = await res.json();
    if (data.status === 'done')  return data;
    if (data.status === 'error') throw new Error(data.erro || 'Erro desconhecido');
    // status === 'running' → continua esperando
  }
  throw new Error('Timeout: coleta demorou mais de 10 minutos');
}

// ── Coleta individual ──────────────────────────
// Inicia a coleta em background e faz polling até concluir.
// Retorna true em sucesso, false em erro.
async function coletar(fonte, { atualizarStatus = true } = {}) {
  const btn = document.getElementById(`btn-${fonte}`);
  btn.disabled = true;
  btn.textContent = 'Coletando…';

  setCardEstado(fonte, 'loading', 'Coletando…');
  log(`Iniciando coleta: <strong>${fonte}</strong>…`);

  let sucesso = false;
  try {
    const res = await fetch('/admin/api/coletar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fonte }),
    });
    const startData = await res.json();
    if (!res.ok) throw new Error(startData.erro || `HTTP ${res.status}`);

    // Aguarda a tarefa background via polling
    const data = await _pollTask(startData.task_id, fonte);

    const m = data.metricas || {};
    const r = data.resultado || {};
    const resumo = [
      m.anuncios_validos != null ? `${m.anuncios_validos} anúncios` : null,
      r.novos != null            ? `${r.novos} novos`               : null,
      r.atualizados != null      ? `${r.atualizados} atualizados`   : null,
      m.tempo_total_s != null    ? `${m.tempo_total_s}s`            : null,
    ].filter(Boolean).join(' · ');

    setCardEstado(fonte, 'ok', resumo);
    log(`<strong>${fonte}</strong> — ${resumo}`, 'ok');
    sucesso = true;

    if (atualizarStatus) await carregarStatus();

  } catch (err) {
    setCardEstado(fonte, 'erro', err.message);
    log(`Erro em <strong>${fonte}</strong>: ${err.message}`, 'erro');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Coletar';
  }
  return sucesso;
}

// ── Coletar todos ──────────────────────────────
async function coletarTodos() {
  const btn = document.getElementById('btn-coletar-todos');
  btn.disabled = true;
  document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = true);

  const fontes = Array.from(document.querySelectorAll('.admin-source-card[data-ativo="true"]'))
    .map(card => card.id.replace('card-', ''))
    .filter(Boolean);

  if (!fontes.length) {
    log('Nenhuma fonte carregada. Aguarde o status carregar.', 'erro');
    btn.disabled = false;
    btn.textContent = 'Coletar todos';
    document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = false);
    return;
  }

  // Reseta todos os cards para idle antes de começar
  fontes.forEach(f => setCardEstado(f, '', ''));

  log(`Iniciando coleta de <strong>${fontes.length} fontes</strong> em sequência…`);

  let ok = 0;
  let erro = 0;

  for (let i = 0; i < fontes.length; i++) {
    btn.textContent = `Coletando… ${i + 1}/${fontes.length}`;
    const sucesso = await coletar(fontes[i], { atualizarStatus: false });
    if (sucesso) ok++; else erro++;
    await new Promise(r => setTimeout(r, 300));
  }

  await carregarStatus();

  log(`Coleta concluída — <strong>${ok} com sucesso</strong>, ${erro} com erro.`, ok > 0 ? 'ok' : 'erro');

  btn.disabled = false;
  btn.textContent = 'Coletar todos';
  document.querySelectorAll('.admin-btn-coletar').forEach(b => b.disabled = false);
}

// ── Init ───────────────────────────────────────
carregarStatus();
