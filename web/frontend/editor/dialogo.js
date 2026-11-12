// Diálogo modal mínimo (<dialog>) para pedir poucos campos.
// dialogo({titulo, campos: [{nome, rotulo, tipo: "texto"|"select", valor, opcoes: [[valor, rótulo]], ajuda, obrigatorio}]})
//   -> Promise<{nome: valor}|null>
// `validar(valores) -> string|null`: mensagem de erro impede o fechamento.
export function dialogo({ titulo, campos, confirmar = "OK", validar = null }) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "sn-dialogo";
    const form = document.createElement("form");
    form.method = "dialog";
    const h = document.createElement("h2");
    h.textContent = titulo;
    form.appendChild(h);
    const inputs = {};
    for (const c of campos) {
      const label = document.createElement("label");
      label.className = "sn-dialogo-campo";
      const span = document.createElement("span");
      span.textContent = c.rotulo;
      label.appendChild(span);
      let el;
      if (c.tipo === "select") {
        el = document.createElement("select");
        for (const [v, r] of c.opcoes) {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = r;
          el.appendChild(o);
        }
      } else {
        el = document.createElement("input");
        el.type = "text";
        el.autocomplete = "off";
      }
      el.className = "campo";
      el.value = c.valor == null ? "" : c.valor;
      if (c.obrigatorio) el.required = true;
      label.appendChild(el);
      if (c.ajuda) {
        const a = document.createElement("small");
        a.textContent = c.ajuda;
        label.appendChild(a);
      }
      form.appendChild(label);
      inputs[c.nome] = el;
    }
    const linha = document.createElement("div");
    linha.className = "sn-dialogo-botoes";
    const cancelar = document.createElement("button");
    cancelar.type = "button";
    cancelar.className = "btn btn-secundario btn-sm";
    cancelar.textContent = "Cancelar";
    const ok = document.createElement("button");
    ok.type = "submit";
    ok.className = "btn btn-primario btn-sm";
    ok.textContent = confirmar;
    linha.append(cancelar, ok);
    form.appendChild(linha);
    d.appendChild(form);
    document.body.appendChild(d);

    let resultado = null;
    cancelar.addEventListener("click", () => d.close());
    const erro = document.createElement("p");
    erro.className = "sn-dialogo-erro";
    erro.hidden = true;
    form.insertBefore(erro, linha);
    form.addEventListener("submit", (ev) => {
      const valores = {};
      for (const [nome, el] of Object.entries(inputs)) valores[nome] = el.value.trim();
      const msg = validar ? validar(valores) : null;
      if (msg) {
        ev.preventDefault();
        erro.textContent = msg;
        erro.hidden = false;
        return;
      }
      resultado = valores;
    });
    d.addEventListener("close", () => {
      d.remove();
      resolve(resultado);
    });
    d.showModal();
    const primeiro = Object.values(inputs)[0];
    if (primeiro) {
      primeiro.focus();
      if (primeiro.select) primeiro.select();
    }
  });
}
