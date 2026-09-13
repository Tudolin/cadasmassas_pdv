/*
 * Tela de caixa - JavaScript puro, sem dependencia e sem build.
 *
 * Duas regras governam este arquivo:
 *
 * 1. O SERVIDOR MANDA. A tela nunca soma, nunca calcula subtotal, nunca
 *    decide preco: cada resposta traz o carrinho inteiro e a tela apenas
 *    redesenha. Assim o total exibido e sempre o mesmo que sera gravado.
 *
 * 2. O FOCO VOLTA PARA O CAMPO DE CODIGO. O leitor USB e um teclado: se o
 *    foco escapar, o codigo vai ser "digitado" em qualquer outro lugar e a
 *    venda se perde. Toda acao termina em `focarCodigo()`.
 */

"use strict";

const $ = (id) => document.getElementById(id);

const el = {
  codigo: $("codigo"),
  formLeitura: $("form-leitura"),
  aviso: $("aviso"),
  corpo: $("corpo-carrinho"),
  total: $("total"),
  contagem: $("contagem"),
  mensagem: $("mensagem"),
  recebido: $("recebido"),
  troco: $("troco"),
  areaDinheiro: $("area-dinheiro"),
  cpf: $("cpf"),
  emitirNf: $("emitir-nf"),
  btnFinalizar: $("btn-finalizar"),
  indCatalogo: $("ind-catalogo"),
  indFila: $("ind-fila"),
  indImpressora: $("ind-impressora"),
  relogio: $("relogio"),
  saidaDiag: $("saida-diagnostico"),
};

/** Ultimo total conhecido, em centavos. Usado so para calcular troco na tela. */
let totalCentavos = 0;
/** Overlay aberto no momento ("busca" | "peso" | "cupom" | null). */
let overlayAberto = null;

// ---------------------------------------------------------------- utilidades

function formatarMoeda(centavos) {
  const sinal = centavos < 0 ? "-" : "";
  const abs = Math.abs(centavos);
  const inteiro = Math.floor(abs / 100).toLocaleString("pt-BR");
  const resto = String(abs % 100).padStart(2, "0");
  return `${sinal}R$ ${inteiro},${resto}`;
}

/** Le "10,50" / "R$ 1.234,56" e devolve centavos. NaN se nao der. */
function paraCentavos(texto) {
  const limpo = String(texto || "").replace(/[R$\s]/g, "");
  if (!limpo) return NaN;
  const normalizado = limpo.includes(",")
    ? limpo.replace(/\./g, "").replace(",", ".")
    : limpo;
  const valor = Number(normalizado);
  return Number.isFinite(valor) ? Math.round(valor * 100) : NaN;
}

function focarCodigo() {
  if (overlayAberto) return;
  el.codigo.focus();
  el.codigo.select();
}

function mostrarMensagem(texto, tipo) {
  el.mensagem.textContent = texto || "";
  el.mensagem.className = "mensagem" + (texto && tipo ? ` ${tipo}` : "");
}

function mostrarAviso(texto) {
  el.aviso.textContent = texto || "";
  el.aviso.classList.toggle("oculto", !texto);
}

async function pedir(url, corpo) {
  const opcoes = corpo
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      }
    : { method: "GET" };

  try {
    const resposta = await fetch(url, opcoes);
    return await resposta.json();
  } catch (erro) {
    // O servidor e local: se o fetch falhou, o processo do PDV caiu.
    return {
      ok: false,
      mensagem: `Sem resposta do PDV (${erro.message}). O servico esta rodando?`,
    };
  }
}

// ------------------------------------------------------------------ carrinho

function desenharCarrinho(carrinho, idDestacado) {
  totalCentavos = carrinho.total_centavos;
  el.total.textContent = carrinho.total_texto;
  el.contagem.textContent = `${carrinho.quantidade_itens} item(ns)`;
  el.btnFinalizar.disabled = carrinho.vazio;

  if (carrinho.vazio) {
    el.corpo.innerHTML =
      '<tr class="vazio"><td colspan="6">Carrinho vazio - passe o primeiro produto.</td></tr>';
  } else {
    el.corpo.replaceChildren(
      ...carrinho.itens.map((item, indice) => linhaItem(item, indice, idDestacado))
    );
    // Item novo entra por baixo: rola para ele ficar visivel.
    el.corpo.lastElementChild?.scrollIntoView({ block: "nearest" });
  }

  atualizarTroco();
}

