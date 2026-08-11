/*
 * Valor Clássico — calculadora de média.
 * Lê a relação de pares (marca, modelo) uma vez, recorta pelo mínimo de
 * anúncios (padrão 3) e, ao escolher o modelo, busca as estatísticas de
 * preço e monta um pequeno dashboard (média em destaque + mediana, faixa,
 * média por versão, por ano e por fonte). A versão é um recorte a mais —
 * é nela que mora boa parte da diferença de preço dentro de um mesmo modelo.
 * Toda contagem é consultável: abre os anúncios daquele recorte ali mesmo,
 * como na lista de marcas/modelos. Sem bibliotecas.
 */
"use strict";

const FMT_INT = new Intl.NumberFormat("pt-BR");

// Sentinela de "sem versão informada" (string vazia na query string não
// distingue isso de "todas as versões") — a API traduz. Ver _arg_versao().
const VERSAO_SEM = "__sem__";

// Corte do servidor em listar_anuncios_do_par — o detalhe é uma amostra
// quando o grupo é maior que isso.
const DETALHE_LIMITE = 300;

// Quantas versões a tabela mostra antes de colapsar. Modelo popular tem
// dezenas de versões de 1 anúncio só (o Fusca tem 60+), que empurrariam as
// seções de ano e fonte pra fora da tela — a lista vem ordenada por
// quantidade, então as que importam estão no topo.
const VERSOES_VISIVEIS = 15;
let mostrarTodasVersoes = false;

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
const selVersao = document.getElementById("calc-versao");
const selGeracao = document.getElementById("calc-geracao");
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

// O critério é do servidor (`tem_colecao`), não uma contagem recalculada
// aqui: o que sustenta a projeção são os anúncios de mercado aberto COM
// preço, e o `qtd` do par conta tudo — loja especializada e "sob consulta"
// inclusive. Filtrar por `qtd` deixaria passar modelo que a calculadora
// depois não consegue aferir.
function passaNoFiltro(p) {
  return selMin.value !== "colecao" || p.tem_colecao;
}

// Marcas que têm pelo menos um modelo passando no filtro.
function popularMarcas() {
  const marcas = [...new Set(pares.filter(passaNoFiltro).map(p => p.marca))]
    .sort((a, b) => a.localeCompare(b));

  const anterior = selMarca.value;
  selMarca.replaceChildren(new Option(
    marcas.length ? "Selecione uma marca" : "Nenhuma marca com esse filtro", ""));
  for (const m of marcas) selMarca.add(new Option(m, m));
  // Preserva a marca se ela ainda passa no filtro.
  if (marcas.includes(anterior)) selMarca.value = anterior;

  popularModelos();
}

// Modelos da marca escolhida que passam no filtro (com a contagem no rótulo).
function popularModelos() {
  const marca = selMarca.value;
  const anterior = selModelo.value;

  if (!marca) {
    selModelo.replaceChildren(new Option("Selecione uma marca", ""));
    selModelo.disabled = true;
    limparVersoes();
    return;
  }
  const modelos = pares
    .filter(p => p.marca === marca && passaNoFiltro(p))
    .sort((a, b) => a.modelo.localeCompare(b.modelo));

  selModelo.replaceChildren(new Option("Selecione um modelo", ""));
  for (const p of modelos) {
    selModelo.add(new Option(`${p.modelo} (${FMT_INT.format(p.qtd)})`, p.modelo));
  }
  selModelo.disabled = false;
  if (modelos.some(p => p.modelo === anterior)) {
    selModelo.value = anterior;
  } else {
    limparVersoes();   // trocou de modelo: a versão anterior não vale mais
  }
}

function limparVersoes() {
  selVersao.replaceChildren(new Option("Selecione um modelo", ""));
  selVersao.disabled = true;
  mostrarTodasVersoes = false;   // outro modelo, outra lista de versões
  selGeracao.replaceChildren(new Option("Selecione um modelo", ""));
  selGeracao.disabled = true;
}

