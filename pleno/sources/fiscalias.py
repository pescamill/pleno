"""State prosecutors' press releases: Ciudad de México, Jalisco and Guerrero. Same rules as fgr.py.

Releases name people the way the prosecutor publishes them («José “N”»), to protect the presumption of
innocence. Pleno keeps exactly that: it never completes a name from another source and never builds a
profile of a detained person. Each release becomes one document with a single turn spoken by the
prosecutor's office; the only named speaker is the head of the office in the transcripts of her own
speeches («Participación de la fiscal general …, Bertha Alcalde Luján, en …»).

Only press releases are read. Missing-person alerts (Alerta Amber, «¿Has visto a…?», Protocolo Alba) are
left out on purpose: they are about private people, often children, and stop being relevant once found.

Checked by hand on 27 Oct 2026: fgjcdmx.gob.mx has an empty robots.txt, fiscalia.jalisco.gob.mx has none,
fiscaliaguerrero.gob.mx only closes /wp-admin/.
"""

import html as htmllib
import json
import re
import urllib.error
from dataclasses import dataclass, field

from pleno.sources.base import CACHE_DIR, Document, Turn, fetch_cached
from pleno.sources.fgr import kind_of
from pleno.sources.transcript import spanish_date

INDEX_TTL = 6 * 3600
FRESH_PAGES = 3          # the newest index pages are re-read; older ones only shift, and were read already


def _text(fragment):
    fragment = re.sub(r"(?i)</p>|<br\s*/?>", "\n", fragment)
    lines = (re.sub(r"[ \t\xa0]+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", l))).strip()
             for l in fragment.split("\n"))
    return "\n".join(l for l in lines if l)


def _get(url, path, delay, max_age=None):
    try:
        raw = fetch_cached(url, path, delay=delay, max_age=max_age)
    except urllib.error.HTTPError as e:   # WordPress answers 400 past its last page
        print(f"  {url}: HTTP {e.code}")
        return ""
    return raw.decode("utf-8", "replace") if raw else ""


@dataclass
class Fiscalia:
    NAME: str
    institution_name: str
    state: str
    items: callable            # (delay, since) -> iterator of {id, date, title, text, url, speaker?, role?}
    since_default: str = "2025-01-01"
    INSTITUTIONS: list = field(init=False)

    def __post_init__(self):
        self.INSTITUTIONS = [{"id": self.NAME, "name": self.institution_name, "level": "estatal",
                              "state": self.state, "kind": "procuración"}]

    def documents(self, since=None, delay=1.0):
        since = since or self.since_default
        for item in self.items(delay, since):
            if not item["date"] or item["date"] < since or not item["text"]:
                continue
            kind = kind_of(item["title"])
            if kind == "comunicado" and re.search(r"(?i)años de (?:cárcel|prisión)", item["title"]):
                kind = "sentencia"           # «DAN CUATRO AÑOS DE CÁRCEL POR ROBO…»
            role = item.get("role") or ("Comunicado" if kind == "comunicado" else f"Comunicado ({kind})")
            yield Document(
                id=f"{self.NAME}:{item['id']}", institution_id=self.NAME, kind=f"comunicado · {kind}",
                date=item["date"], title=item["title"], source_url=item["url"],
                turns=[Turn(speaker=item.get("speaker") or self.institution_name, role=role, name=item.get("name"),
                            text=item["text"])])


# ---------- Fiscalía General de Justicia de la Ciudad de México ----------

CDMX = "https://www.fgjcdmx.gob.mx"
# «Participación de la fiscal general de Justicia de la Ciudad de México, Bertha Alcalde Luján, en la …»
CDMX_SPEECH = re.compile(r"(?i)participaci[óo]n\s+del?\s+(?:la\s+)?fiscal\s+general[^,]{0,80},\s*(?P<name>[A-ZÁÉÍÓÚÑ][^,]{4,60}?),")


def cdmx_note(page, nid):
    title = re.search(r"<h1>(.*?)</h1>", page, re.S)
    when = re.search(r"Publicado el\s+([^<]+)<", page)
    body = re.search(r'class="Datetime-normal".*?</div>(.*?)<div class="Panel-functions Share"', page, re.S)
    if not (title and when and body):
        return None
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body.group(1), re.S)
    item = {"id": nid, "date": spanish_date(when.group(1)), "title": _text(title.group(1)),
            "text": _text("</p>".join(paragraphs)), "url": f"{CDMX}/comunicacion/nota/{nid}"}
    speech = CDMX_SPEECH.search(item["title"]) if nid.startswith("VE") else None
    if speech:
        item.update(speaker=speech.group("name").strip(), name=speech.group("name").strip(),
                    role="Fiscal General de Justicia de la Ciudad de México")
    return item


