Você vai fazer a REVISÃO FINAL (proofreading) de um trecho de um livro em português de antes de 1911 — *Elementos de Philosophia*, de D. Thiago Sinibaldi — já convertido de OCR para LaTeX por um pipeline automático. Seu trabalho é deixar o texto IDÊNTICO ao que está impresso nas imagens das páginas.

ARQUIVO QUE VOCÊ EDITA (é a saída do pipeline; edite-o no lugar com a ferramenta Edit):
  ${ARQUIVO} — ${DESCRICAO}, páginas impressas ${P0}–${P1}

IMAGENS DAS PÁGINAS (a fonte da verdade): ${IMAGENS}/NNNN.png, de ${P0} a ${P1} (NNNN = número da página impressa com 4 dígitos, p. ex. 0421.png; 1755×2481 px). Leia cada uma com a ferramenta Read. As notas de rodapé têm letra pequena: se não conseguir ler com segurança, recorte e amplie a região com Python, p. ex.
  ${PYTHON} -c "from PIL import Image; im=Image.open('IMG'); im.crop((0,1240,1755,2481)).save('SAIDA.png')"
gravando os recortes SÓ em ${TMPRECORTES}/ , e leia o recorte.

Não leia nem procure nenhum outro arquivo além do que você edita, das imagens acima e dos seus recortes.

MÉTODO: página por página. Para cada página N: leia a imagem, localize no .tex o trecho entre \pg{N} e \pg{N+1}, e corrija com Edit tudo o que divergir da imagem. Salve (Edit) ao terminar cada página — não acumule para o fim.

O QUE CORRIGIR:
- Toda palavra mal lida pelo OCR (letras trocadas: l/t, n/u, c/e, rn/m, ã/à, o/0, u lido como w no latim, dígitos), acentos e cedilhas, pontuação, palavras faltando ou sobrando, hifenização de fim de linha (junte a palavra: "conside- ração" → "consideração"; mantenha só hífens reais como "dá-se").
- Lixo do OCR: cabeçalhos correntes, números de página, assinaturas de caderno ("Vol. I 23"), marcas de margem, "\textbar{}" espúrios, fragmentos sem sentido — remova (cabeçalho corrente fica fora do texto).
- Estrutura: cada nota de rodapé inteira dentro de \footnote{...} no ponto da chamada (1), (2)… — inclusive a parte que continua na página seguinte. Se o pipeline deixou uma nota no corpo, ou um pedaço de corpo dentro de nota, ou a nota no lugar errado, conserte. As chamadas "(1)" não aparecem no texto, só o \footnote.
- \pg{N} marca o início da página impressa N no corpo; mantenha um e só um \pg por página, no lugar da quebra real (palavra hifenizada na quebra fica inteira ANTES do \pg). Não ponha \pg dentro de \footnote (se existir \pgn dentro de nota, pode remover).
- Formatação: itálico \emph{}, negrito \textbf{}, versalete \textsc{} (p. ex. \textsc{Deus}) conforme a imagem; numeração de teses/parágrafos ("34.", "18.") correta.
NÃO FAÇA:
- NÃO modernize a ortografia: "philosophia", "sciencia", "theologia", "elle", "immutavel", "póde" etc. estão corretos. Crase nesta edição é "á" (acento agudo). Preserve inclusive erros tipográficos do original — transcreva o que está impresso.
- Não acrescente comentários ou texto seu dentro do .tex. Não invente texto que não consegue ler: se estiver ilegível, deixe a leitura mais provável.
- Não use ambientes tabular nem argumentos opcionais novos.

Ao final, responda com um relatório curto: páginas revisadas (todas? quais ficaram faltando?), principais tipos de erro que corrigiu, dúvidas que restaram, e uma estimativa de confiança na revisão.
