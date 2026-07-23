/*
 * Dashboard do painel admin — gráficos em SVG/CSS puro, sem bibliotecas.
 * Série única em todos os gráficos (verde #2F6B4F, validado 6,0:1 no creme),
 * então nenhum precisa de legenda; valores nas pontas + tooltip por marca.
 */
"use strict";

const FMT_INT = new Intl.NumberFormat("pt-BR");

function fmtBRL(v) {
  if (v == null) return "—";
  if (v >= 1e6) return "R$ " + (v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mi";
  if (v >= 1e3) return "R$ " + Math.round(v / 1e3).toLocaleString("pt-BR") + " mil";
  return "R$ " + Math.round(v).toLocaleString("pt-BR");
}

const NOMES_FAIXAS = [
  "até R$ 25 mil", "R$ 25–50 mil", "R$ 50–100 mil",
  "R$ 100–200 mil", "R$ 200–500 mil", "R$ 500 mil+",
];

function nomeDecada(d) {
  if (d === 1949) return "até 1949";
  if (d === 2000) return "2000";
  return String(d);
}

/* ── Tooltip (um só; textContent sempre — rótulos são dado não confiável) ── */

const tooltip = document.getElementById("dash-tooltip");

function mostrarTooltip(ev, valor, rotulo) {
  tooltip.replaceChildren();
  const v = document.createElement("span");
  v.className = "tt-valor";
  v.textContent = valor;
  const r = document.createElement("span");
  r.className = "tt-rotulo";
  r.textContent = rotulo;
  tooltip.append(v, r);
  tooltip.style.display = "block";
  moverTooltip(ev);
}

function moverTooltip(ev) {
  const margem = 14;
  let x = ev.clientX + margem;
  let y = ev.clientY + margem;
  const rect = tooltip.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = ev.clientX - rect.width - margem;
  if (y + rect.height > window.innerHeight - 8) y = ev.clientY - rect.height - margem;
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
}

function esconderTooltip() {
  tooltip.style.display = "none";
}

function ligarTooltip(el, valorFn, rotuloFn) {
  el.addEventListener("pointerenter", (ev) => mostrarTooltip(ev, valorFn(), rotuloFn()));
  el.addEventListener("pointermove", moverTooltip);
  el.addEventListener("pointerleave", esconderTooltip);
}

/* ── Barras horizontais (HTML/CSS) ── */

function renderBarrasH(container, itens, { fmtValor = (v) => FMT_INT.format(v) } = {}) {
  container.replaceChildren();
  if (!itens.length) {
    container.textContent = "Sem dados para este recorte.";
    return;
  }
  const max = Math.max(...itens.map((i) => i.valor));
  for (const item of itens) {
    const row = document.createElement("div");
    row.className = "dash-hbar-row";

    const label = document.createElement("span");
    label.className = "dash-hbar-label";
    label.textContent = item.rotulo;
    label.title = item.rotulo;

    const track = document.createElement("div");
    track.className = "dash-hbar-track";
    const bar = document.createElement("div");
    bar.className = "dash-hbar-bar";
    bar.style.width = (max ? (item.valor / max) * 100 : 0).toFixed(2) + "%";
    const valor = document.createElement("span");
    valor.className = "dash-hbar-valor";
    valor.textContent = fmtValor(item.valor);
    track.append(bar, valor);

    row.append(label, track);
    ligarTooltip(row, () => fmtValor(item.valor), () => item.rotulo);
    container.append(row);
  }
}

/* ── Colunas (SVG) ── */

const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/** Coluna com topo arredondado (4px) e base reta, crescendo da baseline. */
function pathColuna(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return [
    `M ${x} ${y + h}`,
    `V ${y + r}`,
    `Q ${x} ${y} ${x + r} ${y}`,
    `H ${x + w - r}`,
    `Q ${x + w} ${y} ${x + w} ${y + r}`,
    `V ${y + h}`,
    "Z",
  ].join(" ");
}

function tickLimpo(max) {
  if (max <= 0) return 1;
  const passo = Math.pow(10, Math.floor(Math.log10(max)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (max / (passo * m) <= 4) return passo * m;
  }
  return passo * 10;
}

function renderColunas(container, itens, { fmtValor = (v) => FMT_INT.format(v), fmtTick = fmtValor } = {}) {
  container.replaceChildren();
  if (!itens.length) {
    container.textContent = "Sem dados para este recorte.";
    return;
  }

  // viewBox na largura real do card: SVG espremido encolhe o texto junto
  const W = Math.max(320, container.clientWidth || 600), H = 240;
  const m = { top: 22, right: 8, bottom: 26, left: 56 };
  const plotW = W - m.left - m.right;
  const plotH = H - m.top - m.bottom;
  const max = Math.max(...itens.map((i) => i.valor));
  const passo = tickLimpo(max);
  const teto = Math.ceil(max / passo) * passo || 1;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "dash-svg", role: "img" });

  // grade horizontal (hairline) + ticks do eixo y
  for (let v = 0; v <= teto; v += passo) {
    const y = m.top + plotH - (v / teto) * plotH;
    const linha = el("line", { x1: m.left, x2: W - m.right, y1: y, y2: y, class: "grade" });
    svg.append(linha);
    const tick = el("text", { x: m.left - 8, y: y + 3.5, "text-anchor": "end", class: "tick" });
    tick.textContent = fmtTick(v);
    svg.append(tick);
  }

  const banda = plotW / itens.length;
  const larguraCol = Math.min(24, banda * 0.6);

  itens.forEach((item, i) => {
    const cx = m.left + banda * i + banda / 2;
    const h = (item.valor / teto) * plotH;
    const y = m.top + plotH - h;

    // alvo de interação: a banda inteira, maior que a marca
    const hit = el("rect", {
      x: m.left + banda * i, y: m.top, width: banda, height: plotH, class: "hit",
    });
    const col = el("path", {
      d: pathColuna(cx - larguraCol / 2, y, larguraCol, h, 4), class: "col",
    });
    for (const alvo of [hit, col]) {
      ligarTooltip(alvo, () => fmtValor(item.valor), () => item.rotulo);
    }

    // valor no topo da coluna
    const cap = el("text", { x: cx, y: y - 6, "text-anchor": "middle", class: "cap" });
    cap.textContent = fmtValor(item.valor);

    // rótulo da categoria
    const cat = el("text", { x: cx, y: H - 8, "text-anchor": "middle", class: "cat" });
    cat.textContent = item.rotulo;

    svg.append(hit, col, cap, cat);
  });

  container.append(svg);
}