function linhaItem(item, indice, idDestacado) {
  const tr = document.createElement("tr");
  if (item.id === idDestacado) tr.className = "novo";

  const celulas = [
    ["", String(indice + 1).padStart(3, "0")],
    ["produto", null],
    ["num", item.quantidade_texto],
    ["num", item.preco_unitario_texto + (item.tipo === "peso" ? "/kg" : "")],
    ["num", item.subtotal_texto],
  ];

  for (const [classe, texto] of celulas) {
    const td = document.createElement("td");
    if (classe) td.className = classe;
    if (texto === null) {
      // Nome + codigo, com textContent para nao interpretar HTML vindo do
      // catalogo (nome de produto e dado externo).
      td.append(document.createTextNode(item.nome));
      const pequeno = document.createElement("div");
      pequeno.className = "codigo";
      pequeno.textContent = item.codigo;
      td.append(pequeno);
    } else {
      td.textContent = texto;
    }
    tr.append(td);
  }

  const tdAcao = document.createElement("td");
  const botao = document.createElement("button");
  botao.type = "button";
  botao.className = "remover";
  botao.textContent = "X";
  botao.title = `Remover ${item.nome}`;
  botao.addEventListener("click", () => removerItem(item.id));
  tdAcao.append(botao);
  tr.append(tdAcao);

  return tr;
}

function aplicarResposta(dados) {
  if (dados.carrinho) {
    desenharCarrinho(dados.carrinho, dados.item ? dados.item.id : null);
  }
  mostrarMensagem(dados.mensagem, dados.ok ? "ok" : "erro");
  mostrarAviso(dados.aviso);
  if (!dados.ok) beep();
}

/** Bipe curto de erro: no barulho da loja o operador nao olha a tela. */
function beep() {
  try {
    const contexto = new (window.AudioContext || window.webkitAudioContext)();
    const oscilador = contexto.createOscillator();
    const ganho = contexto.createGain();
    oscilador.frequency.value = 240;
    ganho.gain.value = 0.08;
    oscilador.connect(ganho).connect(contexto.destination);
    oscilador.start();
    oscilador.stop(contexto.currentTime + 0.18);
    oscilador.onended = () => contexto.close();
  } catch {
    /* navegador sem audio: silencio nao e um problema */
  }
}

// -------------------------------------------------------------------- acoes

el.formLeitura.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const codigo = el.codigo.value.trim();
  if (!codigo) return;

  el.codigo.value = "";
  const dados = await pedir("/api/ler", { codigo });

  if (dados.pedir_peso) {
    // Etiqueta generica "2000000": nao da para adivinhar o produto.
    mostrarMensagem(dados.mensagem, "erro");
    abrirBusca();
    return;
  }

  aplicarResposta(dados);
  focarCodigo();
});

async function removerItem(id) {
  aplicarResposta(await pedir("/api/carrinho/remover", { id }));
  focarCodigo();
}

$("btn-limpar").addEventListener("click", limparCarrinho);

async function limparCarrinho() {
  if (totalCentavos > 0 && !confirm("Zerar o carrinho inteiro?")) {
    focarCodigo();
    return;
  }
  aplicarResposta(await pedir("/api/carrinho/limpar", {}));
  focarCodigo();
}

// ---------------------------------------------------------------- pagamento

function formaSelecionada() {
  return document.querySelector('input[name="forma"]:checked').value;
}

function selecionarForma(valor) {
  const alvo = document.querySelector(`input[name="forma"][value="${valor}"]`);
  if (!alvo) return;
  alvo.checked = true;
  aoTrocarForma();
  if (valor === "dinheiro") {
    el.recebido.focus();
    el.recebido.select();
  } else {
    focarCodigo();
  }
}

function aoTrocarForma() {
  const dinheiro = formaSelecionada() === "dinheiro";
  el.areaDinheiro.classList.toggle("oculto", !dinheiro);
  if (!dinheiro) el.recebido.value = "";
  atualizarTroco();
}

for (const radio of document.querySelectorAll('input[name="forma"]')) {
  radio.addEventListener("change", aoTrocarForma);
}

