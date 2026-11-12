// Camada de abas Visual/XML sobre um editor montado por `montar`.
import { postarJSON } from "./rede.js";

export function montarAbas(o) {
  const { editor, textarea, urlConverter, csrf } = o;
  const abas = o.abas; // {visual: {botao, painel}, xml: {botao, painel}}
  const elErros = o.erros || null;
  let ativa = "visual";
  let xmlBase = ""; // texto do textarea no último carregamento/conversão
  let ocupado = false;

  const mudou = () => o.aoMudar && o.aoMudar(sujo());

  function mostrarErros(lista) {
    if (!elErros) return;
    elErros.textContent = "";
    for (const e of lista || []) {
      const li = document.createElement("li");
      li.textContent = e;
      elErros.appendChild(li);
    }
    elErros.classList.toggle("hidden", !(lista && lista.length));
  }

  function mostrar(nome) {
    ativa = nome;
    for (const [k, v] of Object.entries(abas)) {
      const on = k === nome;
      v.botao.className = on ? "aba-ativa" : "aba";
      v.botao.setAttribute("aria-selected", String(on));
      v.painel.classList.toggle("hidden", !on);
      v.painel.classList.toggle("flex", on);
    }
    if (nome === "visual") editor.focar();
    else textarea.focus();
  }

  function xmlSujo() {
    return textarea.value !== xmlBase;
  }

  function sujo() {
    return editor.sujo() || (ativa === "xml" && xmlSujo());
  }

  async function trocar(nome) {
    if (nome === ativa || ocupado) return true;
    ocupado = true;
    try {
      mostrarErros([]);
      if (nome === "xml") {
        const r = await postarJSON(urlConverter, { de: "html", conteudo: editor.obterHtml() }, csrf);
        const d = r.dados;
        if (r.status !== 200 || (d.erros && d.erros.length)) {
          mostrarErros(d.erros && d.erros.length ? d.erros : ["Não foi possível converter para XML."]);
          return false;
        }
        textarea.value = d.xml;
        xmlBase = d.xml;
      } else if (xmlSujo()) {
        const r = await postarJSON(urlConverter, { de: "xml", conteudo: textarea.value }, csrf);
        const d = r.dados;
        if (r.status !== 200 || (d.erros && d.erros.length)) {
          mostrarErros(d.erros && d.erros.length ? d.erros : ["Não foi possível converter o XML."]);
          return false;
        }
        editor.definirHtml(d.html, { limpo: false });
      }
      mostrar(nome);
      mudou();
      return true;
    } finally {
      ocupado = false;
    }
  }

  for (const [nome, v] of Object.entries(abas)) v.botao.addEventListener("click", () => trocar(nome));
  textarea.addEventListener("input", mudou);

  return {
    ativa: () => ativa,
    trocar,
    mostrarErros,
    sujo,
    /** Conteúdo da aba ativa, pronto para `…/gravar/`: {formato: "html"|"xml", conteudo}. */
    conteudo() {
      return ativa === "xml" ? { formato: "xml", conteudo: textarea.value } : { formato: "html", conteudo: editor.obterHtml() };
    },
    /** Recarrega as duas abas com o resultado do servidor e declara tudo "gravado". */
    carregar({ html, xml }) {
      editor.definirHtml(html, { limpo: true });
      if (xml != null) {
        textarea.value = xml;
        xmlBase = xml;
      } else if (ativa === "xml") {
        textarea.value = "";
        xmlBase = "";
      }
      mostrarErros([]);
      mudou();
    },
  };
}
