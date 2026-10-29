import csv as csvlib
import io

import pytest
from fastapi.testclient import TestClient

from pleno import answer, api, db, ingest, nlq, search
from pleno.normalize import find_laws, same_person, slug, title_name
from pleno.search import Query
from pleno.sources import diputados, mananeras
from pleno.sources.base import Document, Turn, legislature_for

SESSION_HTML = """<html><head><meta charset="utf-8"></head><body>
<font>Versión estenográfica de la sesión ordinaria del martes 14 de octubre de 2025</font>
<p><a name="zaper"></a><b>La presidenta diputada Kenia López Rabadán:</b> Se abre la sesión.</p>
<p><b>La presidenta diputada Kenia López Rabadán:</b> Tiene la palabra la diputada Laura Irais Ballesteros Mancilla, del Grupo Parlamentario de Movimiento Ciudadano, hasta por cinco minutos.</p>
<p><b>La diputada Laura Irais Ballesteros Mancilla:</b> Con su venia. Esta reforma a la Ley de Amparo es regresiva.</p>
<p>Lo digo con claridad: la Constitución Política de los Estados Unidos Mexicanos protege a las personas.</p>
<p>(Aplausos)</p>
<p><b>El diputado Ricardo Monreal Ávila</b> (desde la curul): Presidenta, la Ley de Amparo se discutió ampliamente.</p>
</body></html>"""

MANANERA = """Versión estenográfica. Conferencia de prensa de la presidenta Claudia Sheinbaum Pardo del 3 de marzo de 2025
Presidencia de la República
3 de marzo de 2025
---
PRESIDENTA DE MÉXICO, CLAUDIA SHEINBAUM PARDO
Buenos días. Vamos a hablar del agua y de la Ley General de Aguas.
---
PREGUNTA
Muchas gracias. Por cierto, mi nombre es José Lebeña, de Publimetro. ¿Qué pasará con el agua en Monterrey?
---
SECRETARIA DE GOBERNACIÓN, ROSA ICELA RODRÍGUEZ VELÁZQUEZ
Sobre el agua, la Ley General de Aguas se presentará pronto.
"""


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "t.db")
    c = db.connect()
    for source in (diputados, mananeras):
        ingest.upsert_institutions(c, source)
    title, turns = diputados.parse_session(SESSION_HTML.encode(), "u")
    ingest.load_document(c, Document("diputados:2025-10-14", "diputados", "sesion", "2025-10-14", title,
                                     "https://cronica.diputados.gob.mx/Ve14oct2025.html", "LXVI", turns), "diputados")
    ingest.load_document(c, mananeras.parse_transcript(MANANERA, "2025/marzo/03--x.txt"), "presidencia")
    ingest.merge_short_names(c)
    ingest.assign_parties(c)
    c.commit()
    nlq._people_index.cache_clear()
    return c


def test_normalize_helpers():
    assert title_name("ROSA ICELA RODRÍGUEZ DE LA CRUZ") == "Rosa Icela Rodríguez de la Cruz"
    assert same_person("Mariana Gómez del Campo", "Mariana Gómez del Campo Gurza")
    assert not same_person("Gómez", "Mariana Gómez del Campo Gurza")
    assert slug("Ley de Amparo") == "ley-de-amparo"
    assert set(find_laws("reforma a la Ley General de Aguas y a la Ley de Amparo, en lo")) == {"Ley General de Aguas", "Ley de Amparo"}
    assert legislature_for("2025-10-14") == "LXVI" and legislature_for("2024-08-31") == "LXV"


@pytest.mark.parametrize("header,role,name", [
    ("PRESIDENTA DE MÉXICO, CLAUDIA SHEINBAUM PARDO", "Presidenta de México", "Claudia Sheinbaum Pardo"),
    ("PRESIDENTE ANDRÉS MANUEL LÓPEZ OBRADOR", "Presidente de México", "Andrés Manuel López Obrador"),
    ("SECRETARIA DE GOBERNACIÓN, ROSA ICELA RODRÍGUEZ VELÁZQUEZ", "Secretaria de Gobernación", "Rosa Icela Rodríguez Velázquez"),
    ("ZOÉ ROBLEDO ABURTO, DIRECTOR GENERAL DEL IMSS", "Director General del Imss", "Zoé Robledo Aburto"),
    ("PREGUNTA", "Periodista", None),
    ("PRESIDENTA MUNICIPAL DE ECATEPEC, AZUCENA CISNEROS COSS", "Presidenta Municipal de Ecatepec", "Azucena Cisneros Coss"),
    ("PRESIDENTE DEL CONSEJO GENERAL DEL INE, LORENZO CÓRDOVA VIANELLO", "Presidente del Consejo General del Ine", "Lorenzo Córdova Vianello"),
    ("HUGO LÓPEZ-GATELL RAMÍREZ", None, "Hugo López-gatell Ramírez"),
])
def test_mananera_speakers(header, role, name):
    assert mananeras.parse_speaker(header) == (role, name)


def test_outlet_is_taken_only_when_stated():
    doc = mananeras.parse_transcript(MANANERA, "2025/marzo/03--x.txt")
    press = [t for t in doc.turns if t.role == "Periodista"]
    assert press[0].outlet == "Publimetro"
    assert doc.date == "2025-03-03"


def test_session_parsing_joins_paragraphs_and_drops_stage_directions():
    title, turns = diputados.parse_session(SESSION_HTML.encode(), "u")
    assert title.startswith("Versión estenográfica de la sesión ordinaria")
    assert [t.name for t in turns] == ["Kenia López Rabadán"] * 2 + ["Laura Irais Ballesteros Mancilla", "Ricardo Monreal Ávila"]
    assert turns[0].role == "Presidenta de la Mesa (Diputada)"
    assert "Constitución" in turns[2].text and "Aplausos" not in turns[2].text


def test_party_comes_from_the_transcript(con):
    row = con.execute("SELECT party, source FROM people WHERE id = 'laura-irais-ballesteros-mancilla'").fetchone()
    assert tuple(row) == ("MC", "mencionado en sesión")