function atualizarTroco() {
  if (formaSelecionada() !== "dinheiro") {
    el.troco.textContent = formatarMoeda(0);
    return;
  }
  const recebido = paraCentavos(el.recebido.value);
  if (Number.isNaN(recebido)) {
    el.troco.textContent = formatarMoeda(0);
    return;
  }
  const troco = recebido - totalCentavos;
  el.troco.textContent = formatarMoeda(troco);
  // Vermelho enquanto nao cobre o total: erro visivel antes de finalizar.
  el.troco.style.color = troco < 0 ? "var(--erro)" : "var(--ok)";
}

el.recebido.addEventListener("input", atualizarTroco);

// Enter no campo de recebido finaliza -- o fluxo natural do caixa.
el.recebido.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter") {
    evento.preventDefault();
    finalizar();
  }
});

// ----------------------------------------------------------------- checkout

el.btnFinalizar.addEventListener("click", finalizar);

let finalizando = false;

async function finalizar() {
  // Trava contra duplo clique / duplo Enter: sem isso, dois posts viram
  // duas vendas gravadas.
  if (finalizando || el.btnFinalizar.disabled) return;
  finalizando = true;
  el.btnFinalizar.disabled = true;

  try {
    const corpo = {
      forma_pagamento: formaSelecionada(),
      cpf: el.cpf.value.trim() || null,
      emitir_nf: el.emitirNf.checked,
    };
    if (corpo.forma_pagamento === "dinheiro") corpo.recebido = el.recebido.value;

    const dados = await pedir("/api/checkout", corpo);
    aplicarResposta(dados);

    if (dados.ok && dados.venda) {
      mostrarCupom(dados);
      el.recebido.value = "";
      el.cpf.value = "";
      el.emitirNf.checked = false;
    }
  } finally {
    finalizando = false;
    el.btnFinalizar.disabled = totalCentavos === 0;
    atualizarEstado();
  }
}

function mostrarCupom(dados) {
  const venda = dados.venda;
  $("cupom-titulo").textContent = `Venda #${String(venda.cupom).padStart(6, "0")} - ${venda.total_texto}`;
  $("cupom-troco").textContent =
    venda.troco_texto !== null && venda.troco_texto !== undefined
      ? `TROCO: ${venda.troco_texto}`
      : "";
  $("cupom-texto").textContent = dados.cupom_texto || "";
  abrirOverlay("cupom");
}

$("btn-cupom-fechar").addEventListener("click", () => fecharOverlay());

// ------------------------------------------------------------- busca / peso

const elBusca = {
  overlay: $("overlay-busca"),
  termo: $("busca-termo"),
  lista: $("busca-resultados"),
};

let resultadosBusca = [];
let indiceBusca = 0;

function abrirBusca() {
  elBusca.termo.value = "";
  elBusca.lista.replaceChildren();
  resultadosBusca = [];
  abrirOverlay("busca");
  elBusca.termo.focus();
}

let temporizadorBusca = null;

elBusca.termo.addEventListener("input", () => {
  // Debounce curto: o servidor responde em memoria, mas nao ha motivo para
  // uma requisicao por tecla.
  clearTimeout(temporizadorBusca);
  temporizadorBusca = setTimeout(executarBusca, 120);
});

async function executarBusca() {
  const termo = elBusca.termo.value.trim();
  if (termo.length < 2) {
    elBusca.lista.replaceChildren();
    resultadosBusca = [];
    return;
  }

  const dados = await pedir(`/api/buscar?q=${encodeURIComponent(termo)}`);
  resultadosBusca = dados.resultados || [];
  indiceBusca = 0;
  desenharResultados();
}

function desenharResultados() {
  if (!resultadosBusca.length) {
    const vazio = document.createElement("li");
    vazio.textContent = "Nenhum produto encontrado.";
    elBusca.lista.replaceChildren(vazio);
    return;
  }

  elBusca.lista.replaceChildren(
    ...resultadosBusca.map((produto, indice) => {
      const li = document.createElement("li");
      if (indice === indiceBusca) li.className = "ativo";

      const nome = document.createElement("span");
      nome.textContent = produto.nome;

      const preco = document.createElement("span");
      preco.className = "preco";
      preco.textContent =
        formatarMoeda(produto.preco_centavos) +
        (produto.unidade === "kg" ? "/kg" : " /un");

      li.append(nome, preco);
      li.addEventListener("click", () => escolherResultado(indice));
      return li;
    })
  );
}

