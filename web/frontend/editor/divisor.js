// Divisor arrastável entre duas colunas; a posição (% da primeira coluna) fica em localStorage.
//   montarDivisor({divisor, primeira, chave, min, max})
export function montarDivisor({ divisor, primeira, chave = "sinibaldi.divisor", min = 20, max = 80 }) {
  const aplicar = (pct) => {
    pct = Math.min(max, Math.max(min, pct));
    primeira.style.flex = `0 0 ${pct}%`;
    return pct;
  };
  const guardar = (pct) => {
    try { localStorage.setItem(chave, String(pct)); } catch (e) { /* ok */ }
  };
  let atual = 50;
  try {
    const v = parseFloat(localStorage.getItem(chave));
    if (v > 0) atual = v;
  } catch (e) { /* ok */ }
  atual = aplicar(atual);

  divisor.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    divisor.setPointerCapture(e.pointerId);
    const pai = divisor.parentElement.getBoundingClientRect();
    const mover = (ev) => {
      atual = aplicar(((ev.clientX - pai.left) / pai.width) * 100);
    };
    const fim = () => {
      divisor.removeEventListener("pointermove", mover);
      divisor.removeEventListener("pointerup", fim);
      divisor.removeEventListener("pointercancel", fim);
      document.body.classList.remove("sn-redimensionando");
      guardar(atual);
    };
    document.body.classList.add("sn-redimensionando");
    divisor.addEventListener("pointermove", mover);
    divisor.addEventListener("pointerup", fim);
    divisor.addEventListener("pointercancel", fim);
  });
  divisor.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    atual = aplicar(atual + (e.key === "ArrowLeft" ? -2 : 2));
    guardar(atual);
  });
  divisor.addEventListener("dblclick", () => { atual = aplicar(50); guardar(atual); });
}
