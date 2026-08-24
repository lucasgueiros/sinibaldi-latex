#!/usr/bin/env python3
"""Extrai um trecho marcado com %%>>> id / %%<<< id de um .tex do livro.

Fonte unica de verdade: o texto vive so no livro; livro e slides consomem o mesmo recorte.
    python3 tools/trecho.py tex/exemplo-ontologia.tex ente-immutavel
"""
import re, sys


def extrair(src: str, tid: str) -> str:
    texto = open(src, encoding="utf-8").read()
    tag = re.escape(tid)
    m = re.search(rf"^%%>>> *{tag} *$\n(.*?)^%%<<< *{tag} *$", texto, re.M | re.S)
    if not m:
        raise KeyError(f"trecho '{tid}' nao encontrado em {src}")
    return m.group(1)


if __name__ == "__main__":
    try:
        sys.stdout.write(extrair(sys.argv[1], sys.argv[2]))
    except KeyError as e:
        sys.exit(str(e))
