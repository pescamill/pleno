"""Federal legislative: Cámara de Diputados stenographic versions (cronica.diputados.gob.mx).

One page per session day at /Ve{dd}{mmm}{yyyy}.html. The site has no robots.txt restrictions;
we still cache every page (and every 404) and wait between requests.
"""

import datetime as dt
import html
import re

from pleno.normalize import fold, title_name
from pleno.sources.base import CACHE_DIR, Document, Turn, fetch_cached, legislature_for

NAME = "diputados"
BASE = "https://cronica.diputados.gob.mx"
INSTITUTIONS = [
    {"id": "diputados", "name": "Cámara de Diputados", "level": "federal", "state": None, "kind": "legislativo"},
]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
SPEAKER_RE = re.compile(
    r"^(?:El|La) ((?:(?:presidente|presidenta|vicepresidente|vicepresidenta|secretario|secretaria)\s+)?"
    r"(?:diputado|diputada|senador|senadora|ciudadano|ciudadana|licenciado|licenciada|doctor|doctora|maestro|maestra)?)"
    r"\s*(.+)$",
    re.IGNORECASE,
)
TITLE_WORDS = {"diputado", "diputada", "diputados", "diputadas", "senador", "senadora", "presidente", "presidenta",
               "secretario", "secretaria", "vicepresidente", "vicepresidenta"}
PARTIES = {
    "morena": "MORENA", "accion nacional": "PAN", "pan": "PAN", "revolucionario institucional": "PRI",
    "pri": "PRI", "verde ecologista": "PVEM", "verde ecologista de mexico": "PVEM", "pvem": "PVEM",
    "del trabajo": "PT", "pt": "PT", "movimiento ciudadano": "MC", "mc": "MC",
    "de la revolucion democratica": "PRD", "prd": "PRD",
    # State and local parties
    "encuentro solidario": "PES", "encuentro social": "PES", "pes": "PES", "nueva alianza": "PANAL",
    "fuerza por mexico": "FXM", "redes sociales progresistas": "RSP", "hagamos": "HAGAMOS", "futuro": "FUTURO",
    "unidad popular": "PUP", "unidad democratica de coahuila": "UDC",
}
# «…la diputada Fulana de Tal, del Grupo Parlamentario de Morena…», «…al Diputado X, de la fracción
# parlamentaria del Partido de la Revolución Democrática…», «…C. DIP. X, DEL GRUPO LEGISLATIVO DEL PRI…»,
# «Dip. X, integrante del Grupo Legislativo de Morena», «Dip. X del Partido Revolucionario Institucional».
# What follows «del/de la» only counts when it is a known party («de la Comisión…» is not).
PARTY_RE = re.compile(
    r"(?i:diputad[oa]|dip\.|legislador[a]?) ([A-ZÁÉÍÓÚÑ][\wáéíóúñüÁÉÍÓÚÑ]+(?: (?:(?i:de)(?:l| la| los)? )?[A-ZÁÉÍÓÚÑ][\wáéíóúñüÁÉÍÓÚÑ]+){1,5}),? "
    r"(?:(?i:integrante|coordinador[a]?|miembro) )?(?i:del?|de la) "
    r"(?:(?i:grupo parlamentario|GP|fracci[oó]n parlamentaria|fracci[oó]n legislativa|grupo legislativo|bancada|"
    r"representaci[oó]n (?:legislativa|parlamentaria)) (?i:de |del )?)?"
    r"(?i:partido )?([A-Za-zÁÉÍÓÚáéíóúñÑ ]{2,40}?)(?=[,.;:)]| (?i:para|hasta|por|quien|y|en|a) )"
)
# Roll calls and attendance lists: «Aguilar Castillo, Luis Vicente. (MORENA)»
ROLL_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?: (?:de |del |de la )?[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+){1,3}), "
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?: [A-ZÁÉÍÓÚÑ][\wáéíóúñü.]+){0,3})\.? \((MORENA|PAN|PRI|PVEM|PT|MC|PRD|PES)\)"
)


def session_url(day):
    return f"{BASE}/Ve{day.day:02d}{MONTHS[day.month - 1]}{day.year}.html"


