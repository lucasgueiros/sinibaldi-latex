// Esquema ProseMirror/TipTap que espelha EXATAMENTE o dialeto HTML de obra/tei.py
// (fragmento_para_html / html_para_blocos). Nada fora dele existe no editor.
//
//   bloco (grupo "bloco", filhos diretos do documento)
//     marco     div[data-tei=milestone][data-unit][data-n][data-xmlid]   (átomo)
//     titulo    h3[data-tei=head][data-type=rotulo?]
//     paragrafo p[data-tei=p][data-type?][data-xmlid?]
//     sumario   div[data-tei=argument] > p[data-xmlid?]                  (argPara+)
//     cabecalho p[data-tei=fw]
//     gravura   figure[data-tei=figure][data-xmlid][data-url][data-width] > img + figcaption >
//                 div[data-parte=legenda] + div[data-parte=detalhes]   (gravuraLegenda/gravuraDetalhes: text*)
//   inline
//     pb        span[data-tei=pb][data-n][data-facs]                     (átomo)
//     asterisco span[data-tei=anchor][data-type=asterisco]               (átomo; vale também em nota)
//     nota      span[data-tei=note][data-n][data-xmlid] > span[data-tei=note-p]+
//     fwInline  span[data-tei=fw]
//   marcas: citacao q[data-tei=quote][data-type][data-xmlid|data-corresp] (a mais externa),
//           bibl cite[data-tei=bibl][data-corresp] (referência do autor),
//           negrito <b>, italico <i>, versalete span[data-tei=hi][data-rend=sc],
//           latim span[data-tei=foreign][lang], rotulo span[data-tei=label]
//   A citação é uma MARCA (não um nó) para poder cobrir texto com itálico, notas e marcas de
//   página no meio. Segmentos da mesma citação têm atributos diferentes (o 1º tem xmlid, os outros
//   corresp) e por isso continuam elementos separados. As aspas vêm do CSS, não do texto.
//
// Todo bloco carrega data-bloco / data-versao (identidade e versão no servidor).
import { Node, Mark, mergeAttributes } from "@tiptap/core";
import { NodeSelection, TextSelection } from "@tiptap/pm/state";

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

// Componente semântico: gravura recortada do fac-símile
//   <figure><graphic url="…#xywh=…"/><head>legenda</head><p>detalhes</p></figure>.
// A imagem é só apresentação (src vem do servidor ou de quem a inseriu). O conteúdo editável são dois
// filhos sempre presentes: a legenda principal ("FIGURA VIII. — Côrte vertical…") e os detalhes, em
// corpo menor ("A, hemispherio esquerdo; — B, …"); vazios, somem no TEI.
const LARGURAS_GRAVURA = [["", "100%"], ["75%", "75%"], ["60%", "60%"], ["50%", "50%"], ["40%", "40%"], ["33%", "33%"], ["25%", "25%"]];
const MARCAS_LEGENDA = "negrito italico versalete latim rotulo"; // = INLINE_EM_LEGENDA de obra/esquema.py
const PARTES_GRAVURA = { legenda: 0, detalhes: 1 };

const parteDaGravura = (name, parte) => Node.create({
  name,
  content: "text*",
  marks: MARCAS_LEGENDA,
  defining: true,
  parseHTML() {
    return [{ tag: `div[data-parte="${parte}"]`, priority: 60 }];
  },
  renderHTML() {
    return ["div", { "data-parte": parte }, 0];
  },
});
export const GravuraLegenda = parteDaGravura("gravuraLegenda", "legenda");
export const GravuraDetalhes = parteDaGravura("gravuraDetalhes", "detalhes");

/** Cria o nó gravura com legenda e detalhes (strings simples ou Fragment/array de nós de texto). */
export function criarGravura(S, attrs, legenda = "", detalhes = "") {
  const filho = (tipo, v) => S.nodes[tipo].create(null, typeof v === "string" ? (v.trim() ? S.text(v.trim()) : null) : v);
  return S.nodes.gravura.create(attrs, [filho("gravuraLegenda", legenda || ""), filho("gravuraDetalhes", detalhes || "")]);
}

