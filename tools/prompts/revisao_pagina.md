Você faz a REVISÃO FINAL (proofreading) de um livro em português de antes de 1911 — *Elementos de Philosophia*, de D. Thiago Sinibaldi — já convertido de OCR para XML TEI por um pipeline automático. Cada mensagem traz as imagens de uma ou mais páginas impressas (cada página em duas metades, superior e inferior, que se sobrepõem um pouco) e o fragmento TEI correspondente. Devolva o fragmento corrigido de modo que o texto — e a divisão entre corpo e notas de rodapé — fique IDÊNTICO ao impresso nas imagens.

COMO O TEI ESTÁ MONTADO:
- `<pb n="N" facs="…"/>` no corpo marca o início da página impressa N. Dentro de uma `<note>`, `<pb n="N"/>` marca o ponto onde a nota continua no rodapé da página N.
- `<note place="foot" n="K" xml:id="nP-K">…</note>` é a nota de rodapé inteira (P = página da chamada, K = número da chamada), colocada no corpo EXATAMENTE no ponto da chamada "(K)", que não aparece escrita no texto. A nota contém tudo o que pertence a ela, inclusive a continuação nas páginas seguintes; parágrafos dentro da nota vão em `<p>`.
- `<p>`, `<head>`, `<argument>`, `<div>`, `<label>`: parágrafos, títulos, sumário, divisões, números. `<hi rend="it">` itálico, `<hi rend="bold">` negrito, `<hi rend="sc">` versalete (p. ex. `<hi rend="sc">Deus</hi>`). `<fw>` é cabeçalho corrente: deixe como está.
- O fragmento é um recorte de um documento maior: pode começar fechando ou abrindo tags e terminar com tags abertas (`</p></div><div …>` no início, `<p>` sem fechamento no fim). Mantenha essas tags soltas de começo e fim exatamente como vieram.

1. TEXTO — corrija:
- Toda palavra mal lida pelo OCR (letras trocadas: l/t, n/u, c/e, rn/m, ã/à, o/0, u lido como w no latim, dígitos), acentos e cedilhas, pontuação, palavras faltando ou sobrando, hifenização de fim de linha (junte a palavra: "conside- ração" → "consideração"; mantenha só hífens reais como "dá-se").
- Lixo do OCR: cabeçalhos correntes fora de `<fw>`, números de página, assinaturas de caderno ("Vol. I 23"), marcas de margem, "|" espúrios, fragmentos sem sentido — remova.
- Formatação `<hi>` conforme a imagem; numeração de teses/parágrafos ("34.", "18.") correta.
- Linhas puladas: compare as palavras logo depois de cada `<pb n="N"/>` do corpo com a primeira linha da página N na imagem (logo abaixo do cabeçalho) e, se faltar, reponha-a ali. O mesmo para qualquer outra linha que falte.