def _cdmx_items(delay, since):
    """The «boletín» listing, ten notes a page, newest first. Notes never change once published."""
    seen_old = 0
    for n in range(1, 400):
        page = _get(f"{CDMX}/comunicacion/tipo/boletin?page={n}", CACHE_DIR / "fgjcdmx" / "indice" / f"{n}.html", delay,
                    max_age=INDEX_TTL if n <= FRESH_PAGES else None)
        ids = list(dict.fromkeys(re.findall(r"/comunicacion/nota/([A-Z]+\d{4}-\d+)", page)))
        dates = [spanish_date(d) for d in re.findall(r'class="Datetime-tag">\s*<span>\s*Publicado el\s+([^<]+)<', page)]
        if not ids:
            return
        for nid in ids:
            raw = _get(f"{CDMX}/comunicacion/nota/{nid}", CACHE_DIR / "fgjcdmx" / "notas" / f"{nid}.html", delay)
            item = cdmx_note(raw, nid) if raw else None
            if item:
                yield item
        if dates and max(dates) < since:
            seen_old += 1
            if seen_old >= 2:
                return


# ---------- Fiscalía del Estado de Jalisco (CMS Wagtail del gobierno estatal) ----------

JALISCO_API = ("https://fiscalia.jalisco.gob.mx/api/rest/v1/pages/?type=noticias.NoticiasPage&order=-fecha_publicacion"
               "&limit=100&offset={offset}&fields=title,description,rendered_content,fecha_publicacion")


def jalisco_items(page):
    out = []
    for p in json.loads(page or "{}").get("items", []):
        text = "\n".join(t for t in (_text(p.get("description") or ""), _text(p.get("rendered_content") or "")) if t)
        out.append({"id": p["id"], "date": p.get("fecha_publicacion") or "", "title": _text(p["title"]), "text": text,
                    "url": p["meta"]["html_url"].replace("/api/comunicacion-social/", "/comunicacion-social/")})
    return out


def _jalisco_items(delay, since):
    for n in range(0, 200):
        page = _get(JALISCO_API.format(offset=100 * n), CACHE_DIR / "fiscalia-jalisco" / "indice" / f"{n}.json", delay,
                    max_age=INDEX_TTL if n < FRESH_PAGES else None)
        items = jalisco_items(page)
        yield from items
        if not items or max(i["date"] for i in items) < since:
            return


# ---------- Fiscalía General del Estado de Guerrero (WordPress; solo la categoría NOTICIAS) ----------

GUERRERO_API = ("https://fiscaliaguerrero.gob.mx/wp-json/wp/v2/posts?categories=15&per_page=100&page={page}"
                "&_fields=id,date,link,title,content")


def guerrero_items(page):
    try:
        posts = json.loads(page or "[]")
    except ValueError:
        return []
    out = []
    for p in posts if isinstance(posts, list) else []:
        text = _text(p["content"]["rendered"])
        # The post's timestamp runs ahead of local time; the release dates itself («Chilpancingo, Gro., a 26 de octubre…»).
        dateline = re.search(r"Gro\.,?\s+a\s+(\d{1,2}\s+de\s+\w+\s+de(?:l)?\s+\d{4})", text[:1500])
        out.append({"id": p["id"], "date": spanish_date(dateline.group(1)) if dateline else p["date"][:10],
                    "title": _text(p["title"]["rendered"]),
                    "text": text, "url": p["link"]})
    return out


def _guerrero_items(delay, since):
    for n in range(1, 100):
        page = _get(GUERRERO_API.format(page=n), CACHE_DIR / "fiscalia-guerrero" / "indice" / f"{n}.json", delay,
                    max_age=INDEX_TTL if n <= FRESH_PAGES else None)
        items = guerrero_items(page)
        yield from items
        if len(items) < 100 or max(i["date"] for i in items) < since:
            return


FGJCDMX = Fiscalia(NAME="fgjcdmx", institution_name="Fiscalía General de Justicia de la Ciudad de México",
                   state="Ciudad de México", items=_cdmx_items)
JALISCO = Fiscalia(NAME="fiscalia-jalisco", institution_name="Fiscalía del Estado de Jalisco", state="Jalisco",
                   items=_jalisco_items)
GUERRERO = Fiscalia(NAME="fiscalia-guerrero", institution_name="Fiscalía General del Estado de Guerrero",
                    state="Guerrero", items=_guerrero_items, since_default="2026-01-01")

FISCALIAS = {f.NAME: f for f in (FGJCDMX, JALISCO, GUERRERO)}
