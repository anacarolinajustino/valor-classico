/**
 * Valor Clássico — front-end da busca
 * Fluxo encadeado: Marca → Modelo → Ano → Resultado
 */

// ── Elementos ──────────────────────────────────────
const form          = document.getElementById('search-form');
const inputMarca    = document.getElementById('input-marca');
const inputModelo   = document.getElementById('input-modelo');
const inputAno      = document.getElementById('input-ano');
const btnBuscar     = document.getElementById('btn-buscar');
const btnLimpar     = document.getElementById('btn-limpar');
const listModelo    = document.getElementById('list-modelo');

const resultSection = document.getElementById('result-section');
const resultLoading = document.getElementById('result-loading');
const resultError   = document.getElementById('result-error');
const resultErrorMsg = document.getElementById('result-error-msg');
const resultEmpty   = document.getElementById('result-empty');
const resultData    = document.getElementById('result-data');

// ── Helpers ────────────────────────────────────────
function fmt(valor) {
  if (valor == null || valor === 0) return '—';
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
}

function showOnly(el) {
  [resultLoading, resultError, resultEmpty, resultData].forEach(e => e.classList.add('hidden'));
  if (el) el.classList.remove('hidden');
}

function setResultVisible(visible) {
  resultSection.classList.toggle('hidden', !visible);
}

function scrollToResult() {
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Marcas — carrega do catálogo CSV via API ────────
(async () => {
  try {
    const res  = await fetch('/api/marcas');
    const data = await res.json();
    (data.marcas || []).forEach(m => {
      const opt = document.createElement('option');
      // Capitaliza cada palavra para exibição legível
      opt.value = m;
      opt.textContent = m.split(' ').map(
        p => p.charAt(0) + p.slice(1).toLowerCase()
      ).join(' ');
      inputMarca.appendChild(opt);
    });
  } catch {
    // Fallback silencioso: o select fica vazio mas funcional
    console.warn('Não foi possível carregar marcas do catálogo.');
  }
})();

// ── Gatilho: marca selecionada → carrega modelos ──
let debounceTimer = null;

inputMarca.addEventListener('change', () => {
  const marca = inputMarca.value.trim();

  // Resetar campos dependentes
  inputModelo.value = '';
  inputModelo.disabled = true;
  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;
  listModelo.innerHTML = '';

  if (!marca) return;

  carregarModelos(marca);
});

async function carregarModelos(marca) {
  try {
    const res = await fetch(`/api/modelos?marca=${encodeURIComponent(marca)}`);
    if (!res.ok) return;
    const data = await res.json();
    const modelos = data.modelos || [];

    listModelo.innerHTML = '';
    modelos.forEach(m => {
      const opt = document.createElement('option');
      // Capitaliza cada palavra para melhor leitura
      opt.value = m.split(' ').map(p => p.charAt(0) + p.slice(1).toLowerCase()).join(' ');
      listModelo.appendChild(opt);
    });

    if (modelos.length > 0) {
      inputModelo.disabled = false;
      inputModelo.focus();
    }
  } catch {
    // falha silenciosa — campo continua habilitado manualmente
    inputModelo.disabled = false;
  }
}

// ── Gatilho: modelo preenchido → habilita ano ────
inputModelo.addEventListener('focus', () => inputModelo.select());

inputModelo.addEventListener('input', () => {
  document.getElementById('modelo-error')?.classList.add('hidden');
  const marca  = inputMarca.value.trim();
  const modelo = inputModelo.value.trim();

  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;

  if (!marca || modelo.length < 2) return;

  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => carregarAnos(marca, modelo), 400);
});

async function carregarAnos(marca, modelo) {
  try {
    const res = await fetch(`/api/anos?marca=${encodeURIComponent(marca)}&modelo=${encodeURIComponent(modelo)}`);
    if (!res.ok) return;
    const data = await res.json();
    const anos = data.anos || [];

    inputAno.innerHTML = '<option value="">Todos</option>';
    anos.sort((a, b) => b - a).forEach(ano => {
      const opt = document.createElement('option');
      opt.value = ano;
      opt.textContent = ano;
      inputAno.appendChild(opt);
    });

    inputAno.disabled = false;
  } catch {
    inputAno.disabled = false;
  }
}

