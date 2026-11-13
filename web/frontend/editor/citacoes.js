// Comandos de citação do editor (marcas `citacao` e `bibl` de esquema.js).
//
//   citar(editor, cfg)          seleção -> citação (nova ou continuação de outra); no cursor de uma
//                               citação: mudar o tipo ou remover a marca (devolve as aspas ao texto)
//   referenciar(editor)         seleção -> referência do autor ligada a uma citação; no cursor: remove
//   abrirDados(editor, cfg)     abre a ficha da citação (cfg.urlCitacao, "__ID__" = xml:id)
//   detectar(editor, cfg)       reconhecimento automático pelo servidor (obra/citacoes.py, via converter)
//   regraDeDigitacao(view, ch, cfg)  ao digitar » ou ” que fecha um « / “ do mesmo parágrafo,
//                               o trecho vira citação (as aspas saem do texto: quem as desenha é o CSS)
import { TextSelection } from "@tiptap/pm/state";
import { dialogo } from "./dialogo.js";
import { postarJSON } from "./rede.js";

export const TIPOS = [["direta", "Direta (entre aspas)"], ["indireta", "Indireta (paráfrase, sem aspas)"], ["mencao", "Menção (termo entre aspas, sem fonte)"]];
const COM_DADOS = new Set(["direta", "indireta"]);
const PALAVRAS_MENCAO = 4; // igual a obra/citacoes.py
const ASPAS = "«»“”„\"";
const PARES = { "»": "«", "”": "“" };

function aleatorio(n) {
  const a = "abcdefghijklmnopqrstuvwxyz0123456789";
  const buf = new Uint32Array(n);
  window.crypto.getRandomValues(buf);
  return Array.from(buf, (x) => a[x % a.length]).join("");
}

