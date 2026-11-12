import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from obra import arvore, exportacao, scans, servicos, tei
from obra.models import PASSO_ORDEM, Bloco, Edicao, No, Pagina, Revisao
from .base import BaseBanco


def dado(b, xml=None):
    return {"id": b.pk, "versao": b.versao, "xml": xml if xml is not None else b.xml}


class ArvoreTest(BaseBanco):
    def test_reconstruir(self):
        nos = list(No.objects.filter(edicao=self.edicao).order_by("ordem_ini"))
        self.assertEqual([(n.nivel, n.xml_id) for n in nos], [
            ("parte", "v1.parte-1"), ("capitulo", "v1.cap-1"), ("tese", "v1.t1"), ("tese", "v1.t2"),
            ("parte", "v1.parte-2"), ("tese", "v1.t3")])
        parte, cap, t1, t2, parte2, t3 = nos
        self.assertEqual((parte.rotulo, parte.titulo), ("PARTE PRIMEIRA", "LOGICA"))
        self.assertEqual((cap.rotulo, cap.titulo), ("CAPITULO I", "IDEA"))
        self.assertEqual((t1.n, t1.titulo, t1.rotulo), ("1", "Idea", "Tese 1"))
        self.assertEqual(t1.pai_id, cap.pk)
        self.assertEqual(t3.pai_id, parte2.pk)
        self.assertEqual([n.posicao for n in (t1, t2)], [0, 1])
        # faixas
        self.assertEqual(t1.ordem_fim, t2.ordem_ini)
        self.assertEqual(parte.ordem_fim, parte2.ordem_ini)
        self.assertEqual(t3.ordem_fim, arvore.ORDEM_MAX)
        self.assertEqual(cap.ordem_ini, t1.ordem_ini - 4 * PASSO_ORDEM)  # marco, 2 heads, sumário
        self.assertEqual(self.vol, t1.volume)
        self.assertEqual((t1.pagina_ini, t1.pagina_fim), (1, 2))

    def test_auxiliares(self):
        t1, t2 = No.objects.get(xml_id="v1.t1"), No.objects.get(xml_id="v1.t2")
        self.assertEqual(arvore.no_proximo(t1), t2)
        self.assertEqual(arvore.no_anterior(t2), t1)
        self.assertEqual(arvore.no_proximo(t2).xml_id, "v1.t3")  # atravessa a parte
        self.assertIsNone(arvore.no_anterior(t1))
        self.assertEqual([n.xml_id for n in arvore.caminho(t1)], ["v1.parte-1", "v1.cap-1", "v1.t1"])
        tipos = [b.tipo for b in arvore.blocos_do_no(t1)]
        self.assertEqual(tipos, ["marco", "paragrafo", "cabecalho"])
        cap = No.objects.get(xml_id="v1.cap-1")
        self.assertEqual(arvore.blocos_do_no(cap).count(), 4 + 3 + 3)

    def test_idempotente(self):
        antes = list(No.objects.filter(edicao=self.edicao).values_list("xml_id", "ordem_ini"))
        arvore.reconstruir(self.edicao)
        self.assertEqual(list(No.objects.filter(edicao=self.edicao).values_list("xml_id", "ordem_ini")), antes)


