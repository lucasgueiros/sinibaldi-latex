"""Slides de um trecho do livro: fonte (automática ou corrigida), `.tex`, PDF em cache e histórico.

O gerador é `tools/gera_slides.py` (TEI -> fonte `.slides.txt` -> beamer -> PDF); aqui só se cola
o site a ele. A *fonte* é o que o editor humano corrige; o usuário nunca escreve LaTeX.

Sem `Apresentacao` salva, os slides são os automáticos e nada vai ao banco. Com ela, a fonte salva
manda. O PDF fica em `exportacao.dir_cache()`, com chave = hash(versão do tema/gerador + fonte
efetiva): mudar a fonte OU o tema recompila; o mesmo texto reaproveita o arquivo.
"""
import difflib
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from . import exportacao, leitura
from .models import Apresentacao, ApresentacaoRevisao

MAX_BLOCOS = 400           # acima disso os slides não são oferecidos (o capítulo de 345 blocos leva ~45 s)
COMPILAR_TIMEOUT = 150
ESPERA_VAGA = 150          # quanto esperar por uma vaga no semáforo de compilações
ERRO_TTL = 30              # segundos em que uma compilação que falhou não é repetida
MAX_FONTE = 400_000        # caracteres aceitos numa fonte salva

_gerador = None
_lock_gerador = threading.Lock()
_memo_tema = {}


class ErroApresentacao(exportacao.ErroExportacao):
    """Falha amigável. `.log` guarda o resumo do LaTeX (só o editor o vê)."""

    def __init__(self, mensagem, log=""):
        super().__init__(mensagem)
        self.log = log


class Conflito(Exception):
    """Outra pessoa gravou depois da leitura. `.atual` = a `Apresentacao` como está (ou None se foi descartada)."""

    def __init__(self, atual=None):
        super().__init__("conflito de versão")
        self.atual = atual


class FonteInvalida(Exception):
    def __init__(self, erros):
        super().__init__("; ".join(erros))
        self.erros = erros


# ------------------------------------------------------------------ gerador
def _raiz_tools():
    return Path(settings.RAIZ_REPO) / "tools" / "gera_slides.py"


def gerador():
    """Módulo `tools/gera_slides.py`, carregado de novo só se o arquivo mudar (não é um pacote)."""
    global _gerador
    caminho = _raiz_tools()
    marca = caminho.stat().st_mtime_ns
    with _lock_gerador:
        if _gerador is None or _gerador[0] != marca:
            spec = importlib.util.spec_from_file_location("gera_slides", caminho)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["gera_slides"] = mod
            spec.loader.exec_module(mod)
            _gerador = (marca, mod)
    return _gerador[1]


def tipos():
    """{tipo: rótulo} dos slides."""
    return dict(gerador().TIPOS)


def _hash_arquivos(*arquivos):
    marca = tuple((a.stat().st_mtime_ns, a.stat().st_size) if a.is_file() else None for a in arquivos)
    if _memo_tema.get(arquivos, (None,))[0] != marca:
        h = hashlib.sha1()
        for a in arquivos:
            h.update(a.read_bytes() if a.is_file() else b"-")
        _memo_tema[arquivos] = (marca, h.hexdigest())
    return _memo_tema[arquivos][1]


def versao_gerador():
    """Hash de `tools/gera_slides.py` (invalida a fonte automática em cache)."""
    return _hash_arquivos(_raiz_tools())


def versao_tema():
    """Hash do gerador e do tema beamer (invalida o PDF em cache quando um deles muda). Memoizado por mtime."""
    return _hash_arquivos(_raiz_tools(), Path(settings.RAIZ_REPO) / "tex" / "slides" / "academia-slides.sty")


# ------------------------------------------------------------------ disponibilidade
def n_blocos(no):
    return exportacao.blocos_do_no(no).count()


def disponivel(no, total=None):
    """Slides só para nós de até `MAX_BLOCOS` blocos."""
    return (n_blocos(no) if total is None else total) <= MAX_BLOCOS


def chave_texto(no):
    """Versão do texto do livro neste nó (muda quando um bloco muda)."""
    return exportacao._versao(no)


# ------------------------------------------------------------------ fonte
def normalizar(fonte):
    """Quebras de linha `\\n` e uma linha final."""
    fonte = (fonte or "").replace("\r\n", "\n").replace("\r", "\n")
    return fonte.rstrip("\n") + "\n" if fonte.strip() else ""


