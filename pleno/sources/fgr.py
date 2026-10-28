"""Federal prosecutor (FGR): press releases from fgr.org.mx — arrests, «vinculación a proceso», sentences,
extraditions, investigations — with place and date. The site has no robots.txt.

Releases name people the way the prosecutor publishes them («José “N”»), to protect the presumption of
innocence. Pleno keeps exactly that: it never completes a name from another source and never builds a
profile of a detained person. Each release becomes one document with a single turn spoken by the FGR.

Bulletins have consecutive ids, so we walk down from the newest one instead of paginating.
"""

import html as htmllib
import re
import sys
import urllib.error

from pleno.sources.base import CACHE_DIR, Document, Turn, fetch_cached
from pleno.sources.transcript import spanish_date

NAME = "fgr"
BASE = "https://fgr.org.mx"
LIST_URL = BASE + "/en/FGR/Prensa"
DETAIL_URL = BASE + "/en/FGR/Prensa/_rid/61/_mod/story?p=1&ord=desc&f=0&suri=http%3A%2F%2Fwww.FGR.swb%23fgr_Boletin%3A{bid}"
INSTITUTIONS = [
    {"id": "fgr", "name": "Fiscalía General de la República", "level": "federal", "state": None, "kind": "procuración"},
]
# What the release reports, read from its title. Order matters: the first match wins.
KINDS = [
    ("sentencia", r"sentencia|condena|penalmente responsable"),
    ("vinculación a proceso", r"vincula"),
    ("extradición", r"extradi"),
    ("orden de aprehensión", r"orden(?:es)? de aprehensi|cumplimenta"),
    ("detención", r"detenid|detiene|captura|aprehend"),
    ("aseguramiento", r"asegur|decomis"),
    ("investigación", r"investigaci|indaga|denuncia"),
]


STATES_RE = "|".join(sorted(map(re.escape, [
    "Michoacán de Ocampo", "Veracruz de Ignacio de la Llave", "Coahuila de Zaragoza",
    "Ciudad de México", "Estado de México", "CDMX", "Aguascalientes", "Baja California Sur", "Baja California",
    "Campeche", "Chiapas", "Chihuahua", "Coahuila", "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo",
    "Jalisco", "Michoacán", "Morelos", "Nayarit", "Nuevo León", "Oaxaca", "Puebla", "Querétaro", "Quintana Roo",
    "San Luis Potosí", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatán", "Zacatecas",
    "México", "Estados Unidos"]), key=len, reverse=True))


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def _text(fragment):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def latest_id(delay=1.0):
    try:
        raw = fetch_cached(LIST_URL, CACHE_DIR / NAME / "indice.html", delay=delay, max_age=6 * 3600)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raw = None                   # site unreachable: fall back to the newest bulletin we already have
    ids = [int(i) for i in re.findall(r"fgr_Boletin%3A(\d+)", _decode(raw or b""))]
    ids += [int(p.stem) for p in (CACHE_DIR / NAME / "boletines").glob("*.html")] if not ids else []
    return max(ids) if ids else None


def kind_of(title):
    t = title.lower()
    return next((k for k, pattern in KINDS if re.search(pattern, t)), "comunicado")


def parse(page, bid):
    text = _text(page)
    m = re.search(r"(Comunicado FGR [\w/.-]+)\s+(\d{1,2} de \w+,? \d{4})\s+(.*?)$", text)
    if not m:
        return None
    number, when, rest = m.groups()
    body = re.split(r"\s+oOo\s+|\s+Regresar\s+Publicaciones", rest)[0]
    date = spanish_date(when.replace(",", ""))
    # «Tepic, Nayarit Detenidos con fusiles…»: «city, state» comes first, then the headline sentence.
    place = re.match(r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ .]{1,60}?,\s*(?:" + STATES_RE + r"))\.?\s+", body)
    location = place.group(1).strip() if place else ""
    body = body[len(place.group(0)):] if place else body
    title = re.split(r"(?<=[a-záéíóúñ\d)»”:])\s+(?=La Fiscalía|El Ministerio|La FGR|Como resultado|Derivado|En cumplimiento|Elementos|Agentes)", body, maxsplit=1)[0]
    title = title if len(title) < 260 else title[:257] + "…"
    return {"id": bid, "number": number, "date": date, "place": location, "title": title, "text": body}


def documents(since="2025-01-01", delay=2.0, max_misses=40):
    """Releases newer than `since`, newest first, walking bulletin ids downward.

    If the site starts refusing connections we stop instead of insisting; cached bulletins are reused on
    the next run, so the walk resumes where it stopped."""
    top = latest_id(delay)
    if not top:
        return
    misses = older = 0
    for bid in range(top + 5, 0, -1):
        try:
            raw = fetch_cached(DETAIL_URL.format(bid=bid), CACHE_DIR / NAME / "boletines" / f"{bid}.html", delay=delay,
                               retry_missing_after=24 * 3600 if bid > top - 50 else None)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            print(f"fgr: el sitio dejó de responder en el boletín {bid} ({e}); se reanuda en la próxima corrida",
                  file=sys.stderr)
            return
        item = parse(_decode(raw), bid) if raw else None
        if not item or not item["date"]:
            misses += 1
            if misses >= max_misses:
                return
            continue
        misses = 0
        if item["date"] < since:
            older += 1
            if older >= 30:          # ids are roughly chronological; stop once well past `since`
                return
            continue
        older = 0
        kind = kind_of(item["title"])
        yield Document(
            id=f"fgr:{bid}", institution_id="fgr", kind=f"comunicado · {kind}", date=item["date"],
            title=f"{item['number']}. {item['title']}", source_url=DETAIL_URL.format(bid=bid),
            turns=[Turn(speaker="Fiscalía General de la República", role="Comunicado" if kind == "comunicado" else f"Comunicado ({kind})",
                        text=(f"{item['place']}. " if item["place"] else "") + item["text"])],
        )