/* ── Tabela de modelos ── */

function renderTabelaModelos(container, itens) {
  container.replaceChildren();
  if (!itens.length) {
    container.textContent = "Sem dados para este recorte.";
    return;
  }
  const tabela = document.createElement("table");
  tabela.className = "dash-tabela";
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  for (const [texto, num] of [["Marca", false], ["Modelo", false], ["Anúncios", true], ["Preço mediano", true]]) {
    const th = document.createElement("th");
    th.textContent = texto;
    if (num) th.className = "num";
    trh.append(th);
  }
  thead.append(trh);
  const tbody = document.createElement("tbody");
  for (const item of itens) {
    const tr = document.createElement("tr");
    tr.className = "dash-tabela-row-link";
    tr.title = `Ver anúncios de ${item.marca} ${item.modelo}`;
    const params = new URLSearchParams({ marca: item.marca, modelo: item.modelo });
    const href = `/admin/anuncios?${params}`;
    tr.addEventListener("click", (ev) => {
      // Clique já caiu num <a> (marca/modelo) — deixa o link nativo cuidar
      // (Ctrl+clique, nova aba pelo menu etc.); só o resto da linha usa o open manual.
      if (ev.target.closest("a")) return;
      window.open(href, "_blank", "noopener");
    });

    const celulas = [
      [item.marca, false],
      [item.modelo, false],
      [FMT_INT.format(item.qtd), true],
      [fmtBRL(item.preco_mediano), true],
    ];
    for (const [texto, num] of celulas) {
      const td = document.createElement("td");
      if (num) {
        td.textContent = texto;
        td.className = "num";
      } else {
        // Link real (não só onclick na linha) — funciona com Ctrl/Cmd+clique,
        // "abrir em nova aba" do menu de contexto, e leitores de tela.
        const a = document.createElement("a");
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = texto;
        a.className = "dash-tabela-link";
        td.append(a);
      }
      tr.append(td);
    }
    tbody.append(tr);
  }
  tabela.append(thead, tbody);
  container.append(tabela);
}

/* ── Selects de recorte (faceta: opções contadas sob os OUTROS filtros) ── */

/**
 * Repopula um <select> preservando a seleção atual, se ela ainda existir
 * na nova lista (senão o navegador recai pro placeholder).
 */
function popularSelect(select, itens, { valorFn, rotuloFn, placeholder }) {
  const atual = select.value;
  select.replaceChildren();
  const optPlaceholder = document.createElement("option");
  optPlaceholder.value = "";
  optPlaceholder.textContent = placeholder;
  select.append(optPlaceholder);
  for (const item of itens) {
    const opt = document.createElement("option");
    opt.value = valorFn(item);
    opt.textContent = rotuloFn(item);
    select.append(opt);
  }
  if (itens.some((item) => valorFn(item) === atual)) select.value = atual;
}

