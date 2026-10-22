#!/usr/bin/env python3
"""w -> u fora de nomes proprios conhecidos.

O modelo `lat` le muitos `u` como `w` (wma, wniversal, wm); `w` nao existe em
latim e e raro em portugues.  Mas e legitimo em nomes proprios do livro
(Darwin, Newton, Wolf, ...), entao a correcao e por whitelist, nao por
blacklist de caractere.  Ver docs/04-ocr-latim.md.

Import:  from corrige_w import corrige_w, NOMES_COM_W
Filtro:  python3 tools/corrige_w.py < entrada.txt > saida.txt
"""
import re
import sys

NOMES_COM_W = ["Darwin", "Newton", "Wolf", "Edwards", "Wundt", "Schwann", "Wallace",
               "Weber", "Wolff", "Hartmann", "Schwegler"]


def _protege(txt: str) -> str:
    for i, nome in enumerate(NOMES_COM_W):
        txt = re.sub(re.escape(nome), f"\x00{i}\x00", txt, flags=re.I)
    return txt


def _restaura(txt: str) -> str:
    for i, nome in enumerate(NOMES_COM_W):
        txt = txt.replace(f"\x00{i}\x00", nome)
    return txt


def corrige_w(txt: str) -> str:
    """w -> u fora dos nomes proprios conhecidos."""
    txt = _protege(txt)
    txt = txt.replace("w", "u").replace("W", "U")
    return _restaura(txt)


if __name__ == "__main__":
    sys.stdout.write(corrige_w(sys.stdin.read()))
