/* Sinibaldi: «Citar (ABNT)» a partir de um trecho selecionado (JS puro). Mostra um botão flutuante
 * ao lado do «Sugerir correção» e envia (POST) trecho, página inicial/final impressas e bloco para
 * a tela de citação. As páginas vêm das marcas [data-tei="pb"] (data-n = página impressa): a última
 * marca antes do início/fim da seleção. Sem JS, o link «Citar (ABNT)» do cabeçalho cita o trecho inteiro. */
(function () {
  "use strict";
  var botao = document.querySelector("[data-ct-flutuante]");
  var form = document.querySelector("[data-ct-form]");
  var artigo = document.querySelector("article.obra");
  if (!botao || !form || !artigo) return;
  var notas = document.querySelector(".notas-fim");
  var LIMITE = 5000;
  var ATRASO = 200; // depois do botão de sugestão (150 ms), para posicionar-se ao lado dele
  var atual = null;
  var timer = null;

  function elemento(no) { return no && no.nodeType === 1 ? no : no && no.parentElement; }

  // só o corpo do texto: em nota de rodapé a página é a da chamada, que o usuário cita à mão
  function noCorpo(no) { var el = elemento(no); return !!el && artigo.contains(el); }

  // última marca de página que precede (ou contém) o ponto (nó, deslocamento)
  function paginaEm(no, desloc) {
    var marcas = artigo.querySelectorAll('[data-tei="pb"][data-n]');
    var achada = "";
    var ponto = document.createRange();
    ponto.setStart(no, desloc);
    ponto.collapse(true);
    for (var i = 0; i < marcas.length; i++) {
      var r = document.createRange();
      r.selectNode(marcas[i]);
      if (ponto.compareBoundaryPoints(Range.START_TO_START, r) >= 0) achada = marcas[i].getAttribute("data-n");
      else break;
    }
    return achada;
  }

  function blocoDe(no) {
    var el = elemento(no);
    while (el) {
      if (el.id && /^b\d+$/.test(el.id)) return el.id.slice(1);
      el = el.parentElement;
    }
    return "";
  }

  function textoDe(range) {
    var div = document.createElement("div");
    div.appendChild(range.cloneContents());
    var lixo = div.querySelectorAll('.proc, [data-tei="pb"], sup.nref, .volta');
    for (var i = 0; i < lixo.length; i++) lixo[i].remove();
    return div.textContent.replace(/\s+/g, " ").trim();
  }

  function esconder() { botao.hidden = true; atual = null; }

  function atualizar() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return esconder();
    var range = sel.getRangeAt(0);
    if (!noCorpo(range.startContainer) || !noCorpo(range.endContainer)) return esconder();
    var texto = textoDe(range);
    if (!texto) return esconder();
    atual = {
      texto: texto,
      pi: paginaEm(range.startContainer, range.startOffset),
      pf: paginaEm(range.endContainer, range.endOffset),
      bloco: blocoDe(range.startContainer)
    };
    var r = range.getBoundingClientRect();
    if (!r || (r.width === 0 && r.height === 0)) return esconder();
    botao.hidden = false;
    var sg = document.querySelector("[data-sg-flutuante]");
    var largura = botao.offsetWidth;
    var x;
    if (sg && !sg.hidden && sg.style.left) {
      x = parseFloat(sg.style.left) - largura - 6 - window.pageXOffset;   // à esquerda do «Sugerir»
    } else {
      x = r.left + r.width / 2 - largura / 2;
    }
    x = Math.min(Math.max(8, x), document.documentElement.clientWidth - largura - 8);
    botao.style.left = x + window.pageXOffset + "px";
    botao.style.top = r.bottom + window.pageYOffset + 8 + "px";
  }

  function agendar() { clearTimeout(timer); timer = setTimeout(atualizar, ATRASO); }

  function enviar() {
    if (!atual) return;
    var a = atual;
    if (a.texto.length > LIMITE) {
      window.alert("Trecho muito longo para citar (máximo " + LIMITE + " caracteres). Selecione uma passagem menor.");
      return;
    }
    esconder();
    form.querySelector('[name="trecho"]').value = a.texto;
    form.querySelector('[name="pi"]').value = a.pi;
    form.querySelector('[name="pf"]').value = a.pf;
    form.querySelector('[name="bloco"]').value = a.bloco;
    form.submit();
  }

  document.addEventListener("selectionchange", agendar);
  document.addEventListener("mouseup", agendar);
  document.addEventListener("keyup", agendar);
  botao.addEventListener("mousedown", function (e) { e.preventDefault(); });
  botao.addEventListener("touchstart", function (e) { e.preventDefault(); enviar(); }, {passive: false});
  botao.addEventListener("click", enviar);
})();
