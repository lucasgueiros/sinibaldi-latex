/* Sinibaldi: interações do site (JS puro, sem dependências). */
(function () {
  "use strict";
  var toggle = document.querySelector("[data-menu-toggle]");
  var menu = document.querySelector("[data-menu]");
  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      var open = menu.classList.toggle("hidden") === false;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.querySelector("[data-icon-open]").classList.toggle("hidden", open);
      toggle.querySelector("[data-icon-close]").classList.toggle("hidden", !open);
    });
  }
  document.querySelectorAll("[data-dispensar]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var alvo = btn.closest("[data-mensagem]");
      if (alvo) alvo.remove();
    });
  });

  /* Notas de rodapé: clicar no número (<sup class="nref"><a href="#nota-N">) abre a nota num
     popup junto à chamada, em vez de saltar para a lista do fim. Ctrl/⌘/Shift-clique (ou o link
     «ir para as notas» do popup) mantém o salto. Delegação no document: vale também para HTML
     trocado depois do carregamento (editor da nova edição). */
  var pop = null, ref = null;

  function fechar(devolverFoco) {
    if (!pop) return;
    pop.remove();
    pop = null;
    if (ref) {
      ref.setAttribute("aria-expanded", "false");
      if (devolverFoco) ref.focus();
    }
    ref = null;
  }

  function posicionar() {
    if (!pop || !ref) return;
    if (!ref.isConnected) { fechar(false); return; }
    var r = ref.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { fechar(false); return; }
    var vw = document.documentElement.clientWidth, margem = 8;
    var w = Math.min(pop.offsetWidth, vw - 2 * margem);
    var x = Math.max(margem, Math.min(r.left + r.width / 2 - w / 2, vw - w - margem));
    var h = pop.offsetHeight, abaixo = window.innerHeight - r.bottom;
    var acima = abaixo < h + margem && r.top > abaixo;
    pop.classList.toggle("nota-pop-acima", acima);
    pop.style.left = x + "px";
    pop.style.top = (acima ? r.top - h - 8 : r.bottom + 8) + "px";
    var seta = pop.querySelector(".nota-pop-seta");
    if (seta) seta.style.left = Math.max(12, Math.min(r.left + r.width / 2 - x, w - 12)) + "px";
  }

  function abrir(a, item) {
    fechar(false);
    ref = a;
    var n = item.getAttribute("value") || a.textContent.trim();
    pop = document.createElement("div");
    pop.className = "nota-pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Nota " + n);
    pop.tabIndex = -1;
    pop.innerHTML =
      '<span class="nota-pop-seta" aria-hidden="true"></span>' +
      '<div class="nota-pop-cab"><span class="nota-pop-n"></span>' +
      '<a class="nota-pop-ir">ir para as notas</a>' +
      '<button type="button" class="nota-pop-fechar" aria-label="Fechar nota">×</button></div>' +
      '<div class="nota-pop-corpo"></div>';
    pop.querySelector(".nota-pop-n").textContent = "Nota " + n;
    var ir = pop.querySelector(".nota-pop-ir");
    ir.setAttribute("href", a.getAttribute("href"));
    ir.addEventListener("click", function () { fechar(false); });
    pop.querySelector(".nota-pop-fechar").addEventListener("click", function () { fechar(true); });
    var corpo = pop.querySelector(".nota-pop-corpo");
    Array.prototype.forEach.call(item.childNodes, function (no) { corpo.appendChild(no.cloneNode(true)); });
    corpo.querySelectorAll(".volta").forEach(function (el) { el.remove(); });
    corpo.querySelectorAll("[id]").forEach(function (el) { el.removeAttribute("id"); });
    document.body.appendChild(pop);
    a.setAttribute("aria-expanded", "true");
    posicionar();
    pop.focus({ preventScroll: true });
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("sup.nref a[href^='#']");
    if (a) {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) return;
      var item = document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)));
      if (!item) return;
      e.preventDefault();
      if (ref === a) { fechar(false); return; }
      abrir(a, item);
      return;
    }
    if (pop && !pop.contains(e.target)) fechar(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && pop) { e.preventDefault(); fechar(true); }
  });
  window.addEventListener("scroll", posicionar, true);
  window.addEventListener("resize", posicionar);
})();