def test_reloading_unchanged_document_is_a_noop(con):
    doc = mananeras.parse_transcript(MANANERA, "2025/marzo/03--x.txt")
    assert ingest.load_document(con, doc, "presidencia") is False


def test_structured_search_combines_text_and_metadata(con):
    hits = search.search(con, Query(texto="amparo", partidos=["MC"]))
    assert hits["total"] == 1 and hits["resultados"][0]["person"] == "Laura Irais Ballesteros Mancilla"
    assert "⟦" in hits["resultados"][0]["snippet"]
    by_law = search.search(con, Query(leyes=["ley-de-amparo"]))
    assert by_law["total"] == 2
    facets = search.facets(con, Query(texto="agua"))
    assert {f["id"] for f in facets["instituciones"]} == {"presidencia"}
    assert facets["leyes"][0]["nombre"] == "Ley General de Aguas"


def test_fts_query_is_injection_safe(con):
    assert search.search(con, Query(texto='agua" OR x NEAR(* "'))["total"] >= 0


def test_profiles(con):
    p = search.person(con, "claudia-sheinbaum-pardo")
    assert p["estadisticas"]["intervenciones"] == 1 and p["cargos"][0]["role"] == "Presidenta de México"
    law = search.law(con, "ley-de-amparo")
    assert {r["nombre"] for r in law["por_partido"]} == {"MC", "Sin partido registrado"}
    doc = search.document(con, "diputados:2025-10-14")
    assert len(doc["intervenciones"]) == 4


def test_natural_language_becomes_structured_query(con, tmp_path):
    q, notes = nlq.interpret("¿Qué dijo Sheinbaum sobre el agua en 2025?", db.DB_FILE)
    assert q.personas == [] or q.personas == ["claudia-sheinbaum-pardo"]
    assert q.desde == "2025-01-01" and q.hasta == "2025-12-31"
    assert "agua" in q.texto.lower()
    q2, _ = nlq.interpret("diputados de Movimiento Ciudadano y la Ley de Amparo", db.DB_FILE)
    assert q2.instituciones == ["diputados"] and q2.partidos == ["MC"] and q2.leyes == ["ley-de-amparo"]


def test_citations_are_validated():
    text, used = answer.valid_citations("Dijo esto [1] y aquello [2, 9] y nada [7].", 3)
    assert text == "Dijo esto [1] y aquello [2] y nada ." and used == [1, 2]


def test_answer_falls_back_to_sources_without_llm(con, monkeypatch):
    monkeypatch.setattr(answer, "load_config", lambda: {"llm": {"base_url": "http://127.0.0.1:9", "model": "x"}})
    out = answer.answer(con, "¿qué se dijo del amparo?", Query(texto="amparo"))
    assert out["modelo"] is None and len(out["fuentes"]) == 2


@pytest.fixture
def client(con, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "KEYS_FILE", tmp_path / "keys.json")
    (tmp_path / "keys.json").write_text('{"k-pro": {"cliente": "demo", "plan": "pro"}}')
    api._windows.clear()
    monkeypatch.setattr(api._local, "con", con, raising=False)
    return TestClient(api.app)


def test_api_search_and_validation(client):
    r = client.post("/api/v1/buscar", json={"texto": "amparo"})
    assert r.status_code == 200 and r.json()["total"] == 2
    assert client.post("/api/v1/buscar", json={"limite": 1000}).status_code == 422
    assert client.get("/api/v1/personas/no-existe").status_code == 404


