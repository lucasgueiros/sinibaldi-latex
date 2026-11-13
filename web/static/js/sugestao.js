/* Sinibaldi: sugestão de correção a partir de um trecho selecionado (JS puro, sem dependências).
 * Mostra um botão flutuante perto da seleção dentro de article.obra / .notas-fim e abre o <dialog>
 * já preenchido (bloco, trecho, sugestão). O envio é um POST comum de formulário. Sem <dialog>,
 * o botão leva à página do formulário (?bloco=). */
(function () {
  "use strict";
  var botao = document.querySelector("[data-sg-flutuante]");
  var dialogo = document.querySelector("[data-sg-dialogo]");
  var link = document.querySelector("[data-sg-link]");
  var artigo = document.querySelector("article.obra");
  if (!botao || !artigo) return;
  var notas = document.querySelector(".notas-fim");
  var temDialogo = !!dialogo && typeof dialogo.showModal === "function";
  var LIMITE_TRECHO = 2000;
  var ATRASO = 150;
  var atual = null; // {bloco, texto} da seleção que o botão representa
  var timer = null;

  function dentroDeAlvo(no) {
    var el = no && no.nodeType === 1 ? no : no && no.parentElement;
    return !!el && (artigo.contains(el) || (notas && notas.contains(el)));
  }

  // id numérico do bloco (b<pk>) onde está o nó; em nota de rodapé, o bloco que contém a chamada
  function blocoDe(no) {
    var el = no && no.nodeType === 1 ? no : no && no.parentElement;
    while (el) {
      if (el.id && /^b\d+$/.test(el.id)) return el.id.slice(1);
      var m = el.id && /^nota-(\d+)$/.exec(el.id);
      if (m) {
        var ref = document.getElementById("ref-" + m[1]);
        return ref ? blocoDe(ref) : "";
      }
      el = el.parentElement;
    }
    return "";
  }

  // texto da seleção sem etiquetas de procedência, marcas de página, chamadas e "voltar" das notas
  function textoDe(range) {
    var div = document.createElement("div");
    div.appendChild(range.cloneContents());
    var lixo = div.querySelectorAll('.proc, [data-tei="pb"], sup.nref, .volta');
    for (var i = 0; i < lixo.length; i++) lixo[i].remove();
    return div.textContent.replace(/\s+/g, " ").trim();
  }

  function esconder() {
    botao.hidden = true;
    atual = null;
  }

  function atualizar() {
    if (temDialogo && dialogo.open) return esconder();
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return esconder();
    var range = sel.getRangeAt(0);
    if (!dentroDeAlvo(range.startContainer)) return esconder();
    var texto = textoDe(range);
    if (!texto) return esconder();
    atual = {bloco: blocoDe(range.startContainer), texto: texto};
    var r = range.getBoundingClientRect();
    if (!r || (r.width === 0 && r.height === 0)) return esconder();
    botao.hidden = false;
    var largura = botao.offsetWidth;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - largura / 2), document.documentElement.clientWidth - largura - 8);
    botao.style.left = x + window.pageXOffset + "px";
    botao.style.top = r.bottom + window.pageYOffset + 8 + "px";
  }

  function agendar() {
    clearTimeout(timer);
    timer = setTimeout(atualizar, ATRASO);
  }

  function abrir() {
    if (!atual) return;
    var a = atual;
    esconder();
    if (!temDialogo) {
      if (link) window.location.href = link.getAttribute("href") + (a.bloco ? "?bloco=" + a.bloco : "");
      return;
    }
    var texto = a.texto.slice(0, LIMITE_TRECHO);
    dialogo.querySelector('[data-sg="bloco"]').value = a.bloco;
    dialogo.querySelector('[data-sg="trecho"]').value = texto;
    var sug = dialogo.querySelector('[data-sg="sugestao"]');
    sug.value = texto;
    dialogo.showModal();
    sug.focus();
  }

  document.addEventListener("selectionchange", agendar);
  document.addEventListener("mouseup", agendar);
  document.addEventListener("keyup", agendar);
  // não deixa o clique no botão desfazer a seleção antes do "click"
  botao.addEventListener("mousedown", function (e) { e.preventDefault(); });
  botao.addEventListener("touchstart", function (e) { e.preventDefault(); abrir(); }, {passive: false});
  botao.addEventListener("click", abrir);

  if (temDialogo) {
    var cancelar = dialogo.querySelector("[data-sg-cancelar]");
    if (cancelar) cancelar.addEventListener("click", function () { dialogo.close(); });
    dialogo.addEventListener("click", function (e) { if (e.target === dialogo) dialogo.close(); });
  }
})();
