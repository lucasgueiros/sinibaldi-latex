// Componente de editor WYSIWYG (TipTap 2 / ProseMirror) sobre o esquema fechado de esquema.js.
// Ver a API pública documentada em index.js.
import { Editor, Extension, getSchema } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Text from "@tiptap/extension-text";
import History from "@tiptap/extension-history";
import Gapcursor from "@tiptap/extension-gapcursor";
import Dropcursor from "@tiptap/extension-dropcursor";
import { DOMParser as PMDOMParser, Fragment } from "@tiptap/pm/model";
import { EditorState, Plugin, TextSelection, NodeSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import { nosDoEsquema, marcasDoEsquema } from "./esquema.js";
import { dialogo } from "./dialogo.js";
import * as cit from "./citacoes.js";
import { postarJSON } from "./rede.js";

const ESQUEMA_PADRAO = {
  niveis: { anexo: "Anexo", parte: "Parte", seccao: "Secção", capitulo: "Capítulo", artigo: "Artigo", tese: "Tese" },
  tipos_paragrafo: {
    definicao: "Definição", divisao: "Divisão", enunciado: "Tese", argumento: "Argumento",
    objecao: "Objeção", resposta: "Resposta", escolio: "Escólio", corolario: "Corolário", observacao: "Observação",
    "anexo-titulo": "Título no anexo", indice: "Entrada do índice",
  },
  rend: { it: "Itálico", bold: "Negrito", sc: "Versalete" },
  tipos_citacao: { direta: "Citação direta", indireta: "Citação indireta", mencao: "Menção (termo entre aspas)" },
  prefixos_id: { anexo: "anexo", parte: "parte", seccao: "sec", capitulo: "cap", artigo: "art", tese: "t" },
};

// ------------------------------------------------------------ utilidades
function aleatorio(n) {
  const a = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  const buf = new Uint32Array(n);
  (window.crypto || { getRandomValues: (b) => b.forEach((_, i) => (b[i] = Math.random() * 4e9)) }).getRandomValues(buf);
  for (let i = 0; i < n; i++) s += a[buf[i] % a.length];
  return s;
}

function limparBrancos(raiz) {
  // Espaço em branco entre blocos (o servidor separa blocos por \n) não é conteúdo.
  const alvo = (el) =>
    el === raiz || (el.nodeType === 1 && (el.matches('[data-tei="argument"]') || el.matches('[data-tei="note"]')));
  const rec = (el) => {
    for (const c of Array.from(el.childNodes)) {
      if (c.nodeType === 3 && alvo(el) && !c.nodeValue.trim()) el.removeChild(c);
      else if (c.nodeType === 1) rec(c);
    }
  };
  rec(raiz);
}

function htmlParaDoc(schema, html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html || "";
  limparBrancos(tpl.content);
  return PMDOMParser.fromSchema(schema).parse(tpl.content, { preserveWhitespace: "full" });
}

// Seleção inicial segura: cursor de texto no primeiro bloco textual (nunca NodeSelection num marco).
function selecaoInicial(doc) {
  let pos = null;
  doc.descendants((n, p) => {
    if (pos !== null) return false;
    if (n.isTextblock) { pos = p + 1; return false; }
    return true;
  });
  return pos === null ? null : TextSelection.create(doc, pos);
}

const ATOMOS_PROTEGIDOS = ["marco", "pb"];
function atomoSelecionado(state) {
  const sel = state.selection;
  return sel instanceof NodeSelection && ATOMOS_PROTEGIDOS.includes(sel.node.type.name) ? sel.node : null;
}
function intervaloTemMarco(state) {
  const { from, to } = state.selection;
  if (from === to) return false;
  let achou = false;
  state.doc.nodesBetween(from, to, (n) => {
    if (n.type.name === "marco") achou = true;
    return !achou;
  });
  return achou;
}
// Com um marco selecionado, insere um parágrafo vazio depois dele e põe o cursor nele.
function abrirParagrafoDepoisDoMarco(view) {
  const { state } = view;
  const sel = state.selection;
  const fim = sel.to;
  const tr = state.tr.insert(fim, state.schema.nodes.paragrafo.create());
  tr.setSelection(TextSelection.create(tr.doc, fim + 1));
  view.dispatch(tr);
}

function blocosNaSelecao(state) {
  const { from, to } = state.selection;
  const out = [];
  state.doc.forEach((node, offset) => {
    const fim = offset + node.nodeSize;
    if (fim > from && (offset < to || from === to)) out.push({ node, pos: offset });
  });
  return out;
}

function dentroDeNota(state) {
  const { $from } = state.selection;
  for (let d = $from.depth; d > 0; d--) if ($from.node(d).type.name === "nota") return true;
  return false;
}

// ------------------------------------------------------ conversão de bloco
function conteudoAdaptado(content, alvo, S) {
  if (alvo !== "cabecalho") return content;
  const out = [];
  content.forEach((c) => {
    if (c.isText || c.type.name === "pb") out.push(c);
    else if (c.textContent) out.push(S.text(c.textContent));
  });
  return Fragment.from(out);
}

function reconstruirBloco(node, alvo, tipoPar, S) {
  const nome = node.type.name;
  if (nome === "marco" || nome === "gravura") return null;
  const fontes = [];
  if (nome === "sumario") node.forEach((p, _o, i) => fontes.push({ content: p.content, primeiro: i === 0, xmlid: p.attrs.xmlid }));
  else fontes.push({ content: node.content, primeiro: true, xmlid: node.attrs.xmlid });
  const chave = (f) => (f.primeiro ? { dataBloco: node.attrs.dataBloco, dataVersao: node.attrs.dataVersao } : {});
  if (alvo === "sumario") {
    if (nome === "sumario") return null;
    return S.nodes.sumario.create(
      { dataBloco: node.attrs.dataBloco, dataVersao: node.attrs.dataVersao },
      fontes.map((f) => S.nodes.paragrafoSumario.create({ xmlid: nome === "paragrafo" ? f.xmlid : null }, f.content)),
    );
  }
  return fontes.map((f) => {
    const c = conteudoAdaptado(f.content, alvo, S);
    if (alvo === "paragrafo") {
      return S.nodes.paragrafo.create({ ...chave(f), type: tipoPar || null, xmlid: nome === "paragrafo" || nome === "sumario" ? f.xmlid : null }, c);
    }
    if (alvo === "titulo" || alvo === "rotulo") {
      return S.nodes.titulo.create({ ...chave(f), type: alvo === "rotulo" ? "rotulo" : null }, c);
    }
    return S.nodes.cabecalho.create({ ...chave(f) }, c);
  });
}

function converterSelecao(editor, alvo, tipoPar = null) {
  const { state, view } = editor;
  const alvos = blocosNaSelecao(state).filter((b) => b.node.type.name !== "marco");
  if (!alvos.length) return false;
  const tr = state.tr;
  for (const { node, pos } of alvos.slice().reverse()) {
    let novos = reconstruirBloco(node, alvo, tipoPar, state.schema);
    if (!novos) continue;
    tr.replaceWith(pos, pos + node.nodeSize, novos);
  }
  view.dispatch(tr.scrollIntoView());
  return true;
}

function definirTipoParagrafo(editor, tipo) {
  const { state, view } = editor;
  const alvos = blocosNaSelecao(state).filter((b) => !["marco", "gravura"].includes(b.node.type.name));
  if (!alvos.length) return false;
  if (alvos.every((b) => b.node.type.name === "paragrafo")) {
    const tr = state.tr;
    for (const { node, pos } of alvos) tr.setNodeMarkup(pos, null, { ...node.attrs, type: tipo || null });
    view.dispatch(tr);
    return true;
  }
  return converterSelecao(editor, "paragrafo", tipo || null);
}

// ----------------------------------------------------------- barra de ferramentas
function criarBarra(host, editor, cfg, api) {
  const barra = document.createElement("div");
  barra.className = "barra-ferramentas sn-barra";
  barra.setAttribute("role", "toolbar");
  barra.setAttribute("aria-label", "Formatação");
  const esquema = cfg.esquema;
  const itens = []; // {atualizar()}

  const sep = () => {
    const s = document.createElement("span");
    s.className = "sn-sep";
    barra.appendChild(s);
  };
  const botao = (html, titulo, acao, { ativo, desativado, classe } = {}) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ferramenta" + (classe ? " " + classe : "");
    b.innerHTML = html;
    b.title = titulo;
    b.setAttribute("aria-label", titulo);
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", () => {
      if (b.disabled) return;
      acao();
    });
    barra.appendChild(b);
    itens.push({
      atualizar() {
        const on = ativo ? ativo() : false;
        b.classList.toggle("ferramenta-ativa", on);
        b.classList.toggle("ferramenta", !on);
        b.disabled = !editor.isEditable || (desativado ? desativado() : false);
        b.setAttribute("aria-pressed", String(on));
      },
    });
    return b;
  };
  const seletor = (titulo, opcoes, aoEscolher, valorAtual) => {
    const s = document.createElement("select");
    s.className = "sn-select";
    s.title = titulo;
    s.setAttribute("aria-label", titulo);
    for (const [v, r] of opcoes) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = r;
      s.appendChild(o);
    }
    s.addEventListener("change", () => {
      const v = s.value;
      if (v !== "-") aoEscolher(v);
      if (!valorAtual) s.value = "-"; // seletores de ação voltam ao rótulo
      editor.commands.focus();
      itens.forEach((i) => i.atualizar());
    });
    barra.appendChild(s);
    itens.push({
      atualizar() {
        s.disabled = !editor.isEditable;
        if (valorAtual) s.value = valorAtual();
      },
    });
    return s;
  };

  botao("&#8630;", "Desfazer (Ctrl+Z)", () => editor.chain().focus().undo().run(), { desativado: () => !editor.can().undo() });
  botao("&#8631;", "Refazer (Ctrl+Y)", () => editor.chain().focus().redo().run(), { desativado: () => !editor.can().redo() });
  sep();
  const marcas = [
    ["negrito", "<b>N</b>", "Negrito (Ctrl+B)"],
    ["italico", "<i>I</i>", "Itálico (Ctrl+I)"],
    ["versalete", '<span style="font-variant:small-caps">Vs</span>', "Versalete"],
    ["latim", "<i>Lat</i>", "Latim (foreign)"],
    ["rotulo", "Rót", "Rótulo (label): numeração e rótulos inline"],
  ];
  for (const [nome, html, titulo] of marcas) {
    botao(html, titulo, () => editor.chain().focus().toggleMark(nome).run(), { ativo: () => editor.isActive(nome) });
  }
  sep();
  const blocoAtual = () => {
    const bs = blocosNaSelecao(editor.state);
    return bs.length ? bs[0].node : null;
  };
  const opcoesTipo = [["-", "Tipo de parágrafo"], ["", "Parágrafo comum"], ...Object.entries(esquema.tipos_paragrafo)];
  seletor("Tipo do parágrafo", opcoesTipo, (v) => definirTipoParagrafo(editor, v), () => {
    const n = blocoAtual();
    return n && n.type.name === "paragrafo" ? n.attrs.type || "" : "-";
  });
  seletor(
    "Converter o bloco em…",
    [["-", "Converter em…"], ["paragrafo", "Parágrafo"], ["titulo", "Título"], ["rotulo", "Rótulo (título)"], ["sumario", "Sumário"], ["cabecalho", "Cabeçalho corrente"]],
    (v) => converterSelecao(editor, v),
  ).value = "-";
  sep();
  const naCitacao = () => !!cit.marcaNoCursor(editor.state, "citacao");
  const naBibl = () => !!cit.marcaNoCursor(editor.state, "bibl");
  botao("«Cit»", "Citação: marca a seleção (direta, indireta, menção ou continuação de outra); no cursor de uma citação, muda o tipo ou desfaz. Digitar « … » também cria a citação.",
    () => cit.citar(editor, cfg), { ativo: naCitacao, desativado: () => editor.state.selection.empty && !naCitacao() });
  botao("(Ref.)", "Referência do autor: liga o trecho selecionado — ex.: (Sum. Th., I, q. 2) — a uma citação; no cursor de uma referência, desfaz",
    () => cit.referenciar(editor), { ativo: naBibl, desativado: () => editor.state.selection.empty && !naBibl() });
  if (cfg.urlCitacao) {
    botao("Ficha", "Abre a ficha da citação sob o cursor (fonte, páginas, tradução, BibTeX) numa nova aba",
      () => cit.abrirDados(editor, cfg), { desativado: () => !cit.chaveNoCursor(editor.state) });
  }
  if (cfg.urlConverter) {
    botao("Aspas→cit.", "Reconhecer citações: transforma em citação todo trecho entre aspas desta tela (e a referência entre parênteses que vem logo depois). Desfazível com Ctrl+Z.",
      () => api.detectarCitacoes());
  }
  sep();
  botao("Nota", "Inserir nota de rodapé", () => api.inserirNota(), { desativado: () => dentroDeNota(editor.state) });
  botao("[pág.]", "Inserir marca de página", () => api.inserirMarcaPagina());
  botao("∗", "Inserir asterisco de divisão (também dentro de nota)", () => api.inserirAsterisco());
  sep();
  seletor(
    "Iniciar divisão: insere o marco antes do bloco atual",
    [["-", "Iniciar divisão ▾"], ...Object.entries(esquema.niveis)],
    (v) => api.iniciarDivisao(v),
  );

  const aviso = document.createElement("span");
  aviso.className = "sn-aviso";
  aviso.setAttribute("role", "status");
  barra.appendChild(aviso);
  host.appendChild(barra);
  const atualizar = () => itens.forEach((i) => i.atualizar());
  let relogio = null;
  const avisar = (txt) => {
    aviso.textContent = txt || "";
    clearTimeout(relogio);
    if (txt) relogio = setTimeout(() => (aviso.textContent = ""), 9000);
  };
  return { atualizar, barra, avisar };
}

