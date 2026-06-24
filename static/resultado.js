/**
 * Valor Clássico — resultado.js
 * Lê os query params, chama /api/buscar, renderiza a faixa de valores.
 */

const params  = new URLSearchParams(window.location.search);
const marca   = params.get('marca') || '';
const modelo  = params.get('modelo') || '';
const ano     = params.get('ano') || '';

const elLoading   = document.getElementById('estado-loading');
const elErro      = document.getElementById('estado-erro');
const elErroMsg   = document.getElementById('erro-msg');
const elVazio     = document.getElementById('estado-vazio');
const elResultado = document.getElementById('estado-resultado');

function mostrar(el) {
  [elLoading, elErro, elVazio, elResultado].forEach(e => e.classList.add('hidden'));
  el.classList.remove('hidden');
}

function fmt(valor) {
  if (valor == null || valor === 0) return '—';
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
}

// ── Busca ──────────────────────────────────────────────────
async function buscar() {
  if (!marca || !modelo) {
    elErroMsg.textContent = 'Parâmetros de busca inválidos. Volte à página inicial.';
    mostrar(elErro);
    return;
  }

  mostrar(elLoading);

  try {
    const qp = new URLSearchParams({ marca, modelo });
    if (ano) qp.set('ano', ano);

    const res  = await fetch(`/api/buscar?${qp}`);
    const data = await res.json();

    if (!res.ok) {
      elErroMsg.textContent = data.erro || 'Erro desconhecido.';
      mostrar(elErro);
      return;
    }

    const linhas = data.linhas || [];

    if (linhas.length === 0) {
      mostrar(elVazio);
      return;
    }

    renderizar(data, linhas);
    mostrar(elResultado);

  } catch (err) {
    console.error(err);
    elErroMsg.textContent = 'Falha de conexão com o servidor.';
    mostrar(elErro);
  }
}

// ── Renderização ───────────────────────────────────────────
function renderizar(data, linhas) {
  const consulta = data.consulta || {};

  // Título
  const partes = [consulta.marca, consulta.modelo, consulta.ano].filter(Boolean);
  document.getElementById('res-titulo').textContent = partes.join(' · ');
  document.title = `${partes.join(' · ')} — Valor Clássico`;

  // Fontes
  const fontes = (data.fontes_ativas || []);
  document.getElementById('res-fontes').textContent =
    fontes.length ? 'Fontes: ' + fontes.join(', ') : '';

  // Faixa de valores: min global e max global dos dados filtrados
  const todosMin    = linhas.map(l => l.minimo).filter(v => v != null);
  const todosMax    = linhas.map(l => l.maximo).filter(v => v != null);
  const faixaMin    = todosMin.length ? Math.min(...todosMin) : null;
  const faixaMax    = todosMax.length ? Math.max(...todosMax) : null;

  // Mediana: usa o ano mais recente (ou media ponderada simples)
  const totalAmostra = data.total_amostra || 0;
  let medianaGlobal = null;
  if (linhas.length === 1) {
    medianaGlobal = linhas[0].mediana;
  } else if (linhas.length > 1) {
    // mediana ponderada pelo tamanho da amostra de cada ano
    const somaPeso = linhas.reduce((s, l) => s + (l.amostra || 0), 0);
    if (somaPeso > 0) {
      medianaGlobal = linhas.reduce((s, l) => s + (l.mediana || 0) * (l.amostra || 0), 0) / somaPeso;
    }
  }

  document.getElementById('faixa-min').textContent     = fmt(faixaMin);
  document.getElementById('faixa-max').textContent     = fmt(faixaMax);
  document.getElementById('faixa-mediana').textContent = fmt(medianaGlobal);
  document.getElementById('faixa-amostras').textContent = totalAmostra || '—';

  // Badge de confiança
  const badge = document.getElementById('faixa-confianca');
  if (totalAmostra >= 10) {
    badge.className = 'confidence-badge high';
    badge.textContent = 'Alta';
  } else if (totalAmostra >= 4) {
    badge.className = 'confidence-badge medium';
    badge.textContent = 'Média';
  } else {
    badge.className = 'confidence-badge low';
    badge.textContent = 'Baixa — amostra pequena';
  }

  // Data (usa o dado mais recente)
  const hoje = new Date().toLocaleDateString('pt-BR');
  document.getElementById('faixa-data').textContent = `Dados processados em ${hoje}`;

  // Tabela de detalhamento por ano
  const tbody = document.getElementById('year-tbody');
  tbody.innerHTML = '';
  linhas.forEach(l => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="year-cell">${l.ano || '—'}</td>
      <td class="price-cell">${fmt(l.media)}</td>
      <td>${fmt(l.mediana)}</td>
      <td>${fmt(l.minimo)}</td>
      <td>${fmt(l.maximo)}</td>
      <td class="amostra-cell">${l.amostra}</td>
    `;
    tbody.appendChild(tr);
  });

  // Mostra o <details> de breakdown só se houver dados
  document.getElementById('ano-details').classList.toggle('hidden', linhas.length === 0);

  // Anúncios individuais (quando filtrado por ano)
  const anuncios = data.anuncios || [];
  const detAnuncios = document.getElementById('result-anuncios');
  if (anuncios.length > 0) {
    document.getElementById('anuncios-count').textContent = anuncios.length;
    const lista = document.getElementById('anuncios-list');
    lista.innerHTML = '';
    anuncios.forEach(a => {
      const li   = document.createElement('li');
      const link = document.createElement('a');
      link.href   = /^https?:\/\//.test(a.url) ? a.url : '#';
      link.target = '_blank';
      link.rel    = 'noopener noreferrer';
      link.textContent = a.titulo || a.url;

      const preco = document.createElement('span');
      preco.className = 'anuncio-preco';
      preco.textContent = fmt(a.preco);

      const fonte = document.createElement('span');
      fonte.className = 'anuncio-fonte';
      fonte.textContent = a.fonte;

      li.append(link, preco, fonte);
      lista.appendChild(li);
    });
    detAnuncios.classList.remove('hidden');
  } else {
    detAnuncios.classList.add('hidden');
  }

}

// ── Inicia ─────────────────────────────────────
buscar();
