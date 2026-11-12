"""Diff por palavras sobre o XML dos blocos (para o histórico de revisões)."""
import difflib
import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

_TOKEN = re.compile(r"<[^>]*>|\s+|[^\s<]+")


def tokens(xml):
    return _TOKEN.findall(xml or "")


def diff_html(antes, depois):
    """HTML seguro com `<del class="dif-del">` / `<ins class="dif-ins">` sobre os tokens (tags, espaços, palavras)."""
    a, b = tokens(antes), tokens(depois)
    saida = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            saida.append(escape("".join(a[i1:i2])))
            continue
        if i2 > i1:
            saida.append('<del class="dif-del">%s</del>' % escape("".join(a[i1:i2])))
        if j2 > j1:
            saida.append('<ins class="dif-ins">%s</ins>' % escape("".join(b[j1:j2])))
    return mark_safe("".join(saida))