// ── Limpar ─────────────────────────────────────────
btnLimpar.addEventListener('click', () => {
  inputMarca.value  = '';
  inputModelo.value = '';
  inputModelo.disabled = true;
  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;
  listModelo.innerHTML = '';
  setResultVisible(false);
  inputMarca.focus();
  // Dispara change manualmente para garantir reset de estado
  inputMarca.dispatchEvent(new Event('change'));
});

// ── Busca principal ────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const marca  = inputMarca.value.trim();
  const modelo = inputModelo.value.trim();
  const ano    = inputAno.value.trim();

  const modeloError = document.getElementById('modelo-error');
  if (!modelo) {
    modeloError.classList.remove('hidden');
    inputModelo.focus();
    return;
  }
  modeloError.classList.add('hidden');

  if (!marca) {
    inputMarca.focus();
    return;
  }

  // Mostrar seção de resultado com loading
  setResultVisible(true);
  showOnly(resultLoading);
  scrollToResult();
  btnBuscar.disabled = true;

  try {
    const params = new URLSearchParams({ marca, modelo });
    if (ano) params.set('ano', ano);

    const res  = await fetch(`/api/buscar?${params}`);
    const data = await res.json();

    if (!res.ok) {
      resultErrorMsg.textContent = data.erro || 'Erro desconhecido na consulta.';
      showOnly(resultError);
      return;
    }

    const linhas = data.linhas || [];
    if (linhas.length === 0) {
      showOnly(resultEmpty);
      return;
    }

    // Preenche header
    const consulta = data.consulta;
    const tituloConsulta = `${consulta.marca} · ${consulta.modelo}${consulta.ano ? ' · ' + consulta.ano : ''}`;
    document.getElementById('result-title').textContent = tituloConsulta;
    document.getElementById('result-fontes').textContent = (data.fontes_ativas || []).join(', ');

    // Preenche tabela por ano
    const tbody = document.getElementById('year-tbody');
    tbody.innerHTML = '';
    linhas.forEach(linha => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="year-cell">${linha.ano || '—'}</td>
        <td class="price-cell">${fmt(linha.media)}</td>
        <td>${fmt(linha.mediana)}</td>
        <td>${fmt(linha.minimo)}</td>
        <td>${fmt(linha.maximo)}</td>
        <td class="amostra-cell">${linha.amostra}</td>
      `;
      tbody.appendChild(tr);
    });

    // Total de amostras + badge de confiança
    const totalAmostra = data.total_amostra || 0;
    document.getElementById('result-total-amostra').textContent = totalAmostra;
    const badge = document.getElementById('confidence-badge');
    if (totalAmostra >= 10) {
      badge.className = 'confidence-badge high';
      badge.textContent = 'Alta confiança';
    } else if (totalAmostra >= 4) {
      badge.className = 'confidence-badge medium';
      badge.textContent = 'Confiança média';
    } else {
      badge.className = 'confidence-badge low';
      badge.textContent = 'Amostra pequena';
    }

    // Anúncios individuais (só quando ano filtrado)
    const anunciosDetails = document.getElementById('result-anuncios');
    const anunciosList    = document.getElementById('anuncios-list');
    const anunciosCount   = document.getElementById('anuncios-count');
    const anuncios = data.anuncios || [];
    if (anuncios.length > 0) {
      anunciosCount.textContent = anuncios.length;
      anunciosList.innerHTML = '';
      anuncios.forEach(a => {
        const li    = document.createElement('li');
        const link  = document.createElement('a');
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
        anunciosList.appendChild(li);
      });
      anunciosDetails.classList.remove('hidden');
      anunciosDetails.removeAttribute('open');
    } else {
      anunciosDetails.classList.add('hidden');
    }

    showOnly(resultData);

  } catch (err) {
    console.error(err);
    resultErrorMsg.textContent = 'Falha de conexão com o servidor. Verifique sua internet e tente novamente.';
    showOnly(resultError);
  } finally {
    btnBuscar.disabled = false;
  }
});

// ── Segurança: escape HTML para evitar XSS ────────
function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}
