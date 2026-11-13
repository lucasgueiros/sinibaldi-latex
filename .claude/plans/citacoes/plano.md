# Componente de citação

Pedido: componente de citação (direta/indireta, com texto do autor interrompendo a citação),
aspas padronizadas, inserível pela web, reconhecido automaticamente pelas aspas, dados
estruturados (BibTeX, página na edição) para trocar na nova edição as referências vagas de
Sinibaldi por edições críticas/traduções.

## Decisões
- Dialeto: `<quote type=direta|indireta xml:id>`; continuação `<quote type corresp="#id">`;
  referência do autor `<bibl corresp="#id">(Post. anal., l. I)</bibl>`. Texto SEM aspas.
- Dados: `Fonte` (BibTeX) e `Citacao` (chave = xml:id, comum às duas edições).
- Detector único em Python (`obra/citacoes.py`), usado pelo comando e pelo editor (`converter`).
- Saídas: CSS `«»` (web), texto/HTML/TEI (`<back>`), tei2latex (`«»`; nova: referência precisa).

## Etapas
1. esquema + tei (HTML `q`/`cite`)            2. detector + testes
3. modelos + migração + bibtex                4. indexação ao gravar + `marcar_citacoes`
5. editor (marcas, botões, regra de digitação) 6. telas de citações/fontes
7. leitura, exportações, tei2latex            8. docs; rodar no corpus real
