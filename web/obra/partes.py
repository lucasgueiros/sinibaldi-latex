"""Partes da obra e a ordem-alvo da nova edição (Lógica > Cosmologia > Antropologia > Ontologia > Teodiceia > Moral).

Só leitura: classifica os nós `parte` pelo título (sem acento/caixa) e monta o plano de reordenação.
A escrita está em `servicos_nova.aplicar_ordem_partes`."""
import re
import unicodedata

from .models import No

ORDEM_PARTES = ["Lógica", "Cosmologia", "Antropologia", "Ontologia", "Teodiceia", "Moral"]
_CHAVES_PARTE = [
    (0, re.compile(r"\blogic")),
    (1, re.compile(r"\bcosmolog")),
    (2, re.compile(r"\ban?thropolog|\bantropolog")),
    (3, re.compile(r"\bontolog")),
    (4, re.compile(r"\bth?eodic")),
    (5, re.compile(r"\bmoral\b|\bethic|\betic")),
]


def _sem_acento(txt):
    return re.sub(r"[^a-z ]+", " ", unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower())


def classificar_parte(no):
    """Índice em ORDEM_PARTES conforme o título (depois o rótulo) do nó, ou None."""
    for campo in (no.titulo, no.rotulo):
        t = _sem_acento(campo)
        for rank, rx in _CHAVES_PARTE:
            if rx.search(t):
                return rank
    return None


def plano_partes(edicao):
    """Situação das partes: {partes [nós], rank {pk: rank|None}, identificadas {rank: [nós]},
    faltam [ranks], alvo [nós na ordem-alvo], na_ordem bool}.

    Parte não identificada (ex.: "Direito natural") segue a identificada anterior."""
    partes = list(No.objects.filter(edicao=edicao, nivel="parte").order_by("ordem_ini"))
    rank, anterior, chave = {}, -1, {}
    for p in partes:
        r = classificar_parte(p)
        rank[p.pk] = r
        if r is not None:
            anterior = r
        chave[p.pk] = anterior
    identificadas = {}
    for p in partes:
        if rank[p.pk] is not None:
            identificadas.setdefault(rank[p.pk], []).append(p)
    faltam = [r for r in range(len(ORDEM_PARTES)) if r not in identificadas]
    alvo = sorted(partes, key=lambda p: (chave[p.pk], p.ordem_ini))
    return {"partes": partes, "rank": rank, "identificadas": identificadas, "faltam": faltam,
            "alvo": alvo, "na_ordem": [p.pk for p in alvo] == [p.pk for p in partes]}