// Geração só existe pra parte dos modelos (Gol, Parati, Saveiro...), então o
// select fica escondido quando o modelo escolhido não tem nenhuma — mostrar
// um seletor com uma opção só ("sem geração") não ajudaria em nada.
function popularGeracoes(porGeracao) {
  const anterior = selGeracao.value;
  const comGeracao = (porGeracao || []).filter(r => r.geracao);
  const grupo = selGeracao.closest(".calc-grupo");
  if (comGeracao.length === 0) {
    if (grupo) grupo.classList.add("hidden");
    selGeracao.replaceChildren(new Option("Todas", ""));
    selGeracao.disabled = true;
    return;
  }
  if (grupo) grupo.classList.remove("hidden");
  selGeracao.replaceChildren(new Option("Todas as gerações", ""));
  for (const r of porGeracao) {
    const valor  = r.geracao ? r.geracao : VERSAO_SEM;
    const rotulo = r.geracao ? `Geração ${r.geracao}` : "Sem geração informada";
    selGeracao.add(new Option(`${rotulo} (${FMT_INT.format(r.qtd)})`, valor));
  }
  selGeracao.disabled = false;
  if ([...selGeracao.options].some(o => o.value === anterior)) selGeracao.value = anterior;
}

// As versões vêm de `por_versao` (sempre o par inteiro, mesmo com recorte
// ativo), então a lista não muda ao escolher uma versão — só a seleção.
function popularVersoes(porVersao) {
  const anterior = selVersao.value;
  selVersao.replaceChildren(new Option("Todas as versões", ""));
  for (const r of porVersao) {
    const valor  = r.versao ? r.versao : VERSAO_SEM;
    const rotulo = r.versao ? r.versao : "Sem versão informada";
    selVersao.add(new Option(`${rotulo} (${FMT_INT.format(r.qtd)})`, valor));
  }
  selVersao.disabled = porVersao.length === 0;
  if ([...selVersao.options].some(o => o.value === anterior)) selVersao.value = anterior;
}