class SalvarBlocosTest(BaseBanco):
    def escopo(self, xml_id):
        no = No.objects.get(xml_id=xml_id)
        bs = list(arvore.blocos_do_no(no))
        return bs, [b.pk for b in bs]

    def test_edicao(self):
        bs, ids = self.escopo("v1.t2")
        p = bs[2]
        novos = [dado(b) for b in bs]
        novos[2]["xml"] = "<p>Editado.</p>"
        r = servicos.salvar_blocos(self.edicao, ids, novos, self.user, "corrige")
        self.assertEqual((r.criados, r.editados, r.removidos), (0, 1, 0))
        p.refresh_from_db()
        self.assertEqual((p.versao, p.atualizado_por, p.xml), (2, self.user, "<p>Editado.</p>"))
        rev = Revisao.objects.get()
        self.assertEqual((rev.acao, rev.autor, rev.comentario, rev.bloco), ("editar", self.user, "corrige", p))
        self.assertIn("Outro", rev.xml_antes)
        self.assertEqual(rev.lote, r.lote)
        self.assertFalse(r.arvore_reconstruida)

    def test_sem_mudanca_nao_grava(self):
        bs, ids = self.escopo("v1.t2")
        r = servicos.salvar_blocos(self.edicao, ids, [dado(b) for b in bs], self.user)
        self.assertFalse(r.alterou)
        self.assertEqual(Revisao.objects.count(), 0)
        self.assertTrue(all(Bloco.objects.get(pk=b.pk).versao == 1 for b in bs))

    def test_insercao_e_divisao_de_paragrafo(self):
        bs, ids = self.escopo("v1.t2")
        novos = [dado(b) for b in bs]
        # divide o parágrafo: o 2º tem o mesmo id -> vira bloco novo
        novos.insert(2, {"id": bs[1].pk, "versao": 1, "xml": '<p xml:id="v1.t2.p1">segunda metade</p>'})
        self.assertEqual(novos[2]["id"], novos[1]["id"])
        novos.insert(1, {"id": None, "versao": None, "xml": "<p>inserido antes</p>"})
        r = servicos.salvar_blocos(self.edicao, ids, novos, self.user, pagina=2)
        self.assertEqual((r.criados, r.editados), (2, 0))
        xmls = [b.xml for b in self.blocos()]
        self.assertEqual(xmls.count("<p>segunda metade</p>"), 1)  # sem o xml:id repetido
        self.assertLess(xmls.index("<p>inserido antes</p>"), xmls.index("<p>segunda metade</p>"))
        ordens = [b.ordem for b in self.blocos()]
        self.assertEqual(ordens, sorted(ordens))
        self.assertEqual(len(set(ordens)), len(ordens))
        criados = Bloco.objects.filter(criado_por=self.user)
        self.assertEqual(criados.count(), 2)
        self.assertTrue(all(b.procedencia == "copia" and b.pagina == 2 and b.versao == 1 for b in criados))
        self.assertEqual(Revisao.objects.filter(acao="criar").count(), 2)

    def test_remocao(self):
        bs, ids = self.escopo("v1.t2")
        r = servicos.salvar_blocos(self.edicao, ids, [dado(b) for b in bs if b.xml != "<p>Outro parágrafo.</p>"],
                                   self.user)
        self.assertEqual(r.removidos, 1)
        self.assertFalse(Bloco.objects.filter(xml="<p>Outro parágrafo.</p>").exists())
        rev = Revisao.objects.get(acao="remover")
        self.assertIsNone(rev.bloco)
        self.assertEqual(rev.xml_antes, "<p>Outro parágrafo.</p>")
        self.assertEqual(rev.xml_depois, "")

    def test_conflito(self):
        bs, ids = self.escopo("v1.t2")
        # alguém grava primeiro
        servicos.salvar_blocos(self.edicao, [bs[1].pk], [dado(bs[1], "<p>Do outro.</p>")], self.user2)
        # eu tinha a versão 1 e envio uma edição minha
        novos = [dado(b) for b in bs]
        novos[1]["xml"] = "<p>Minha.</p>"
        with self.assertRaises(servicos.Conflito) as cm:
            servicos.salvar_blocos(self.edicao, ids, novos, self.user)
        self.assertEqual(cm.exception.ids, [bs[1].pk])
        self.assertEqual(Bloco.objects.get(pk=bs[1].pk).xml, "<p>Do outro.</p>")
        self.assertEqual(Revisao.objects.count(), 1)  # nada foi gravado pela tentativa

    def test_validacao_antes_de_gravar(self):
        bs, ids = self.escopo("v1.t2")
        novos = [dado(b) for b in bs]
        novos[1]["xml"] = "<p>ok</p>"
        novos.append({"id": None, "versao": None, "xml": "<p><u>x</u></p>"})
        with self.assertRaises(servicos.ErroValidacao) as cm:
            servicos.salvar_blocos(self.edicao, ids, novos, self.user)
        self.assertTrue(any("<u>" in e for e in cm.exception.erros))
        self.assertEqual(Revisao.objects.count(), 0)
        self.assertNotEqual(Bloco.objects.get(pk=bs[1].pk).xml, "<p>ok</p>")

    def test_id_fora_do_escopo(self):
        bs, ids = self.escopo("v1.t2")
        outro = Bloco.objects.get(xml='<p xml:id="v1.t3.p1"><label>3.</label> <hi rend="bold">Mundo.</hi> — Corpo.</p>')
        with self.assertRaises(servicos.ErroValidacao):
            servicos.salvar_blocos(self.edicao, ids, [dado(outro)], self.user)

    def test_escopo_vazio_com_ancora(self):
        bs, _ = self.escopo("v1.t2")
        r = servicos.salvar_blocos(self.edicao, [], [{"id": None, "versao": None, "xml": "<p>após a âncora</p>"}],
                                   self.user, ancora=bs[1].pk)
        novo = r.blocos[0]
        proximo = Bloco.objects.filter(edicao=self.edicao, ordem__gt=bs[1].ordem).order_by("ordem").first()
        self.assertEqual(proximo, novo)

    def test_marco_reconstroi_arvore(self):
        bs, ids = self.escopo("v1.t2")
        novos = [dado(b) for b in bs]
        novos.append({"id": None, "versao": None, "xml": '<milestone unit="tese" n="9" xml:id="v1.t9"/>'})
        novos.append({"id": None, "versao": None, "xml": '<p xml:id="v1.t9.p1"><hi rend="bold">Nova.</hi> x</p>'})
        r = servicos.salvar_blocos(self.edicao, ids, novos, self.user)
        self.assertTrue(r.arvore_reconstruida)
        self.assertEqual(No.objects.get(xml_id="v1.t9").titulo, "Nova")

    def test_titulo_da_tese_muda_ao_editar_primeiro_paragrafo(self):
        bs, ids = self.escopo("v1.t2")
        novos = [dado(b) for b in bs]
        novos[1]["xml"] = '<p xml:id="v1.t2.p1"><hi rend="bold">Outro título.</hi> x</p>'
        r = servicos.salvar_blocos(self.edicao, ids, novos, self.user)
        self.assertTrue(r.arvore_reconstruida)
        self.assertEqual(No.objects.get(xml_id="v1.t2").titulo, "Outro título")

    def test_renumera_quando_nao_ha_folga(self):
        bs, ids = self.escopo("v1.t2")
        # estreita a folga entre o marco e o parágrafo
        Bloco.objects.filter(pk=bs[1].pk).update(ordem=bs[0].ordem + 1)
        bs, ids = self.escopo("v1.t2")
        novos = [dado(bs[0])] + [{"id": None, "versao": None, "xml": f"<p>n{i}</p>"} for i in range(3)] + [dado(b) for b in bs[1:]]
        servicos.salvar_blocos(self.edicao, ids, novos, self.user)
        ordens = [b.ordem for b in self.blocos()]
        self.assertEqual(ordens, sorted(ordens))
        self.assertEqual(len(set(ordens)), len(ordens))
        xs = [b.xml for b in self.blocos()]
        i = xs.index("<p>n0</p>")
        self.assertEqual(xs[i:i + 3], ["<p>n0</p>", "<p>n1</p>", "<p>n2</p>"])

    def test_nova_edicao_procedencia(self):
        nova = Edicao.objects.create(slug="nova", titulo="N", tipo="nova")
        b = Bloco.objects.create(edicao=nova, ordem=1024, tipo="paragrafo", xml="<p>a</p>", volume=self.vol)
        servicos.salvar_blocos(nova, [b.pk], [dado(b, "<p>b</p>")], self.user)
        b.refresh_from_db()
        self.assertEqual(b.procedencia, "adaptado")
        r = servicos.salvar_blocos(nova, [], [{"id": None, "versao": None, "xml": "<p>c</p>"}], self.user)
        self.assertEqual(r.blocos[0].procedencia, "novo")


