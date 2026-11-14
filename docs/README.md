# docs/

- [01-fontes-e-pipeline.md](01-fontes-e-pipeline.md) — arquivos, pipeline de OCR, qualidade do texto.
- [02-numeracao-de-paginas.md](02-numeracao-de-paginas.md) — por que o número de página não se perdeu e como recuperá-lo.
- [03-latex-e-slides.md](03-latex-e-slides.md) — macros do preâmbulo, trechos nomeados, `tex/_preview.tex`, slides.
- [04-ocr-latim.md](04-ocr-latim.md) — reOCR com modelo de latim: medições, armadilha do `w`, `tools/corrige_w.py`.
- [05-estrutura-por-no.md](05-estrutura-por-no.md) — árvore por nó (`volN/…/`), `tools/corta.py`, fluxo faixa → LaTeX → slides.
- [06-formatacao.md](06-formatacao.md) — itálico, versalete e negrito medidos na imagem (`tools/formatacao.py`), precisão no padrão-ouro, `tools/gera_volume.sh`.
- [07-padrao-ouro.md](07-padrao-ouro.md) — padrões-ouro dos dois volumes (vol. 2 pp. 421–442; vol. 1 três blocos em `vol1/ouro/`), convenções de transcrição, WER e formatação medidos.
- [08-estrutura-e-trechos.md](08-estrutura-e-trechos.md) — `tools/titulos.py` (proposta de `estrutura.tsv` + alertas) e `tools/trecho.py` (trechos por id, tese ou página).
- [09-revisao-llm.md](09-revisao-llm.md) — revisão final por LLM (Haiku) sobre o TEI, uma chamada por página (`tools/revisa_paginas.py`), corrigindo também a fronteira corpo/nota: método, validador, medição; e o bug de `trecho.py` que perdia a 1ª linha de cada página.
- [10-citacoes.md](10-citacoes.md) — componente de citação (`<quote>`/`<bibl>`, direta/indireta/menção, citação interrompida), reconhecimento automático pelas aspas (`marcar_citacoes`), fichas e fontes (BibTeX) e a troca, na nova edição, das referências de Sinibaldi pelas precisas.
- [11-pretextuais.md](11-pretextuais.md) — elementos pré-textuais (rosto, imprimatur, cartas de aprovação, prefácio): componente `pretextual` (nó + parágrafos tipados), revisão por LLM (`tools/revisa_pretextuais.py`) e `manage.py aplicar_pretextuais`.
- [../deploy/README.md](../deploy/README.md) — deploy do editor web na VM do site da Academia (mesmo banco, esquema próprio), CI/CD no GitHub Actions, envio dos scans e do banco, homologação.
