// Esquema ProseMirror/TipTap que espelha EXATAMENTE o dialeto HTML de obra/tei.py
// (fragmento_para_html / html_para_blocos). Nada fora dele existe no editor.
//
//   bloco (grupo "bloco", filhos diretos do documento)
//     marco     div[data-tei=milestone][data-unit][data-n][data-xmlid]   (átomo)
//     titulo    h3[data-tei=head][data-type=rotulo?]
//     paragrafo p[data-tei=p][data-type?][data-xmlid?]
//     sumario   div[data-tei=argument] > p[data-xmlid?]                  (argPara+)
//     cabecalho p[data-tei=fw]
//   inline
//     pb        span[data-tei=pb][data-n][data-facs]                     (átomo)
//     asterisco span[data-tei=anchor][data-type=asterisco]               (átomo; vale também em nota)
//     nota      span[data-tei=note][data-n][data-xmlid] > span[data-tei=note-p]+
//     fwInline  span[data-tei=fw]
//   marcas: negrito <b>, italico <i>, versalete span[data-tei=hi][data-rend=sc],
//           latim span[data-tei=foreign][lang], rotulo span[data-tei=label]
//
// Todo bloco carrega data-bloco / data-versao (identidade e versão no servidor).
import { Node, Mark, mergeAttributes } from "@tiptap/core";

const attr = (nome, html) => ({
  default: null,
  parseHTML: (el) => el.getAttribute(html),
  renderHTML: (a) => (a[nome] != null && a[nome] !== "" ? { [html]: a[nome] } : {}),
});

const attrsBloco = () => ({
  dataBloco: attr("dataBloco", "data-bloco"),
  dataVersao: attr("dataVersao", "data-versao"),
});