// ── Estatísticas do recorte escolhido ────────────────────────────────────
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
  fecharDetalheGeral();
  try {
    const p = new URLSearchParams({ marca, modelo });
    if (selVersao.value) p.set("versao", selVersao.value);
    if (selGeracao.value) p.set("geracao", selGeracao.value);
    const res = await fetch(`/admin/api/media-modelo?${p.toString()}`);
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

// Recorte ativo (o que os detalhes e o link pra lista completa carregam).
// `versao`: "" = todas, VERSAO_SEM = sem versão informada, texto = exata.
function recorteAtual() {
  return {
    marca: selMarca.value,
    modelo: selModelo.value,
    versao: selVersao.value,
    geracao: selGeracao.value,
  };
}

// Query string de um recorte: o base (marca/modelo/versão) mais o que a
// linha clicada acrescenta (ano, fonte ou uma versão própria).
function qsRecorte(extra = {}) {
  const base = recorteAtual();
  const p = new URLSearchParams({ marca: base.marca, modelo: base.modelo });
  const versao = extra.versao !== undefined ? extra.versao : base.versao;
  if (versao) p.set("versao", versao);
  const geracao = extra.geracao !== undefined ? extra.geracao : base.geracao;
  if (geracao) p.set("geracao", geracao);
  if (extra.ano)   p.set("ano",   extra.ano);
  if (extra.fonte) p.set("fonte", extra.fonte);
  return p;
}

/**
 * Diferente dos outros números da página, este não resume a amostra:
 * projeta o preço de um exemplar em estado de coleção a partir da mediana
 * do mercado aberto (ver src/pipeline/valor_colecao.py). Por isso a banda
 * de confiança fica na nota, visível, em vez de escondida no tooltip — o
 * erro típico é de 20% e quem lê precisa ver isso junto do número.
 */
function renderValorColecao(vc) {
  const valor = document.getElementById("calc-colecao");
  const nota = document.getElementById("calc-colecao-nota");

  if (!vc) {
    valor.textContent = "—";
    nota.textContent = "sem base de mercado aberto neste recorte";
    valor.removeAttribute("title");
    return;
  }

  valor.textContent = fmtBRL(vc.estimado);
  const c = vc.calibracao;
  valor.title =
    `Projetado a partir da mediana de ${fmtBRL(vc.mediana_mercado)} em ` +
    `${FMT_INT.format(vc.n_mercado)} anúncios de marketplace ` +
    `(${vc.premio.toFixed(2)}x). Curva calibrada em ${c.n_modelos} modelos ` +
    `contra lojas de carro antigo, R² ${c.r2.toFixed(2)}, ` +
    `erro típico ${Math.round(c.erro_tipico * 100)}% — ${c.data}.`;

  // Projetar abaixo do mercado é legítimo em carro caro (ninguém anuncia
  // 911 detonado, então a mediana do marketplace já é preço de coleção),
  // mas sem uma palavra o número parece erro.
  nota.textContent = `${fmtBRL(vc.piso)} a ${fmtBRL(vc.teto)} · ` + (
    vc.abaixo_do_mercado
      ? `${vc.premio.toFixed(2)}x — mercado já em preço de coleção`
      : `${vc.premio.toFixed(2)}x o mercado aberto`);
}

function render(d) {
  popularVersoes(d.por_versao);
  popularGeracoes(d.por_geracao);

  const rotuloVersao = selVersao.value
    ? (selVersao.value === VERSAO_SEM ? "sem versão informada" : d.versao)
    : "";
  const rotuloGeracao = selGeracao.value
    ? (selGeracao.value === VERSAO_SEM ? "sem geração informada" : `geração ${d.geracao}`)
    : "";
  const recorte = [rotuloVersao, rotuloGeracao].filter(Boolean).join(" · ");
  document.getElementById("calc-modelo-nome").textContent =
    `${d.marca} ${d.modelo}${recorte ? " · " + recorte : ""}`;

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
  renderValorColecao(d.valor_colecao);

  renderVersoes(d.por_versao);
  renderAnos(d.por_ano);
  renderFontes(d.por_fonte);

  // Atalho pra ver o recorte inteiro na lista paginada
  document.getElementById("calc-ver-anuncios").href = `/admin/anuncios?${qsRecorte().toString()}`;
}

// Contagem clicável: abre os anúncios daquele recorte logo abaixo da linha.
function celulaContagem(qtd, recorte) {
  const td = document.createElement("td");
  td.className = "num";
  const btn = texto("button", FMT_INT.format(qtd), "qv-count");
  btn.type = "button";
  btn.title = "Ver os anúncios deste recorte";
  btn.dataset.qtd = qtd;
  btn.dataset.recorte = JSON.stringify(recorte);
  btn.addEventListener("click", () => verAnunciosDaLinha(btn));
  td.append(btn);
  return td;
}

function renderVersoes(porVersao) {
  const tb = document.querySelector("#calc-tab-versao tbody");
  tb.replaceChildren();
  if (!porVersao.length) {
    const tr = document.createElement("tr");
    const td = texto("td", "Nenhum anúncio.");
    td.colSpan = 3;
    tr.append(td);
    tb.append(tr);
    return;
  }

  // A versão recortada tem de aparecer sempre, mesmo que seja uma das raras
  // que ficariam abaixo do corte.
  const posicaoAtiva = porVersao.findIndex(r => (r.versao || VERSAO_SEM) === selVersao.value);
  const todas = mostrarTodasVersoes || posicaoAtiva >= VERSOES_VISIVEIS;
  const visiveis = todas ? porVersao : porVersao.slice(0, VERSOES_VISIVEIS);

  for (const r of visiveis) {
    const valor = r.versao ? r.versao : VERSAO_SEM;
    const tr = document.createElement("tr");
    if (selVersao.value === valor) tr.className = "calc-linha-ativa";

    // Clicar no nome recorta a média por essa versão (e destrava com um 2º clique).
    const tdNome = document.createElement("td");
    const btn = texto("button", r.versao || "Sem versão informada", "calc-versao-link");
    btn.type = "button";
    btn.title = selVersao.value === valor
      ? "Clique pra voltar a todas as versões"
      : "Clique pra recortar a média por esta versão";
    btn.addEventListener("click", () => {
      selVersao.value = selVersao.value === valor ? "" : valor;
      calcular();
    });
    tdNome.append(btn);

    tr.append(tdNome);
    tr.append(celulaContagem(r.qtd, { versao: valor }));
    tr.append(texto("td", r.preco_medio == null ? "—" : fmtBRL(r.preco_medio), "num"));
    tb.append(tr);
  }

  if (visiveis.length < porVersao.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    const btn = texto(
      "button",
      `Mostrar as outras ${FMT_INT.format(porVersao.length - visiveis.length)} versões ` +
      `(as de menos anúncios)`,
      "calc-versao-link",
    );
    btn.type = "button";
    btn.addEventListener("click", () => {
      mostrarTodasVersoes = true;
      renderVersoes(porVersao);
    });
    td.append(btn);
    tr.append(td);
    tb.append(tr);
  }
}

function renderAnos(porAno) {
  const tb = document.querySelector("#calc-tab-ano tbody");
  tb.replaceChildren();
  if (!porAno.length) {
    const tr = document.createElement("tr");
    const td = texto("td", "Nenhum ano identificado.");
    td.colSpan = 3;
    tr.append(td);
    tb.append(tr);
    return;
  }
  for (const r of porAno) {
    const tr = document.createElement("tr");
    tr.append(texto("td", r.ano));
    tr.append(celulaContagem(r.qtd, { ano: r.ano }));
    tr.append(texto("td", r.preco_medio == null ? "—" : fmtBRL(r.preco_medio), "num"));
    tb.append(tr);
  }
}

function renderFontes(porFonte) {
  const tb = document.querySelector("#calc-tab-fonte tbody");
  tb.replaceChildren();
  for (const r of porFonte) {
    const tr = document.createElement("tr");
    tr.append(texto("td", r.fonte || "—"));
    tr.append(celulaContagem(r.qtd, { fonte: r.fonte }));
    tr.append(texto("td", r.preco_medio == null ? "—" : fmtBRL(r.preco_medio), "num"));
    tb.append(tr);
  }
}

// ── Detalhe: os anúncios por trás de um número ───────────────────────────
function verAnunciosDaLinha(btn) {
  const tr = btn.closest("tr");
  const seguinte = tr.nextElementSibling;
  if (seguinte && seguinte.classList.contains("qv-detail")) {
    seguinte.remove();
    return;
  }
  const linha = document.createElement("tr");
  linha.className = "qv-detail";
  const cell = document.createElement("td");
  cell.className = "qv-detail-cell";
  cell.colSpan = tr.children.length;
  linha.append(cell);
  tr.after(linha);

  const extra = JSON.parse(btn.dataset.recorte);
  carregarDetalhe(cell, qsRecorte(extra), parseInt(btn.dataset.qtd, 10));
}

// Mesmo detalhe, mas do recorte inteiro (botão do rodapé) — fora de tabela.
function verAnunciosDoRecorte(btn) {
  const alvo = document.getElementById("calc-detalhe-geral");
  if (alvo.firstChild) {
    fecharDetalheGeral();
    return;
  }
  const cell = document.createElement("div");
  cell.className = "qv-detail-cell";
  alvo.append(cell);
  btn.textContent = "Esconder os anúncios";
  const total = parseInt(
    (document.getElementById("calc-qtd").textContent.split("/")[1] || "").replace(/\D/g, ""),
    10,
  );
  carregarDetalhe(cell, qsRecorte(), total);
}

function fecharDetalheGeral() {
  document.getElementById("calc-detalhe-geral").replaceChildren();
  document.getElementById("calc-ver-aqui").textContent = "Ver os anúncios aqui";
}

async function carregarDetalhe(cell, params, total) {
  cell.replaceChildren(texto("p", "Carregando…", "qv-detail-nota"));
  try {
    const res  = await fetch(`/admin/api/anuncios-do-par?${params.toString()}`);
    const data = await res.json();
    if (data.erro) throw new Error(data.erro);
    const rows = data.rows || [];
    if (!rows.length) {
      cell.replaceChildren(texto("p", "Nenhum anúncio.", "qv-detail-nota"));
      return;
    }
    cell.replaceChildren();

    // O servidor corta em 300: em grupo gordo o detalhe é uma amostra — diz
    // isso, em vez de fingir que é tudo, e oferece a lista paginada.
    const nota = document.createElement("p");
    nota.className = "qv-detail-nota";
    if (rows.length >= DETALHE_LIMITE && total > rows.length) {
      nota.append(document.createTextNode(
        `Mostrando ${FMT_INT.format(rows.length)} dos ${FMT_INT.format(total)} anúncios deste recorte ` +
        `(os de ano mais antigo primeiro). `));
    } else {
      nota.append(document.createTextNode(`${FMT_INT.format(rows.length)} anúncio(s). `));
    }
    const link = texto("a", "Ver na lista completa", "btn btn-outline btn-sm");
    link.href = `/admin/anuncios?${params.toString()}`;
    nota.append(link);
    cell.append(nota);

    const wrap = document.createElement("div");
    wrap.className = "qv-detail-wrap";
    const tabela = document.createElement("table");
    tabela.className = "qv-detail-table";

    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    for (const [rotulo, classe] of [
      ["Fonte", ""], ["Título", ""], ["Ano", "an-th--num"],
      ["Preço", "an-th--num"], ["Versão", ""], ["Geração", ""],
      ["Motor", ""], ["Obs", ""],
    ]) trh.append(texto("th", rotulo, classe));
    thead.append(trh);
    tabela.append(thead);

    const tbody = document.createElement("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.append(texto("td", r.fonte || "—"));

      const tdTitulo = document.createElement("td");
      if (r.url) {
        const a = texto("a", r.titulo || "(sem título)");
        a.href = r.url;
        a.target = "_blank";
        a.rel = "noopener";
        tdTitulo.append(a);
      } else {
        tdTitulo.textContent = r.titulo || "(sem título)";
      }
      tr.append(tdTitulo);

      tr.append(texto("td", r.ano || "—", "an-td--num"));
      tr.append(texto("td", fmtBRL(r.preco), "an-td--num"));
      tr.append(texto("td", r.versao || "—"));
      tr.append(texto("td", r.geracao || "—"));
      tr.append(texto("td", r.motor || "—"));
      tr.append(texto("td", r.obs || "—"));
      tbody.append(tr);
    }
    tabela.append(tbody);
    wrap.append(tabela);
    cell.append(wrap);
  } catch (err) {
    cell.replaceChildren(texto("p", `Erro: ${err.message}`, "calc-erro"));
  }
}

function mostrarMsg(txt, classe) {
  msg.textContent = txt;
  msg.className = classe || "calc-hint";
  msg.style.display = txt ? "" : "none";
}

// ── Wiring ───────────────────────────────────────────────────────────────
selMin.addEventListener("change", () => {
  popularMarcas();
  calcular();  // o par pode ter deixado de passar no filtro → esconde/recalcula
});
selMarca.addEventListener("change", () => {
  limparVersoes();   // outra marca, outras versões
  popularModelos();
  calcular();
});
selModelo.addEventListener("change", () => {
  limparVersoes();   // a versão do modelo anterior não vale pro novo
  calcular();
});
selVersao.addEventListener("change", calcular);
selGeracao.addEventListener("change", calcular);

carregarPares();
