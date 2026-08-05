// Pendências de verificação — fila única de decisões manuais.
//
// A página é uma tabela só, filtrada por aba. Cada aba corresponde a um TIPO
// de pendência com uma ação diferente, e a evidência das fontes externas é o
// que define o tipo (ver src/pipeline/pendencias.py). Separar em abas evita o
// erro que a lista chapada antiga convidava: tratar "nome truncado no banco"
// como se fosse "modelo faltando no catálogo" e cadastrar o nome errado.

let pdDados = null;      // resposta de /admin/api/pendencias
let pdAliases = null;    // resposta de /admin/api/aliases-pendentes
let pdAba = 'corrigir_nome';
let pdOrder = 'qtd';
let pdDir = 'desc';

const AJUDA = {
  corrigir_nome:
    'A fonte de referência tem um nome MAIS LONGO que o do banco (ex.: o banco diz "RANGE", ' +
    'a fonte diz "RANGE ROVER"). Isso quase sempre é modelo truncado numa extração ruim — ' +
    'o certo é corrigir o nome, não cadastrar o pedaço no catálogo. A sugestão já vem preenchida.',
  confirmado:
    'A fonte confirma que esse carro existe, muitas vezes com a faixa de produção. Se marca e ' +
    'modelo estão certos, "Ao catálogo" cadastra o par no suplemento manual e ele sai da fila. ' +
    'Atenção: a faixa de ano é de produção MUNDIAL, costuma ser mais larga que a brasileira.',
  sem_evidencia:
    'Nenhuma fonte conhece esse par. Para carro NACIONAL isso é o esperado — as duas fontes são ' +
    'europeias e americanas, e nenhuma marca brasileira existe nelas. Então "sem evidência" não ' +
    'quer dizer errado: quer dizer que só você pode decidir se é carro de verdade ou lixo de parsing.',
  alias:
    'Palpites de tradução entre a grafia do banco e a das fontes em inglês, gerados por ' +
    'semelhança de texto. Só os incertos aparecem aqui — as traduções de regra fixa ' +
    '(Série 3 → 3 Series, espaçamento) não precisam de conferência. Um alias rejeitado deixa ' +
    'de valer como evidência nas outras abas.',
};

// ── Abas ────────────────────────────────────────────────────────────────
function trocarAba(tipo) {
  pdAba = tipo;
  document.querySelectorAll('.pd-tab').forEach(b => {
    b.classList.toggle('pd-tab--ativa', b.dataset.tipo === tipo);
  });
  document.getElementById('pd-tab-ajuda').textContent = AJUDA[tipo] || '';

  const ehAlias = tipo === 'alias';
  document.getElementById('pd-pares-section').classList.toggle('hidden', ehAlias);
  document.getElementById('pd-alias-section').classList.toggle('hidden', !ehAlias);

  if (ehAlias) {
    if (pdAliases === null) carregarAliases(); else renderAliases();
  } else {
    renderPares();
  }
}

