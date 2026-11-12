/*
 * SinibaldiEditor — editor WYSIWYG de estruturas limitadas para os blocos de
 * "Elementos de Philosophia" (TipTap 2 / ProseMirror + esquema próprio que espelha o
 * dialeto HTML de obra/tei.py). Empacotado por `npm run build:editor` em
 * static/js/editor.bundle.js (commitado; sem CDN).
 *
 * window.SinibaldiEditor.montar(elemento, opcoes) -> editor
 *   opcoes:
 *     html          string  HTML do servidor (tei.blocos_para_html); cada bloco com data-bloco/data-versao
 *     esquema       objeto  constantes de esquema.py ({niveis, tipos_paragrafo, rend, prefixos_id}), via json_script
 *     urlConverter  string  endpoint POST {de:"html"|"xml", conteudo} -> {html, xml, erros} (name obra:converter)
 *     csrf          string  token CSRF (para urlConverter)
 *     somenteLeitura bool
 *     prefixoId     string  prefixo dos xml:id sugeridos ao iniciar divisão ("v2.")
 *     pagina        {n, facs}  página corrente (sugestão ao inserir marca de página)
 *     facsDe(n)     função  facs de um <pb> novo (padrão "paginas/NNNN.png")
 *     barra         bool    false = sem barra de ferramentas própria
 *     decorarBloco(idBloco) -> {class, title, ...attrs}|null   atributos extras num bloco (ex.: "atravessa a página")
 *     aoMudar(sujo, editor)      a cada alteração (e a cada definirHtml/marcarLimpo)
 *     aoBlocoAtivo(idBloco|null) o bloco (data-bloco) sob o cursor mudou
 *   retorno:
 *     obterHtml()            HTML atual (enviar ao servidor: formato "html")
 *     definirHtml(html, {limpo=true})  substitui o conteúdo (zera o desfazer); limpo=false mantém a base de sujo()
 *     sujo()                 há alterações em relação ao último carregamento/marcarLimpo?
 *     marcarLimpo()          declara o conteúdo atual como gravado
 *     obterXml() / definirXml(xml)  via servidor (urlConverter): {xml, erros} / {html, erros}
 *     somenteLeitura(bool), focar(), redecorar(), destruir()
 *     editor                 a instância TipTap (uso avançado)
 *
 * window.SinibaldiEditor.montarAbas({editor, textarea, urlConverter, csrf, abas, erros, aoMudar})
 *   Abas Visual/XML. `abas` = {visual: {botao, painel}, xml: {botao, painel}}; `erros` = <ul> oculto.
 *   -> {ativa(), trocar(nome) (Promise<bool>; não troca se o servidor acusar erros),
 *       conteudo() ({formato, conteudo} para …/gravar/), carregar({html, xml}), sujo(), mostrarErros(lista)}
 *
 * window.SinibaldiEditor.montarVisualizador(el, {botoes, indicador, chave}) — scan com zoom/arrasto.
 * window.SinibaldiEditor.montarDivisor({divisor, primeira, chave}) — divisor arrastável (posição em localStorage).
 * window.SinibaldiEditor.postarJSON(url, corpo, csrf) -> Promise<{status, dados}>
 */
import { montar } from "./editor.js";
import { montarAbas } from "./abas.js";
import { montarVisualizador } from "./visualizador.js";
import { montarDivisor } from "./divisor.js";
import { postarJSON } from "./rede.js";

window.SinibaldiEditor = { montar, montarAbas, montarVisualizador, montarDivisor, postarJSON };
