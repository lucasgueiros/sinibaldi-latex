// Controlador da tela de revisão (templates/edicao/revisar.html). Usa window.SinibaldiEditor.
(function () {
  "use strict";
  const SE = window.SinibaldiEditor;
  const raiz = document.querySelector("[data-revisao]");
  if (!SE || !raiz) return;
  const $ = (s) => document.querySelector(s);
  const dados = JSON.parse($("#dados-revisao").textContent);
  const esquema = JSON.parse($("#esquema-editor").textContent);

  let ids = dados.ids.slice();
  let info = dados.info;
  let estadoGravado = dados.estado.valor;

  SE.montarDivisor({ divisor: $("#divisor"), primeira: $("#col-scan"), chave: "sinibaldi.divisor" });
  SE.montarVisualizador($("#visualizador"), {
    botoes: $("#col-scan .barra-ferramentas"), indicador: $("[data-zoom-indicador]"), chave: "sinibaldi.scan",
  });

  const elSujo = $("[data-sujo]");
  const elMsg = $("#estado-revisao");
  const elInfoTexto = $("[data-info-texto]");
  const elInfoLink = $("[data-info-link]");
  const selEstado = $("#estado");

  function mensagem(texto, erro) {
    elMsg.textContent = texto;
    elMsg.className = "px-3 pb-1 text-[11px] " + (erro ? "text-red-800" : "text-ink/60");
  }

  function mostrarInfo(id) {
    const i = id != null ? info[String(id)] : null;
    elInfoLink.classList.add("hidden");
    if (id == null) {
      elInfoTexto.textContent = "Bloco novo (ainda não gravado).";
      return;
    }
    if (!i) {
      elInfoTexto.textContent = "Clique num bloco para ver quem o alterou por último.";
      return;
    }
    const quem = i.autor ? `última alteração por ${i.autor} em ${i.em}` : "sem alterações desde a importação";
    elInfoTexto.textContent = `Bloco #${id} · v${i.versao} · ${quem}` +
      (i.comeca_antes ? ` · começou na pág. (scan) ${i.pagina} e atravessa para esta` : "");
    elInfoLink.href = dados.urlHistoricoBloco.replace("/0/", `/${id}/`);
    elInfoLink.classList.remove("hidden");
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
      if (i && i.comeca_antes) {
        return { class: "sn-continua", "data-continua": `← começa na pág. ${i.pagina}`, title: "Este bloco começou numa página anterior e atravessa para esta." };
      }
      return null;
    },
    aoMudar: () => atualizarSujo(),
    aoBlocoAtivo: mostrarInfo,
  });

  const abas = SE.montarAbas({
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

  function sujoGeral() {
    return abas.sujo() || selEstado.value !== estadoGravado;
  }
  function atualizarSujo() {
    elSujo.classList.toggle("hidden", !sujoGeral());
  }
  selEstado.addEventListener("change", atualizarSujo);

  window.addEventListener("beforeunload", (e) => {
    if (sujoGeral()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  let gravando = false;
  async function gravar(seguir) {
    if (gravando) return false;
    gravando = true;
    $("#btn-gravar").disabled = true;
    mensagem("Gravando…");
    try {
      const { formato, conteudo } = abas.conteudo();
      const r = await SE.postarJSON(dados.urlGravar, {
        formato, conteudo, ids, comentario: $("#comentario").value, estado: selEstado.value,
      }, dados.csrf);
      const d = r.dados;
      if (r.status === 200 && d.ok) {
        ids = d.ids;
        info = d.info;
        abas.carregar({ html: d.html, xml: d.xml });
        estadoGravado = d.estado.valor;
        selEstado.value = estadoGravado;
        $("[data-estado-rotulo]").textContent = d.estado.rotulo;
        $("#comentario").value = "";
        const rs = d.resumo;
        const partes = [];
        if (rs.editados) partes.push(`${rs.editados} editado${rs.editados > 1 ? "s" : ""}`);
        if (rs.criados) partes.push(`${rs.criados} criado${rs.criados > 1 ? "s" : ""}`);
        if (rs.removidos) partes.push(`${rs.removidos} removido${rs.removidos > 1 ? "s" : ""}`);
        const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        mensagem(`Gravado às ${hora}` + (partes.length ? ": " + partes.join(", ") + "." : ": nenhuma alteração no texto."));
        atualizarSujo();
        editor.redecorar();
        if (seguir && dados.urlSeguinte) window.location.href = dados.urlSeguinte;
        return true;
      }
      if (r.status === 409) {
        abas.mostrarErros(d.erros || ["Conflito de versão."]);
        const ul = $("#erros");
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = window.location.href;
        a.textContent = "Recarregar a página (descarta o que não foi gravado)";
        a.className = "font-semibold underline";
        li.appendChild(a);
        ul.appendChild(li);
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
  $("#btn-gravar").addEventListener("click", () => gravar(false));
  const seguirBtn = $("#btn-gravar-seguir");
  if (seguirBtn) seguirBtn.addEventListener("click", () => gravar(true));
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "s") {
      e.preventDefault();
      gravar(false);
    }
  });

  atualizarSujo();
  // exposto para depuração e testes de navegador
  window.__revisao = { editor, abas, gravar, ids: () => ids };
})();