class MoverNoTest(BaseBanco):
    def setUp(self):
        from django.core.management import call_command
        from io import StringIO
        self.nova = Edicao.objects.create(slug="nova", titulo="N", tipo="nova")
        Bloco.objects.bulk_create([
            Bloco(edicao=self.nova, ordem=b.ordem, tipo=b.tipo, xml=b.xml, volume=b.volume, pagina=b.pagina, origem=b)
            for b in self.blocos() if b.tipo != "cabecalho"])
        arvore.reconstruir(self.nova)

    def ids(self):
        return [n.xml_id for n in No.objects.filter(edicao=self.nova).order_by("ordem_ini")]

    def test_so_na_nova(self):
        with self.assertRaises(servicos.ErroOperacao):
            servicos.mover_no(No.objects.get(edicao=self.edicao, xml_id="v1.t1"),
                              depois_de=No.objects.get(edicao=self.edicao, xml_id="v1.t2"))

    def test_mover_tese_depois_de_outra(self):
        t1 = No.objects.get(edicao=self.nova, xml_id="v1.t1")
        t2 = No.objects.get(edicao=self.nova, xml_id="v1.t2")
        n_antes = Bloco.objects.filter(edicao=self.nova).count()
        servicos.mover_no(t1, depois_de=t2, autor=self.user)
        self.assertEqual(self.ids(), ["v1.parte-1", "v1.cap-1", "v1.t2", "v1.t1", "v1.parte-2", "v1.t3"])
        self.assertEqual(Bloco.objects.filter(edicao=self.nova).count(), n_antes)
        rev = Revisao.objects.get(acao="mover")
        self.assertEqual((rev.autor, rev.edicao), (self.user, self.nova))
        ordens = list(Bloco.objects.filter(edicao=self.nova).order_by("ordem").values_list("ordem", flat=True))
        self.assertEqual(len(set(ordens)), len(ordens))
        # a tese movida leva seus blocos
        self.assertEqual(arvore.blocos_do_no(No.objects.get(edicao=self.nova, xml_id="v1.t1")).count(), 2)

    def test_antes_de_e_para_pai(self):
        t3 = No.objects.get(edicao=self.nova, xml_id="v1.t3")
        t1 = No.objects.get(edicao=self.nova, xml_id="v1.t1")
        servicos.mover_no(t3, antes_de=t1)
        self.assertEqual(self.ids(), ["v1.parte-1", "v1.cap-1", "v1.t3", "v1.t1", "v1.t2", "v1.parte-2"])
        self.assertEqual(No.objects.get(edicao=self.nova, xml_id="v1.t3").pai.xml_id, "v1.cap-1")
        # para_pai: último filho de parte-2
        servicos.mover_no(No.objects.get(edicao=self.nova, xml_id="v1.t3"),
                          para_pai=No.objects.get(edicao=self.nova, xml_id="v1.parte-2"))
        self.assertEqual(self.ids(), ["v1.parte-1", "v1.cap-1", "v1.t1", "v1.t2", "v1.parte-2", "v1.t3"])

    def test_mover_parte(self):
        p1 = No.objects.get(edicao=self.nova, xml_id="v1.parte-1")
        p2 = No.objects.get(edicao=self.nova, xml_id="v1.parte-2")
        servicos.mover_no(p2, antes_de=p1)
        self.assertEqual(self.ids(), ["v1.parte-2", "v1.t3", "v1.parte-1", "v1.cap-1", "v1.t1", "v1.t2"])

    def test_sem_folga_renumera(self):
        t1 = No.objects.get(edicao=self.nova, xml_id="v1.t1")
        t2 = No.objects.get(edicao=self.nova, xml_id="v1.t2")
        # comprime as ordens para forçar a renumeração geral
        for i, b in enumerate(Bloco.objects.filter(edicao=self.nova).order_by("ordem"), 1):
            Bloco.objects.filter(pk=b.pk).update(ordem=i)
        arvore.reconstruir(self.nova)
        t1, t2 = (No.objects.get(edicao=self.nova, xml_id=x) for x in ("v1.t1", "v1.t2"))
        servicos.mover_no(t1, depois_de=t2)
        self.assertEqual(self.ids(), ["v1.parte-1", "v1.cap-1", "v1.t2", "v1.t1", "v1.parte-2", "v1.t3"])

    def test_erros(self):
        t1 = No.objects.get(edicao=self.nova, xml_id="v1.t1")
        cap = No.objects.get(edicao=self.nova, xml_id="v1.cap-1")
        with self.assertRaises(servicos.ErroOperacao):
            servicos.mover_no(cap, antes_de=t1)       # nível diferente
        with self.assertRaises(servicos.ErroOperacao):
            servicos.mover_no(t1, para_pai=t1)
        with self.assertRaises(servicos.ErroOperacao):
            servicos.mover_no(t1)