/* ── Carga e composição ── */

const grid = document.getElementById("dash-grid");
const filtroFonte = document.getElementById("filtro-fonte");
const filtroMarca = document.getElementById("filtro-marca");
const filtroModelo = document.getElementById("filtro-modelo");
const filtroAno = document.getElementById("filtro-ano");
const filtroMinAnuncios = document.getElementById("filtro-min-anuncios");
let fontesPopuladas = false;

async function carregar() {
  grid.classList.add("carregando");
  try {
    const params = new URLSearchParams();
    if (filtroFonte.value) params.set("fonte", filtroFonte.value);
    if (filtroMarca.value) params.set("marca", filtroMarca.value);
    if (filtroModelo.value) params.set("modelo", filtroModelo.value);
    if (filtroAno.value) params.set("ano", filtroAno.value);
    if (filtroMinAnuncios.value) params.set("min_anuncios", filtroMinAnuncios.value);
    const qs = params.toString();
    const resp = await fetch("/admin/api/dashboard" + (qs ? `?${qs}` : ""));
    const dados = await resp.json();
    if (dados.erro) throw new Error(dados.erro);

    // popula o select de fontes uma única vez, com a lista completa
    if (!fontesPopuladas) {
      for (const f of dados.por_fonte) {
        const opt = document.createElement("option");
        opt.value = f.fonte;
        opt.textContent = f.fonte;
        filtroFonte.append(opt);
      }
      fontesPopuladas = true;
    }

    popularSelect(filtroMarca, dados.opcoes.marca, {
      valorFn: (x) => x.marca,
      rotuloFn: (x) => `${x.marca} (${FMT_INT.format(x.qtd)})`,
      placeholder: "Todas as marcas",
    });

    const temMarca = Boolean(filtroMarca.value);
    filtroModelo.disabled = !temMarca;
    popularSelect(filtroModelo, dados.opcoes.modelo, {
      valorFn: (x) => x.modelo,
      rotuloFn: (x) => `${x.modelo} (${FMT_INT.format(x.qtd)})`,
      placeholder: temMarca ? "Todos os modelos" : "Selecione uma marca",
    });

    popularSelect(filtroAno, dados.opcoes.ano, {
      valorFn: (x) => String(x.ano),
      rotuloFn: (x) => `${x.ano} (${FMT_INT.format(x.qtd)})`,
      placeholder: "Todos os anos",
    });

    const k = dados.kpis;
    document.getElementById("kpi-total").textContent = FMT_INT.format(k.total);
    document.getElementById("kpi-mediana").textContent = fmtBRL(k.preco_mediano);
    document.getElementById("kpi-fontes").textContent = FMT_INT.format(k.fontes);
    document.getElementById("kpi-com-ano").textContent =
      k.total ? Math.round((k.com_ano / k.total) * 100) + "%" : "—";

    // fontes: top 10 + "outras" agregadas
    const top = dados.por_fonte.slice(0, 10).map((f) => ({ rotulo: f.fonte, valor: f.qtd }));
    const resto = dados.por_fonte.slice(10).reduce((s, f) => s + f.qtd, 0);
    if (resto > 0) top.push({ rotulo: `outras (${dados.por_fonte.length - 10})`, valor: resto });
    renderBarrasH(document.getElementById("chart-fontes"), top);

    renderBarrasH(
      document.getElementById("chart-marcas"),
      dados.top_marcas.map((x) => ({ rotulo: x.marca, valor: x.qtd })),
    );

    renderColunas(
      document.getElementById("chart-decadas"),
      dados.por_decada.map((x) => ({ rotulo: nomeDecada(x.decada), valor: x.qtd })),
    );

    renderColunas(
      document.getElementById("chart-preco-decada"),
      dados.por_decada.map((x) => ({ rotulo: nomeDecada(x.decada), valor: x.preco_mediano || 0 })),
      { fmtValor: fmtBRL },
    );

    renderColunas(
      document.getElementById("chart-faixas"),
      dados.faixas_preco.map((x) => ({ rotulo: NOMES_FAIXAS[x.faixa], valor: x.qtd })),
    );

    renderTabelaModelos(document.getElementById("tabela-modelos"), dados.top_modelos);
  } catch (exc) {
    console.error("dashboard:", exc);
  } finally {
    grid.classList.remove("carregando");
  }
}

filtroFonte.addEventListener("change", carregar);
filtroMarca.addEventListener("change", () => {
  filtroModelo.value = "";
  filtroAno.value = "";
  carregar();
});
filtroModelo.addEventListener("change", () => {
  filtroAno.value = "";
  carregar();
});
filtroAno.addEventListener("change", carregar);
filtroMinAnuncios.addEventListener("change", carregar);
carregar();