// ── Pares ───────────────────────────────────────────────────────────────
async function carregarPendencias() {
  const tbody = document.getElementById('pd-tbody');
  tbody.innerHTML = '<tr><td colspan="5" class="an-empty">Carregando…</td></tr>';
  const incluir = document.getElementById('pd-dispensadas').value === '1' ? '?incluir_dispensadas=1' : '';
  try {
    const res = await fetch(`/admin/api/pendencias${incluir}`);
    const data = await res.json();
    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="5" class="an-empty an-empty--erro">${escapeHtml(data.erro)}</td></tr>`;
      return;
    }
    pdDados = data;
    document.getElementById('pd-marcas').innerHTML =
      (data.marcas_catalogo || []).map(m => `<option value="${escapeAttr(m)}">`).join('');
    Object.entries(data.totais || {}).forEach(([tipo, n]) => {
      const el = document.getElementById(`pd-cont-${tipo}`);
      if (el) el.textContent = n.toLocaleString('pt-BR');
    });
    renderPares();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function ordenarPares(col) {
  if (pdOrder === col) {
    pdDir = pdDir === 'asc' ? 'desc' : 'asc';
  } else {
    pdOrder = col;
    pdDir = col === 'qtd' ? 'desc' : 'asc';
  }
  ['marca', 'modelo', 'qtd'].forEach(c => {
    const el = document.getElementById(`pd-sort-${c}`);
    if (el) el.textContent = c === pdOrder ? (pdDir === 'asc' ? '↑' : '↓') : '';
  });
  renderPares();
}

// Frase curta do que a fonte sabe — é o que substitui a pesquisa manual que a
// usuária tinha que fazer par a par na lista antiga.
function textoEvidencia(p) {
  const ev = p.evidencia;
  if (!ev) return '<span class="pd-ev pd-ev--nada">nenhuma fonte conhece</span>';

  const faixa = (ev.ano_min && ev.ano_max)
    ? ` · produção <strong>${ev.ano_min}–${ev.ano_max}</strong>`
    : ' · sem faixa de ano';
  const via = ev.estrategia === 'literal' ? '' : ` (por ${escapeHtml(ev.estrategia)})`;
  const classe = p.tipo === 'corrigir_nome' ? 'pd-ev--alerta' : 'pd-ev--ok';

  return `<span class="pd-ev ${classe}">` +
    `<strong>${escapeHtml(ev.modelo_fonte)}</strong>${via}${faixa}` +
    `<span class="pd-ev-fonte">${escapeHtml(ev.fonte)}</span></span>`;
}

function acoesDaLinha(p) {
  const ev = p.evidencia;
  // "Ao catálogo" leva a faixa da fonte junto quando existe: min/max de dois
  // ou três anúncios soltos é pior referência que a produção real do carro.
  const anos = (ev && ev.ano_min && ev.ano_max)
    ? ` data-ano-min="${ev.ano_min}" data-ano-max="${ev.ano_max}"`
    : '';

  if (p.dispensada) {
    return `<button class="btn btn-outline btn-sm" onclick="restaurarPar(this)">Devolver à fila</button>
            <span class="pd-msg pd-msg--aviso">dispensada</span>`;
  }

  // No caso do nome truncado o botão "Ao catálogo" fica de fora de propósito:
  // cadastrar 'RANGE' cimentaria o erro em vez de corrigi-lo.
  const aoCatalogo = p.tipo === 'corrigir_nome'
    ? ''
    : `<button class="btn btn-outline btn-sm"${anos} onclick="adicionarCatalogo(this)"
         title="O par já está correto — cadastra no catálogo (suplemento manual)">Ao catálogo</button>`;

  // Os campos de correção só ficam abertos na aba de nome incompleto, onde
  // corrigir É a ação e a sugestão já vem preenchida. Nas outras duas a
  // decisão costuma ser um clique só ("Ao catálogo"/"Dispensar"), e três
  // campos abertos em 250+ linhas viram muito ruído e muita rolagem.
  const abrirEdicao = p.tipo === 'corrigir_nome';

  return `
    <div class="pd-acoes">
      ${abrirEdicao ? '' : `
        <button class="btn btn-neutro btn-sm" onclick="alternarEdicao(this)"
                title="Ajustar marca/modelo deste par">Corrigir…</button>`}
      ${aoCatalogo}
      <button class="btn btn-neutro btn-sm" onclick="dispensarPar(this)"
              title="Já analisei e vou deixar como está — tira da fila sem alterar nada">Dispensar</button>
      <button class="btn btn-danger btn-sm" onclick="excluirPar(this)"
              title="O veículo não pertence ao acervo — apaga todos os anúncios deste par">Excluir</button>
      <span class="pd-msg"></span>
    </div>
    <div class="pd-edicao ${abrirEdicao ? '' : 'hidden'}">
      <input class="an-filter-input pd-in-marca" list="pd-marcas" value="${escapeAttr(p.marca)}" placeholder="marca"
             oninput="atualizarModelosLinha(this)" />
      <select class="an-filter-select pd-sel-modelo" onchange="aoSelecionarModelo(this)"
              title="Selecionar um modelo já cadastrado desta marca">${opcoesModeloSelect(p.marca)}</select>
      <input class="an-filter-input pd-in-modelo" value="${escapeAttr(p.sugestao || p.modelo || '')}"
             placeholder="ou digite um modelo novo" />
      <button class="btn btn-primary btn-sm" onclick="corrigirPar(this)">Corrigir</button>
    </div>`;
}

// Abre/fecha os campos de correção de uma linha.
function alternarEdicao(btn) {
  const edicao = btn.closest('tr').querySelector('.pd-edicao');
  edicao.classList.toggle('hidden');
  if (!edicao.classList.contains('hidden')) edicao.querySelector('.pd-in-modelo').focus();
}

function renderPares() {
  const tbody = document.getElementById('pd-tbody');
  if (pdDados === null) return;

  const termo = document.getElementById('pd-busca').value.trim().toUpperCase();
  let linhas = pdDados.pares.filter(p => p.tipo === pdAba);
  if (termo) {
    linhas = linhas.filter(p => p.marca.includes(termo) || (p.modelo || '').includes(termo));
  }

  linhas.sort((a, b) => {
    const dir = pdDir === 'asc' ? 1 : -1;
    if (pdOrder === 'qtd') return (a.qtd - b.qtd) * dir;
    return String(a[pdOrder]).localeCompare(String(b[pdOrder])) * dir;
  });

  const anuncios = linhas.reduce((s, p) => s + p.qtd, 0);
  document.getElementById('pd-total').textContent =
    `${linhas.length.toLocaleString('pt-BR')} pares · ${anuncios.toLocaleString('pt-BR')} anúncios`;

  if (!linhas.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="an-empty">Nada pendente nesta aba.</td></tr>';
    return;
  }

  tbody.innerHTML = linhas.map(p => `
    <tr data-marca="${escapeAttr(p.marca)}" data-modelo="${escapeAttr(p.modelo || '')}"
        class="${p.dispensada ? 'pd-row--dispensada' : ''}">
      <td class="an-td">${escapeHtml(p.marca)}</td>
      <td class="an-td">${escapeHtml(p.modelo || '—')}</td>
      <td class="an-td an-td--num">
        <button class="qv-count" onclick="verAnunciosDoPar(this)" title="Ver os anúncios deste par">${p.qtd.toLocaleString('pt-BR')}</button>
      </td>
      <td class="an-td">${textoEvidencia(p)}</td>
      <td class="an-td">${acoesDaLinha(p)}</td>
    </tr>
  `).join('');
}

// Opções do <select> de modelos já cadastrados da marca (vazio se a marca não
// está no catálogo — a usuária ajusta a marca primeiro e o select repopula).
function opcoesModeloSelect(marca) {
  const modelos = (pdDados?.modelos_catalogo || {})[(marca || '').trim().toUpperCase()] || [];
  const cabeca = modelos.length
    ? '<option value="">— modelo cadastrado —</option>'
    : '<option value="">— marca sem modelos no catálogo —</option>';
  return cabeca + modelos.map(m => `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`).join('');
}

function aoSelecionarModelo(sel) {
  if (!sel.value) return;
  sel.closest('tr').querySelector('.pd-in-modelo').value = sel.value;
}

function atualizarModelosLinha(inp) {
  const sel = inp.closest('tr').querySelector('.pd-sel-modelo');
  if (sel) sel.innerHTML = opcoesModeloSelect(inp.value);
}

// Remove o par do estado local e re-renderiza, sem ida extra ao servidor.
function tirarDaFila(tr) {
  const marca = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const alvo = pdDados.pares.find(p => p.marca === marca && (p.modelo || '') === modelo);
  if (alvo) {
    pdDados.totais[alvo.tipo] = Math.max(0, (pdDados.totais[alvo.tipo] || 1) - 1);
    const el = document.getElementById(`pd-cont-${alvo.tipo}`);
    if (el) el.textContent = pdDados.totais[alvo.tipo].toLocaleString('pt-BR');
  }
  pdDados.pares = pdDados.pares.filter(p => !(p.marca === marca && (p.modelo || '') === modelo));
  setTimeout(renderPares, 700);
}

async function postar(url, payload, btn, msg) {
  btn.disabled = true;
  msg.className = 'pd-msg';
  msg.textContent = 'Salvando…';
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.erro) {
      msg.className = 'pd-msg pd-msg--erro';
      msg.textContent = data.erro;
      btn.disabled = false;
      return null;
    }
    return data;
  } catch (err) {
    msg.className = 'pd-msg pd-msg--erro';
    msg.textContent = `Erro: ${err.message}`;
    btn.disabled = false;
    return null;
  }
}

async function corrigirPar(btn) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.pd-msg');
  const data = await postar('/admin/api/corrigir-marca-modelo', {
    marca: tr.dataset.marca,
    modelo: tr.dataset.modelo,
    marca_nova: tr.querySelector('.pd-in-marca').value.trim(),
    modelo_nova: tr.querySelector('.pd-in-modelo').value.trim(),
  }, btn, msg);
  if (!data) return;

  if (data.no_catalogo) {
    msg.className = 'pd-msg pd-msg--ok';
    msg.textContent = `✓ ${data.atualizados} → catálogo`;
    tirarDaFila(tr);
  } else {
    // Gravado, mas o par corrigido ainda não está no catálogo — recarrega do
    // servidor pra refletir a fusão/renomeação; continua na fila.
    msg.className = 'pd-msg pd-msg--aviso';
    msg.textContent = `✓ ${data.atualizados} (ainda fora do catálogo)`;
    setTimeout(carregarPendencias, 900);
  }
}

async function adicionarCatalogo(btn) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.pd-msg');
  const payload = {
    marca: tr.querySelector('.pd-in-marca').value.trim() || tr.dataset.marca,
    modelo: tr.querySelector('.pd-in-modelo').value.trim() || tr.dataset.modelo,
  };
  // Par sem modelo não pode ser cadastrado: a chave do catálogo é (marca,
  // modelo), e uma entrada com modelo vazio casaria com qualquer coisa.
  if (!payload.modelo) {
    msg.className = 'pd-msg pd-msg--erro';
    msg.textContent = 'Sem modelo — preencha o campo e use "Corrigir" antes.';
    return;
  }
  if (btn.dataset.anoMin) payload.ano_min = btn.dataset.anoMin;
  if (btn.dataset.anoMax) payload.ano_max = btn.dataset.anoMax;

  const data = await postar('/admin/api/adicionar-ao-catalogo', payload, btn, msg);
  if (!data) return;
  msg.className = 'pd-msg pd-msg--ok';
  const faixa = (data.ano_min && data.ano_max) ? ` (${data.ano_min}–${data.ano_max})` : '';
  msg.textContent = data.ja_existia ? '✓ já estava no catálogo' : `✓ cadastrado${faixa}`;
  tirarDaFila(tr);
}

async function dispensarPar(btn) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.pd-msg');
  const data = await postar('/admin/api/dispensar-pendencia', {
    marca: tr.dataset.marca,
    modelo: tr.dataset.modelo,
  }, btn, msg);
  if (!data) return;
  msg.className = 'pd-msg pd-msg--ok';
  msg.textContent = '✓ dispensada';
  tirarDaFila(tr);
}

async function restaurarPar(btn) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.pd-msg');
  const data = await postar('/admin/api/dispensar-pendencia', {
    marca: tr.dataset.marca,
    modelo: tr.dataset.modelo,
    restaurar: true,
  }, btn, msg);
  if (!data) return;
  setTimeout(carregarPendencias, 700);
}

async function excluirPar(btn) {
  // Apaga TODOS os anúncios do par — pro caso em que o veículo nem pertence ao
  // acervo (ex.: um VW T-Cross que entrou por ano forjado no título). Ação
  // destrutiva e irreversível: o confirm mostra a contagem real.
  const tr = btn.closest('tr');
  const marca = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const qtd = tr.querySelector('.qv-count')?.textContent?.trim() || '?';
  const nome = `${marca} ${modelo || '(sem modelo)'}`.trim();
  if (!confirm(`Apagar definitivamente ${qtd} anúncio(s) de "${nome}"?\n\nUse esta opção só quando o veículo não pertence ao acervo. Não dá pra desfazer.`)) {
    return;
  }
  const msg = tr.querySelector('.pd-msg');
  const data = await postar('/admin/api/excluir-marca-modelo', { marca, modelo }, btn, msg);
  if (!data) return;
  msg.className = 'pd-msg pd-msg--ok';
  msg.textContent = `✓ ${data.excluidos} apagados`;
  tirarDaFila(tr);
}

// Expande/colapsa uma linha de detalhe com os anúncios do par — é como a
// usuária confere o título original antes de decidir.
async function verAnunciosDoPar(btn) {
  const tr = btn.closest('tr');
  const existente = tr.nextElementSibling;
  if (existente && existente.classList.contains('qv-detail')) {
    existente.remove();
    return;
  }
  const marca = tr.dataset.marca;
  const modelo = tr.dataset.modelo;
  const detail = document.createElement('tr');
  detail.className = 'qv-detail';
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
    cell.innerHTML = `
      <div class="qv-detail-wrap">
        <table class="qv-detail-table">
          <thead>
            <tr><th>Fonte</th><th>Título</th><th class="an-th--num">Ano</th><th class="an-th--num">Preço</th><th>Versão</th><th>Geração</th></tr>
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
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  } catch (err) {
    cell.innerHTML = `<span class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</span>`;
  }
}