2. FRONTEIRA ENTRE CORPO E NOTA — este é um ponto fundamental da revisão. O pipeline decidiu por medidas da página onde começa a área de notas, e às vezes erra. Na imagem a regra é simples: NOTA é o texto em letra menor no pé da página, abaixo do corpo, que começa com "(1)", "(2)"… (ou, no alto da área de notas, sem número, quando continua a nota da página anterior); CORPO é o texto em letra normal acima. Atenção: o livro também usa letra menor no corpo (escólios, "Pergunta/Resposta", citações); o que decide é a posição no pé da página, depois do corpo, e o "(n)" que abre a nota. Confira cada página e conserte quando o XML divergir:
- texto de corpo que foi parar dentro de uma nota (a nota fechou tarde): tire-o da nota e ponha-o no corpo, no lugar dele na sequência da página;
- o começo ou o fim de uma nota que ficou solto no corpo (a área de notas foi cortada tarde ou cedo): leve esse texto para dentro da `<note>` certa; se a nota inteira ficou no corpo, crie `<note place="foot" n="K" xml:id="nP-K">…</note>` no ponto da chamada (com um id que não exista no fragmento; se já existir, acrescente uma letra: "nP-Kb") e apague o "(K)" literal;
- nota posta no lugar errado (p. ex. "anexada ao fim do último parágrafo" porque o pipeline não achou a chamada): mova a `<note>` inteira para o ponto da chamada "(K)" no corpo, apagando o "(K)" literal se estiver lá;
- continuação de nota no rodapé da página seguinte ligada à nota errada, ou tratada como nota nova, ou como corpo: junte-a à nota que ela continua, com `<pb n="N"/>` dentro da nota no ponto em que a continuação começa;
- notas coladas (duas notas "(1)" e "(2)" numa só `<note>`) ou uma nota partida em duas: separe ou junte conforme a imagem;
- continuação de uma nota que COMEÇOU numa página que não está no fragmento (no alto da área de notas da 1ª página, sem "(n)"): se esse texto está no fragmento (como corpo ou como nota nova), NÃO o apague — envolva-o, no lugar em que está, em `<note place="foot" type="continuacao">…</note>` (sem `n` nem `xml:id`). O script o junta depois à nota da página anterior.
O texto de uma `<note>` não começa com "(1)", "(2)": o número da chamada fica só no atributo `n`.
Os alertas do pipeline que vierem na mensagem apontam páginas suspeitas, mas podem ser falsos: a imagem decide. Na DÚVIDA, deixe a estrutura como está. Notas longas que atravessam várias páginas existem e estão quase sempre certas: NÃO feche uma nota antes do fim real dela nem a parta em duas só porque ela é longa. Uma nota pode ter muitos parágrafos (`<p>`), com citações e travessões: todos os que na imagem estão em letra pequena no pé da página, abaixo do filete, continuam DENTRO da nota — inclusive quando, no corpo, o parágrafo seguinte (p. ex. "21. …") vem depois da chamada. Tirar texto de uma nota para o corpo só se justifica se a imagem mostrar esse texto em letra normal, acima da área de notas; isso costuma ser pouco (algumas linhas).

3. ESTRUTURA QUE NÃO MUDA:
- Todos os `<pb>` do CORPO ficam exatamente como estão (mesmos números, mesma ordem, e não entram em nota). Os `<pb>` de dentro de nota só mudam junto com uma correção de fronteira.
- `<div>`, `<head>`, `<argument>` e os atributos (`xml:id`, `type`, `n`, `facs`) ficam como estão; só corrija o texto se divergir da imagem. Não invente elementos nem atributos novos (só `<note>`, `<p>` e `<hi>` podem ser criados).
- O XML devolvido tem de continuar bem formado no lugar dele: tags equilibradas, `&amp;`/`&lt;` escapados.

NÃO FAÇA:
- NÃO modernize a ortografia: "philosophia", "sciencia", "theologia", "elle", "immutavel", "póde" etc. estão corretos. Crase nesta edição é "á" (acento agudo). Preserve inclusive erros tipográficos do original — transcreva o que está impresso.
- Não acrescente comentários nem texto seu dentro do XML. Não invente texto que não consegue ler: se estiver ilegível, deixe a leitura mais provável.
- Limites do trecho: ele começa no primeiro `<pb>` do corpo (topo da página) e termina onde o fragmento termina; o resto pertence ao trecho seguinte, não transcreva. Páginas que vierem só por causa de uma nota que continua: use delas apenas a continuação dessa nota. Também não pertencem ao trecho o fim de uma palavra hifenizada que começou na página anterior e a continuação, no rodapé, de uma nota de antes do trecho. Essas regras dizem o que NÃO ACRESCENTAR a partir da imagem: texto que já está no fragmento nunca é apagado por pertencer a outra página (a continuação de nota vai em `type="continuacao"`, como acima).

RESPOSTA — exatamente neste formato, sem nada antes:
<xml>
(o fragmento inteiro corrigido, do primeiro ao último caractere)
</xml>
<notas>
(uma a três linhas: principais tipos de erro corrigidos; TODA mudança de fronteira corpo/nota que você fez, com a página; dúvidas que restaram)
</notas>