def test_api_keys_and_rate_limit(client, monkeypatch):
    assert client.get("/api/v1/estado", headers={"x-api-key": "nope"}).status_code == 401
    assert client.get("/api/v1/estado", headers={"x-api-key": "k-pro"}).status_code == 200
    monkeypatch.setitem(api.PLANS, "anonimo", 2)
    codes = [client.get("/api/v1/estado").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_unnamed_speakers_and_head_of_state_in_the_chamber():
    from pleno.normalize import clean_person_name
    assert clean_person_name("Beneficiaria del Programa Vivienda para el Bienestar") is None
    assert clean_person_name("Habitante de Tlaxiaco, Oaxaca") is None
    assert clean_person_name("presidente José Gerardo Rodolfo Fernández Noroña") == "José Gerardo Rodolfo Fernández Noroña"
    assert diputados.parse_speaker("La presidenta constitucional Claudia Sheinbaum Pardo") == ("Presidenta de México", "Claudia Sheinbaum Pardo")


def test_law_names_keep_their_connectors():
    assert find_laws("la Ley del Impuesto sobre la Renta y la Ley del Impuesto al Valor Agregado") == [
        "Ley del Impuesto al Valor Agregado", "Ley del Impuesto sobre la Renta"]


def test_name_variants_fold_into_the_most_used_person(con):
    def person(pid, name, n):
        con.execute("INSERT INTO people(id, name) VALUES (?, ?)", (pid, name))
        for i in range(n):
            con.execute("INSERT INTO turns(document_id, idx, speaker, person_id, text) VALUES ('diputados:2025-10-14', ?, ?, ?, 'x')",
                        (100 + i + len(pid) * 50, name, pid))
    person("omar-garcia-harfuch", "Omar García Harfuch", 12)
    person("omar-hamid-garcia-harfuch", "Omar Hamid García Harfuch", 1)
    person("erubiel-lorenzo-alonso-que", "Erubiel Lorenzo Alonso Que", 5)
    person("alonso-que-erubiel-lorenzo", "Alonso Que Erubiel Lorenzo", 1)
    assert ingest.merge_reordered(con) == 1
    ingest.merge_short_names(con)
    ids = {r[0] for r in con.execute("SELECT id FROM people")}
    assert "omar-hamid-garcia-harfuch" not in ids and "alonso-que-erubiel-lorenzo" not in ids
    assert con.execute("SELECT COUNT(*) FROM turns WHERE person_id = 'omar-garcia-harfuch'").fetchone()[0] == 13


def test_api_home_suggest_export_and_labels(client, monkeypatch):
    monkeypatch.setattr(search, "_panorama", {})
    home = client.get("/api/v1/panorama").json()
    assert home["hasta"] == "2025-10-14" and home["leyes_en_alza"][0]["n"] >= 1
    assert {d["id"] for docs in home["recientes"].values() for d in docs} == {"diputados:2025-10-14", "mananeras:2025/marzo/03--x"}

    s = client.get("/api/v1/sugerir?q=ballesteros").json()
    assert s["personas"][0]["id"] == "laura-irais-ballesteros-mancilla"
    assert client.get("/api/v1/sugerir?q=a").status_code == 422

    r = client.post("/api/v1/buscar", json={"leyes": ["ley-de-amparo"], "personas": ["laura-irais-ballesteros-mancilla"]})
    body = r.json()
    assert body["etiquetas"] == {"ley-de-amparo": "Ley de Amparo", "laura-irais-ballesteros-mancilla": "Laura Irais Ballesteros Mancilla"}
    assert {"id": "ley-de-amparo", "nombre": "Ley de Amparo"} in body["resultados"][0]["leyes"]
    assert body["facetas"]["meses"] == [{"id": "2025-10", "n": 1}]

    csv = client.post("/api/v1/exportar", json={"texto": "amparo"})
    rows = list(csvlib.reader(io.StringIO(csv.text.lstrip("\ufeff"))))
    assert csv.headers["content-type"].startswith("text/csv") and rows[0][:2] == ["fecha", "institucion"]
    assert len(rows) == 3 and any("Ley de Amparo" in r[7] for r in rows[1:])


def test_autocomplete_has_its_own_rate_bucket(client, monkeypatch):
    monkeypatch.setitem(api.PLANS, "anonimo", 1)
    assert client.get("/api/v1/estado").status_code == 200
    assert client.get("/api/v1/estado").status_code == 429
    assert client.get("/api/v1/sugerir?q=agua").status_code == 200


# ---------- multi-source: transcripts, standardization, votes, alerts ----------

from pleno import actualizar, fuentes
from pleno.sources import estatales, scjn as scjn_src, transcript


def test_pdf_transcript_cleaning_and_labels():
    pages = ["Congreso de la Ciudad de México  Pág. 1\nLA C. PRESIDENTA.- Se abre la\nsesión.\n1",
             "Congreso de la Ciudad de México  Pág. 2\nLA C. DIPUTADA CLAUDIA SUSANA PÉREZ\nROMERO.- Con su venia. La Ley de Ingre-\nsos es clave.\n2",
             "Congreso de la Ciudad de México  Pág. 3\nEL C. SECRETARIO DIPUTADO JUAN ESTUARDO RUBIO GUALITO.- Se aprueba.\n3"]
    text = transcript.clean("\f".join(pages))
    assert "Pág." not in text and "Ingresos es clave" in text
    turns = transcript.split_turns(text, estatales.CDMX.label_re)
    assert [(t.role, t.name) for t in turns] == [
        ("Presidenta de la Mesa", None), ("Diputada", "Claudia Susana Pérez Romero"),
        ("Secretario de la Mesa (Diputado)", "Juan Estuardo Rubio Gualito")]
    assert transcript.parse_label("A LA C. DIP. ANA MELISA PEÑA VILLAGÓMEZ") == ("Diputada", "Ana Melisa Peña Villagómez")
    assert transcript.spanish_date("Sesión del 5 de octubre de 2026") == "2026-10-05"


def test_supreme_court_names_ministers_by_surname_and_date():
    assert scjn_src.speaker("SEÑORA MINISTRA BATRES GUADARRAMA", "2026-10-26") == ("Ministra", "Lenia Batres Guadarrama")
    assert scjn_src.speaker("SEÑOR MINISTRO PRESIDENTE", "2026-10-26") == ("Ministro Presidente", "Hugo Aguilar Ortiz")
    assert scjn_src.speaker("SEÑOR MINISTRO PRESIDENTE", "2024-10-01")[1] == "Norma Lucía Piña Hernández"
    assert scjn_src.speaker("SECRETARIO GENERAL DE ACUERDOS", "2026-10-26") == ("Secretaría General de Acuerdos", None)


def test_state_index_parsers():
    cdmx = estatales._cdmx('<a href="archivo-ab12.pdf"></a><p><strong>Diario de los Debates, Año 3, 29/09/2026, No. 9, Ordinaria</strong>',
                           "https://www.congresocdmx.gob.mx/x.html")
    assert cdmx[0].date == "2026-09-29" and cdmx[0].url.endswith("/archivo-ab12.pdf") and cdmx[0].key == "9"
    tab = estatales._tabasco('<a href="https://congresotabasco.gob.mx/wp-content/uploads/2026/10/29_09_26_DSP.pdf">', "u")
    assert tab[0].date == "2026-09-29"
    nl = estatales._nl('<tr><td><h5>Año III Número 194 LXXVII</h5></td><td class="text-center">30/09/2026</td>'
                       '<td><a href="https://www.hcnl.gob.mx/x/D.D.%20197.pdf">pdf</a></td><tr>', "u")
    assert nl[0].date == "2026-09-30" and nl[0].key == "194"


def test_new_state_index_parsers():
    ver = estatales._veracruz("<tr><td>02/06/2026</td><td>Décimasegunda Sesión Ordinaria</td><td><a href=\"javascript:"
                              "PDF('../VersionEstenografica/versionLXVII/Version_02junio26_12aOrd.pdf');\">x</a></td></tr>",
                              "https://www.legisver.gob.mx/Inicio.php?p=sesiones")
    assert ver[0].date == "2026-06-02" and ver[0].key == "12aord"
    assert ver[0].url == "https://www.legisver.gob.mx/VersionEstenografica/versionLXVII/Version_02junio26_12aOrd.pdf"
    edo = estatales._edomex('<td class="encabezado"><strong>Sesión de la Diputación Permanente.\n</strong><br><strong '
                            'class="fecha"><span>\n 10 de Diciembre 2025</span></strong></td><td><a href="\n Tomo XXVII/'
                            '93-10dic25p.pdf"><img/></a></td>', "https://x.gob.mx/Diario/LXII/Tomo%20XXVII.html")
    assert edo[0].date == "2025-12-10" and edo[0].url.endswith("/LXII/Tomo XXVII/93-10dic25p.pdf")
    gto = estatales._guanajuato('<tr><td>SESIÓN ORDINARIA</td><td>26/03/2026 &nbsp;<a href="https://congreso-gto.s3.'
                                'amazonaws.com/uploads/sesion/transcripcion/1060/54.-_SESI_N.pdf" class="download">D</a></td>', "u")
    assert gto[0].date == "2026-03-26" and gto[0].key == "1060" and "Sesión ordinaria" in gto[0].title
    coah = estatales._coahuila('<tr class="rowss"><td>06/10/2026</td><td>Segundo Período</td><td>Sexta Sesión</td>'
                               '<td>LXIII</td><td class="Hide">20261006_SPO_S06.docx</td><td></td>', "u")
    assert coah[0].url == "https://www.congresocoahuila.gob.mx/congreso/TG/debates/20261006_SPO_S06.pdf"
    sin = estatales._sinaloa('[{"id_sesion": 1700, "numero": 153, "fecha": "2026-06-02", "nb_nombre": "Sesión Pública '
                             'Ordinaria", "id_legi": 65, "pdf": true}, {"id_sesion": 1743, "pdf": false, "fecha": "x"}]', "u")
    assert len(sin) == 1 and sin[0].url.endswith(":3001/pdfs/sesiones/65/Debate_1700.pdf") and sin[0].key == "153"
    tam = estatales._tamaulipas('<tr><td>1</td><td>01/10/2024 12:10:00 a.m.</td><td>Sesión Pública y Solemne</td><td><a '
                                'href="/Parlamentario/Archivos/VersionesEstenograficas/1 SESION SOLEMNE.pdf">PDF</a></td>',
                                "https://www.congresotamaulipas.gob.mx/T/V.asp")
    assert tam[0].date == "2024-10-01" and tam[0].key == "1" and tam[0].title.endswith("Sesión Pública y Solemne")
    yuc = estatales._yucatan('<tr><td>LXIV</td><td>Primer Período</td><td>Sesión Ordinaria</td><td>2026-09-30</td><td><a '
                             'href="/storage/uploadCey/e7fd15_Sesión Ordinaria-30-Septiembre-26.pdf">x</a></td></tr><tr><td>'
                             'LXIII</td><td>p</td><td>s</td><td>2023-09-30</td><td><a href="/storage/uploadCey/aa_x.pdf"></a></td>',
                             "https://www.congresoyucatan.gob.mx/gaceta/diario-debates")
    assert [e.key for e in yuc] == ["e7fd15"]
    zac = estatales._zacatecas('<a href="/o/26797" class="list-group-item">Acta 30 junio 2025 I</a>', "https://www.congresozac.gob.mx/65/v")
    assert zac[0].date == "2025-06-30" and zac[0].url == "https://www.congresozac.gob.mx/o/26797"
    dgo = estatales._durango('<tr class="row-6"><td class="column-1">30 Septiembre 2026</td><td class="column-2">1</td>'
                             '<td class="column-3"><a href="https://congresodurango.gob.mx/Archivos/LXX/ACTAS/260930.pdf">', "u")
    assert dgo[0].date == "2026-09-30" and dgo[0].key == "260930"
    col = estatales._colima('<div class="row" style="margin-bottom:20px;"><div title="Fecha" class="x">2026-10-14</div>'
                            '<div title="Descripci&oacute;n" class="y">DIARIO DEBATES SESIÓN ORDINARIA No. 2</div><a href=\''
                            '/web/Sistema/uploads/Diario_Debates/Sesion Ordinaria 02.pdf\'>', "https://congresocol.gob.mx/web/www/g/p.php")
    assert col[0].date == "2026-10-14" and col[0].url.endswith("/Diario_Debates/Sesion Ordinaria 02.pdf")
    bcs = estatales._bcs('<a href="/CONGRESO/DIARIO-DEBATES/XVII-LEGISLATURA/16-SPO-MARTES-08-OCTUBRE-2024.pdf">', "https://www.cbcs.gob.mx/x")
    assert bcs[0].date == "2024-10-08" and bcs[0].key == "16"
    chis = estatales._chiapas('<a href="https://congresochiapas.gob.mx/pdf/debates/LXIX/II/Segundo Periodo Ordinario/Mayo/'
                              'Acta_13 Mayo 2026_Sesión Ordinaria.pdf?v=MTc4" target="_blank">', "u")
    assert chis[0].date == "2026-05-13" and chis[0].url.endswith("/Acta_13 Mayo 2026_Sesión Ordinaria.pdf")
    turns = transcript.split_turns("TIENE EL USO DE LA PALABRA LA DIPUTADA LUZ MARÍA CASTILLO MORENO, DEL PARTIDO MORENA”.- "
                                   "La legisladora hizo uso de la tribuna (cuya intervención será insertada) y expresó: Muy "
                                   "buenas tardes.", estatales.CHIAPAS.label_re, min_chars=5)
    assert (turns[0].role, turns[0].name) == ("Diputada", "Luz María Castillo Moreno")


def test_state_speaker_labels_and_presiding_officers():
    text = transcript.clean(estatales._veracruz_prepare(
        "MESA DIRECTIVA DIP. NAOMI EDITH GÓMEZ SANTOS PRESIDENTA DIP. ALEJANDRO PORRAS MARÍN SECRETARIO\n"
        "- LA C. PRESIDENTA: \nBuenos días a todas y todos.\n- LA C. DIP. ANA ROSA VALDÉS SALAZAR: \nCon su venia.\n"
        "- LA C. PRESIDENTA: \nAdelante.\n- CONTINÚA LA C. DIP. ANA ROSA VALDÉS SALAZAR: \nSaludo a la asamblea.\n"))
    turns = transcript.split_turns(text, estatales.VERACRUZ.label_re, min_chars=5)
    estatales._name_officers(turns, estatales.officers(text))
    assert [(t.role, t.name) for t in turns] == [
        ("Presidenta de la Mesa", "Naomi Edith Gómez Santos"), ("Diputada", "Ana Rosa Valdés Salazar"),
        ("Presidenta de la Mesa", "Naomi Edith Gómez Santos"), ("Diputada", "Ana Rosa Valdés Salazar")]
    assert estatales.officers("BAJO LA PRESIDENCIA DE LA DIPUTADA KARINA OLIVAS PARRA PRIMER -TIMBRE-")["Presidenta"] == \
        "Karina Olivas Parra"
    found = estatales.officers("PRESIDENTE: DIPUTADO SERGIO ARTURO OJEDA CASTILLO.\n"
                               "SECRETARIOS: DIPUTADO JOSÉ ABDO SCHEKAIBÁN ONGAY Y DIPUTADA MAYRA BENAVIDES VILLAFRANCA.\n")
    assert found["Presidente"] == "Sergio Arturo Ojeda Castillo" and found["Secretaria"] == "Mayra Benavides Villafranca"
    assert estatales._parse_abbreviated("DIP. GABRIELA MONTOYA TERRAZAS") == ("Diputado(a)", "Gabriela Montoya Terrazas")
    assert estatales._parse_abbreviated("PRESIDENTA DIP. MARTHA AZUCENA CAMACHO REYNOSO")[0] == "Presidenta de la Mesa (Diputada)"
    sin = transcript.split_turns("Se concedió el uso de la palabra a la diputada Paola Iveth Gárate Valenzuela, del Grupo "
                                 "Parlamentario de Morena, quien dijo: Gracias, presidente.", estatales.SINALOA.label_re)
    assert (sin[0].role, sin[0].name) == ("Diputada", "Paola Iveth Gárate Valenzuela")


def test_state_names_are_tidied_matched_to_the_roster_and_minors_left_out():
    assert estatales.tidy_name("Yuriria Iturbe Vázquez. Secretarias") == "Yuriria Iturbe Vázquez"
    assert estatales.tidy_name("Rita Fierro Reyes P.M.D.L") == "Rita Fierro Reyes"
    assert estatales.tidy_name("Omar Ortega Álvarez Decreto Número la H") == "Omar Ortega Álvarez"
    assert estatales.tidy_name("PRESIDENTA.- Adelante") is None
    assert estatales.tidy_name("Julián César Rivas B. Nevárez") == "Julián César Rivas B. Nevárez"
    members = ["José Manuel Romero Coello", "Martín Álvarez Casio", "Irma Mirella Martínez Silva"]
    assert estatales._canonical("Jose Maue Lromero Coello", members) == "José Manuel Romero Coello"
    assert estatales._canonical("Álvarez Casio", members) == "Martín Álvarez Casio"
    assert estatales._canonical("Secretarua Irma Mirella Martiniez Silva", members) == "Irma Mirella Martínez Silva"
    assert estatales._canonical("Juan Pérez López", members) == "Juan Pérez López"
    from pleno.sources.base import Turn
    turns = [Turn("Diputado Martín Álvarez Casio", "Bienvenidos.", "Diputado", "Martín Álvarez Casio"),
             Turn("Diputada Ana Niña Pérez", "Propongo…", "Diputada", "Ana Niña Pérez"),
             Turn("Diputada Estudiantil Sara Ruiz", "Gracias.", "Diputada", "Estudiantil Sara Ruiz")]
    kept = estatales._without_minors(turns, "…se desarrollará el Parlamento Infantil 2026…", members)
    assert [t.name for t in kept] == ["Martín Álvarez Casio"]
    assert estatales._without_minors(turns[:2], "Sesión ordinaria", members) == turns[:2]
    assert estatales._squeeze("la Constitución Política del Estado de Durango14 y TEXTO VIGENTE") == \
        "la Constitución Política del Estado de Durango y "


def test_state_prosecutors_keep_names_as_published():
    from pleno.sources import fiscalias
    page = ('<h1> Fiscalía CDMX obtiene sentencia contra Atzin “N”</h1><div class="Datetime-normal"> <span> Publicado el 27 '
            'Octubre 2026 </span></div><div class="Slider-image"></div><p>Atzin “N” fue sentenciado.</p><p>Se le considera '
            'inocente…</p></div><div class="Panel-functions Share">')
    item = fiscalias.cdmx_note(page, "CS2026-373")
    assert item["date"] == "2026-10-27" and item["text"] == "Atzin “N” fue sentenciado.\nSe le considera inocente…"
    speech = fiscalias.cdmx_note(page.replace("Fiscalía CDMX obtiene sentencia contra Atzin “N”", "Participación de la fiscal "
                                 "general de Justicia de la Ciudad de México, Bertha Alcalde Luján, en la conferencia"), "VE2026-024")
    assert speech["name"] == "Bertha Alcalde Luján"
    jal = fiscalias.jalisco_items('{"items": [{"id": 3608, "title": "VINCULADO A PROCESO", "description": "Felipe de Jesús '
                                  '“N” fue vinculado", "rendered_content": "<p>Los hechos…</p>", "fecha_publicacion": '
                                  '"2025-09-26", "meta": {"html_url": "https://fiscalia.jalisco.gob.mx/api/comunicacion-social/'
                                  'boletines-de-prensa/x/"}}]}')
    assert jal[0]["url"] == "https://fiscalia.jalisco.gob.mx/comunicacion-social/boletines-de-prensa/x/"
    assert "Felipe de Jesús “N”" in jal[0]["text"]
    gro = fiscalias.guerrero_items('[{"id": 6652, "date": "2026-10-27T04:44:18", "link": "https://fiscaliaguerrero.gob.mx/x/", '
                                   '"title": {"rendered": "DETIENE A CARLOS &#171;N&#187;"}, "content": {"rendered": "<p>Carlos '
                                   '“N” fue detenido.</p>"}}]')
    assert gro[0]["date"] == "2026-10-27" and gro[0]["title"] == "DETIENE A CARLOS «N»"
    doc = next(fiscalias.Fiscalia(NAME="x", institution_name="Fiscalía X", state="Jalisco",
                                  items=lambda delay, since: jal).documents())
    assert doc.kind == "comunicado · vinculación a proceso" and doc.turns[0].name is None


def test_laws_are_standardized_against_the_federal_catalog():
    catalog = [{"name": "Ley de Amparo, Reglamentaria de los Artículos 103 y 107", "key": "ley de amparo",
                "url": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LAmp.pdf", "last_reform": "2025-10-16"}]
    from pleno import db as dbm
    c = sqlite3_connect()
    r = ingest.LawResolver(catalog)
    assert r.ids(c, "la Ley de Amparo", ("estatal", "Oaxaca")) == ["ley-de-amparo"]
    assert r.ids(c, "la Ley de Anparo", ("estatal", "Oaxaca")) == ["ley-de-amparo"]   # OCR typo
    assert r.ids(c, "la Ley de Ingresos", ("estatal", "Oaxaca")) == ["ley-de-ingresos-oaxaca"]
    assert r.ids(c, "la Ley de Ingresos", ("federal", None)) == ["ley-de-ingresos"]
    row = c.execute("SELECT jurisdiction, official_url FROM laws WHERE id = 'ley-de-amparo'").fetchone()
    assert row[0] == "federal" and row[1].endswith("LAmp.pdf")
    assert find_laws("la Constitución dice", federal=False) == []
    assert find_laws("la Constitución Política del Estado Libre y Soberano de Oaxaca", federal=False) == [
        "Constitución Política del Estado de Oaxaca"]


def test_laws_that_name_a_state_are_never_federal():
    c = sqlite3_connect()
    r = ingest.LawResolver([])
    jurisdiction = lambda lid: c.execute("SELECT jurisdiction FROM laws WHERE id = ?", (lid,)).fetchone()[0]
    [gto] = r.ids(c, "conforme a la Ley Orgánica de la Fiscalía General del Estado de Guanajuato", ("estatal", "Guanajuato"))
    assert jurisdiction(gto) == "Guanajuato"
    # A federal source citing a state constitution points to the same law the state congress cites.
    [fed] = r.ids(c, "según la Constitución Política del Estado de Oaxaca", ("federal", None))
    [oax] = r.ids(c, "según la Constitución Política del Estado de Oaxaca", ("estatal", "Oaxaca"))
    assert fed == oax and jurisdiction(oax) == "Oaxaca"
    [cdmx] = r.ids(c, "la Ley de Defensoría Pública del Distrito Federal", ("estatal", "Ciudad de México"))
    assert jurisdiction(cdmx) == "Ciudad de México"
    assert jurisdiction(r.ids(c, "la Ley General de Salud", ("estatal", "Oaxaca"))[0]) == "federal"


def sqlite3_connect():
    import tempfile
    from pathlib import Path
    return db.connect(Path(tempfile.mkdtemp()) / "laws.db")


def test_people_are_not_merged_across_state_congresses(con):
    for inst in estatales.OAXACA.INSTITUTIONS + estatales.TABASCO.INSTITUTIONS:
        con.execute("INSERT INTO institutions(id, name, level, state, kind) VALUES (:id, :name, :level, :state, :kind)", inst)
    for doc, inst in (("congreso-oaxaca:2026-01-01", "congreso-oaxaca"), ("congreso-tabasco:2026-01-01", "congreso-tabasco")):
        con.execute("INSERT INTO documents(id, institution_id, kind, date, title, source_url, sha1) VALUES (?, ?, 'sesion', '2026-01-01', 't', 'u', 'x')", (doc, inst))
    con.execute("INSERT INTO people(id, name) VALUES ('juan-perez', 'Juan Pérez'), ('juan-perez-lopez', 'Juan Pérez López')")
    con.execute("INSERT INTO turns(document_id, idx, speaker, person_id, text) VALUES ('congreso-oaxaca:2026-01-01', 0, 'x', 'juan-perez', 'a')")
    con.execute("INSERT INTO turns(document_id, idx, speaker, person_id, text) VALUES ('congreso-tabasco:2026-01-01', 0, 'x', 'juan-perez-lopez', 'b')")
    ingest.merge_short_names(con)
    assert {r[0] for r in con.execute("SELECT id FROM people WHERE id LIKE 'juan-perez%'")} == {"juan-perez", "juan-perez-lopez"}


def _load_vote(con):
    ingest.load_roster(con, [
        {"official_id": "1", "name": "Laura Irais Ballesteros Mancilla", "party": "MC", "state": None, "district": "Circunscripción 5",
         "principle": "Representación proporcional", "seat": "A-1", "committees": '["Hacienda"]', "source_url": "https://sitl/1"},
        {"official_id": "2", "name": "Ricardo Monreal Ávila", "party": "MORENA", "state": "Zacatecas", "district": "Distrito 1",
         "principle": "Mayoría Relativa", "seat": "A-2", "committees": "[]", "source_url": "https://sitl/2"},
        {"official_id": "3", "name": "Ana Prueba Morena", "party": "MORENA", "state": "Zacatecas", "district": "Distrito 2",
         "principle": "Mayoría Relativa", "seat": "A-3", "committees": "[]", "source_url": "https://sitl/3"},
        {"official_id": "4", "name": "Beto Prueba Morena", "party": "MORENA", "state": "Zacatecas", "district": "Distrito 3",
         "principle": "Mayoría Relativa", "seat": "A-4", "committees": "[]", "source_url": "https://sitl/4"}])
    ingest.load_votes(con, [{"id": "diputados:lxvi:9", "date": "2025-10-01", "title": "DECRETO EN MATERIA DE AMPARO",
                             "source_url": "https://sitl/v9", "A favor": 3, "En contra": 1, "Abstención": 0, "Ausente": 0, "otros": 0,
                             "casts": [("1", "x", "MC", "En contra"), ("2", "x", "MORENA", "En contra"),
                                       ("3", "x", "MORENA", "A favor"), ("4", "x", "MORENA", "A favor")]}])
    ingest.assign_parties(con)
    con.commit()


def test_roster_matches_speakers_and_votes_show_party_discipline(con):
    _load_vote(con)
    person = search.person(con, "ricardo-monreal-avila")
    assert person["persona"]["party"] == "MORENA" and person["persona"]["source"] == "padrón oficial"
    assert person["padron"][0]["committees"] == []
    assert person["votaciones"]["n_contra_bancada"] == 1
    v = search.vote(con, "diputados:lxvi:9")
    assert v["por_partido"]["MORENA"] == {"En contra": 1, "A favor": 2}
    assert [c["nombre"] for c in v["votos"] if c["contra_bancada"]] == ["Ricardo Monreal Ávila"]
    assert search.votes_search(con, "amparo")["total"] == 1


def test_alerts_report_only_new_turns_and_publish_rss(con):
    aid = actualizar.create_alert(con, "Amparo", {"texto": "amparo"})
    alert = next(a for a in actualizar.list_alerts(con) if a["id"] == aid)
    assert alert["nuevas"] == 0
    assert "<rss" in actualizar.rss(con, alert) and "Ballesteros" in actualizar.rss(con, alert)


def test_state_questions_and_sources_registry(con):
    q, _ = nlq.interpret("diputados de Oaxaca que hablan del agua", db.DB_FILE)
    assert q.estados == ["Oaxaca"] and "diputados" not in q.instituciones and q.texto == "agua"
    q, _ = nlq.interpret("¿Qué dijo la presidenta sobre Jalisco?", db.DB_FILE)
    assert q.estados == [] and "Jalisco" in q.texto
    reg = fuentes.registry(con)
    assert {f["estatus"] for f in reg} >= {"integrada", "bloqueada", "sin publicar"}
    assert next(f for f in reg if f["id"] == "diputados")["cobertura"]["documentos"] == 1


def test_api_votes_sources_and_alerts(client, con):
    _load_vote(con)
    assert client.get("/api/v1/votaciones?q=amparo").json()["total"] == 1
    assert client.get("/api/v1/votaciones/diputados:lxvi:9").status_code == 200
    assert len(client.get("/api/v1/fuentes").json()) > 30
    r = client.post("/api/v1/alertas", json={"nombre": "Amparo", "consulta": {"texto": "amparo"}}).json()
    assert client.get(r["rss"]).headers["content-type"].startswith("application/rss+xml")
    assert client.delete(f"/api/v1/alertas/{r['id']}").status_code == 200
    body = client.post("/api/v1/buscar", json={"texto": "amparo"}).json()
    assert body["votaciones"]["total"] == 1


def test_prosecutor_releases_keep_names_as_published():
    from pleno.sources import fgr
    page = ("<div>Comunicado FGR DPE/4855/2026 26 de octubre, 2026 Toluca, Estado de México Obtiene FGR vinculación a "
            "proceso contra José “N” por portación de arma. La Fiscalía General de la República (FGR) obtuvo… oOo Regresar</div>")
    item = fgr.parse(page, 1)
    assert item["date"] == "2026-10-26" and item["place"] == "Toluca, Estado de México"
    assert item["title"].startswith("Obtiene FGR vinculación") and "José “N”" in item["text"]
    assert fgr.kind_of(item["title"]) == "vinculación a proceso"
    assert fgr.kind_of("Obtiene FGR sentencia condenatoria contra dos personas") == "sentencia"


def test_law_names_drop_what_pdfs_glue_on():
    from pleno.normalize import find_laws
    text = ("conforme a la Ley de Procedimiento Administrativo de la Ciudad de México20 y la Ley Orgánica del "
            "Congreso de la Ciudad de México TEXTO VIGENTE TEXTO PROPUESTO, la Ley Orgánica de Alcaldías de la "
            "Ciudad de México y Ley para la Integración al Desarrollo de las Personas, la Ley del ISSSTE y la "
            "Ley de Defensoría Pública del Distrito Federal La reforma, la Ley Orgánica del Doc ID")
    assert find_laws(text, federal=False) == [
        "Ley Orgánica de Alcaldías de la Ciudad de México", "Ley Orgánica del Congreso de la Ciudad de México",
        "Ley de Defensoría Pública del Distrito Federal", "Ley de Procedimiento Administrativo de la Ciudad de México",
        "Ley del ISSSTE", "Ley para la Integración al Desarrollo de las Personas"]


def test_dataset_masks_private_people_and_detainees():
    from pleno import dataset
    text = ("Se detuvo a Juan \"N\" y a Cecilia \"N\", alias “La Güera”. Juan \"N\" fue vinculado a proceso. "
            "Informes al 55 1234 5678 o a prensa@fgr.org.mx")
    out = dataset.mask_contacts(dataset.mask_detainees(text))
    assert "Juan" not in out and "Cecilia" not in out and "Güera" not in out
    assert out.count("Persona A “N”") == 2 and "Persona B “N”" in out
    assert "[teléfono]" in out and "[correo]" in out
    assert dataset.license_of("presidencia") == "cc-by-sa-4.0"
    assert dataset.license_of("scjn") == "textos-oficiales"


def test_dataset_vote_tasks_have_exact_answers():
    from pleno import dataset
    votes = [{"id": "v1", "fecha": "2025-01-01", "titulo": "Decreto X", "fuente": "https://x"}]
    casts = [{"votacion": "v1", "nombre": "Ana Pérez", "partido": "PAN", "sentido": "En contra", "contra_bancada": True}]
    [task] = dataset.vote_tasks(votes, casts)
    assert task["respuesta"] == "En contra" and "Ana Pérez" in task["pregunta"] and task["fuente"] == "https://x"


def test_crime_figures_compare_the_same_months():
    from pleno import estadistica
    rows = [{"anio": 2025, "mes": m, "metodologia": "2015-2025", "valor": 10} for m in range(1, 13)] + \
           [{"anio": 2026, "mes": m, "metodologia": "2026", "valor": 8} for m in range(1, 10)]
    cmp = estadistica.compare(rows, 2026)
    assert cmp["anio_anterior"] == 90 and cmp["valor"] == 72 and cmp["cambio_pct"] == -20.0
    assert cmp["cambio_de_metodologia"]
    assert estadistica.crime_in("¿Bajaron los homicidios?")[1] == "Homicidio doloso"
    assert estadistica.crime_in("feminicidios en Jalisco")[1] == "Feminicidio"
    assert estadistica.crime_in("el agua en Monterrey") is None


SITL_SUMMARY = """<a href="listados_votacionesnplxvi.php?partidot=14&votaciont=2" class="estilolinks">MORENA</a>
<a href="listados_votacionesnplxvi.php?partidot=5&votaciont=2" class="estilolinks">PVEM</a>
<a href="listados_votacionesnplxvi.php?partidot=2&votaciont=2" class="estilolinks">PRD</a>
<a href="listados_votacionesnplxvi.php?partidot=7&votaciont=2" class="estilolinks"> </a>"""


def test_vote_party_comes_from_the_vote_summary_not_the_site_id():
    from pleno.sources import sitl
    parties = sitl.summary_parties(SITL_SUMMARY, "2")
    # Id 2 is not a current bench but the summary names it; an unlabelled id stays unknown instead of a number.
    assert parties == {"14": "MORENA", "5": "PVEM", "2": "PRD", "7": None}


def test_numeric_parties_are_repaired_and_flagged_by_the_eval(con):
    from pleno import evaluar
    _load_vote(con)
    con.execute("UPDATE vote_casts SET party = '2' WHERE official_id = '1'")
    assert evaluar.integrity(con)["votos_con_partido_desconocido"] == 1
    assert ingest.repair_vote_parties(con) == 1
    assert evaluar.integrity(con)["votos_con_partido_desconocido"] == 0
    assert con.execute("SELECT party FROM vote_casts WHERE official_id = '1'").fetchone()[0] == "PRD"


def test_unlabelled_party_falls_back_to_the_roster(con):
    _load_vote(con)
    ingest.load_votes(con, [{"id": "diputados:lxvi:10", "date": "2025-10-02", "title": "OTRA", "source_url": "https://sitl/v10",
                             "A favor": 1, "En contra": 0, "Abstención": 0, "Ausente": 0, "otros": 0,
                             "casts": [("2", "x", None, "A favor")]}])
    assert con.execute("SELECT party FROM vote_casts WHERE vote_id = 'diputados:lxvi:10'").fetchone()[0] == "MORENA"


def test_reported_errors_stay_fixed(con):
    from pleno import evaluar
    _load_vote(con)
    case = {"id": "T1", "tipo": "partido_voto", "votacion": "diputados:lxvi:9", "persona": "ricardo-monreal-avila", "espera": "MORENA"}
    assert evaluar.reports(con, [case])["corregidos_pct"] == 100
    con.execute("UPDATE vote_casts SET party = 'PT' WHERE person_id = 'ricardo-monreal-avila'")
    out = evaluar.reports(con, [case])
    assert out["corregidos_pct"] == 0 and out["fallos"][0]["obtuvo"] == "PT"


def test_report_cases_file_is_well_formed():
    import json
    from pleno import evaluar
    cases = json.loads((evaluar.GOLD_DIR / "reportes.json").read_text(encoding="utf-8"))
    required = {"partido_voto": {"votacion", "persona"}, "persona_intervencion": {"documento", "texto"}, "veredicto": {"afirmacion"}}
    for c in cases:
        assert {"id", "fecha", "origen", "descripcion", "tipo", "espera"} <= c.keys()
        assert required[c["tipo"]] <= c.keys()
    assert len({c["id"] for c in cases}) == len(cases)


def test_quick_install_repairs_the_downloaded_database(tmp_path):
    import sqlite3
    from pleno import instalador
    path = tmp_path / "descargada.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE vote_casts(vote_id, person_id, official_id, party, sense)")
    con.execute("INSERT INTO vote_casts VALUES ('diputados:lxvi:2', 'x', '50', '2', 'En contra')")
    con.commit(); con.close()
    instalador._repair(path)
    assert sqlite3.connect(path).execute("SELECT party FROM vote_casts").fetchone()[0] == "PRD"


def test_catch_up_on_open(tmp_path, monkeypatch):
    """Opening Pleno pulls what is new only when the last update is old and none is running."""
    from pleno import actualizar
    monkeypatch.setattr(actualizar, "LAST_FILE", tmp_path / "ultima.txt")
    monkeypatch.setattr(actualizar, "LOG_FILE", tmp_path / "actualizaciones.log")
    monkeypatch.setattr(actualizar, "LOCK_FILE", tmp_path / "actualizando.lock")
    monkeypatch.delenv("PLENO_SIN_ACTUALIZAR", raising=False)
    assert actualizar.pendiente()                      # never updated
    actualizar.LAST_FILE.write_text(str(1000.0))
    assert not actualizar.pendiente(now=1000 + actualizar.STALE - 1)
    assert actualizar.pendiente(now=1000 + actualizar.STALE + 1)
    actualizar.LOCK_FILE.write_text("1")               # the daily run is going: do not start another
    assert actualizar.en_curso() and not actualizar.pendiente(now=10**12)
    assert actualizar.actualizar() is None
    actualizar.LOCK_FILE.unlink()
    monkeypatch.setenv("PLENO_SIN_ACTUALIZAR", "1")
    assert not actualizar.pendiente(now=10**12)


def test_update_releases_its_lock_and_records_the_time(tmp_path, monkeypatch):
    from pleno import actualizar
    monkeypatch.setattr(actualizar, "LAST_FILE", tmp_path / "ultima.txt")
    monkeypatch.setattr(actualizar, "LOCK_FILE", tmp_path / "actualizando.lock")
    monkeypatch.setattr(actualizar, "_actualizar", lambda *a: "resumen.md")
    assert actualizar.actualizar() == "resumen.md"
    assert not actualizar.LOCK_FILE.exists() and actualizar.ultima() > 0
    monkeypatch.setattr(actualizar, "_actualizar", lambda *a: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        actualizar.actualizar()
    assert not actualizar.LOCK_FILE.exists()
