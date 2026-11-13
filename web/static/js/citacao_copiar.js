/* Botões «Copiar LaTeX» e «Copiar para o Word» da tela de citação (sem eles a tela segue completa). */
(function () {
  "use strict";
  if (!navigator.clipboard) return;
  var ta = document.querySelector('[data-ct="latex"]');
  function marcar(b, ok) {
    var t = b.textContent;
    b.textContent = ok ? "Copiado ✓" : "Não foi possível copiar";
    setTimeout(function () { b.textContent = t; }, 1800);
  }
  var bl = document.querySelector('[data-ct-copiar="latex"]');
  if (bl && ta) {
    bl.hidden = false;
    bl.addEventListener("click", function () {
      navigator.clipboard.writeText(ta.value).then(function () { marcar(bl, true); }, function () { marcar(bl, false); });
    });
  }
  // HTML formatado (negrito do título; recuo da citação longa): o Word cola com a formatação
  var bw = document.querySelector('[data-ct-copiar="word"]');
  var cit = document.querySelector('[data-ct="citacao"]');
  var ref = document.querySelector('[data-ct="referencia"]');
  if (bw && cit && ref && window.ClipboardItem) {
    bw.hidden = false;
    bw.addEventListener("click", function () {
      var h = (cit.classList.contains("ct-longa")
        ? '<p style="margin-left:4cm;font-size:10pt;text-align:justify">' + cit.innerHTML + "</p>"
        : '<p style="text-align:justify;line-height:1.5">' + cit.innerHTML + "</p>")
        + "<p><b>REFERÊNCIAS</b></p><p>" + ref.innerHTML + "</p>";
      var txt = cit.textContent.trim() + "\n\nREFERÊNCIAS\n" + ref.textContent.trim();
      navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([h], {type: "text/html"}),
        "text/plain": new Blob([txt], {type: "text/plain"})
      })]).then(function () { marcar(bw, true); }, function () { marcar(bw, false); });
    });
  }
})();
