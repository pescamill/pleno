"""Federal judiciary: stenographic versions of the Supreme Court's plenary sessions (scjn.gob.mx).

The index lists 20 PDFs per page, newest first. robots.txt allows both the index and the files.
Ministers are named by surname in the transcript («SEÑORA MINISTRA BATRES GUADARRAMA»); the court's
public roster below turns that into a full name, and «SEÑOR MINISTRO PRESIDENTE» into whoever presided then.
"""

import re
import urllib.parse

from pleno.normalize import fold
from pleno.sources.base import CACHE_DIR, Document, fetch_cached, pdf_text
from pleno.sources.transcript import clean, parse_label, spanish_date, split_turns

NAME = "scjn"
BASE = "https://www.scjn.gob.mx"
INDEX = BASE + "/multimedia/versiones-taquigraficas?fecha=All&field_vsts_instancia_target_id_1=All&page={page}"
INSTITUTIONS = [
    {"id": "scjn", "name": "Suprema Corte de Justicia de la Nación", "level": "federal", "state": None, "kind": "judicial"},
]
MINISTERS = [
    # Court elected in 2025 (took office 1 September 2025)
    "Hugo Aguilar Ortiz", "Lenia Batres Guadarrama", "Yasmín Esquivel Mossa", "Loretta Ortiz Ahlf",
    "María Estela Ríos González", "Sara Irene Herrerías Guerra", "Giovanni Azael Figueroa Mejía",
    "Irving Espinosa Betanzo", "Arístides Rodrigo Guerrero García",
    # Until 31 August 2025
    "Norma Lucía Piña Hernández", "Luis María Aguilar Morales", "Alfredo Gutiérrez Ortiz Mena",
    "Juan Luis González Alcántara Carrancá", "Jorge Mario Pardo Rebolledo", "Javier Laynez Potisek",
    "Alberto Pérez Dayán", "Ana Margarita Ríos Farjat",
]
PRESIDENTS = [("2025-09-01", "Hugo Aguilar Ortiz"), ("2023-01-02", "Norma Lucía Piña Hernández")]
LABEL_RE = re.compile(
    r"(?m)^(?P<label>(?:SEÑOR|SEÑORA)\s+MINIS\s?TR[OA](?:\s+PRESIDENT[EA])?(?:\s+[A-ZÁÉÍÓÚÑ]+){0,5}"
    r"|SECRETARI[OA](?:\s+GENERAL)?\s+DE\s+ACUERDOS)\s*:")


def _key(text):
    return re.sub(r"[^a-z]", "", fold(text))


SURNAMES = {}
for full in MINISTERS:
    parts = full.split()
    for k in (2, 3, 4):
        SURNAMES.setdefault(_key(" ".join(parts[-k:])), full)


def speaker(label, date):
    if re.search(r"ACUERDOS", label):
        return "Secretaría General de Acuerdos", None
    role, _ = parse_label(label.replace("MINIS TRO", "MINISTRO"))
    rest = re.sub(r"(?i)^se[ñn]ora?\s+minis\s?tr[oa]\s*(president[ea])?\s*", "", label).strip()
    if rest:
        full = SURNAMES.get(_key(rest))
        return role, full or rest.title()
    if "PRESIDENT" in label:
        return role, next((name for start, name in PRESIDENTS if date >= start), None)
    return role, None


def listing(since, delay=1.0, max_pages=220):
    """(date, url) for every plenary PDF newer than `since`, newest first."""
    seen = set()
    for page in range(max_pages):
        raw = fetch_cached(INDEX.format(page=page), CACHE_DIR / NAME / "indice" / f"{page}.html",
                           delay=delay, max_age=12 * 3600)
        hrefs = re.findall(r'href="(/sites/default/files/versiones-taquigraficas/documento/[^"]+\.pdf)"',
                           (raw or b"").decode("utf-8", "replace"))
        if not hrefs:
            return
        oldest = None
        for href in hrefs:
            url = BASE + href
            name = urllib.parse.unquote(href.rsplit("/", 1)[1])
            date = spanish_date(name) or href.split("/")[-2]
            oldest = date
            if date >= since and url not in seen:
                seen.add(url)
                yield date, url
        if oldest and oldest < since:
            return


def documents(since="2024-09-01", delay=1.0):
    taken = set()
    for date, url in listing(since, delay):
        if date in taken:          # a second «versión definitiva» of the same session
            continue
        taken.add(date)
        try:
            text = pdf_text(url, CACHE_DIR / NAME / "pdf" / f"{date}.pdf", delay=delay)
        except Exception as err:
            print(f"  scjn: omitido {url} ({type(err).__name__})")
            continue
        if not text:
            continue
        turns = split_turns(clean(text), LABEL_RE, parse=lambda label: speaker(label, date))
        if turns:
            yield Document(id=f"scjn:{date}", institution_id="scjn", kind="sesion", date=date,
                           title=f"Sesión del Pleno de la Suprema Corte del {date}", source_url=url, turns=turns)
