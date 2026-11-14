"""Peças pré-textuais como componente: folha de rosto, imprimatur, dedicatória, prefácio, cartas de aprovação…

Cada peça é um nó de nível `pretextual` (marco `<milestone unit="pretextual" xml:id="vN.pre-<tipo>"/>`, um
`<head>` com o título da peça e os blocos), e cada linha ganha a função que tem na página: parágrafos
tipados `titulo-obra`, `centro`, `enderecamento`, `saudacao`, `data-local`, `fecho` (`esquema.TIPOS_PARAGRAFO`).

O texto vem de `volN/pretextuais.json`, gerado por `tools/revisa_pretextuais.py` (Sonnet/Haiku lendo a imagem
de cada página; docs/11). Aqui só se monta a lista de blocos e se acha a região a substituir; a gravação é do
comando `aplicar_pretextuais`.
"""
import json
from html import escape
from pathlib import Path

from . import esquema
from .models import Bloco

COMENTARIO = "Elementos pré-textuais convertidos em peças (aplicar_pretextuais)."


def carregar(caminho):
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if dados.get("falhas"):
        raise ValueError("páginas que falharam na revisão: " + ", ".join(dados["falhas"]))
    return dados


def blocos_da_peca(peca):
    """[xml] da peça: marco, `<head>` com o título e os blocos."""
    return ([f'<milestone unit="pretextual" xml:id="{escape(peca["xml_id"])}"/>',
             f'<head>{escape(peca["titulo"])}</head>'] + list(peca["blocos"]))


def blocos_do_volume(dados):
    return [x for p in dados["pecas"] for x in blocos_da_peca(p)]


def regiao(edicao, volume_id, ate):
    """Blocos que a conversão substitui: do início do volume até o primeiro marco que NÃO é pretextual, e só
    até a página impressa `ate` (o resto é do livro: `METAPHYSICA` na p. 5 do vol. 2)."""
    r = []
    for b in Bloco.objects.filter(edicao=edicao, volume_id=volume_id).order_by("ordem"):
        if b.tipo == Bloco.MARCO and 'unit="pretextual"' not in b.xml:
            break
        if b.pagina is not None and b.pagina > ate:
            break
        r.append(b)
    return r


def validar(dados):
    """Erros de esquema em toda a lista (lista vazia = ok)."""
    return esquema.validar_blocos(blocos_do_volume(dados))


def paginas_do_volume(dados):
    """Página impressa onde cada bloco COMEÇA, na ordem de `blocos_do_volume`. Marco e título da peça levam a
    página do 1º bloco dela. (`salvar_blocos` dá a todos a mesma, e o banco não guarda `<pb>` no começo do bloco:
    a página vem do campo `pagina`, e o exportador reinsere o `<pb>`.)"""
    out = []
    for p in dados["pecas"]:
        out += [p["pag_blocos"][0]] * 2 + list(p["pag_blocos"])
    return out