export function chaveDe(attrs) {
  return attrs.xmlid || (attrs.corresp || "").replace(/^#/, "") || null;
}

/** Citações com dados no documento, na ordem: [{xmlid, tipo, texto}]. */
export function citacoesDoDoc(doc) {
  const out = new Map();
  doc.descendants((n) => {
    if (!n.isText) return true;
    const m = n.marks.find((k) => k.type.name === "citacao");
    if (!m) return false;
    const k = chaveDe(m.attrs);
    if (!k) return false;
    if (!out.has(k)) out.set(k, { xmlid: k, tipo: m.attrs.tipo, texto: "" });
    const c = out.get(k);
    if (m.attrs.xmlid) c.tipo = m.attrs.tipo;
    if (c.texto.length < 80) c.texto += n.text;
    return false;
  });
  return Array.from(out.values());
}

function idsDoDoc(doc) {
  const s = new Set();
  doc.descendants((n) => {
    if (n.attrs && n.attrs.xmlid) s.add(n.attrs.xmlid);
    for (const m of n.marks || []) if (m.attrs.xmlid) s.add(m.attrs.xmlid);
  });
  return s;
}

function novoId(doc, prefixo) {
  const usados = idsDoDoc(doc);
  let i;
  do i = `${prefixo || ""}cit-${aleatorio(6)}`;
  while (usados.has(i));
  return i;
}

/** Marca `nome` sob o cursor (ou logo antes dele): {mark, from, to} cobrindo o trecho contínuo. */
export function marcaNoCursor(state, nome) {
  const { $from } = state.selection;
  const pai = $from.parent;
  if (!pai.inlineContent) return null;
  const tipo = state.schema.marks[nome];
  const depois = $from.nodeAfter, antes = $from.nodeBefore;
  const mark = (depois && tipo.isInSet(depois.marks)) || (antes && tipo.isInSet(antes.marks));
  if (!mark) return null;
  const inicio = $from.start();
  const filhos = [];
  pai.forEach((c, off) => filhos.push({ c, de: inicio + off, ate: inicio + off + c.nodeSize }));
  let i = filhos.findIndex((f) => f.de <= $from.pos && $from.pos <= f.ate && mark.isInSet(f.c.marks));
  if (i < 0) return null;
  let a = i, b = i;
  while (a > 0 && mark.isInSet(filhos[a - 1].c.marks)) a--;
  while (b < filhos.length - 1 && mark.isInSet(filhos[b + 1].c.marks)) b++;
  return { mark, from: filhos[a].de, to: filhos[b].ate };
}

/** Faixas de todos os segmentos da citação `chave` no documento. */
function segmentos(doc, chave) {
  const out = [];
  doc.descendants((n, pos) => {
    for (const m of n.marks || []) {
      if (m.type.name === "citacao" && chaveDe(m.attrs) === chave) out.push({ from: pos, to: pos + n.nodeSize, mark: m });
    }
    return true;
  });
  return out;
}

// Tira aspas e espaços das pontas de [from, to); devolve a faixa resultante (posições já mapeadas).
function aparar(tr, from, to) {
  const ch = (p) => tr.doc.textBetween(p, p + 1, "￼", "￼");
  let fim = to;
  while (fim > from && (ASPAS.includes(ch(fim - 1)) || /\s/.test(ch(fim - 1)))) fim--;
  if (fim < to) tr.delete(fim, to);
  let ini = from;
  while (ini < fim && (ASPAS.includes(ch(ini)) || /\s/.test(ch(ini)))) ini++;
  if (ini > from) tr.delete(from, ini);
  return { from, to: fim - (ini - from) };
}

function atributosNovos(state, tipo, continua, cfg) {
  if (continua) {
    const alvo = citacoesDoDoc(state.doc).find((c) => c.xmlid === continua);
    return { tipo: alvo ? alvo.tipo : tipo, xmlid: null, corresp: "#" + continua };
  }
  return { tipo, xmlid: COM_DADOS.has(tipo) ? novoId(state.doc, cfg.prefixoId) : null, corresp: null };
}

export async function citar(editor, cfg) {
  if (!editor.isEditable) return;
  const { state } = editor;
  const S = state.schema;
  const sob = marcaNoCursor(state, "citacao");
  if (state.selection.empty && sob) return editarCitacao(editor, cfg, sob);
  if (state.selection.empty) return;
  const { from, to } = state.selection;
  if (!state.selection.$from.sameParent(state.selection.$to)) {
    await dialogo({ titulo: "Citação", campos: [], confirmar: "Entendi", validar: () => null,
      ajuda: "Uma citação fica dentro de um parágrafo (ou de uma nota). Selecione um trecho de um só parágrafo." });
    return;
  }
  const existentes = citacoesDoDoc(state.doc);
  const r = await dialogo({
    titulo: "Marcar citação",
    campos: [
      { nome: "tipo", rotulo: "Tipo", tipo: "select", valor: "direta", opcoes: TIPOS },
      {
        nome: "continua", rotulo: "Continua a citação…", tipo: "select", valor: "",
        opcoes: [["", "— é uma citação nova —"], ...existentes.map((c) => [c.xmlid, `${c.xmlid}: ${c.texto.slice(0, 50)}…`])],
        ajuda: "Para citação interrompida pelo autor («algo é assim», porém, «e assado»): marque o 2º trecho como continuação do 1º.",
      },
    ],
    confirmar: "Marcar",
  });
  if (!r) return;
  const tr = editor.state.tr;
  const faixa = aparar(tr, from, to);
  if (faixa.to <= faixa.from) return;
  tr.addMark(faixa.from, faixa.to, S.marks.citacao.create(atributosNovos(editor.state, r.tipo, r.continua, cfg)));
  tr.setSelection(TextSelection.create(tr.doc, faixa.to));
  editor.view.dispatch(tr.scrollIntoView());
  editor.commands.focus();
}

async function editarCitacao(editor, cfg, sob) {
  const k = chaveDe(sob.mark.attrs);
  const cabeca = sob.mark.attrs.xmlid || !sob.mark.attrs.corresp;
  const r = await dialogo({
    titulo: k ? `Citação ${k}` : "Menção",
    campos: [
      ...(cabeca ? [{ nome: "tipo", rotulo: "Tipo (vale para todos os segmentos)", tipo: "select", valor: sob.mark.attrs.tipo || "direta", opcoes: TIPOS }] : []),
      { nome: "acao", rotulo: "Ação", tipo: "select", valor: "", opcoes: [["", "Só mudar o tipo"], ["segmento", "Desfazer a marca deste segmento"], ...(k ? [["toda", "Desfazer a citação inteira (todos os segmentos)"]] : [])],
        ajuda: "Desfazer devolve as aspas « » ao texto das citações diretas e menções." },
    ],
    confirmar: "Aplicar",
  });
  if (!r) return;
  const { state } = editor;
  const S = state.schema;
  const alvo = r.acao === "toda" ? segmentos(state.doc, k) : r.acao === "segmento" ? [{ ...sob }] : (k ? segmentos(state.doc, k) : [{ ...sob }]);
  const tr = state.tr;
  if (r.acao) {
    // de trás para a frente: inserir aspas não desloca as faixas anteriores
    for (const s of mesclar(alvo).reverse()) {
      tr.removeMark(s.from, s.to, S.marks.citacao);
      if ((s.mark.attrs.tipo || "direta") !== "indireta") {
        tr.insertText("»", s.to);
        tr.insertText("«", s.from);
      }
    }
  } else if (r.tipo && r.tipo !== sob.mark.attrs.tipo) {
    let ident = sob.mark.attrs.xmlid;
    if (COM_DADOS.has(r.tipo) && !ident) ident = novoId(state.doc, cfg.prefixoId);
    for (const s of alvo) {
      const a = s.mark.attrs.corresp && !s.mark.attrs.xmlid
        ? { tipo: r.tipo, xmlid: null, corresp: s.mark.attrs.corresp }
        : { tipo: r.tipo, xmlid: COM_DADOS.has(r.tipo) ? ident : null, corresp: null };
      tr.removeMark(s.from, s.to, S.marks.citacao);
      tr.addMark(s.from, s.to, S.marks.citacao.create(a));
    }
  }
  if (tr.docChanged) editor.view.dispatch(tr);
  editor.commands.focus();
}

// Junta faixas contíguas do mesmo segmento (o texto de um segmento pode ser vários nós).
function mesclar(faixas) {
  const out = [];
  for (const f of faixas.slice().sort((a, b) => a.from - b.from)) {
    const u = out[out.length - 1];
    if (u && u.to === f.from && u.mark.eq(f.mark)) u.to = f.to;
    else out.push({ ...f });
  }
  return out;
}

export async function referenciar(editor) {
  if (!editor.isEditable) return;
  const { state } = editor;
  const S = state.schema;
  const sob = marcaNoCursor(state, "bibl");
  if (state.selection.empty && sob) {
    editor.view.dispatch(state.tr.removeMark(sob.from, sob.to, S.marks.bibl));
    return;
  }
  if (state.selection.empty) return;
  const existentes = citacoesDoDoc(state.doc);
  if (!existentes.length) {
    await dialogo({ titulo: "Referência do autor", campos: [], confirmar: "Entendi", ajuda: "Marque antes a citação a que esta referência pertence." });
    return;
  }
  // padrão: a última citação que começa antes da seleção
  let padrao = existentes[0].xmlid;
  state.doc.nodesBetween(0, state.selection.from, (n) => {
    const m = n.isText && n.marks.find((k) => k.type.name === "citacao");
    if (m && chaveDe(m.attrs)) padrao = chaveDe(m.attrs);
    return true;
  });
  const r = await dialogo({
    titulo: "Referência dada pelo autor",
    campos: [{ nome: "cit", rotulo: "Referência da citação", tipo: "select", valor: padrao,
      opcoes: existentes.map((c) => [c.xmlid, `${c.xmlid}: ${c.texto.slice(0, 50)}…`]),
      ajuda: "O trecho selecionado — ex.: (Sum. Th., I, q. 2, a. 3) — é a referência que Sinibaldi deu. Na nova edição, ela é trocada pela referência precisa da ficha." }],
    confirmar: "Marcar",
  });
  if (!r) return;
  const { from, to } = editor.state.selection;
  editor.view.dispatch(editor.state.tr.addMark(from, to, S.marks.bibl.create({ corresp: "#" + r.cit })));
  editor.commands.focus();
}

export function chaveNoCursor(state) {
  const c = marcaNoCursor(state, "citacao") || marcaNoCursor(state, "bibl");
  return c ? chaveDe(c.mark.attrs) : null;
}

export function abrirDados(editor, cfg) {
  const k = chaveNoCursor(editor.state);
  if (!k || !cfg.urlCitacao) return;
  window.open(cfg.urlCitacao.replace("__ID__", encodeURIComponent(k)), "_blank", "noopener");
}

/** Reconhecimento automático no servidor. Substitui o documento numa transação (desfazível).
 *  -> {relatorio, erros} */
export async function detectar(editor, cfg, htmlParaDoc) {
  const r = await postarJSON(cfg.urlConverter, { de: "html", conteudo: editor.getHTML(), detectar: true, prefixo: cfg.prefixoId || "" }, cfg.csrf);
  const d = r.dados || {};
  if (r.status !== 200 || (d.erros && d.erros.length) || !d.html) return { relatorio: null, erros: d.erros || [`Erro (HTTP ${r.status}).`] };
  if (d.marcadas) {
    const doc = htmlParaDoc(editor.schema, d.html);
    const { state } = editor;
    const tr = state.tr.replaceWith(0, state.doc.content.size, doc.content);
    const pos = Math.min(state.selection.from, tr.doc.content.size - 1);
    try { tr.setSelection(TextSelection.near(tr.doc.resolve(Math.max(pos, 1)))); } catch (_) { /* seleção padrão */ }
    editor.view.dispatch(tr);
  }
  return { relatorio: d.relatorio, erros: [] };
}

/** Ao digitar a aspa de fechamento: «texto» -> citação. true se tratou o evento. */
export function regraDeDigitacao(view, ch, cfg) {
  const abre = PARES[ch];
  if (!abre) return false;
  const { state } = view;
  const sel = state.selection;
  if (!sel.empty) return false;
  const $p = sel.$from;
  if (!$p.parent.inlineContent || ["cabecalho", "titulo", "gravuraLegenda", "gravuraDetalhes"].includes($p.parent.type.name)) return false;
  const S = state.schema;
  if (S.marks.citacao.isInSet($p.marks())) return false;
  // procura para trás, no mesmo bloco de texto, a aspa de abertura (sem outra aspa nem citação no meio)
  const inicio = $p.start();
  let achou = null;
  let ok = true;
  $p.parent.forEach((c, off) => {
    if (!ok) return;
    const de = inicio + off;
    if (de >= $p.pos) return;
    if (S.marks.citacao.isInSet(c.marks)) { achou = null; return; }
    if (!c.isText) return;
    const txt = c.text.slice(0, Math.max(0, $p.pos - de));
    for (let i = 0; i < txt.length; i++) {
      if (txt[i] === abre) achou = de + i;
      else if ("«»“”".includes(txt[i])) achou = null;
    }
  });
  if (achou === null || $p.pos - achou > 6000) return false;
  const miolo = state.doc.textBetween(achou + 1, $p.pos, " ", " ");
  if (!/[\p{L}\p{N}]/u.test(miolo)) return false;
  const tr = state.tr;
  const faixa = aparar(tr, achou, $p.pos);
  if (faixa.to <= faixa.from) return false;
  const palavras = miolo.trim().split(/\s+/).length;
  const tipo = palavras > PALAVRAS_MENCAO ? "direta" : "mencao";
  tr.addMark(faixa.from, faixa.to, S.marks.citacao.create(atributosNovos(state, tipo, null, cfg)));
  tr.removeStoredMark(S.marks.citacao);
  tr.setSelection(TextSelection.create(tr.doc, faixa.to));
  view.dispatch(tr.scrollIntoView());
  return true;
}