// ── Aliases ─────────────────────────────────────────────────────────────
async function carregarAliases() {
  const tbody = document.getElementById('pd-alias-tbody');
  tbody.innerHTML = '<tr><td colspan="6" class="an-empty">Carregando…</td></tr>';
  try {
    const res = await fetch('/admin/api/aliases-pendentes');
    const data = await res.json();
    if (data.erro) {
      tbody.innerHTML = `<tr><td colspan="6" class="an-empty an-empty--erro">${escapeHtml(data.erro)}</td></tr>`;
      return;
    }
    pdAliases = data;
    const el = document.getElementById('pd-cont-alias');
    if (el) el.textContent = (data.total_pendentes || 0).toLocaleString('pt-BR');
    renderAliases();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="an-empty an-empty--erro">Erro: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderAliases() {
  const tbody = document.getElementById('pd-alias-tbody');
  if (pdAliases === null) return;

  document.getElementById('pd-alias-nota').textContent =
    `${pdAliases.total_deterministicos} traduções de regra fixa foram aceitas automaticamente e não aparecem aqui.`;

  const linhas = pdAliases.aliases || [];
  if (!linhas.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="an-empty">Nenhum alias pendente.</td></tr>';
    return;
  }
  tbody.innerHTML = linhas.map(a => `
    <tr data-marca="${escapeAttr(a.marca)}" data-ptbr="${escapeAttr(a.modelo_ptbr)}">
      <td class="an-td">${escapeHtml(a.marca)}</td>
      <td class="an-td">${escapeHtml(a.modelo_ptbr)}</td>
      <td class="an-td"><strong>${escapeHtml(a.modelo_intl)}</strong>
        <span class="pd-ev-fonte">${escapeHtml(a.fonte)}</span></td>
      <td class="an-td an-td--num">${(a.similaridade * 100).toFixed(0)}%</td>
      <td class="an-td an-td--num">${a.n_anuncios.toLocaleString('pt-BR')}</td>
      <td class="an-td">
        <div class="pd-acoes">
          <button class="btn btn-primary btn-sm" onclick="decidirAlias(this,'aprovado')"
                  title="É o mesmo carro — o alias passa a valer como evidência">É o mesmo carro</button>
          <button class="btn btn-danger btn-sm" onclick="decidirAlias(this,'rejeitado')"
                  title="São carros diferentes — o alias deixa de valer">São diferentes</button>
          <span class="pd-msg"></span>
        </div>
      </td>
    </tr>
  `).join('');
}

async function decidirAlias(btn, decisao) {
  const tr = btn.closest('tr');
  const msg = tr.querySelector('.pd-msg');
  const data = await postar('/admin/api/decidir-alias', {
    marca: tr.dataset.marca,
    modelo_ptbr: tr.dataset.ptbr,
    decisao,
  }, btn, msg);
  if (!data) return;
  msg.className = 'pd-msg pd-msg--ok';
  msg.textContent = decisao === 'aprovado' ? '✓ confirmado' : '✓ rejeitado';
  pdAliases.aliases = pdAliases.aliases.filter(
    a => !(a.marca === tr.dataset.marca && a.modelo_ptbr === tr.dataset.ptbr));
  pdAliases.total_pendentes = Math.max(0, pdAliases.total_pendentes - 1);
  const el = document.getElementById('pd-cont-alias');
  if (el) el.textContent = pdAliases.total_pendentes.toLocaleString('pt-BR');
  // Rejeitar um alias muda a evidência das outras abas — força recarga.
  if (decisao === 'rejeitado') pdDados = null;
  setTimeout(renderAliases, 700);
}

// ── Utilitários ─────────────────────────────────────────────────────────
function fmtPreco(val) {
  if (val == null) return '—';
  return 'R$ ' + Number(val).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

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

// ── Início ──────────────────────────────────────────────────────────────
document.getElementById('pd-tab-ajuda').textContent = AJUDA[pdAba];
carregarPendencias();
carregarAliases();