// ------------------------------------------------------------------ montar
export function montar(elemento, opcoes = {}) {
  const cfg = { esquema: opcoes.esquema || ESQUEMA_PADRAO, ...opcoes };
  cfg.esquema = { ...ESQUEMA_PADRAO, ...(opcoes.esquema || {}) };

  const estado = { baseline: null, ultimoBloco: undefined, destruido: false };
  let colando = false;

  const Sinibaldi = Extension.create({
    name: "sinibaldi",
    addStorage() {
      return { editarMarco: null, decorarBloco: null };
    },
    addProseMirrorPlugins() {
      const st = this.storage;
      return [
        new Plugin({
          props: {
            // Marco/pb selecionados nunca são substituídos por digitação ou colagem.
            handleTextInput(view, _from, _to, texto) {
              if (!colando && cit.regraDeDigitacao(view, texto, cfg)) return true;
              const at = atomoSelecionado(view.state);
              if (at) {
                if (at.type.name === "marco") {
                  abrirParagrafoDepoisDoMarco(view);
                  view.dispatch(view.state.tr.insertText(texto));
                }
                return true;
              }
              return intervaloTemMarco(view.state); // seleção de vários blocos com marco: ignora a tecla
            },
            handleKeyDown(view, ev) {
              if (ev.key !== "Backspace" && ev.key !== "Delete") return false;
              if (ev.ctrlKey || ev.metaKey || ev.altKey) return false;
              const { selection: sel, doc } = view.state;
              if (!sel.empty || sel.$from.depth !== 1 || !sel.$from.parent.isTextblock) return false;
              const $f = sel.$from;
              let alvo = null;
              if (ev.key === "Backspace" && $f.parentOffset === 0 && $f.index(0) > 0) alvo = doc.child($f.index(0) - 1) && { n: doc.child($f.index(0) - 1), pos: $f.before(1) - doc.child($f.index(0) - 1).nodeSize };
              if (ev.key === "Delete" && $f.parentOffset === $f.parent.content.size && $f.index(0) < doc.childCount - 1) alvo = { n: doc.child($f.index(0) + 1), pos: $f.after(1) };
              if (!alvo || !["marco", "gravura"].includes(alvo.n.type.name)) return false;
              view.dispatch(view.state.tr.setSelection(NodeSelection.create(doc, alvo.pos)).scrollIntoView());
              return true; // 1º toque seleciona o marco/gravura; só um segundo toque (com ele selecionado) o remove
            },
            decorations(state) {
              if (!st.decorarBloco) return null;
              const decos = [];
              state.doc.forEach((node, off) => {
                const d = st.decorarBloco(node.attrs.dataBloco);
                if (d) decos.push(Decoration.node(off, off + node.nodeSize, d));
              });
              return DecorationSet.create(state.doc, decos);
            },
          },
        }),
      ];
    },
  });

  const extensoes = [
    Document.extend({ content: "bloco+" }),
    Text,
    ...nosDoEsquema,
    ...marcasDoEsquema,
    History,
    Gapcursor,
    Dropcursor,
    Sinibaldi,
  ];
  const schema = getSchema(extensoes);

  elemento.classList.add("sn-componente");
  const barraHost = document.createElement("div");
  const area = document.createElement("div");
  area.className = "sn-area";
  elemento.append(barraHost, area);

  const docInicial = htmlParaDoc(schema, cfg.html || "");
  const editor = new Editor({
    element: area,
    extensions: extensoes,
    content: docInicial.toJSON(),
    editable: !cfg.somenteLeitura,
    editorProps: {
      attributes: { class: "obra obra-edicao sn-editor", spellcheck: "false", lang: "pt" },
      transformPastedHTML: (html) => html.replace(/\sdata-(bloco|versao|xmlid)="[^"]*"/g, ""),
      handlePaste(view, event) {
        const at = atomoSelecionado(view.state);
        if (at) {
          if (at.type.name === "marco") abrirParagrafoDepoisDoMarco(view);
          else return true; // pb: ignora a colagem
          // com o cursor no parágrafo novo, segue o fluxo normal abaixo
        } else if (intervaloTemMarco(view.state)) return true;
        if (colando) return false; // pasteText volta a chamar handlePaste: deixa o padrão agir
        const cd = event.clipboardData;
        if (!cd) return false;
        const html = cd.getData("text/html");
        const texto = cd.getData("text/plain");
        // Só o que veio deste editor (data-tei) mantém estrutura; o resto (Word, web) vira texto simples.
        if (html && !/data-tei=/.test(html) && texto) {
          colando = true;
          try {
            if (view.pasteText) view.pasteText(texto, event);
            else view.dispatch(view.state.tr.insertText(texto));
          } finally {
            colando = false;
          }
          return true;
        }
        return false;
      },
    },
  });
  {
    const si = selecaoInicial(editor.state.doc);
    if (si) editor.view.dispatch(editor.state.tr.setSelection(si).setMeta("addToHistory", false));
  }
  estado.baseline = editor.state.doc;
  editor.storage.sinibaldi.decorarBloco = cfg.decorarBloco || null;

  // ---- comandos de inserção
  const api = {
    async inserirNota() {
      const { state, view } = editor;
      if (dentroDeNota(state) || !editor.isEditable) return;
      const { $to } = state.selection;
      if (!$to.parent.inlineContent) return;
      let antes = 0;
      state.doc.descendants((n, pos) => {
        if (n.type.name === "nota" && pos < $to.pos) antes++;
      });
      const S = state.schema;
      const nota = S.nodes.nota.create({ n: String(antes + 1) }, [S.nodes.paragrafoNota.create()]);
      const tr = state.tr.insert($to.pos, nota);
      tr.setSelection(TextSelection.near(tr.doc.resolve($to.pos + 2)));
      view.dispatch(tr.scrollIntoView());
      editor.commands.focus();
    },
    inserirAsterisco() {
      const { state, view } = editor;
      if (!editor.isEditable || !state.selection.$to.parent.inlineContent) return;
      view.dispatch(state.tr.replaceSelectionWith(state.schema.nodes.asterisco.create()));
      editor.commands.focus();
    },
    async inserirMarcaPagina() {
      const { state, view } = editor;
      if (!editor.isEditable || !state.selection.$to.parent.inlineContent) return;
      const base = cfg.pagina || {};
      const r = await dialogo({
        titulo: "Inserir marca de página",
        campos: [{ nome: "n", rotulo: "Número da página (scan)", valor: base.n != null ? String(base.n) : "", obrigatorio: true }],
        validar: (v) => (/^-?\d+$/.test(v.n) ? null : "Informe um inteiro (o valor de <pb n>)."),
      });
      if (!r) return;
      const facs = cfg.facsDe ? cfg.facsDe(Number(r.n)) : `paginas/${String(Math.abs(Number(r.n))).padStart(4, "0")}.png`;
      const pb = state.schema.nodes.pb.create({ n: r.n, facs });
      view.dispatch(editor.state.tr.replaceSelectionWith(pb));
      editor.commands.focus();
    },
    async iniciarDivisao(unit) {
      const { state, view } = editor;
      if (!editor.isEditable) return;
      const nivel = cfg.esquema.niveis[unit] || unit;
      const existentes = new Set();
      state.doc.descendants((n) => {
        if (n.attrs && n.attrs.xmlid) existentes.add(n.attrs.xmlid);
      });
      const pre = (cfg.esquema.prefixos_id || {})[unit] || unit;
      let sugestao;
      do sugestao = `${cfg.prefixoId || ""}${pre}-${aleatorio(5)}`;
      while (existentes.has(sugestao));
      const r = await dialogo({
        titulo: `Iniciar ${nivel}`,
        campos: [
          { nome: "n", rotulo: "Número (n)", valor: "", ajuda: "Opcional: o número da divisão, como impresso (ex.: 27, II)." },
          { nome: "xmlid", rotulo: "xml:id", valor: sugestao, obrigatorio: true, ajuda: "Único em toda a edição." },
        ],
        confirmar: "Inserir marco",
        validar: (v) =>
          !/^[A-Za-z_][\w.\-]*$/.test(v.xmlid) ? "xml:id inválido (letras, dígitos, ponto, hífen e _; não começa por dígito)." :
          existentes.has(v.xmlid) ? "Este xml:id já existe nesta página." : null,
      });
      if (!r) return;
      const S = state.schema;
      const marco = S.nodes.marco.create({ unit, n: r.n || null, xmlid: r.xmlid });
      const sel = editor.state.selection;
      const pos = sel.$from.depth === 0 ? sel.from : sel.$from.before(1);
      view.dispatch(editor.state.tr.insert(pos, marco).scrollIntoView());
      editor.commands.focus();
    },
    /** Insere uma gravura ({xmlid, url, width, legenda, src}) antes do bloco atual se o cursor está no
     *  início dele, senão depois. Devolve false se o xml:id já existe nesta tela. */
    inserirGravura({ xmlid, url, width = null, legenda = "", src = "" }) {
      const { state, view } = editor;
      if (!editor.isEditable) return false;
      let repetido = false;
      state.doc.descendants((n) => {
        if (n.attrs && n.attrs.xmlid === xmlid) repetido = true;
      });
      if (repetido) return false;
      const S = state.schema;
      const leg = (legenda || "").trim();
      const node = S.nodes.gravura.create({ xmlid, url, width: width || null, src }, leg ? S.text(leg) : null);
      const { $from } = state.selection;
      let pos;
      if ($from.depth === 0) pos = state.selection.to;
      else pos = $from.parentOffset === 0 && $from.depth === 1 ? $from.before(1) : $from.after(1);
      const tr = state.tr.insert(pos, node);
      tr.setSelection(NodeSelection.create(tr.doc, pos));
      view.dispatch(tr.scrollIntoView());
      editor.commands.focus();
      return true;
    },
    async editarMarco(pos) {
      const node = editor.state.doc.nodeAt(pos);
      if (!node || node.type.name !== "marco" || !editor.isEditable) return;
      const r = await dialogo({
        titulo: "Marco de divisão",
        campos: [
          { nome: "unit", rotulo: "Unidade", tipo: "select", valor: node.attrs.unit, opcoes: Object.entries(cfg.esquema.niveis) },
          { nome: "n", rotulo: "Número (n)", valor: node.attrs.n || "" },
          { nome: "xmlid", rotulo: "xml:id", valor: node.attrs.xmlid || "" },
        ],
        validar: (v) => (v.xmlid && !/^[A-Za-z_][\w.\-]*$/.test(v.xmlid) ? "xml:id inválido." : null),
      });
      if (!r) return;
      const atual = editor.state.doc.nodeAt(pos);
      if (!atual || atual.type.name !== "marco") return;
      editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, null, { ...atual.attrs, unit: r.unit, n: r.n || null, xmlid: r.xmlid || null }));
    },
  };
  api.detectarCitacoes = async () => {
    if (!editor.isEditable) return;
    const r = await cit.detectar(editor, cfg, htmlParaDoc);
    const msg = r.erros.length ? "Não foi possível reconhecer: " + r.erros.join(" ") : r.relatorio;
    if (barra) barra.avisar(msg);
    return r;
  };
  editor.storage.sinibaldi.editarMarco = (pos) => api.editarMarco(pos);

  let barra = null;
  if (cfg.barra !== false) barra = criarBarra(barraHost, editor, cfg, api);
  else barraHost.remove();

  // ---- eventos
  const notificar = () => {
    if (cfg.aoMudar) cfg.aoMudar(sujo(), publico);
  };
  const blocoAtivo = () => {
    const bs = blocosNaSelecao(editor.state);
    const sel = editor.state.selection;
    const { $from } = sel;
    const topo = $from.depth >= 1 ? $from.node(1) : sel.node || (bs[0] && bs[0].node) || null;
    return topo ? topo.attrs.dataBloco || null : null;
  };
  editor.on("transaction", () => {
    if (barra) barra.atualizar();
    if (cfg.aoBlocoAtivo) {
      const id = blocoAtivo();
      if (id !== estado.ultimoBloco) {
        estado.ultimoBloco = id;
        cfg.aoBlocoAtivo(id);
      }
    }
  });
  editor.on("update", notificar);
  if (barra) barra.atualizar();

  const sujo = () => !editor.state.doc.eq(estado.baseline);

  const publico = {
    editor,
    schema,
    /** HTML do dialeto de tei.py, pronto para `POST …/converter/` ou `…/gravar/` (formato "html"). */
    obterHtml: () => editor.getHTML(),
    /** Substitui o conteúdo. `limpo` (padrão true) também redefine a base de comparação de `sujo()`. Zera o desfazer. */
    definirHtml(html, { limpo = true } = {}) {
      const doc = htmlParaDoc(schema, html);
      const novo = EditorState.create({ schema, doc, plugins: editor.state.plugins, selection: selecaoInicial(doc) || undefined });
      editor.view.updateState(novo);
      if (limpo) estado.baseline = editor.state.doc;
      if (barra) barra.atualizar();
      estado.ultimoBloco = undefined;
      notificar();
    },
    sujo,
    /** Gravura recortada do fac-símile (ver api.inserirGravura). */
    inserirGravura: (g) => api.inserirGravura(g),
    /** Declara o conteúdo atual como "gravado". */
    marcarLimpo() {
      estado.baseline = editor.state.doc;
      notificar();
    },
    somenteLeitura(v) {
      editor.setEditable(!v);
      if (barra) barra.atualizar();
    },
    /** Força nova avaliação das decorações (p.ex. depois de mudar o mapa de informações dos blocos). */
    redecorar() {
      editor.view.dispatch(editor.state.tr.setMeta("sn-redecorar", true));
    },
    focar: () => editor.commands.focus(),
    /** Reconhece as citações pelas aspas (servidor). -> {relatorio, erros} */
    detectarCitacoes: () => api.detectarCitacoes(),
    /** Converte o conteúdo atual via servidor: `{xml, erros}` (usa `urlConverter`). */
    async obterXml() {
      const r = await postarJSON(cfg.urlConverter, { de: "html", conteudo: editor.getHTML() }, cfg.csrf);
      return r.dados;
    },
    async definirXml(xml, opts) {
      const r = await postarJSON(cfg.urlConverter, { de: "xml", conteudo: xml }, cfg.csrf);
      if (r.dados.erros && r.dados.erros.length) return r.dados;
      publico.definirHtml(r.dados.html, opts);
      return r.dados;
    },
    destruir() {
      estado.destruido = true;
      editor.destroy();
      elemento.classList.remove("sn-componente");
      elemento.textContent = "";
    },
  };
  return publico;
}
