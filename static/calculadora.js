/*
 * Valor Clássico — calculadora de média.
 * Lê a relação de pares (marca, modelo) uma vez, recorta pelo mínimo de
 * anúncios (padrão 3) e, ao escolher o modelo, busca as estatísticas de
 * preço e monta um pequeno dashboard (média em destaque + mediana, faixa,
 * média por ano e por fonte). Sem bibliotecas.
 */
"use strict";

const FMT_INT = new Intl.NumberFormat("pt-BR");

function fmtBRL(v) {
  if (v == null) return "—";
  return "R$ " + Math.round(v).toLocaleString("pt-BR");
}

// Rótulos são dado do banco (não confiável) — nunca interpolar em innerHTML.
function texto(tag, valor, classe) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  el.textContent = valor;
  return el;
}

let pares = [];   // [{marca, modelo, qtd}] — carregado uma vez

const selMin    = document.getElementById("calc-min");
const selMarca  = document.getElementById("calc-marca");
const selModelo = document.getElementById("calc-modelo");
const msg       = document.getElementById("calc-msg");
const resultado = document.getElementById("calc-resultado");

// ── Carga inicial dos pares ──────────────────────────────────────────────
async function carregarPares() {
  try {
    const res  = await fetch("/admin/api/marca-modelo");
    const data = await res.json();
    if (data.erro) throw new Error(data.erro);
    // Só pares com modelo (sem modelo não dá pra calcular média de "um modelo").
    pares = (data.pares || []).filter(p => p.modelo && p.modelo.trim());
    popularMarcas();
  } catch (err) {
    selMarca.replaceChildren(new Option("Erro ao carregar", ""));
    mostrarMsg(`Erro ao carregar a relação de modelos: ${err.message}`, "calc-erro");
  }
}

function minAtual() {
  return parseInt(selMin.value, 10) || 1;
}

// Marcas que têm pelo menos um modelo alcançando o mínimo.
function popularMarcas() {
  const min = minAtual();
  const marcas = [...new Set(pares.filter(p => p.qtd >= min).map(p => p.marca))]
    .sort((a, b) => a.localeCompare(b));

  const anterior = selMarca.value;
  selMarca.replaceChildren(new Option(
    marcas.length ? "Selecione uma marca" : "Nenhuma marca com esse mínimo", ""));
  for (const m of marcas) selMarca.add(new Option(m, m));
  // Preserva a marca se ela ainda alcança o mínimo.
  if (marcas.includes(anterior)) selMarca.value = anterior;

  popularModelos();
}

// Modelos da marca escolhida que alcançam o mínimo (com a contagem no rótulo).
function popularModelos() {
  const min = minAtual();
  const marca = selMarca.value;
  const anterior = selModelo.value;

  if (!marca) {
    selModelo.replaceChildren(new Option("Selecione uma marca", ""));
    selModelo.disabled = true;
    return;
  }
  const modelos = pares
    .filter(p => p.marca === marca && p.qtd >= min)
    .sort((a, b) => a.modelo.localeCompare(b.modelo));

  selModelo.replaceChildren(new Option("Selecione um modelo", ""));
  for (const p of modelos) {
    selModelo.add(new Option(`${p.modelo} (${FMT_INT.format(p.qtd)})`, p.modelo));
  }
  selModelo.disabled = false;
  if (modelos.some(p => p.modelo === anterior)) {
    selModelo.value = anterior;
  }
}

// ── Estatísticas do modelo escolhido ─────────────────────────────────────
async function calcular() {
  const marca  = selMarca.value;
  const modelo = selModelo.value;
  if (!marca || !modelo) {
    resultado.classList.add("hidden");
    mostrarMsg("Selecione uma marca e um modelo acima.", "calc-hint");
    return;
  }

  resultado.classList.remove("hidden");
  resultado.classList.add("carregando");
  mostrarMsg("", "calc-hint");
  try {
    const qs  = `marca=${encodeURIComponent(marca)}&modelo=${encodeURIComponent(modelo)}`;
    const res = await fetch(`/admin/api/media-modelo?${qs}`);
    const d   = await res.json();
    if (d.erro) throw new Error(d.erro);
    render(d);
  } catch (err) {
    resultado.classList.add("hidden");
    mostrarMsg(`Erro ao calcular: ${err.message}`, "calc-erro");
  } finally {
    resultado.classList.remove("carregando");
  }
}

function render(d) {
  document.getElementById("calc-modelo-nome").textContent = `${d.marca} ${d.modelo}`;

  const semPreco = !d.com_preco;
  document.getElementById("calc-media").textContent = semPreco ? "sem preço" : fmtBRL(d.preco_medio);

  const periodo = (d.ano_min && d.ano_max)
    ? (d.ano_min === d.ano_max ? `ano ${d.ano_min}` : `anos ${d.ano_min}–${d.ano_max}`)
    : "ano não identificado";
  const base = semPreco
    ? `${FMT_INT.format(d.total)} anúncio(s), nenhum com preço informado`
    : `média de ${FMT_INT.format(d.com_preco)} de ${FMT_INT.format(d.total)} anúncio(s) com preço · ${periodo}`;
  document.getElementById("calc-media-sub").textContent = base;

  document.getElementById("calc-mediana").textContent   = semPreco ? "—" : fmtBRL(d.preco_mediano);
  document.getElementById("calc-qtd").textContent       = `${FMT_INT.format(d.com_preco)} / ${FMT_INT.format(d.total)}`;
  document.getElementById("calc-min-preco").textContent = semPreco ? "—" : fmtBRL(d.preco_min);
  document.getElementById("calc-max-preco").textContent = semPreco ? "—" : fmtBRL(d.preco_max);

  // Média por ano
  const tbAno = document.querySelector("#calc-tab-ano tbody");
  tbAno.replaceChildren();
  if (!d.por_ano.length) {
    const tr = document.createElement("tr");
    tr.append(texto("td", "Nenhum ano identificado."));
    tr.firstChild.colSpan = 3;
    tbAno.append(tr);
  } else {
    for (const r of d.por_ano) {
      const tr = document.createElement("tr");
      tr.append(texto("td", r.ano));
      tr.append(texto("td", FMT_INT.format(r.qtd), "num"));
      tr.append(texto("td", r.preco_medio == null ? "—" : fmtBRL(r.preco_medio), "num"));
      tbAno.append(tr);
    }
  }

  // Por fonte
  const tbFonte = document.querySelector("#calc-tab-fonte tbody");
  tbFonte.replaceChildren();
  for (const r of d.por_fonte) {
    const tr = document.createElement("tr");
    tr.append(texto("td", r.fonte || "—"));
    tr.append(texto("td", FMT_INT.format(r.qtd), "num"));
    tr.append(texto("td", r.preco_medio == null ? "—" : fmtBRL(r.preco_medio), "num"));
    tbFonte.append(tr);
  }

  // Atalho pra ver os anúncios desse par na lista
  const link = document.getElementById("calc-ver-anuncios");
  const p = new URLSearchParams({ marca: d.marca, modelo: d.modelo });
  link.href = `/admin/anuncios?${p.toString()}`;
}

function mostrarMsg(txt, classe) {
  msg.textContent = txt;
  msg.className = classe || "calc-hint";
  msg.style.display = txt ? "" : "none";
}

// ── Wiring ───────────────────────────────────────────────────────────────
selMin.addEventListener("change", () => {
  popularMarcas();
  calcular();  // o par pode ter deixado de alcançar o mínimo → esconde/recalcula
});
selMarca.addEventListener("change", () => {
  popularModelos();
  calcular();
});
selModelo.addEventListener("change", calcular);

carregarPares();