export const Paragrafo = Node.create({
  name: "paragrafo",
  group: "bloco",
  content: "inline*",
  addAttributes() {
    return { ...attrsBloco(), type: attr("type", "data-type"), xmlid: attr("xmlid", "data-xmlid") };
  },
  parseHTML() {
    return [{ tag: 'p[data-tei="p"]', priority: 60 }, { tag: "p", priority: 40 }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["p", mergeAttributes({ "data-tei": "p" }, HTMLAttributes), 0];
  },
});

export const Titulo = Node.create({
  name: "titulo",
  group: "bloco",
  content: "inline*",
  addAttributes() {
    return { ...attrsBloco(), type: attr("type", "data-type") };
  },
  parseHTML() {
    return [
      { tag: 'h3[data-tei="head"]', priority: 60 },
      ...["h1", "h2", "h3", "h4", "h5", "h6"].map((tag) => ({ tag, priority: 40 })),
    ];
  },
  renderHTML({ HTMLAttributes }) {
    return ["h3", mergeAttributes({ "data-tei": "head" }, HTMLAttributes), 0];
  },
});

export const Cabecalho = Node.create({
  name: "cabecalho",
  group: "bloco",
  content: "(text|pb)*",
  addAttributes() {
    return attrsBloco();
  },
  parseHTML() {
    return [{ tag: 'p[data-tei="fw"]', priority: 60 }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["p", mergeAttributes({ "data-tei": "fw" }, HTMLAttributes), 0];
  },
});

export const ParagrafoSumario = Node.create({
  name: "paragrafoSumario",
  content: "inline*",
  addAttributes() {
    return { xmlid: attr("xmlid", "data-xmlid") };
  },
  parseHTML() {
    return [{ tag: "p", context: "sumario/", priority: 60 }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["p", HTMLAttributes, 0];
  },
});

export const Sumario = Node.create({
  name: "sumario",
  group: "bloco",
  content: "paragrafoSumario+",
  defining: true,
  addAttributes() {
    return attrsBloco();
  },
  parseHTML() {
    return [{ tag: 'div[data-tei="argument"]', priority: 60 }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes({ "data-tei": "argument" }, HTMLAttributes), 0];
  },
});

export const Marco = Node.create({
  name: "marco",
  group: "bloco",
  atom: true,
  selectable: true,
  draggable: false,
  addAttributes() {
    return {
      ...attrsBloco(),
      unit: attr("unit", "data-unit"),
      n: attr("n", "data-n"),
      xmlid: attr("xmlid", "data-xmlid"),
    };
  },
  parseHTML() {
    return [{ tag: 'div[data-tei="milestone"]', priority: 60 }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes({ "data-tei": "milestone" }, HTMLAttributes)];
  },
  addNodeView() {
    // Visual de edição: o rótulo vem do CSS (::before em data-unit/data-n); o botão abre o formulário.
    return ({ node, editor, getPos }) => {
      const dom = document.createElement("div");
      dom.className = "sn-marco";
      dom.contentEditable = "false";
      const botao = document.createElement("button");
      botao.type = "button";
      botao.className = "sn-marco-editar";
      botao.textContent = "editar";
      botao.title = "Editar unidade, número e xml:id";
      dom.appendChild(botao);
      const info = document.createElement("span");
      info.className = "sn-marco-id";
      dom.appendChild(info);
      const pintar = (n) => {
        dom.setAttribute("data-tei", "milestone");
        for (const [a, k] of [["data-unit", "unit"], ["data-n", "n"], ["data-xmlid", "xmlid"]]) {
          if (n.attrs[k]) dom.setAttribute(a, n.attrs[k]);
          else dom.removeAttribute(a);
        }
        info.textContent = n.attrs.xmlid ? n.attrs.xmlid : "";
      };
      pintar(node);
      const abrir = () => {
        const api = editor.storage.sinibaldi;
        if (api && api.editarMarco) api.editarMarco(getPos());
      };
      botao.addEventListener("click", abrir);
      dom.addEventListener("dblclick", abrir);
      let atual = node;
      return {
        dom,
        update(n) {
          if (n.type !== atual.type) return false;
          atual = n;
          pintar(n);
          return true;
        },
        stopEvent: (e) => e.target === botao,
        ignoreMutation: () => true,
      };
    };
  },
});

export const MarcaPagina = Node.create({
  name: "pb",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { n: attr("n", "data-n"), facs: attr("facs", "data-facs") };
  },
  parseHTML() {
    return [{ tag: 'span[data-tei="pb"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-tei": "pb", contenteditable: "false" }, HTMLAttributes)];
  },
});

// Componente semântico: o ∗ de divisão de assunto do original (<anchor type="asterisco"/>).
export const Asterisco = Node.create({
  name: "asterisco",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  parseHTML() {
    return [{ tag: 'span[data-tei="anchor"]' }];
  },
  renderHTML() {
    return ["span", { "data-tei": "anchor", "data-type": "asterisco", contenteditable: "false" }];
  },
});

export const ParagrafoNota = Node.create({
  name: "paragrafoNota",
  content: "(text|pb|asterisco|fwInline)*",
  addAttributes() {
    return {};
  },
  parseHTML() {
    return [{ tag: 'span[data-tei="note-p"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-tei": "note-p" }, HTMLAttributes), 0];
  },
});

export const Nota = Node.create({
  name: "nota",
  group: "inline",
  inline: true,
  content: "paragrafoNota+",
  isolating: true,
  addAttributes() {
    return { n: attr("n", "data-n"), xmlid: attr("xmlid", "data-xmlid") };
  },
  parseHTML() {
    return [{ tag: 'span[data-tei="note"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-tei": "note" }, HTMLAttributes), 0];
  },
});

export const CabecalhoInline = Node.create({
  name: "fwInline",
  group: "inline",
  inline: true,
  content: "(text|pb)*",
  parseHTML() {
    return [{ tag: 'span[data-tei="fw"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-tei": "fw" }, HTMLAttributes), 0];
  },
});

// ---------------------------------------------------------------- marcas
// A ordem de declaração define o aninhamento na saída (a primeira fica por fora).
export const Negrito = Mark.create({
  name: "negrito",
  parseHTML() {
    return [{ tag: "b" }, { tag: "strong" }];
  },
  renderHTML() {
    return ["b", 0];
  },
  addKeyboardShortcuts() {
    return { "Mod-b": () => this.editor.commands.toggleMark(this.name) };
  },
});

export const Italico = Mark.create({
  name: "italico",
  parseHTML() {
    return [{ tag: "i" }, { tag: "em" }];
  },
  renderHTML() {
    return ["i", 0];
  },
  addKeyboardShortcuts() {
    return { "Mod-i": () => this.editor.commands.toggleMark(this.name) };
  },
});

export const Versalete = Mark.create({
  name: "versalete",
  parseHTML() {
    return [{ tag: 'span[data-tei="hi"][data-rend="sc"]' }];
  },
  renderHTML() {
    return ["span", { "data-tei": "hi", "data-rend": "sc" }, 0];
  },
});

export const Latim = Mark.create({
  name: "latim",
  addAttributes() {
    return { lang: { default: "la", parseHTML: (el) => el.getAttribute("lang") || "la" } };
  },
  parseHTML() {
    return [{ tag: 'span[data-tei="foreign"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-tei": "foreign" }, HTMLAttributes), 0];
  },
});

export const Rotulo = Mark.create({
  name: "rotulo",
  parseHTML() {
    return [{ tag: 'span[data-tei="label"]' }];
  },
  renderHTML() {
    return ["span", { "data-tei": "label" }, 0];
  },
});

// Ordem importa: o primeiro nó do grupo "bloco" é o bloco padrão (Enter no fim de um bloco).
export const nosDoEsquema = [
  Paragrafo, Titulo, Sumario, ParagrafoSumario, Cabecalho, Marco,
  MarcaPagina, Asterisco, Nota, ParagrafoNota, CabecalhoInline,
];
export const marcasDoEsquema = [Negrito, Italico, Versalete, Latim, Rotulo];