// Texto (com as marcas que a legenda aceita) de [from, to): só nós de texto; átomos e notas ficam onde
// estão. Devolve {nos, faixas, blocos}: os pedaços (um espaço entre blocos), as faixas a apagar e as
// posições dos blocos de topo tocados.
function textoEntre(doc, from, to, tipoDestino) {
  const S = tipoDestino.schema;
  const nos = [];
  const faixas = [];
  const blocos = [];
  let blocoAtual = null;
  doc.nodesBetween(from, to, (n, p, pai) => {
    if (pai === doc) blocos.push(p);
    if (n.isText) {
      const a = Math.max(from, p);
      const b = Math.min(to, p + n.nodeSize);
      if (b <= a) return false;
      const bloco = doc.resolve(a).before(1);
      const pedaco = n.cut(a - p, b - p).mark(n.marks.filter((m) => tipoDestino.allowsMarkType(m.type)));
      if (blocoAtual !== null && bloco !== blocoAtual && nos.length) {
        // fim de linha do OCR: «cere-» + «bello» -> «cerebello»; senão, um espaço entre os blocos
        const ult = nos[nos.length - 1];
        if (/\p{Ll}-\s*$/u.test(ult.text) && /^\p{Ll}/u.test(pedaco.text)) {
          nos[nos.length - 1] = S.text(ult.text.replace(/-\s*$/, ""), ult.marks);
        } else nos.push(S.text(" "));
      }
      blocoAtual = bloco;
      nos.push(pedaco);
      faixas.push([a, b]);
      return false;
    }
    return !n.isInline; // pb, asterisco, nota (e o texto dentro dela) ficam no texto
  });
  // apara as pontas
  const aparar = (i, re) => {
    while (nos.length) {
      const k = i < 0 ? nos.length - 1 : 0;
      const t = nos[k].text.replace(re, "");
      if (t) {
        nos[k] = S.text(t, nos[k].marks);
        return;
      }
      nos.splice(k, 1);
    }
  };
  aparar(0, /^\s+/);
  aparar(-1, /\s+$/);
  return { nos, faixas, blocos };
}

/**
 * Traz para a legenda (`parte` = "legenda") ou para os detalhes ("detalhes") da gravura em `pos` o
 * texto que vem depois dela: a seleção, se houver uma seleção de texto depois da gravura; senão, o
 * bloco de texto seguinte inteiro. O texto sai do lugar de origem (blocos esvaziados são removidos;
 * marcas de página e notas ficam). Devolve uma mensagem de erro ou null.
 */
export function puxarParaGravura(editor, pos, parte) {
  const { state, view } = editor;
  const fig = state.doc.nodeAt(pos);
  if (!fig || fig.type.name !== "gravura") return "Gravura não encontrada.";
  const fim = pos + fig.nodeSize;
  const sel = state.selection;
  let from;
  let to;
  if (!sel.empty && sel.from >= fim && !(sel instanceof NodeSelection)) {
    from = sel.from;
    to = sel.to;
  } else {
    const prox = fim < state.doc.content.size ? state.doc.nodeAt(fim) : null;
    if (!prox || !prox.isTextblock) return "Não há parágrafo logo depois da gravura (selecione o texto a trazer).";
    from = fim + 1;
    to = fim + 1 + prox.content.size;
  }
  const idx = PARTES_GRAVURA[parte];
  const destino = fig.child(idx);
  const { nos, faixas, blocos } = textoEntre(state.doc, from, to, destino.type);
  if (!nos.length) return "Nada a trazer: o trecho não tem texto.";

  const tr = state.tr;
  for (const [a, b] of faixas.slice().reverse()) tr.delete(a, b);
  // blocos que ficaram vazios (ou só com espaços) somem
  for (const p of blocos.slice().reverse()) {
    const m = tr.mapping.map(p);
    const n = tr.doc.nodeAt(m);
    let soTexto = true;
    if (n) n.forEach((c) => { if (!c.isText) soTexto = false; });
    if (n && n.isTextblock && soTexto && !n.textContent.trim()) {
      tr.delete(m, m + n.nodeSize);
    }
  }
  // fim do filho de destino (as remoções são todas depois da gravura: posições dela não mudam)
  let p = pos + 1;
  for (let i = 0; i < idx; i++) p += fig.child(i).nodeSize;
  let fimDestino = p + 1 + destino.content.size;
  const S = state.schema;
  let conteudo = nos;
  if (destino.content.size) {
    const hifen = destino.textContent.match(/\p{Ll}(-\s*)$/u);
    if (hifen && /^\p{Ll}/u.test(nos[0].text)) {  // «cere-» já na legenda + «bello» que chega
      tr.delete(fimDestino - hifen[1].length, fimDestino);
      fimDestino -= hifen[1].length;
    } else if (!/\s$/.test(destino.textContent)) conteudo = [S.text(" "), ...nos];
  }
  tr.insert(fimDestino, conteudo);
  const depois = fimDestino + conteudo.reduce((s, n) => s + n.nodeSize, 0);
  tr.setSelection(TextSelection.create(tr.doc, depois));
  view.dispatch(tr.scrollIntoView());
  editor.commands.focus();
  return null;
}

