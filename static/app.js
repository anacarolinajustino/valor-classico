/**
 * Valor Clássico — home search
 * Fluxo: Marca → Modelo → Ano → navega para /resultado?...
 */

const form       = document.getElementById('search-form');
const inputMarca  = document.getElementById('input-marca');
const inputModelo = document.getElementById('input-modelo');
const inputAno    = document.getElementById('input-ano');
const btnBuscar   = document.getElementById('btn-buscar');
const btnLimpar   = document.getElementById('btn-limpar');

// ── Marcas ─────────────────────────────────────
(async () => {
  try {
    const res  = await fetch('/api/marcas');
    const data = await res.json();
    (data.marcas || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m.split(' ').map(p => p.charAt(0) + p.slice(1).toLowerCase()).join(' ');
      inputMarca.appendChild(opt);
    });
  } catch {
    console.warn('Não foi possível carregar marcas do catálogo.');
  }
})();

// ── Marca → Modelos ────────────────────────────
inputMarca.addEventListener('change', () => {
  const marca = inputMarca.value.trim();
  inputModelo.innerHTML = '<option value="">Selecione o modelo…</option>';
  inputModelo.disabled = true;
  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;
  if (marca) carregarModelos(marca);
});

async function carregarModelos(marca) {
  try {
    const res  = await fetch(`/api/modelos?marca=${encodeURIComponent(marca)}`);
    const data = await res.json();
    (data.modelos || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m.split(' ').map(p => p.charAt(0) + p.slice(1).toLowerCase()).join(' ');
      inputModelo.appendChild(opt);
    });
    if ((data.modelos || []).length > 0) {
      inputModelo.disabled = false;
      inputModelo.focus();
    }
  } catch {
    inputModelo.disabled = false;
  }
}

// ── Modelo → Anos ──────────────────────────────
inputModelo.addEventListener('change', () => {
  document.getElementById('modelo-error')?.classList.add('hidden');
  const marca  = inputMarca.value.trim();
  const modelo = inputModelo.value.trim();
  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;
  if (marca && modelo) carregarAnos(marca, modelo);
});

async function carregarAnos(marca, modelo) {
  try {
    const res  = await fetch(`/api/anos?marca=${encodeURIComponent(marca)}&modelo=${encodeURIComponent(modelo)}`);
    const data = await res.json();
    inputAno.innerHTML = '<option value="">Todos</option>';
    (data.anos || []).sort((a, b) => b - a).forEach(ano => {
      const opt = document.createElement('option');
      opt.value = opt.textContent = ano;
      inputAno.appendChild(opt);
    });
    inputAno.disabled = false;
  } catch {
    inputAno.disabled = false;
  }
}

// ── Limpar ─────────────────────────────────────
btnLimpar.addEventListener('click', () => {
  inputMarca.value = '';
  inputModelo.innerHTML = '<option value="">Selecione o modelo…</option>';
  inputModelo.disabled = true;
  inputAno.innerHTML = '<option value="">Todos</option>';
  inputAno.disabled = true;
  inputMarca.focus();
  inputMarca.dispatchEvent(new Event('change'));
});

// ── Submit → navega para /resultado ────────────
form.addEventListener('submit', (e) => {
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

  const params = new URLSearchParams({ marca, modelo });
  if (ano) params.set('ano', ano);
  window.location.href = '/resultado?' + params.toString();
});