function escolherResultado(indice) {
  const produto = resultadosBusca[indice];
  if (!produto) return;

  if (produto.tipo === "peso") {
    abrirPeso(produto);
  } else {
    fecharOverlay();
    pedir("/api/carrinho/unidade", { codigo: produto.codigo, quantidade: 1 }).then(
      (dados) => {
        aplicarResposta(dados);
        focarCodigo();
      }
    );
  }
}

const elPeso = {
  overlay: $("overlay-peso"),
  produto: $("peso-produto"),
  valor: $("peso-valor"),
};

let produtoDoPeso = null;

function abrirPeso(produto) {
  produtoDoPeso = produto || null;
  if (!produtoDoPeso) {
    // F4 sem produto escolhido: manda escolher primeiro.
    abrirBusca();
    return;
  }
  elPeso.produto.textContent = `${produtoDoPeso.nome} - ${formatarMoeda(
    produtoDoPeso.preco_centavos
  )}/kg`;
  elPeso.valor.value = "";
  abrirOverlay("peso");
  elPeso.valor.focus();
}

$("btn-peso-confirmar").addEventListener("click", confirmarPeso);
$("btn-peso-cancelar").addEventListener("click", () => fecharOverlay());

elPeso.valor.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter") {
    evento.preventDefault();
    confirmarPeso();
  }
});

async function confirmarPeso() {
  if (!produtoDoPeso) return;
  const gramas = elPeso.valor.value.trim();
  if (!gramas) return;

  fecharOverlay();
  const dados = await pedir("/api/carrinho/peso", {
    plu: produtoDoPeso.plu,
    peso_g: gramas,
  });
  aplicarResposta(dados);
  produtoDoPeso = null;
  focarCodigo();
}

// ------------------------------------------------------------- overlays

function abrirOverlay(qual) {
  overlayAberto = qual;
  $(`overlay-${qual}`).classList.remove("oculto");
}

function fecharOverlay() {
  if (!overlayAberto) return;
  $(`overlay-${overlayAberto}`).classList.add("oculto");
  overlayAberto = null;
  focarCodigo();
}

// -------------------------------------------------------------- atalhos

document.addEventListener("keydown", (evento) => {
  // Dentro de overlay, as setas e o Enter pertencem ao overlay.
  if (overlayAberto === "busca") {
    if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
      evento.preventDefault();
      const passo = evento.key === "ArrowDown" ? 1 : -1;
      indiceBusca = Math.max(
        0,
        Math.min(resultadosBusca.length - 1, indiceBusca + passo)
      );
      desenharResultados();
      return;
    }
    if (evento.key === "Enter") {
      evento.preventDefault();
      escolherResultado(indiceBusca);
      return;
    }
  }

  if (overlayAberto === "cupom" && evento.key === "Enter") {
    evento.preventDefault();
    fecharOverlay();
    return;
  }

  if (evento.key === "Escape") {
    evento.preventDefault();
    if (overlayAberto) fecharOverlay();
    else focarCodigo();
    return;
  }

  if (overlayAberto) return;

  switch (evento.key) {
    case "F2":
      evento.preventDefault();
      abrirBusca();
      break;
    case "F4":
      evento.preventDefault();
      abrirPeso(produtoDoPeso);
      break;
    case "F5":
      evento.preventDefault();
      selecionarForma("dinheiro");
      break;
    case "F6":
      evento.preventDefault();
      selecionarForma("debito");
      break;
    case "F7":
      evento.preventDefault();
      selecionarForma("credito");
      break;
    case "F8":
      evento.preventDefault();
      selecionarForma("pix");
      break;
    case "F9":
      evento.preventDefault();
      finalizar();
      break;
    case "Delete":
      if (evento.ctrlKey) {
        evento.preventDefault();
        limparCarrinho();
      }
      break;
    default:
      break;
  }
});

/*
 * Rede de seguranca do foco: se o operador clicar em qualquer area neutra,
 * o foco volta para o campo de codigo. Sem isso, o proximo bipe do leitor
 * seria digitado no vazio.
 */