export const Gravura = Node.create({
  name: "gravura",
  group: "bloco",
  content: "gravuraLegenda gravuraDetalhes",
  defining: true,
  isolating: true,
  priority: 1000,
  addAttributes() {
    return {
      ...attrsBloco(),
      xmlid: attr("xmlid", "data-xmlid"),
      url: attr("url", "data-url"),
      width: attr("width", "data-width"),
      src: {
        default: "",
        parseHTML: (el) => {
          const img = el.querySelector("img");
          return img ? img.getAttribute("src") || "" : "";
        },
        renderHTML: () => ({}),
      },
    };
  },
  parseHTML() {
    // figcaption sem data-parte (HTML antigo/colado): o texto solto cai na legenda
    return [{ tag: 'figure[data-tei="figure"]', contentElement: "figcaption", priority: 60 }];
  },
  renderHTML({ node, HTMLAttributes }) {
    const img = { src: node.attrs.src || "", alt: "Gravura", "data-tei": "graphic", draggable: "false" };
    if (node.attrs.width) img.style = `width: ${node.attrs.width}`;
    return ["figure", mergeAttributes({ "data-tei": "figure" }, HTMLAttributes), ["img", img], ["figcaption", 0]];
  },
  addKeyboardShortcuts() {
    const parte = (state) => {
      const n = state.selection.$from.parent.type.name;
      return n === "gravuraLegenda" ? "legenda" : n === "gravuraDetalhes" ? "detalhes" : null;
    };
    return {
      // Enter na legenda passa o resto dela (do cursor em diante) para o início dos detalhes e põe o
      // cursor lá; nos detalhes, abre um parágrafo depois da gravura (nunca a divide: o xml:id é único).
      Enter: ({ editor }) => {
        const { state, view } = editor;
        const qual = parte(state);
        if (!qual) return false;
        const $f = state.selection.$from;
        if (qual === "legenda") {
          // o que está depois do cursor passa para o início dos detalhes
          const tr = state.tr;
          if (!state.selection.empty) tr.deleteSelection();
          const $c = tr.selection.$from;
          const resto = [];
          tr.doc.slice($c.pos, $c.end()).content.forEach((c) => resto.push(c));
          if (resto.length) tr.delete($c.pos, $c.end());
          // espaços nas pontas: no fim da legenda e no início do resto
          const $l = tr.doc.resolve($c.pos);
          const antes = $l.parent.textContent.match(/\s+$/);
          if (antes) tr.delete($l.end() - antes[0].length, $l.end());
          while (resto.length && !resto[0].text.replace(/^\s+/, "")) resto.shift();
          if (resto.length) resto[0] = state.schema.text(resto[0].text.replace(/^\s+/, ""), resto[0].marks);
          const inicioDet = tr.doc.resolve(tr.mapping.map($c.pos)).after() + 1;
          const det = tr.doc.resolve(inicioDet).parent;
          if (resto.length) {
            const ultimo = resto[resto.length - 1];
            if (det.content.size && !/^\s/.test(det.textContent) && !/\s$/.test(ultimo.text)) resto.push(state.schema.text(" "));
            tr.insert(inicioDet, resto);
          }
          tr.setSelection(TextSelection.create(tr.doc, inicioDet));
          view.dispatch(tr.scrollIntoView());
          return true;
        }
        const fim = $f.after(1);
        const tr = state.tr.insert(fim, state.schema.nodes.paragrafo.create());
        tr.setSelection(TextSelection.create(tr.doc, fim + 1));
        view.dispatch(tr.scrollIntoView());
        return true;
      },
      // Backspace no início dos detalhes volta ao fim da legenda; no início da legenda seleciona a
      // gravura (nada se funde com o bloco anterior nem entre as partes).
      Backspace: ({ editor }) => {
        const { state, view } = editor;
        const { selection: sel } = state;
        const qual = parte(state);
        if (!qual || !sel.empty || sel.$from.parentOffset !== 0) return false;
        if (qual === "detalhes") {
          view.dispatch(state.tr.setSelection(TextSelection.create(state.doc, sel.$from.before() - 1)));
          return true;
        }
        view.dispatch(state.tr.setSelection(NodeSelection.create(state.doc, sel.$from.before(1))));
        return true;
      },
    };
  },
  addNodeView() {
    return ({ node, editor, getPos }) => {
      const dom = document.createElement("figure");
      dom.className = "sn-gravura";
      dom.setAttribute("data-tei", "figure");
      const barra = document.createElement("div");
      barra.className = "sn-gravura-barra";
      barra.contentEditable = "false";
      const rotulo = document.createElement("span");
      rotulo.textContent = "Gravura";
      const sel = document.createElement("select");
      sel.className = "sn-select";
      sel.title = "Largura da gravura (em relação à largura do texto)";
      for (const [v, r] of LARGURAS_GRAVURA) {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = r;
        sel.appendChild(o);
      }
      const botoes = [["legenda", "↥ Legenda"], ["detalhes", "↥ Detalhes"]].map(([parte, texto]) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "sn-gravura-puxar";
        b.textContent = texto;
        b.title = `Trazer para ${parte === "legenda" ? "a legenda" : "os detalhes da legenda"} o texto depois da gravura: `
          + "a seleção, se houver; senão, o parágrafo seguinte inteiro";
        // mousedown não tira o foco nem a seleção do editor
        b.addEventListener("mousedown", (e) => e.preventDefault());
        b.addEventListener("click", () => {
          const pos = getPos();
          if (typeof pos !== "number" || !editor.isEditable) return;
          const erro = puxarParaGravura(editor, pos, parte);
          if (erro) {
            b.title = erro;
            barra.dataset.erro = erro;
            barra.classList.add("sn-gravura-erro");
            setTimeout(() => barra.classList.remove("sn-gravura-erro"), 2500);
          }
        });
        return b;
      });
      const ident = document.createElement("span");
      ident.className = "sn-marco-id";
      barra.append(rotulo, sel, ...botoes, ident);
      const img = document.createElement("img");
      img.alt = "Gravura";
      img.draggable = false;
      img.contentEditable = "false";
      const cap = document.createElement("figcaption");
      dom.append(barra, img, cap);
      let atual = node;
      const pintar = (n) => {
        if (img.getAttribute("src") !== (n.attrs.src || "")) img.setAttribute("src", n.attrs.src || "");
        img.style.width = n.attrs.width || "";
        if (!LARGURAS_GRAVURA.some(([v]) => v === (n.attrs.width || ""))) {
          const o = document.createElement("option");
          o.value = o.textContent = n.attrs.width;
          sel.appendChild(o);
        }
        sel.value = n.attrs.width || "";
        ident.textContent = n.attrs.xmlid || "";
        dom.classList.toggle("sn-gravura-sem-legenda", !n.childCount || n.child(0).content.size === 0);
        dom.classList.toggle("sn-gravura-sem-detalhes", n.childCount < 2 || n.child(1).content.size === 0);
        sel.disabled = !editor.isEditable;
        for (const b of botoes) b.disabled = !editor.isEditable;
      };
      pintar(node);
      sel.addEventListener("change", () => {
        const pos = getPos();
        if (typeof pos !== "number") return;
        editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, null, { ...atual.attrs, width: sel.value || null }));
      });
      return {
        dom,
        contentDOM: cap,
        update(n) {
          if (n.type !== atual.type) return false;
          atual = n;
          pintar(n);
          return true;
        },
        stopEvent: (e) => barra.contains(e.target),
        ignoreMutation: (m) => m.type !== "selection" && !cap.contains(m.target),
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
export const Citacao = Mark.create({
  name: "citacao",
  inclusive: false,   // digitar logo depois do fim não estende a citação
  excludes: "citacao",
  addAttributes() {
    return { tipo: attr("tipo", "data-type"), xmlid: attr("xmlid", "data-xmlid"), corresp: attr("corresp", "data-corresp") };
  },
  parseHTML() {
    return [{ tag: 'q[data-tei="quote"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["q", mergeAttributes({ "data-tei": "quote" }, HTMLAttributes), 0];
  },
});

export const ReferenciaAutor = Mark.create({
  name: "bibl",
  inclusive: false,
  addAttributes() {
    return { corresp: attr("corresp", "data-corresp") };
  },
  parseHTML() {
    return [{ tag: 'cite[data-tei="bibl"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["cite", mergeAttributes({ "data-tei": "bibl" }, HTMLAttributes), 0];
  },
});

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
  Paragrafo, Titulo, Sumario, ParagrafoSumario, Cabecalho, Marco, Gravura, GravuraLegenda, GravuraDetalhes,
  MarcaPagina, Asterisco, Nota, ParagrafoNota, CabecalhoInline,
];
export const marcasDoEsquema = [Citacao, ReferenciaAutor, Negrito, Italico, Versalete, Latim, Rotulo];