def fonte_automatica(no):
    """Fonte gerada do TEI do nó. Determinística; guardada em disco, pela versão do texto e do gerador."""
    chave = hashlib.sha1(f"{chave_texto(no)}|{leitura.titulo_do_no(no)}|{versao_gerador()}".encode()).hexdigest()[:20]
    cache = exportacao.dir_cache()
    arq = cache / f"slides-auto-{chave}.txt"
    if arq.is_file() and arq.stat().st_size:
        return arq.read_text(encoding="utf-8")
    with exportacao._Trava(cache / f"slides-auto-{chave}.lock"):
        if arq.is_file() and arq.stat().st_size:
            return arq.read_text(encoding="utf-8")
        try:
            fonte = gerador().tei_para_fonte(exportacao.tei_do_no(no), titulo=leitura.titulo_do_no(no))
        except Exception as e:  # o gerador é tolerante, mas a mensagem ao leitor tem de ser amigável
            raise ErroApresentacao("Não foi possível gerar os slides deste trecho.", repr(e))
        fonte = normalizar(fonte)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache, prefix="tmp-", delete=False) as f:
            f.write(fonte)
        os.replace(f.name, arq)
    return fonte


def apresentacao_do_no(no):
    return Apresentacao.objects.filter(edicao_id=no.edicao_id, xml_id=no.xml_id).select_related(
        "atualizado_por", "criado_por").first()


def fonte_do_no(no, apresentacao=None):
    """Fonte efetiva: a salva, se houver; senão a automática (sem gravar nada)."""
    ap = apresentacao or apresentacao_do_no(no)
    return ap.fonte if ap is not None else fonte_automatica(no)


def validar_fonte(fonte):
    """Mensagens `linha N: …` (lista vazia = ok)."""
    if not (fonte or "").strip():
        return ["A fonte está vazia."]
    if len(fonte) > MAX_FONTE:
        return [f"A fonte é grande demais (mais de {MAX_FONTE} caracteres)."]
    return gerador().validar(fonte)


_TIPO_SLIDE = re.compile(r"^===[ \t]*(\S*)", re.M)


def resumo(fonte):
    """(nº de slides, [(rótulo do tipo, quantidade)]) na ordem de `TIPOS`."""
    g = gerador()
    cont = {}
    for t in _TIPO_SLIDE.findall(fonte):
        t = t if t in g.TIPOS else "texto"
        cont[t] = cont.get(t, 0) + 1
    return g.contar_slides(fonte), [(g.TIPOS[t], cont[t]) for t in g.TIPOS if t in cont]


# ------------------------------------------------------------------ .tex / PDF
def tex_da_fonte(fonte, no=None):
    return gerador().fonte_para_tex(fonte, trecho=leitura.titulo_do_no(no) if no is not None else None)


def tex_do_no(no, fonte=None):
    return tex_da_fonte(fonte if fonte is not None else fonte_do_no(no), no)


def chave_da_fonte(fonte):
    """Chave de cache do PDF: hash(tema + fonte)."""
    return hashlib.sha1((versao_tema() + "\0" + fonte).encode("utf-8")).hexdigest()[:20]


def _arquivo_erro(chave):
    return exportacao.dir_cache() / f"slides-{chave}.erro"


def erro_da_fonte(fonte):
    """`(mensagem, log)` da última compilação que falhou para esta fonte, ou None (para mostrar ao editor)."""
    chave = chave_da_fonte(fonte)
    if (exportacao.dir_cache() / f"slides-{chave}.pdf").is_file():
        return None
    try:
        d = json.loads(_arquivo_erro(chave).read_text(encoding="utf-8"))
        return d["mensagem"], d.get("log", "")
    except (OSError, ValueError, KeyError):
        return None


def pdf_do_no(no, fonte=None):
    """Caminho do PDF dos slides (em cache), compilando se preciso. Levanta `ErroApresentacao`."""
    if not disponivel(no):
        raise ErroApresentacao("Este trecho é grande demais para gerar slides de uma vez; "
                               "abra um dos seus capítulos, artigos ou teses.")
    fonte = fonte if fonte is not None else fonte_do_no(no)
    chave = chave_da_fonte(fonte)
    cache = exportacao.dir_cache()
    pdf = cache / f"slides-{chave}.pdf"
    if pdf.is_file() and pdf.stat().st_size:
        return pdf
    with exportacao._Trava(cache / f"slides-{chave}.lock"):
        if pdf.is_file() and pdf.stat().st_size:
            return pdf
        arq_erro = _arquivo_erro(chave)
        anterior = erro_da_fonte(fonte)
        if anterior and time.time() - arq_erro.stat().st_mtime < ERRO_TTL:
            raise ErroApresentacao(*anterior)
        if not exportacao._semaforo_pdf.acquire(timeout=ESPERA_VAGA):
            raise ErroApresentacao("O servidor está ocupado gerando outros PDFs. Tente novamente em instantes.")
        g = gerador()
        try:
            tex = tex_da_fonte(fonte, no)
            with tempfile.TemporaryDirectory(dir=cache, prefix="tmp-slides-") as tmp:
                saida = Path(tmp) / "slides.pdf"
                g.compilar(tex, saida, timeout=COMPILAR_TIMEOUT)
                os.replace(saida, pdf)
        except g.ErroSlides as e:
            msg = "Não foi possível compilar os slides deste trecho."
            if "passou de" in e.mensagem:
                msg = "A geração dos slides passou do tempo limite."
            elif "latexmk" in e.mensagem:
                msg = "A geração de slides não está disponível neste servidor (falta o LaTeX)."
            log = (e.log_resumido or e.mensagem).strip()
            arq_erro.write_text(json.dumps({"mensagem": msg, "log": log}), encoding="utf-8")
            raise ErroApresentacao(msg, log)
        finally:
            exportacao._semaforo_pdf.release()
        arq_erro.unlink(missing_ok=True)
    return pdf