document.addEventListener("click", (evento) => {
  const alvo = evento.target;
  if (
    overlayAberto ||
    alvo.closest("button") ||
    alvo.closest("input") ||
    alvo.closest("summary") ||
    alvo.closest("label")
  ) {
    return;
  }
  focarCodigo();
});

// A janela recuperando foco (o operador voltou de outro programa) tambem
// devolve o cursor para o campo de leitura.
window.addEventListener("focus", focarCodigo);

// ------------------------------------------------------------- diagnostico

/**
 * Usada tanto pelo botao do topo (acesso rapido, ao lado do indicador)
 * quanto pelo de dentro de "Operacao" -- os dois fazem a mesma coisa.
 */
async function sincronizarCatalogo() {
  const desabilitados = [$("btn-sinc-catalogo"), $("btn-sinc-catalogo-topo")].filter(Boolean);
  for (const b of desabilitados) b.disabled = true;

  mostrarMensagem("Atualizando catalogo...", null);
  try {
    const dados = await pedir("/api/catalogo/sincronizar", {});
    mostrarMensagem(dados.mensagem, dados.ok ? "ok" : "erro");
    await atualizarEstado();
  } finally {
    for (const b of desabilitados) b.disabled = false;
    focarCodigo();
  }
}

$("btn-sinc-catalogo").addEventListener("click", () => sincronizarCatalogo());
$("btn-sinc-catalogo-topo").addEventListener("click", () => sincronizarCatalogo());

$("btn-sinc-vendas").addEventListener("click", async () => {
  const dados = await pedir("/api/vendas/sincronizar", {});
  mostrarMensagem(dados.mensagem, "ok");
  atualizarEstado();
});

$("btn-fechamento").addEventListener("click", async () => {
  const dados = await pedir("/api/fechamento");
  el.saidaDiag.textContent = JSON.stringify(dados.fechamento, null, 2);
});

$("btn-reimprimir").addEventListener("click", async () => {
  const cupom = $("cupom-reimprimir").value.trim();
  if (!cupom) return;
  const dados = await pedir("/api/reimprimir", { cupom });
  mostrarMensagem(dados.mensagem, dados.ok ? "ok" : "erro");
  focarCodigo();
});

async function atualizarEstado() {
  const dados = await pedir("/api/estado");
  if (!dados.catalogo) return;

  const catalogo = dados.catalogo;
  const total = catalogo.produtos_peso + catalogo.produtos_unidade;
  el.indCatalogo.textContent = `catalogo ${total} itens (${catalogo.origem})`;
  el.indCatalogo.className =
    "indicador" + (total === 0 ? " ruim" : catalogo.ultimo_erro ? " alerta" : "");
  el.indCatalogo.title = catalogo.ultimo_erro
    ? `Ultimo erro: ${catalogo.ultimo_erro}`
    : `Versao ${catalogo.versao} - atualizado ${catalogo.atualizado_em || "nunca"}`;

  const fila = dados.fila_vendas;
  el.indFila.textContent =
    fila.pendentes > 0 ? `fila ${fila.pendentes} pendente(s)` : "fila em dia";
  el.indFila.className = "indicador" + (fila.pendentes > 0 ? " alerta" : "");
  el.indFila.title = fila.upstash_configurado
    ? fila.ultimo_erro || "Sincronizando com o Upstash."
    : "Upstash nao configurado: vendas ficam apenas no SQLite local.";

  const impressao = dados.impressao;
  el.indImpressora.textContent = impressao.habilitado
    ? `impressora ${impressao.impressora || "nao definida"}`
    : "impressao desligada";
  el.indImpressora.className = "indicador" + (impressao.ultimo_erro ? " ruim" : "");
  el.indImpressora.title = impressao.ultimo_erro || "";
}

function atualizarRelogio() {
  el.relogio.textContent = new Date().toLocaleTimeString("pt-BR");
}

// -------------------------------------------------------------- inicio

(async function iniciar() {
  aoTrocarForma();
  const dados = await pedir("/api/carrinho");
  if (dados.carrinho) desenharCarrinho(dados.carrinho, null);
  mostrarMensagem("Caixa pronto.", "ok");

  atualizarRelogio();
  setInterval(atualizarRelogio, 1000);
  atualizarEstado();
  // 20s: so mexe nos indicadores da barra, nao interfere na venda.
  setInterval(atualizarEstado, 20000);

  focarCodigo();
})();