class OutrosTest(BaseBanco):
    def test_blocos_da_pagina(self):
        p1 = servicos.blocos_da_pagina(self.edicao, self.vol, 1)
        self.assertTrue(any("Idea." in b.xml for b in p1))
        p2 = servicos.blocos_da_pagina(self.edicao, self.vol, 2)
        # o parágrafo da t1 começa na pág. 1 mas contém <pb n="2"> inline: aparece na página 2
        self.assertTrue(any('xml:id="v1.t1.p1"' in b.xml for b in p2))
        self.assertTrue(any(b.tipo == "cabecalho" for b in p2))
        self.assertEqual(servicos.blocos_da_pagina(self.edicao, self.vol, 99), [])

    def test_marcar_pagina(self):
        pg = Pagina.objects.get(volume=self.vol, seq=2)
        servicos.marcar_pagina(pg, "revisada", self.user)
        pg.refresh_from_db()
        self.assertEqual((pg.estado, pg.revisada_por), ("revisada", self.user))
        self.assertIsNotNone(pg.revisada_em)
        servicos.marcar_pagina(pg, "nao_revisada", self.user)
        pg.refresh_from_db()
        self.assertIsNone(pg.revisada_por)
        with self.assertRaises(servicos.ErroValidacao):
            servicos.marcar_pagina(pg, "xyz", self.user)

    def test_exportacao(self):
        t1 = No.objects.get(xml_id="v1.t1")
        x = exportacao.tei_do_no(t1)
        self.assertTrue(x.startswith("<?xml"))
        self.assertIn('type="tese"', x)
        self.assertIn('<pb n="1" facs="paginas/0001.png"/>', x)
        txt = exportacao.texto_do_no(t1)
        self.assertIn("[pág. 1]", txt)
        self.assertIn("[pág. 2]", txt)
        self.assertIn("— Notas —", txt)
        self.assertIn("[1] Nota um it. Segunda.", txt)
        self.assertNotIn("CABEC", txt)
        h = exportacao.html_do_no(t1)
        self.assertIn("<!doctype html>", h)
        self.assertIn('href="#nota-1"', h)
        v = exportacao.tei_do_volume(self.edicao, self.vol)
        self.assertIn('xml:id="t1"', v)
        self.assertNotIn("v1.t1", v)
        # autoria no teiHeader
        Revisao.objects.create(edicao=self.edicao, autor=self.user, acao="editar", lote=uuid.uuid4())
        self.assertIn("ana", exportacao.tei_do_volume(self.edicao, self.vol))

    def test_scan(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "vol1" / "paginas").mkdir(parents=True)
            (Path(d) / "vol1" / "paginas" / "0002.png").write_bytes(b"\x89PNG fake")
            with override_settings(SINIBALDI_DADOS=Path(d)):
                self.assertEqual(scans.caminho_scan(self.vol, 2).name, "0002.png")
                self.assertEqual(scans.caminho_scan(1, 2).name, "0002.png")
                self.assertIsNone(scans.caminho_scan(self.vol, 3))
                self.assertIsNone(scans.caminho_scan(9, 2))
                r = self.client.get(reverse("obra:scan", args=[1, 2]))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r["Content-Type"], "image/png")
                self.assertIn("max-age", r["Cache-Control"])
                r.close()
                self.assertEqual(self.client.get(reverse("obra:scan", args=[1, 3])).status_code, 404)
        self.assertEqual(reverse("obra:scan", args=[1, -14]), "/scan/1/-14.png")

    def test_scan_jpg(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c:
            (Path(d) / "vol1" / "paginas").mkdir(parents=True)
            Image.new("L", (2400, 3000), 200).save(Path(d) / "vol1" / "paginas" / "0002.png")
            with override_settings(SINIBALDI_DADOS=Path(d), SINIBALDI_CACHE=Path(c)):
                url = reverse("obra:scan_jpg", args=[1, 2])
                self.assertEqual(url, "/scan/1/2.jpg")
                r = self.client.get(url, {"l": 1000})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r["Content-Type"], "image/jpeg")
                self.assertIn("max-age", r["Cache-Control"])
                corpo = b"".join(r.streaming_content)
                r.close()
                import io
                im = Image.open(io.BytesIO(corpo))
                self.assertEqual((im.format, im.width, im.height, im.mode), ("JPEG", 1000, 1250, "L"))
                cache = Path(c) / "scans" / "v1_0002_1000.jpg"
                self.assertTrue(cache.is_file())
                self.assertEqual(list((Path(c) / "scans").glob("*.tmp")), [])
                # reuso: o cache não é regerado
                m = cache.stat().st_mtime_ns
                from unittest import mock
                with mock.patch("obra.scans._gera_jpg", side_effect=AssertionError("regerou")):
                    r = self.client.get(url, {"l": 1000})
                    self.assertEqual(r.status_code, 200)
                    r.close()
                self.assertEqual(cache.stat().st_mtime_ns, m)
                r = self.client.get(url, {"l": 1600})
                self.assertEqual(r.status_code, 200)
                r.close()
                self.assertTrue((Path(c) / "scans" / "v1_0002_1600.jpg").is_file())
                # inexistente, largura não permitida ou ausente
                self.assertEqual(self.client.get(reverse("obra:scan_jpg", args=[1, 3]), {"l": 1000}).status_code, 404)
                self.assertEqual(self.client.get(url, {"l": 777}).status_code, 404)
                self.assertEqual(self.client.get(url, {"l": "x"}).status_code, 404)
                self.assertEqual(self.client.get(url).status_code, 404)
                # o PNG continua
                r = self.client.get(reverse("obra:scan", args=[1, 2]))
                self.assertEqual(r["Content-Type"], "image/png")
                r.close()

    def test_grupo_editores(self):
        from django.contrib.auth.models import Group
        g = Group.objects.get(name="editores")
        self.assertEqual(set(g.permissions.values_list("codename", flat=True)),
                         {"add_bloco", "change_bloco", "delete_bloco"})
