// Visualizador de scan: zoom (botões, Ctrl+roda, teclas), arrasto e ajuste à largura.
//   montarVisualizador(el, {botoes, indicador, chave}) -> {largura(), tamanhoReal(), ampliar(f), destruir()}
//   `el` contém um <img>; `botoes` é o elemento com [data-zoom=mais|menos|largura|cem].
//   selecionarCaixa() -> Promise<{x, y, l, a}|null>: modo de recorte (arrastar desenha a caixa, Esc
//   cancela); coordenadas em pixels naturais da imagem exibida. A caixa fica desenhada até limparCaixa().
export function montarVisualizador(el, { botoes = null, indicador = null, chave = "sinibaldi.scan" } = {}) {
  const img = el.querySelector("img");
  const aviso = el.querySelector("[data-sem-scan]");
  const S = { s: 1, x: 0, y: 0, modo: "largura" };
  // recorte (gravuras): caixa em pixels naturais da imagem; acompanha zoom e arrasto
  const R = { ativo: null, caixa: null, ini: null, div: null };
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
    pintarCaixa();
  };
  function pintarCaixa() {
    if (!R.caixa) {
      if (R.div) R.div.style.display = "none";
      return;
    }
    if (!R.div) {
      R.div = document.createElement("div");
      R.div.className = "sn-caixa";
      el.appendChild(R.div);
    }
    const c = R.caixa;
    Object.assign(R.div.style, {
      display: "block", left: `${S.x + c.x * S.s}px`, top: `${S.y + c.y * S.s}px`,
      width: `${c.l * S.s}px`, height: `${c.a * S.s}px`,
    });
  }
  const pontoNatural = (e) => {
    const r = el.getBoundingClientRect();
    const nx = (e.clientX - r.left - S.x) / S.s;
    const ny = (e.clientY - r.top - S.y) / S.s;
    return [Math.min(Math.max(nx, 0), img.naturalWidth), Math.min(Math.max(ny, 0), img.naturalHeight)];
  };
  const caixaEntre = ([x0, y0], [x1, y1]) => ({
    x: Math.min(x0, x1), y: Math.min(y0, y1), l: Math.abs(x1 - x0), a: Math.abs(y1 - y0),
  });
  const encerrarRecorte = (resultado) => {
    const r = R.ativo;
    R.ativo = null;
    R.ini = null;
    el.classList.remove("sn-recortando");
    document.removeEventListener("keydown", escRecorte, true);
    if (r) r(resultado);
  };
  function escRecorte(e) {
    if (e.key === "Escape" && R.ativo) {
      e.preventDefault();
      e.stopPropagation();
      R.caixa = null;
      pintarCaixa();
      encerrarRecorte(null);
    }
  }
  const selecionarCaixa = () => {
    if (R.ativo) encerrarRecorte(null);
    if (!img.naturalWidth) return Promise.resolve(null);
    R.caixa = null;
    pintarCaixa();
    el.classList.add("sn-recortando");
    document.addEventListener("keydown", escRecorte, true);
    return new Promise((resolve) => { R.ativo = resolve; });
  };
  const limparCaixa = () => {
    R.caixa = null;
    pintarCaixa();
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
    if (R.ativo) {
      R.ini = pontoNatural(e);
      R.caixa = { x: R.ini[0], y: R.ini[1], l: 0, a: 0 };
      el.setPointerCapture(e.pointerId);
      pintarCaixa();
      return;
    }
    arrasto = { x: e.clientX - S.x, y: e.clientY - S.y };
    el.setPointerCapture(e.pointerId);
    el.classList.add("sn-arrastando");
  });
  el.addEventListener("pointermove", (e) => {
    if (R.ativo && R.ini) {
      R.caixa = caixaEntre(R.ini, pontoNatural(e));
      pintarCaixa();
      return;
    }
    if (!arrasto) return;
    S.x = e.clientX - arrasto.x;
    S.y = e.clientY - arrasto.y;
    aplicar();
  });
  const soltar = (e) => {
    if (R.ativo && R.ini) {
      if (e.pointerId != null && el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
      R.ini = null;
      const c = R.caixa;
      if (e.type === "pointercancel" || !c || c.l * S.s < 6 || c.a * S.s < 6) {  // clique sem arrastar: continua no modo
        R.caixa = null;
        pintarCaixa();
        return;
      }
      encerrarRecorte({ x: Math.round(c.x), y: Math.round(c.y), l: Math.round(c.l), a: Math.round(c.a) });
      return;
    }
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
  return { largura, tamanhoReal, ampliar, selecionarCaixa, limparCaixa, destruir: () => ro && ro.disconnect() };
}
