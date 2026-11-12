// Controlador do editor de trecho da NOVA EDIÇÃO (templates/nova/editor.html). Usa window.SinibaldiEditor.
// Esquerda: abas "Texto de 1916" (só leitura, destaca o bloco de origem do bloco ativo) e "Scan".
// Direita: o mesmo editor da revisão da 1916 (abas Visual/XML), com indicador de procedência por bloco.
(function () {
  "use strict";
  const SE = window.SinibaldiEditor;
  const raiz = document.querySelector("[data-nova]");
  if (!SE || !raiz) return;
  const $ = (s, r) => (r || document).querySelector(s);
  const dados = JSON.parse($("#dados-nova").textContent);
  const esquema = JSON.parse($("#esquema-editor").textContent);
  const ROTULO = { copia: "cópia", adaptado: "adaptado", novo: "novo", suprimido: "suprimido" };

  let ids = dados.ids.slice();
  let info = dados.info;
  let ativo = null;

  SE.montarDivisor({ divisor: $("#divisor"), primeira: $("#col-scan"), chave: "sinibaldi.divisor.nova" });
  SE.montarVisualizador($("#visualizador"), {
    botoes: $("[data-barra-scan]"), indicador: $("[data-zoom-indicador]"), chave: "sinibaldi.scan",
  });

  // ------------------------------------------------------------ abas da esquerda
  const painelTexto = $("#painel-esq-texto");
  const painelScan = $("#painel-esq-scan");
  function aba(nome) {
    const scan = nome === "scan";
    painelTexto.classList.toggle("hidden", scan);
    painelScan.classList.toggle("hidden", !scan);
    painelScan.classList.toggle("flex", scan);
    document.querySelectorAll("[data-esq]").forEach((b) => {
      b.className = b.getAttribute("data-esq") === nome ? "aba-ativa" : "aba";
    });
    try { localStorage.setItem("sinibaldi.nova.esq", nome); } catch (e) { /* ok */ }
  }
  document.querySelectorAll("[data-esq]").forEach((b) => b.addEventListener("click", () => aba(b.getAttribute("data-esq"))));
  let inicial = "texto";
  try { inicial = localStorage.getItem("sinibaldi.nova.esq") || "texto"; } catch (e) { /* ok */ }
  aba(inicial === "scan" ? "scan" : "texto");

  // ------------------------------------------------------------------- scan
  const img = $("#visualizador img");
  const elIndicador = $("[data-scan-indicador]");
  const linkRevisar = $("[data-scan-revisar]");
  let scanAtual = null; // {vol, seq}
  function irScan(vol, seq) {
    if (vol == null || seq == null) {
      elIndicador.textContent = "sem página";
      return;
    }
    scanAtual = { vol, seq };
    const lista = dados.paginas[String(vol)] || [];
    const reg = lista.find((x) => x[0] === seq);
    elIndicador.textContent = `vol. ${vol} · pág. ${reg ? reg[1] : seq} · scan ${seq}`;
    const url = dados.urlScan.replace("9991", vol).replace("9992", seq);
    if (!img.src.endsWith(url)) {
      img.style.display = "";
      const aviso = $("[data-sem-scan]");
      aviso.classList.add("hidden");
      aviso.classList.remove("flex");
      img.src = url;
    }
    linkRevisar.href = dados.urlRevisar.replace("9991", vol).replace("9992", seq);
  }
  document.querySelectorAll("[data-scan]").forEach((b) => b.addEventListener("click", () => {
    if (!scanAtual) return;
    const lista = dados.paginas[String(scanAtual.vol)] || [];
    const i = lista.findIndex((x) => x[0] === scanAtual.seq);
    const j = b.getAttribute("data-scan") === "ant" ? i - 1 : i + 1;
    if (i >= 0 && j >= 0 && j < lista.length) irScan(scanAtual.vol, lista[j][0]);
  }));

  // ------------------------------------------------------------ painel de 1916
  const elSemOrigem = $("[data-sem-origem]");
  const elEsqInfo = $("[data-esq-info]");
  function destacarOrigem(i) {
    painelTexto.querySelectorAll(".destaque-origem").forEach((e) => e.classList.remove("destaque-origem"));
    elSemOrigem.classList.add("hidden");
    elEsqInfo.textContent = "";
    if (!i) return;
    if (!i.origem) {
      elSemOrigem.classList.remove("hidden");
      return;
    }
    const alvo = painelTexto.querySelector("#b" + i.origem);
    if (alvo) {
      alvo.classList.add("destaque-origem");
      alvo.scrollIntoView({ block: "nearest" });
    }
    elEsqInfo.textContent = `bloco de 1916 #${i.origem}`;
  }

  // ------------------------------------------------------------ info do bloco
  const elInfoTexto = $("[data-info-texto]");
  const elInfoLink = $("[data-info-link]");
  const elMsg = $("#estado-revisao");
  const btnRestaurar = $('[data-acao-bloco="restaurar_1916"]');
  const btnSuprimir = $('[data-acao-bloco="suprimir"]');

  function mensagem(texto, erro) {
    elMsg.textContent = texto;
    elMsg.className = "px-3 pb-1 text-[11px] " + (erro ? "text-red-800" : "text-ink/60");
  }

  function mostrarInfo(id) {
    ativo = id != null ? String(id) : null;
    const i = ativo != null ? info[ativo] : null;
    elInfoLink.classList.add("hidden");
    btnRestaurar.disabled = !(i && i.origem && i.procedencia !== "copia");
    btnSuprimir.disabled = !i;
    btnSuprimir.textContent = i && i.procedencia === "suprimido" ? "restaurar bloco" : "suprimir";
    btnSuprimir.setAttribute("data-acao-bloco", i && i.procedencia === "suprimido" ? "restaurar_supressao" : "suprimir");
    destacarOrigem(i);
    if (i && i.pagina != null) irScan(i.volume, i.pagina);
    if (ativo == null) {
      elInfoTexto.textContent = "Bloco novo (ainda não gravado).";
      return;
    }
    if (!i) {
      elInfoTexto.textContent = "Clique num bloco para ver a procedência e quem o alterou por último.";
      return;
    }
    const quem = i.autor ? `última alteração por ${i.autor} em ${i.em}` : "sem alterações desde a derivação";
    elInfoTexto.textContent = `Bloco #${ativo} · ${ROTULO[i.procedencia] || i.procedencia} · v${i.versao} · ${quem}`;
    elInfoLink.href = dados.urlHistoricoBloco.replace("/0/", `/${ativo}/`);
    elInfoLink.classList.remove("hidden");
  }

  // ------------------------------------------------------------------ editor
  let abas = null;
  const elSujo = $("[data-sujo]");
  function atualizarSujo() {
    elSujo.classList.toggle("hidden", !(abas && abas.sujo()));
  }
  const editor = SE.montar($("#editor"), {
    html: dados.html,
    esquema,
    urlConverter: dados.urlConverter,
    csrf: dados.csrf,
    prefixoId: dados.prefixoId,
    pagina: dados.pagina,
    decorarBloco(id) {
      const i = id != null ? info[String(id)] : null;
      const proc = i ? i.procedencia : "novo";
      return {
        class: `sn-proc sn-proc-${proc}`,
        "data-proc": i ? ROTULO[proc] : "novo (não gravado)",
        title: i ? `Procedência: ${ROTULO[proc]}` : "Bloco criado agora; ainda não gravado",
      };
    },
    aoMudar: () => atualizarSujo(),
    aoBlocoAtivo: mostrarInfo,
  });

  abas = SE.montarAbas({
    editor,
    textarea: $("#texto-xml"),
    urlConverter: dados.urlConverter,
    csrf: dados.csrf,
    erros: $("#erros"),
    abas: {
      visual: { botao: $('[data-aba="visual"]'), painel: $("#painel-visual") },
      xml: { botao: $('[data-aba="xml"]'), painel: $("#painel-xml") },
    },
    aoMudar: () => atualizarSujo(),
  });

  window.addEventListener("beforeunload", (e) => {
    if (abas.sujo()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  const sel = $("[data-subnos]");
  if (sel) sel.addEventListener("change", () => {
    if (sel.value) window.location.href = `${dados.base}?p=${sel.value}`;
  });

  function recarregarDe(d) {
    ids = d.ids;
    info = d.info;
    // mantém o cursor e a rolagem (carregar() leva o cursor ao início)
    const tip = editor.editor;
    const area = $(".sn-area");
    const visual = abas.ativa() === "visual";
    const pos = tip.state.selection.from;
    const rolagem = area ? area.scrollTop : 0;
    abas.carregar({ html: d.html, xml: d.xml });
    if (visual) {
      try { tip.commands.focus(Math.min(pos, tip.state.doc.content.size), { scrollIntoView: false }); } catch (e) { /* ok */ }
      if (area) area.scrollTop = rolagem;
    }
    editor.redecorar();
    atualizarSujo();
    mostrarInfo(ativo != null && info[ativo] ? ativo : null);
  }

  function mostrarConflito(d) {
    abas.mostrarErros(d.erros || ["Conflito de versão."]);
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = window.location.href;
    a.textContent = "Recarregar a tela (descarta o que não foi gravado)";
    a.className = "font-semibold underline";
    li.appendChild(a);
    $("#erros").appendChild(li);
  }

  let gravando = false;
  async function gravar() {
    if (gravando) return false;
    gravando = true;
    $("#btn-gravar").disabled = true;
    mensagem("Gravando…");
    try {
      const { formato, conteudo } = abas.conteudo();
      const r = await SE.postarJSON(dados.urlGravar, { formato, conteudo, ids, comentario: $("#comentario").value }, dados.csrf);
      const d = r.dados;
      if (r.status === 200 && d.ok) {
        recarregarDe(d);
        $("#comentario").value = "";
        const rs = d.resumo;
        const partes = [];
        if (rs.editados) partes.push(`${rs.editados} editado${rs.editados > 1 ? "s" : ""}`);
        if (rs.criados) partes.push(`${rs.criados} criado${rs.criados > 1 ? "s" : ""}`);
        if (rs.removidos) partes.push(`${rs.removidos} removido${rs.removidos > 1 ? "s" : ""}`);
        const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        mensagem(`Gravado às ${hora}` + (partes.length ? ": " + partes.join(", ") + "." : ": nenhuma alteração no texto."));
        if (d.estrutura_mudou) {
          const a = document.createElement("a");
          a.href = dados.urlEstrutura;
          a.textContent = " A estrutura mudou: ver a árvore.";
          a.className = "font-semibold text-crimson underline";
          elMsg.appendChild(a);
        }
        return true;
      }
      if (r.status === 409) {
        mostrarConflito(d);
        mensagem("Conflito: outra pessoa alterou estes blocos.", true);
        return false;
      }
      abas.mostrarErros(d.erros || [`Erro ao gravar (HTTP ${r.status}).`]);
      mensagem("Não gravado.", true);
      return false;
    } finally {
      gravando = false;
      $("#btn-gravar").disabled = false;
    }
  }
  $("#btn-gravar").addEventListener("click", gravar);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "s") {
      e.preventDefault();
      gravar();
    }
  });

  // -------------------------------------------------- ações sobre o bloco ativo
  document.querySelectorAll("[data-acao-bloco]").forEach((b) => b.addEventListener("click", async () => {
    const acao = b.getAttribute("data-acao-bloco");
    if (ativo == null || !info[ativo]) return;
    if (abas.sujo()) {
      mensagem("Grave (Ctrl+S) as alterações antes de usar esta ação.", true);
      return;
    }
    if (acao === "restaurar_1916" && !window.confirm("Voltar o texto deste bloco ao da edição de 1916? O texto adaptado fica no histórico.")) return;
    const r = await SE.postarJSON(dados.urlAcaoBloco, { acao, bloco: Number(ativo), ids }, dados.csrf);
    const d = r.dados;
    if (r.status === 200 && d.ok) {
      recarregarDe(d);
      mensagem(acao === "restaurar_1916" ? "Texto de 1916 restaurado." : acao === "suprimir" ? "Bloco suprimido." : "Bloco restaurado.");
    } else {
      mensagem((d.erros || [`Erro (HTTP ${r.status}).`]).join(" "), true);
    }
  }));

  atualizarSujo();
  if (dados.ids.length) {
    const i = info[String(dados.ids[0])];
    if (i && i.pagina != null) irScan(i.volume, i.pagina);
  }
  window.__nova = { editor, abas, gravar, ids: () => ids, info: () => info };
})();
