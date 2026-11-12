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
})();