def decode(raw):
    head = raw[:3000].lower()
    return raw.decode("utf-8", errors="replace") if b"utf-8" in head else raw.decode("latin-1")


def clean(fragment):
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_speaker(label):
    """«La presidenta diputada Kenia López Rabadán» → ("Presidenta de la Mesa (Diputada)", "Kenia López Rabadán")."""
    label = re.sub(r"\s*\([^)]*\)\s*", " ", label).strip(" :")
    m = SPEAKER_RE.match(label)
    if not m:
        return None, title_name(label)
    titles, name = m.group(1).lower().split(), m.group(2).strip()
    if fold(name) in TITLE_WORDS:  # «El diputado (desde la curul):» with no name
        titles, name = titles + [fold(name)], ""
    office = next((t for t in titles if t in {"presidente", "presidenta", "vicepresidente", "vicepresidenta", "secretario", "secretaria"}), None)
    member = next((t for t in titles if t not in {office}), None)
    if office in {"presidente", "presidenta"} and fold(name).startswith("constitucional "):
        # «La presidenta constitucional Claudia Sheinbaum Pardo» at a joint session: head of state, not the chair.
        role, name = f"{office.capitalize()} de México", name.split(" ", 1)[1]
    elif office:
        role = f"{office.capitalize()} de la Mesa" + (f" ({member.capitalize()})" if member else "")
    elif member in {"diputado", "diputada", "senador", "senadora"}:
        role = member.capitalize()
    else:
        role = "Invitado"
    return role, (title_name(name) if name.isupper() else name) or None


def parse_session(raw, url):
    page = decode(raw)
    heading = re.search(r"Versión estenográfica de la (sesi[oó]n[^<]*)", page, re.IGNORECASE)
    title = clean(heading.group(0)) if heading else "Sesión"
    turns, current = [], None
    for para in re.findall(r"<p[^>]*>(.*?)</p>", page, re.IGNORECASE | re.DOTALL):
        para = re.sub(r"<a [^>]*></a>", "", para, flags=re.IGNORECASE).strip()
        bold = re.match(r"<b>(.*?)</b>\s*(\([^)]*\))?\s*:?\s*(.*)$", para, re.IGNORECASE | re.DOTALL)
        label = clean(bold.group(1)) if bold else ""
        if bold and re.match(r"(?i)^(el|la) ", label) and (label.endswith(":") or bold.group(2) or ":" in para[:400]):
            role, name = parse_speaker(label)
            text = clean(bold.group(3)).lstrip(": ")
            current = Turn(speaker=label.rstrip(": "), text=text, role=role, name=name)
            turns.append(current)
        elif current is not None:
            text = clean(para)
            if text and not re.fullmatch(r"\(.*\)|-+o0o-+", text):
                current.text = f"{current.text}\n{text}".strip()
    turns = [t for t in turns if t.text]
    return title, turns


def party_mentions(text):
    """Yield (name, party) pairs stated in the transcript itself."""
    for m in PARTY_RE.finditer(text):
        party = PARTIES.get(fold(m.group(2)).replace("partido ", "").strip())
        if party:
            yield m.group(1).strip(), party
    for m in ROLL_RE.finditer(text):
        yield f"{m.group(2).rstrip('.')} {m.group(1)}", m.group(3)


def documents(since=None, end=None, delay=1.0):
    start = dt.date.fromisoformat(since) if since else dt.date(2024, 9, 1)
    end = end or dt.date.today()
    recent = end - dt.timedelta(days=21)
    day = start
    while day <= end:
        url = session_url(day)
        # A session can be published days later: re-check a missing page from the last three weeks daily.
        raw = fetch_cached(url, CACHE_DIR / NAME / f"{url.rsplit('/', 1)[1]}", delay=delay,
                           retry_missing_after=20 * 3600 if day >= recent else None)
        if raw:
            title, turns = parse_session(raw, url)
            if turns:
                iso = day.isoformat()
                yield Document(
                    id=f"diputados:{iso}", institution_id="diputados", kind="sesion", date=iso,
                    title=title, source_url=url, legislature=legislature_for(iso), turns=turns,
                )
        day += dt.timedelta(days=1)
