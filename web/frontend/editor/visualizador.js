// Visualizador de scan: zoom (botões, Ctrl+roda, teclas), arrasto e ajuste à largura.
//   montarVisualizador(el, {botoes, indicador, chave}) -> {largura(), tamanhoReal(), ampliar(f), destruir()}
//   `el` contém um <img>; `botoes` é o elemento com [data-zoom=mais|menos|largura|cem].
export function montarVisualizador(el, { botoes = null, indicador = null, chave = "sinibaldi.scan" } = {}) {
  const img = el.querySelector("img");
  const aviso = el.querySelector("[data-sem-scan]");
  const S = { s: 1, x: 0, y: 0, modo: "largura" };
  try {
    const salvo = JSON.parse(localStorage.getItem(chave) || "null");
    if (salvo && (salvo.modo === "largura" || salvo.modo === "escala")) {
      S.modo = salvo.modo;
      if (salvo.modo === "escala" && salvo.s > 0) S.s = salvo.s;
    }
  } catch (e) { /* localStorage indisponível */ }

  const guardar = () => {
    try { localStorage.setItem(chave, JSON.stringify({ modo: S.modo, s: S.s })); } catch (e) { /* ok */ }
  };
  const aplicar = () => {
    img.style.transform = `translate(${S.x}px, ${S.y}px) scale(${S.s})`;
    img.style.visibility = "visible";
    if (indicador) indicador.textContent = Math.round(S.s * 100) + "%";
  };
  const larguraNatural = () => img.naturalWidth || 1;
  const largura = () => {
    S.modo = "largura";
    S.s = el.clientWidth / larguraNatural();
    S.x = 0;
    S.y = 0;
    aplicar();
    guardar();
  };
  const zoomEm = (fator, cx, cy) => {
    const novo = Math.min(8, Math.max(0.05, S.s * fator));
    const k = novo / S.s;
    S.x = cx - (cx - S.x) * k;
    S.y = cy - (cy - S.y) * k;
    S.s = novo;
    S.modo = "escala";
    aplicar();
    guardar();
  };
  const centro = () => [el.clientWidth / 2, el.clientHeight / 2];
  const ampliar = (f) => zoomEm(f, ...centro());
  const tamanhoReal = () => {
    const [cx, cy] = centro();
    zoomEm(1 / S.s, cx, cy);
  };

  const iniciar = () => {
    if (S.modo === "largura") largura();
    else { S.x = 0; S.y = 0; aplicar(); }
  };
  if (img.complete && img.naturalWidth) iniciar();
  img.addEventListener("load", iniciar);
  img.addEventListener("error", () => {
    img.style.display = "none";
    if (aviso) { aviso.classList.remove("hidden"); aviso.classList.add("flex"); }
  });

  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => { if (S.modo === "largura" && img.naturalWidth) largura(); }) : null;
  if (ro) ro.observe(el);

  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const r = el.getBoundingClientRect();
      zoomEm(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    } else {
      S.x -= e.deltaX;
      S.y -= e.deltaY;
      aplicar();
    }
  }, { passive: false });

  let arrasto = null;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    arrasto = { x: e.clientX - S.x, y: e.clientY - S.y };
    el.setPointerCapture(e.pointerId);
    el.classList.add("sn-arrastando");
  });
  el.addEventListener("pointermove", (e) => {
    if (!arrasto) return;
    S.x = e.clientX - arrasto.x;
    S.y = e.clientY - arrasto.y;
    aplicar();
  });
  const soltar = (e) => {
    arrasto = null;
    el.classList.remove("sn-arrastando");
    if (e.pointerId != null && el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
  };
  el.addEventListener("pointerup", soltar);
  el.addEventListener("pointercancel", soltar);

  el.addEventListener("keydown", (e) => {
    if (e.target !== el) return;
    const passo = 60;
    const mapa = {
      "+": () => ampliar(1.2), "=": () => ampliar(1.2), "-": () => ampliar(1 / 1.2), "0": largura,
      ArrowUp: () => { S.y += passo; aplicar(); }, ArrowDown: () => { S.y -= passo; aplicar(); },
      ArrowLeft: () => { S.x += passo; aplicar(); }, ArrowRight: () => { S.x -= passo; aplicar(); },
    };
    if (mapa[e.key]) { e.preventDefault(); mapa[e.key](); }
  });

  if (botoes) {
    botoes.addEventListener("click", (e) => {
      const b = e.target.closest("[data-zoom]");
      if (!b) return;
      const acao = b.getAttribute("data-zoom");
      if (acao === "mais") ampliar(1.25);
      else if (acao === "menos") ampliar(1 / 1.25);
      else if (acao === "largura") largura();
      else if (acao === "cem") tamanhoReal();
    });
  }
  return { largura, tamanhoReal, ampliar, destruir: () => ro && ro.disconnect() };
}