# ------------------------------------------------------------------ gravação
def _revisao(no, usuario, acao, fonte):
    ApresentacaoRevisao.objects.create(edicao_id=no.edicao_id, xml_id=no.xml_id, autor=usuario, acao=acao,
                                       fonte=fonte)


def gravar(no, fonte, usuario, acao, versao_lida):
    """Grava a fonte (acao: editar|restaurar|regenerar) com controle otimista de concorrência.

    `versao_lida` é a `versao` que quem edita viu (0 = ainda não havia registro). Levanta `Conflito`
    se mudou no meio e `FonteInvalida` se a fonte não passa em `validar_fonte`."""
    auto = fonte_automatica(no)
    if acao == ApresentacaoRevisao.REGENERAR:
        fonte = auto
    fonte = normalizar(fonte)
    erros = [] if acao == ApresentacaoRevisao.REGENERAR else validar_fonte(fonte)
    if erros:
        raise FonteInvalida(erros)
    chave = chave_texto(no)
    agora = timezone.now()
    with transaction.atomic():
        ap = apresentacao_do_no(no)
        if ap is None:
            if versao_lida != 0:
                raise Conflito(None)
            try:
                with transaction.atomic():
                    ap = Apresentacao.objects.create(
                        edicao_id=no.edicao_id, xml_id=no.xml_id, titulo=leitura.titulo_do_no(no)[:300],
                        fonte=fonte, fonte_gerada=auto, chave_texto=chave, editada=fonte != auto,
                        criado_por=usuario, atualizado_por=usuario)
            except IntegrityError:
                raise Conflito(apresentacao_do_no(no))
        else:
            campos = dict(fonte=fonte, versao=F("versao") + 1, atualizado_por=usuario, atualizado_em=agora,
                          titulo=leitura.titulo_do_no(no)[:300])
            if acao == ApresentacaoRevisao.REGENERAR:
                campos.update(fonte_gerada=auto, chave_texto=chave, editada=False)
            else:
                campos["editada"] = fonte != ap.fonte_gerada
            if not Apresentacao.objects.filter(pk=ap.pk, versao=versao_lida).update(**campos):
                raise Conflito(ap)
            ap = apresentacao_do_no(no)
        _revisao(no, usuario, acao, fonte)
    return ap


def descartar(no, usuario, versao_lida):
    """Apaga a apresentação salva (volta ao automático). A fonte descartada fica no histórico."""
    with transaction.atomic():
        ap = apresentacao_do_no(no)
        if ap is None:
            return
        if ap.versao != versao_lida:
            raise Conflito(ap)
        _revisao(no, usuario, ApresentacaoRevisao.DESCARTAR, ap.fonte)
        ap.delete()


def historico(no, limite=40):
    return list(ApresentacaoRevisao.objects.filter(edicao_id=no.edicao_id, xml_id=no.xml_id)
                .select_related("autor")[:limite])


def revisao_do_no(no, pk):
    return ApresentacaoRevisao.objects.filter(edicao_id=no.edicao_id, xml_id=no.xml_id, pk=pk).first()


# ------------------------------------------------------------------ aviso de texto mudado / diff
def texto_mudou(no, ap):
    return ap is not None and bool(ap.chave_texto) and ap.chave_texto != chave_texto(no)


def diff_fontes(antes, depois, contexto=2, max_linhas=400):
    """HTML seguro (para `<pre class="dif">`) com as linhas que mudaram entre duas fontes."""
    saida = []
    for l in difflib.unified_diff((antes or "").splitlines(), (depois or "").splitlines(), n=contexto, lineterm=""):
        if l.startswith(("---", "+++")):
            continue
        if l.startswith("@@"):
            saida.append('<span class="text-ink/50">…</span>')
        elif l.startswith("+"):
            saida.append('<ins class="dif-ins">%s</ins>' % escape(l))
        elif l.startswith("-"):
            saida.append('<del class="dif-del">%s</del>' % escape(l))
        else:
            saida.append(escape(l))
        if len(saida) >= max_linhas:
            saida.append("… (diferença truncada)")
            break
    return mark_safe("\n".join(saida))
