"""State legislatures that publish their stenographic versions or debate journals as PDFs with text.

Each congress is a small configuration: where its index lives, how to read a (date, url, title) out of
it, and how its transcripts mark a speaker. Fetching, caching, cleaning and splitting are shared.
Every site here was checked by hand: robots.txt allows it (or has none) and the PDFs carry real text.
"""

import base64
import html as htmllib
import json
import re
import urllib.parse
from dataclasses import dataclass, field

from pleno.normalize import edit_distance, fold, name_tokens, slug, title_name
from pleno.sources.base import CACHE_DIR, Document, fetch_cached, pdf_text
from pleno.sources.transcript import clean, parse_label, spanish_date, split_turns

INDEX_TTL = 12 * 3600  # index pages grow; re-read them twice a day at most


@dataclass
class Entry:
    date: str
    url: str
    title: str
    key: str = ""          # distinguishes two sessions on the same day


@dataclass
class Congreso:
    NAME: str
    state: str
    institution_name: str
    index_urls: list
    entries: callable          # (html, page_url) -> [Entry]
    label_re: re.Pattern
    legislature: str
    since_default: str
    notes: str = ""
    parse: callable = parse_label
    roster: callable = None    # () -> [member dicts] when the congress publishes its members by party
    pages: callable = None     # (delay) -> [(html, url)] when the index spans several pages or needs a request
    prepare: callable = None   # raw PDF text -> text, before cleaning (one congress's layout quirks)
    keep: str = None           # lines that repeat on many pages but are speaker labels, not running headers
    officers: callable = None  # cleaned text -> {"Presidenta": name, …}: who presides, read from the header
    min_chars: int = 2         # shortest turn kept
    tidy_names: bool = False   # cut what a loose label drags into a name («X. Gracias», «X P.M.D.L», «X Secretarias»)
    directory: callable = None # () -> [names] of the members when the roster gives no party (names only)
    INSTITUTIONS: list = field(init=False)

    def __post_init__(self):
        self.INSTITUTIONS = [{"id": self.institution_id, "name": self.institution_name, "level": "estatal",
                              "state": self.state, "kind": "legislativo"}]

    @property
    def institution_id(self):
        return f"congreso-{self.NAME}"

    def members(self, delay=1.0):
        """Official member names, to correct a transcript's spelling and to tell members from guests."""
        if not hasattr(self, "_members"):
            try:
                names = [r["name"] for r in self.roster(delay)] if self.roster else (self.directory(delay) if self.directory else [])
            except Exception as err:   # an unreachable roster only costs the corrections
                print(f"  {self.NAME}: padrón no disponible ({type(err).__name__})")
                names = []
            self._members = names
        return self._members

    def index_pages(self, delay=1.0):
        if self.pages:
            return self.pages(delay)
        return [(_get(url, CACHE_DIR / self.NAME / "indice" / f"{i}.html", delay), url)
                for i, url in enumerate(self.index_urls)]

    def listing(self, delay=1.0):
        seen = {}
        for page, url in self.index_pages(delay):
            for e in self.entries(page, url) if page else []:
                if e.date and e.url not in seen:
                    seen[e.url] = e
        return sorted(seen.values(), key=lambda e: (e.date, e.key), reverse=True)

    def documents(self, since=None, delay=1.0):
        since = since or self.since_default
        used = set()
        for e in self.listing(delay):
            if e.date < since:
                continue
            doc_id = f"{self.institution_id}:{e.date}" + (f"-{e.key}" if e.key else "")
            if doc_id in used:
                doc_id += "-" + slug(e.url.rsplit("/", 1)[-1])[:24]
            used.add(doc_id)
            cache = CACHE_DIR / self.NAME / "pdf" / f"{slug(doc_id)}.pdf"
            _forget_if_replaced(cache, e.url)
            try:
                text = pdf_text(e.url, cache, delay=delay)
            except Exception as err:   # one broken file never stops a whole congress
                print(f"  {self.NAME}: omitido {e.url} ({type(err).__name__})")
                continue
            if not text:
                continue
            text = clean(self.prepare(text) if self.prepare else text, keep=self.keep)
            turns = split_turns(text, self.label_re, parse=self.parse, min_chars=self.min_chars)
            if self.tidy_names:
                for t in turns:
                    t.name = tidy_name(t.name)
            if turns and self.officers:
                _name_officers(turns, self.officers(text[:8000]))
            if turns and self.tidy_names:
                members = self.members(delay)
                for t in turns:
                    t.name = _canonical(t.name, members)
                turns = _without_minors(turns, text, members)
            if turns:
                yield Document(id=doc_id, institution_id=self.institution_id, kind="sesion", date=e.date,
                               title=e.title, source_url=e.url, legislature=self.legislature, turns=turns)


def _forget_if_replaced(cache, url):
    """A session republished under a new file name (a preliminary version replaced by the final one) is read
    again instead of keeping the old text."""
    receipt = cache.with_suffix(".json")
    try:
        stale = json.loads(receipt.read_text(encoding="utf-8")).get("url") != url
    except (OSError, ValueError):
        return
    if stale:
        for suffix in (".txt", ".json", ".404"):
            cache.with_suffix(suffix).unlink(missing_ok=True)


def _is_utf8(raw):
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _get(url, path, delay, max_age=INDEX_TTL, data=None):
    raw = fetch_cached(url, path, delay=delay, max_age=max_age, data=data)
    if not raw:
        return ""
    return raw.decode("utf-8") if _is_utf8(raw) else raw.decode("latin-1")


def _text(fragment):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _abs(base, href):
    return urllib.parse.urljoin(base, htmllib.unescape(href).strip())


def _squeeze(text):
    """Collapse runs of spaces, so a padded running header is recognised as one repeated line; drop footnote
    calls glued to a word («…del Estado de Durango14») and the headers of comparison tables («TEXTO VIGENTE
    TEXTO PROPUESTO»), which otherwise end up inside law names."""
    text = re.sub(r"(?<=[a-záéíóúñ])\d{1,4}(?=[\s.,;:)]|$)", "", text)
    text = re.sub(r"(?<=[a-záéíóúñ])\d{1,4}(?=[A-ZÁÉÍÓÚÑ])", " ", text)
    text = re.sub(r"\b(?:TEXTO\s+(?:VIGENTE|PROPUESTO|ACTUAL)|PROPUESTA\s+DE\s+(?:MODIFICACI[ÓO]N|REFORMA)|DEBE\s+DECIR)\b",
                  " ", text)
    return re.sub(r"[ \t]{2,}", " ", text)


# ---------- who presides: read once from the session header, given to unnamed «Presidenta:» turns ----------

_NAMEW = r"(?!(?i:dip\.|diputad[oa]\b))[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü.'-]*"   # a word of a name, never «Dip.»
_FULLNAME = _NAMEW + r"(?:\s+(?:(?i:de|del|la|las|los|y)\s+)?" + _NAMEW + r"){1,6}"
_PRESIDING_RE = re.compile(r"(?i:presidencia\s+de(?:l|\s+la)\s+(?:ciudadan[oa]\s+)?|\bpresident[ea]\s*:\s*)"
                           r"(?P<who>(?i:diputad[oa]|dip\.))\s+(?P<name>" + _FULLNAME + ")")
_SECRETARIES_RE = re.compile(r"(?i:\bsecretari[oa]s?\s*:)(?P<list>[^\n]{5,240})")
_MEMBER_RE = re.compile(r"(?P<who>(?i:diputad[oa]))\s+(?P<name>" + _FULLNAME + ")")
# «MESA DIRECTIVA DIP. NAOMI EDITH GÓMEZ SANTOS PRESIDENTA DIP. …», «Dip. Moncerrat López López, presidenta;»
_LISTED_RE = re.compile(r"(?i:\bdip\.|\bdiputad[oa])\s+(?P<name>" + _FULLNAME + r"),?\s+"
                        r"(?P<office>(?i:vicepresident[ea]|president[ea]|secretari[oa]))\b"
                        r"(?!\s+(?i:de\s+la\s+comisi|del?\s+(?:comit|ayuntamiento|junta|consejo|instituto)|municipal))")
_NAME_STOP = {"primer", "primera", "segundo", "segunda", "tercer", "tercera", "presidente", "presidenta",
              "secretario", "secretaria", "secretarios", "vicepresidente", "vicepresidenta", "asistido", "asistida",
              "auxiliado", "auxiliada", "sesion", "timbre", "en", "con", "quien", "y", "e", "dip", "diputado", "diputada"}


def _officer_name(raw):
    words = []
    for w in raw.split():
        if fold(w).strip(".,") in _NAME_STOP and words:
            break
        words.append(w.strip(",;"))
    while words and fold(words[-1]) in {"de", "del", "la", "las", "los", "y"}:
        words.pop()
    return tidy_name(" ".join(words))


_NOT_A_NAME = {"decreto", "vocal", "vocales", "miembro", "miembros", "articulo", "transitorio", "transitorios", "punto",
               "junta", "primero", "segundo", "tercero", "local", "dtto", "distrito", "presentante", "h", "numero", "no",
               "gracias", "presente", "integrante", "integrantes", "coordinador", "coordinadora", "comision"}
_OFFICE_WORD = re.compile(r"(?i)\b(?:vice)?president[ea]s?\b|\bsecretari[oa]s?\b|\bdiputad[oa]s?\b|\bdip\.")


def tidy_name(name):
    """«Yuriria Iturbe Vázquez. Secretarias» → «Yuriria Iturbe Vázquez»; «Rita Fierro Reyes P.M.D.L» → «Rita Fierro
    Reyes»; «PRESIDENTA.- Adelante» → None. Initials («Ma.», «B.») stay."""
    if not name:
        return None
    name = re.split(r"\.-|(?<=[^\W\d_]{3})\.(?=\s|$)|\s+(?:[A-Z]\.){2,}", name)[0]
    office = _OFFICE_WORD.search(name)
    name = name[:office.start()] if office else name
    words = name.strip(" ,;:.-–").split()
    cut = next((i for i, w in enumerate(words) if fold(w).strip(".,") in _NOT_A_NAME
                or re.fullmatch(r"(?i)[ivxl]+", w) and i), None)       # signature blocks: «… Vocal», «… Decreto Número»
    words = words[:cut] if cut is not None else words
    while words and fold(words[-1]) in {"de", "del", "la", "las", "los", "y"}:
        words.pop()
    name = " ".join(words)
    if not name[:1].isupper() or re.search(r"\d", name) or not 2 <= len(words) <= 7:
        return None
    return title_name(name) if name.isupper() else name


def officers(text):
    """{"Presidenta": "Karina Olivas Parra", "Secretario": …} from «BAJO LA PRESIDENCIA DE LA DIPUTADA …»,
    «PRESIDENTE: DIPUTADO …» or «SECRETARIOS: DIPUTADO X Y DIPUTADA Z». A secretary is named only when the
    header leaves no doubt which one speaks (one man and one woman, or a single secretary)."""
    out = {}
    m = _PRESIDING_RE.search(text)
    if m and (name := _officer_name(m.group("name"))):
        out["Presidenta" if fold(m.group("who")).startswith("diputada") else "Presidente"] = name
        out["Presidencia"] = name
    m = _SECRETARIES_RE.search(text)
    if m:
        by_gender = {}
        for s in _MEMBER_RE.finditer(m.group("list")):
            if name := _officer_name(s.group("name")):
                by_gender.setdefault("Secretaria" if fold(s.group("who")) == "diputada" else "Secretario", []).append(name)
        for office, names in by_gender.items():
            if len(names) == 1:
                out[office] = names[0]
    for m in _LISTED_RE.finditer(text):           # the Mesa Directiva is listed first
        if name := _officer_name(m.group("name")):
            out.setdefault(m.group("office").capitalize(), name)
    if "Presidencia" not in out and (out.get("Presidenta") or out.get("Presidente")):
        out["Presidencia"] = out.get("Presidenta") or out.get("Presidente")
    return out


def _name_officers(turns, found):
    """Unnamed «Presidenta:» turns get the name the header gives, or else the one name the same document
    gives that office elsewhere («Diputada Presidenta María del Mar Treviño Garza:»)."""
    office = lambda t: t.role.split(" de la Mesa")[0]
    named = {}
    for t in turns:
        if t.name and t.role and " de la Mesa" in t.role:
            named.setdefault(office(t), set()).add(t.name)
    for t in turns:
        if not t.name and t.role:
            only = named.get(office(t), set())
            t.name = found.get(office(t)) or (next(iter(only)) if len(only) == 1 else None)


def _canonical(name, members):
    """The roster's spelling of a member the transcript misspells or names by surname only: «Jose Maue Lromero
    Coello» → «José Manuel Romero Coello», «Álvarez Casio» → «Martín Álvarez Casio». Unknown names stay as written."""
    if not name or not members:
        return name
    toks = set(name_tokens(name))
    exact = [m for m in members if set(name_tokens(m)) == toks]
    if exact:
        return exact[0]
    wider = [m for m in members if toks and toks <= set(name_tokens(m))]
    if len(wider) == 1 and len(toks) >= 2:
        return wider[0]
    squeeze = lambda n: re.sub(r"[^a-z]", "", fold(n))
    words = name.split()
    best = []
    for drop in range(min(2, len(words) - 2) + 1):          # «Secretarua Irma Mirella Martiniez Silva»
        flat = squeeze(" ".join(words[drop:]))
        limit = max(2, len(flat) // 8)
        for m in members:
            d = edit_distance(flat, squeeze(m), limit=limit)
            if d <= limit:
                best.append((d, m))
    best.sort()
    if best and (len(best) == 1 or best[0][0] < best[1][0] or best[0][1] == best[1][1]):
        return best[0][1]
    return name


_YOUTH = re.compile(r"(?i)parlamento\s+(?:infantil|juvenil|estudiantil|de\s+(?:la\s+)?(?:niñez|juventud|niñas))|"
                    r"congreso\s+(?:infantil|juvenil|estudiantil)|diputad[oa]s?\s+(?:infantil|juvenil|estudiantil|niñ[oa])")
_YOUTH_LABEL = re.compile(r"(?i)\b(?:infantil|juvenil|estudiantil)\b")


def _without_minors(turns, text, members):
    """Children's and students' parliaments seat minors as «diputadas» for a day. Their turns are dropped:
    those labelled so, and, in a session that hosts one, any «diputado» who is not an official member."""
    if not _YOUTH.search(text):
        return turns
    official = {frozenset(name_tokens(m)) for m in members}
    return [t for t in turns if not _YOUTH_LABEL.search(t.speaker)
            and not (official and (t.role or "").startswith("Diputad") and frozenset(name_tokens(t.name or "")) not in official)]


def _parse_abbreviated(label):
    """«DIP. X» says nothing about gender: «PRESIDENTA DIP. X» is a woman, a bare «DIP. X» stays unknown."""
    role, name = parse_label(label)
    if role and re.match(r"(?i)^\s*(?:(?:president|vicepresident|secretari)[ae]\s+)?dip\.", label):
        office = fold(label.split()[0])
        if office.endswith("a") and office != "dip.":
            role = role.replace("(Diputado)", "(Diputada)")
        elif role == "Diputado":
            role = "Diputado(a)"
    return role, name


# ---------- Ciudad de México: Diario de los Debates, III Legislatura (2024–2027) ----------

def _cdmx(page, url):
    out = []
    for href, title in re.findall(r'href="(archivo-[0-9a-f]+\.pdf)".*?<strong>(.*?)</strong>', page, re.S):
        title = _text(title)
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", title)
        if not m:
            continue
        number = re.search(r"No\.\s*([\w]+)", title)
        out.append(Entry(f"{m.group(3)}-{m.group(2)}-{m.group(1)}", _abs(url, href), title,
                         slug(number.group(1)) if number else ""))
    return out


CDMX = Congreso(
    NAME="cdmx", state="Ciudad de México", institution_name="Congreso de la Ciudad de México",
    index_urls=["https://www.congresocdmx.gob.mx/diaro-los-debates-iii-legislatura-207-4.html"],
    entries=_cdmx, legislature="III", since_default="2024-09-01",
    label_re=re.compile(r"(?P<label>\b(?:EL|LA) C\. [A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]{2,110}?)\s?\.-"),
)


# ---------- Oaxaca: versiones estenográficas, LXVI Legislatura (2024–2027) ----------

def _oaxaca(page, url):
    out = []
    # Rows: «2024-11-13 · Sesión Instalación LXVI Legislatura · [pdf]»
    for row in re.findall(r"<tr.*?</tr>", page, re.S | re.I):
        date = re.search(r"(20\d\d-\d\d-\d\d)", row)
        href = re.search(r'href="([^"]+\.pdf)"', row, re.I)
        if date and href:
            cells = [c for c in (_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)) if c]
            title = max(cells, key=len) if cells else "Sesión"
            out.append(Entry(date.group(1), _abs(url, href.group(1)), f"Versión estenográfica. {title}",
                             slug(href.group(1).rsplit("/", 1)[1])[-30:]))
    return out


OAXACA = Congreso(
    NAME="oaxaca", state="Oaxaca", institution_name="Congreso del Estado de Oaxaca",
    index_urls=["https://www.congresooaxaca.gob.mx/version_estenografs.html"],
    entries=_oaxaca, legislature="LXVI", since_default="2024-11-01",
    label_re=re.compile(r"(?m)^(?P<label>(?:El|La)\s+(?:Diputad[oa]|Presidente|Presidenta|Secretari[oa]|"
                        r"Vicepresident[ea]|ciudadan[oa])\b[^:\n]{0,110}?):"),
)


# ---------- Quintana Roo: versiones estenográficas, XVIII Legislatura (2024–2027) ----------

def _qroo(page, url):
    out = []
    for href in set(re.findall(r'href="([^"]*versiones_estenograficas/VE-[^"]+\.pdf)"', page)):
        m = re.search(r"VE-[A-Z]+-(\d{4})-(\d{1,2})-(\d{1,2})-\d+-([a-z0-9-]+?)(?:_\d{8}T\d+)?\.pdf", href)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            out.append(Entry(date, _abs(url, href), f"Versión estenográfica, {m.group(4).replace('-', ' ')}",
                             slug(m.group(4))[:20]))
    return out


QROO = Congreso(
    NAME="qroo", state="Quintana Roo", institution_name="Congreso del Estado de Quintana Roo",
    index_urls=["https://www.congresoqroo.gob.mx/sesiones/"],
    entries=_qroo, legislature="XVIII", since_default="2024-09-01",
    label_re=re.compile(r"(?m)^(?P<label>(?:DIPUTAD[OA]|PRESIDENT[EA]|SECRETARI[OA]|VICEPRESIDENT[EA])"
                        r"(?:\s+[A-ZÁÉÍÓÚÑ.]+){1,9})\s*:"),
)


# ---------- Tabasco: Diario de los Debates, LXV Legislatura (2024–2027) ----------

def _tabasco(page, url):
    out = []
    for href in set(re.findall(r'href="([^"]+/(\d{2})_(\d{2})_(\d{2})_D[^"/]*\.pdf)"', page)):
        link, d, m, y = href
        out.append(Entry(f"20{y}-{m}-{d}", _abs(url, link), "Diario de los Debates",
                         slug(link.rsplit("/", 1)[1])[9:24]))
    return out


TABASCO = Congreso(
    NAME="tabasco", state="Tabasco", institution_name="Congreso del Estado de Tabasco",
    index_urls=["https://congresotabasco.gob.mx/diario-de-debates/"],
    entries=_tabasco, legislature="LXV", since_default="2024-09-01",
    notes="Diario narrado: «…al Diputado X, quien en uso de la tribuna señaló: …».",
    label_re=re.compile(
        r"(?:\b(?:al|a la)\s+(?P<label>Diputad[oa]\s+[A-ZÁÉÍÓÚÑ][^,:\n]{3,80}?),[^:]{0,400}?quien en uso de "
        r"(?:la tribuna|la voz|la palabra)\s+(?:expres[óo]|señal[óo]|manifest[óo]|dijo|mencion[óo]|refiri[óo]|"
        r"coment[óo])\s*:)"
        r"|(?:\b(?:la|el)\s+(?P<label2>Diputad[oa]\s+President[ea]),?\s+(?:expres[óo]|señal[óo]|manifest[óo]|dijo)\s*:)"),
)


# ---------- Nuevo León: Diario de los Debates, LXXVII Legislatura (2024–2027) ----------

def _nl(page, url):
    out = []
    for row in re.split(r"<tr\b", page, flags=re.I)[1:]:      # rows are not always closed
        date = re.search(r">\s*(\d{2})/(\d{2})/(\d{4})\s*<", row)
        href = re.search(r'href="([^"]+\.pdf)"', row, re.I)
        if date and href:
            title = _text(re.search(r"<td[^>]*>(.*?)</td>", row, re.S).group(1))
            number = re.search(r"N[úu]mero\s*(\d+)", title)
            out.append(Entry(f"{date.group(3)}-{date.group(2)}-{date.group(1)}", _abs(url, href.group(1)),
                             f"Diario de los Debates. {title}", number.group(1) if number else ""))
    return out


NUEVO_LEON = Congreso(
    NAME="nl", state="Nuevo León", institution_name="Congreso del Estado de Nuevo León",
    index_urls=["https://www.hcnl.gob.mx/trabajo_legislativo/diario_debates.php"],
    entries=_nl, legislature="LXXVII", since_default="2024-09-01",
    notes="Diario narrado en mayúsculas: «…AL C. DIP. X, QUIEN EXPRESÓ: “…”».",
    label_re=re.compile(
        r"(?P<label>\b(?:AL|A LA|EL|LA)\s+C\.\s+(?:DIP\.|DIPUTAD[OA])\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]{3,80}?),?\s+"
        r"(?:QUIEN\s+)?(?:EXPRES[ÓO]|EXPRESABA|MANIFEST[ÓO]|SEÑAL[ÓO]|DIJO|COMENT[ÓO])[^:“\"]{0,40}:"
        r"|(?m:^(?P<label2>C\.\s+(?:PRESIDENT[EA]|SECRETARI[OA]|VICEPRESIDENT[EA]))\s*:)"),
)


# ---------- Guerrero: Diario de los Debates, LXIV Legislatura (2024–2027) ----------

def _guerrero(page, url):
    out = []
    for href in set(re.findall(r'href="([^"]*diario-debates/\d+/(20\d\d-\d\d-\d\d)-[^"]+\.pdf)"', page)):
        link, date = href
        out.append(Entry(date, _abs(url, link), "Diario de los Debates", slug(link.rsplit("-", 1)[1])[:8]))
    return out


def _guerrero_roster(delay=1.0):
    """Members by party from congresogro.gob.mx (phone numbers and e-mails on the page are not stored)."""
    out = []
    for party in ("MORENA", "PRI", "PVEM", "PT", "PRD", "PAN", "MC"):
        url = f"https://congresogro.gob.mx/64/diputadas-diputados/diputados-partido.php?p={party}"
        raw = fetch_cached(url, CACHE_DIR / "guerrero" / "padron" / f"{party}.html", delay=delay, max_age=7 * 24 * 3600)
        page = (raw or b"").decode("utf-8", "replace")
        for row in re.split(r"<tr\b", page)[1:]:
            link = re.search(r'href="perfil\.php\?id=([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', row)
            if not link:
                continue
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            principle = next((c for c in cells if c.lower().startswith(("mayor", "represent"))), None)
            district = next((c for c in cells if re.fullmatch(r"\d{1,2}", c)), None)
            out.append({"official_id": link.group(1), "name": htmllib.unescape(link.group(2)), "party": party,
                        "state": "Guerrero", "district": f"Distrito {district}" if district else None,
                        "principle": principle, "seat": None, "committees": "[]",
                        "source_url": "https://congresogro.gob.mx/64/diputadas-diputados/perfil.php?id=" + link.group(1)})
    return out


GUERRERO = Congreso(
    NAME="guerrero", state="Guerrero", institution_name="Congreso del Estado de Guerrero",
    index_urls=["https://congresogro.gob.mx/64/sesiones/debates.php"],
    entries=_guerrero, legislature="LXIV", since_default="2024-09-01", roster=_guerrero_roster,
    label_re=re.compile(r"(?m)^(?P<label>(?:El|La)\s+(?:[Dd]iputad[oa]|[Ss]ecretari[oa]|[Pp]resident[ea]|"
                        r"[Vv]icepresident[ea])\b[^:\n]{0,90}?):"),
)

_W = r"[A-ZÁÉÍÓÚÑ](?:[a-záéíóúñü]{0,2}\.|[\wáéíóúñü'-]*)"     # one capitalised word of a name («Ma.», «B.»)
_NAME = r"(?:\s+(?:(?:de|del|la|las|los|y)\s+)?" + _W + r")"  # …and the words after it
_SAID = (r"(?:continu[óo] diciendo|dijo|declar[óo]|expres[óo]|manifest[óo]|señal[óo]|coment[óo]|indic[óo]|mencion[óo]|"
         r"agreg[óo]|inform[óo]|pregunt[óo]|expuso|continu[óo])")


# ---------- official rosters by party (no phone numbers or e-mails are stored) ----------

_LOGO_PARTY = {"morena": "MORENA", "pan": "PAN", "pri": "PRI", "pvem": "PVEM", "verde": "PVEM", "pt": "PT", "mc": "MC",
               "movimientociudadano": "MC", "movimiento-ciudadano": "MC", "prd": "PRD", "pes": "PES",
               "partido-del-trabajo": "PT", "sin-partido": None, "sp": None}


def _member(name, party, state, url, official_id=None, district=None):
    return {"official_id": official_id, "name": name, "party": party, "state": state, "district": district,
            "principle": None, "seat": None, "committees": "[]", "source_url": url}


def _veracruz_roster(delay=1.0):
    url = "https://www.legisver.gob.mx/Inicio.php?p=legis"
    page = _get(url, CACHE_DIR / "veracruz" / "padron" / "legis.html", delay, max_age=7 * 24 * 3600)
    out = []
    for row in page.split('<div class="row" style="margin-top:10px">')[1:]:
        who = re.search(r"dipInt&d=(\d+)[^>]*><a[^>]*>\s*Dip\.\s*([^<]+)</a>", row)
        logo = re.search(r"logos/logo_?(\w+)\.(?:jpg|png)", row)
        district = re.search(r"<p1>\s*(Distrito[^<]+)</p1>", row)
        if who:
            out.append(_member(re.sub(r"\s+", " ", htmllib.unescape(who.group(2))).strip(),
                               _LOGO_PARTY.get(logo.group(1).lower()) if logo else None, "Veracruz", url, who.group(1),
                               district.group(1).strip() if district else None))
    return out


def _edomex_roster(delay=1.0):
    url = "https://legislacion.congresoedomex.gob.mx/asuntosparlamentarios/diputadasydiputados"
    page = _get(url, CACHE_DIR / "edomex" / "padron" / "diputados.html", delay, max_age=7 * 24 * 3600)
    out = []
    for card in page.split("<!-- FIN FOTO -->")[:-1]:
        party = re.findall(r"storage/img/partidos/([\w-]+)\.svg", card)
        rest = page[page.index(card) + len(card):][:600]
        name = re.search(r"<!-- DATOS -->\s*<div[^>]*>\s*([^<]+?)\s*<br>", rest, re.S)
        if name and "," in name.group(1):
            surnames, given = (re.sub(r"\s+", " ", x).strip() for x in name.group(1).split(",", 1))
            out.append(_member(f"{given} {surnames}", _LOGO_PARTY.get(party[-1].lower()) if party else None,
                               "Estado de México", url))
    return out


def _guanajuato_roster(delay=1.0):
    out = {}
    for key in ("morena", "pan", "pri", "pvem", "partido-del-trabajo", "movimiento-ciudadano", "prd"):
        url = f"https://www.congresogto.gob.mx/partidos/{key}"
        page = _get(url + ".html", CACHE_DIR / "guanajuato" / "padron" / f"{key}.html", delay, max_age=7 * 24 * 3600)
        for slug_, name in re.findall(r'<a href="/diputados/([^"]+)"><img[^>]*/></a>\s*<p[^>]*>\s*([^<]+?)\s*</p>', page):
            out[slug_] = _member(htmllib.unescape(name), _LOGO_PARTY.get(key, key.upper()), "Guanajuato",
                                 "https://www.congresogto.gob.mx/diputados/" + slug_, slug_)
    return list(out.values())


def _yucatan_roster(delay=1.0):
    url = "https://www.congresoyucatan.gob.mx/diputados"
    page = _get(url, CACHE_DIR / "yucatan" / "padron" / "diputados.html", delay, max_age=7 * 24 * 3600)
    out = {}
    for party, link, name in re.findall(r'<div data-orden="\d+" class="itm ([\w-]+) all">\s*<a href="([^"]+)">.*?<h2>([^<]+)</h2>',
                                        page, re.S):
        out[link] = _member(title_name(htmllib.unescape(name).strip()), _LOGO_PARTY.get(party), "Yucatán", link,
                            link.rsplit("/", 1)[1])
    return list(out.values())


_GROUP_PARTY = [("REVOLUCIONARIO INSTITUCIONAL", "PRI"), ("REGENERACION NACIONAL", "MORENA"), ("MORENA", "MORENA"),
                ("ACCION NACIONAL", "PAN"), ("REVOLUCION DEMOCRATICA", "PRD"), ("DEL TRABAJO", "PT"), ("VERDE", "PVEM"),
                ("UNIDAD DEMOCRATICA", "UDC"), ("MOVIMIENTO CIUDADANO", "MC")]


def _coahuila_roster(delay=1.0):
    url = "https://congresocoahuila.gob.mx/coahuila/grupos_fracciones.html"
    text = _text(_get(url, CACHE_DIR / "coahuila" / "padron" / "grupos.html", delay, max_age=7 * 24 * 3600))
    out = []
    for block in re.split(r"(?=(?:GRUPO|FRACCI[ÓO]N) PARLAMENTARI[OA])", text)[1:]:
        head = fold(block.split("DIP.", 1)[0]).upper()
        party = next((p for key, p in _GROUP_PARTY if key in head), None)
        for name in re.findall(r"\bDIP\.?\s+([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ]{5,80}?)\s+Comisiones", block):
            out.append(_member(title_name(name.strip()), party, "Coahuila", url))
    return out


def _colima_roster(delay=1.0):
    url = "https://congresocol.gob.mx/web/www/diputados/index.php"
    page = _get(url, CACHE_DIR / "colima" / "padron" / "diputados.html", delay, max_age=7 * 24 * 3600)
    logos = {"verde": "PVEM", "pt": "PT", "morena": "MORENA", "pri": "PRI", "pan": "PAN", "movimiento": "MC",
             "nuevaalianza": "PANAL"}
    out = {}
    for pid, logo, name in re.findall(r'index2\.php\?id=(\d+)&vlegis=61&vlogo=(\w+)\.png">\s*Dip\.\s*([^<]+?)\s*</a>', page):
        out[pid] = _member(htmllib.unescape(name), logos.get(logo.lower()), "Colima", url, pid)
    return list(out.values())


def _durango_roster(delay=1.0):
    url = "https://congresodurango.gob.mx/directorio-lxx/"
    text = _text(_get(url, CACHE_DIR / "durango" / "padron" / "directorio.html", delay, max_age=7 * 24 * 3600))
    out = []
    for block in re.split(r"\bDIP\.\s+", text)[1:]:
        name = re.match(r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ]{5,80}?)\s+(?:Coordinador|Información)", block)
        head = fold(block[:400]).upper()
        party = next((p for key, p in _GROUP_PARTY if key in head), None)
        district = re.search(r"Distrito:\s*(\d+)", block[:400])
        if name:
            out.append(_member(title_name(name.group(1).strip()), party, "Durango", url,
                               district=f"Distrito {int(district.group(1))}" if district else None))
    return out


# ---------- Veracruz: versiones estenográficas, LXVII Legislatura (2024–2027) ----------

def _veracruz(page, url):
    out = []
    for row in re.split(r"<tr\b", page, flags=re.I)[1:]:
        date = re.search(r"<td>\s*(\d{2})/(\d{2})/(\d{4})\s*</td>", row)
        href = re.search(r"PDF\('([^']*VersionEstenografica/[^']+\.pdf)'", row)
        if date and href:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            title = _text(cells[1]) if len(cells) > 1 else "Sesión"
            out.append(Entry(f"{date.group(3)}-{date.group(2)}-{date.group(1)}", _abs(url, href.group(1)),
                             f"Versión estenográfica. {title}", slug(href.group(1).rsplit("_", 1)[1][:-4])[:20]))
    return out


_VERACRUZ_LABEL = re.compile(r"(?m)^\s*-\s*(CONTIN[ÚU]A\s+)?((?:EL|LA)\s+C\.[^:\n]{2,100}):[ \t]*\n?\s*")


def _veracruz_prepare(text):
    """Labels sit alone on their line («- LA C. PRESIDENTA:»), so they repeat like headers; join each to its
    speech. «- CONTINÚA LA C. DIP. X:» after a page break is the same turn, after an interruption a new one."""
    text = _squeeze(text)
    out, last, pos = [], None, 0
    for m in _VERACRUZ_LABEL.finditer(text):
        out.append(text[pos:m.start()])
        who = re.sub(r"\s+", " ", m.group(2)).strip()
        if not (m.group(1) and who == last):
            out.append(f"\n- {who}: ")
        last, pos = who, m.end()
    out.append(text[pos:])
    return "".join(out)


VERACRUZ = Congreso(
    NAME="veracruz", state="Veracruz", institution_name="Congreso del Estado de Veracruz",
    index_urls=["https://www.legisver.gob.mx/Inicio.php?p=sesiones"],
    entries=_veracruz, roster=_veracruz_roster, legislature="LXVII", since_default="2024-11-01", prepare=_veracruz_prepare,
    officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)(?:^|(?<=\s))-\s*(?P<label>(?:EL|LA)\s+C\.\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .]{2,100}?)\s*:"),
)


# ---------- Estado de México: Diario de Debates, LXII Legislatura (2024–2027), por tomos ----------

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def _roman(s):
    values = [_ROMAN[c] for c in s if c in _ROMAN]
    return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))


def _edomex_pages(delay=1.0):
    """The legislature's page lists one index per tomo; only the newest tomos still grow."""
    root = "https://legislacion.congresoedomex.gob.mx/asuntosparlamentarios/debates"
    page = _get(root, CACHE_DIR / "edomex" / "indice" / "tomos.html", delay)
    tomos = sorted({re.sub(r"^http:", "https:", u) for u in re.findall(
        r'href="(https?://www\.secretariadeasuntosparlamentarios\.gob\.mx/mainstream/Actividad/Diario/LXII/'
        r'Tomo%20[IVXL]+\.html)"', page)}, key=lambda u: _roman(u.rsplit("%20", 1)[1]))
    return [(_get(u, CACHE_DIR / "edomex" / "indice" / f"tomo-{u.rsplit('%20', 1)[1][:-5]}.html", delay,
                  max_age=INDEX_TTL if i >= len(tomos) - 2 else None), u) for i, u in enumerate(tomos)]


def _edomex(page, url):
    out = []
    for title, when, href in re.findall(
            r"<strong>(.*?)</strong>\s*<br>\s*<strong class=\"fecha\">\s*<span>(.*?)</span>.*?<a href=\"\s*([^\"]+?\.pdf)\s*\"",
            page, re.S | re.I):
        date = spanish_date(_text(when))
        out.append(Entry(date, _abs(url, href.strip()), f"Diario de Debates. {_text(title)}",
                         slug(href.rsplit("/", 1)[-1].strip()[:-4])[:24]))
    return out


EDOMEX = Congreso(
    NAME="edomex", state="Estado de México", institution_name="Congreso del Estado de México",
    index_urls=[], pages=_edomex_pages, entries=_edomex, roster=_edomex_roster, legislature="LXII", since_default="2024-09-01",
    notes="Diario a dos columnas; la cabecera de página va pegada a la primera línea.",
    prepare=lambda t: _squeeze(re.sub(r"Tomo\s+[XVIL]+\s+Sesión\s+No\.\s*\d+\s*[XVIL]+\s+Legislatura del Estado "
                                      r"de México\s*Diario de Debates\s*\w+\s+\d{1,2}\s+de\s+\d{4}", "\n", t)),
    keep=r"(?:(?:PRESIDENT|VICEPRESIDENT|SECRETARI)[AEO]\s+)?(?:DIP\.|DIPUTAD[OA])\s", parse=_parse_abbreviated,
    officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?:^|(?<=\s))(?P<label>(?:(?:PRESIDENT|VICEPRESIDENT|SECRETARI)[AEO]\s+)?(?:DIP\.|DIPUTAD[OA])"
                        r"\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ]{3,80}?)\.(?=\s)"),
)


# ---------- Guanajuato: transcripciones del Diario de los Debates, LXVI Legislatura (2024–2027) ----------

def _guanajuato_pages(delay=1.0):
    """One page per period of sessions. The site answers XML unless the URL ends in .html."""
    root = "https://www.congresogto.gob.mx/trabajos_legislativos"
    page = _get(root, CACHE_DIR / "guanajuato" / "indice" / "periodos.html", delay)
    periods = []
    for row in re.split(r"<tr\b", page)[1:]:
        link = re.search(r'href="(/periodos/(\d+)-[^"]+)"', row)
        if link and re.search(r"<td>\s*LXVI\s*</td>", row):
            periods.append((int(link.group(2)), "https://www.congresogto.gob.mx" + link.group(1) + ".html"))
    periods.sort()
    return [(_get(u, CACHE_DIR / "guanajuato" / "indice" / f"periodo-{n}.html", delay,
                  max_age=INDEX_TTL if i >= len(periods) - 2 else None), u) for i, (n, u) in enumerate(periods)]


def _guanajuato(page, url):
    out = []
    for row in re.split(r"<tr\b", page)[1:]:
        cell = re.search(r"(\d{2})/(\d{2})/(\d{4})[^<]*<a href=\"([^\"]+/uploads/sesion/transcripcion/(\d+)/[^\"]+\.pdf)\"",
                         row, re.I)
        if cell:
            d, m, y, href, sid = cell.groups()
            kind = re.search(r"<td>(.*?)</td>", row, re.S)
            out.append(Entry(f"{y}-{m}-{d}", href, f"Diario de los Debates. {_text(kind.group(1)).capitalize()}"
                             if kind else "Diario de los Debates", sid))
    return out


def _guanajuato_parse(label):
    if label.endswith("Presidencia"):
        return "Presidencia de la Mesa", None
    if re.search(r"Secretar[ií]a$", label):
        return "Secretaría de la Mesa", None
    return parse_label(label)


GUANAJUATO = Congreso(
    NAME="guanajuato", state="Guanajuato", institution_name="Congreso del Estado de Guanajuato",
    index_urls=[], pages=_guanajuato_pages, entries=_guanajuato, roster=_guanajuato_roster, legislature="LXVI", since_default="2024-09-25",
    notes="Los PDF están en congreso-gto.s3.amazonaws.com; el /uploads que prohíbe su robots.txt es el de "
          "www.congresogto.gob.mx.",
    prepare=_squeeze, keep=r"-\s*(?:La|El)\s+(?:Presidencia|Secretar)", parse=_guanajuato_parse,
    officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?:^|(?<=\s))-\s*(?P<label>(?:La|El)\s+(?:Presidencia|Secretar[ií]a)|(?:Diputad[oa]|Dip\.)\s+"
                        r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü .]{3,80}?)\s*\.?-(?=\s)"),
)


# ---------- Coahuila: Diario de los Debates, LXIII Legislatura (2024–2026) ----------

COAHUILA_INDEX = "https://www.congresocoahuila.gob.mx/coahuila/congreso/debates.aspx"


def _coahuila_pages(delay=1.0, since="2024-01-01"):
    """An ASP.NET grid of ten rows per page; the next page is the form the «2, 3, …» links post."""
    pages, n = [], 1
    page = _get(COAHUILA_INDEX, CACHE_DIR / "coahuila" / "indice" / "1.html", delay)
    while page:
        pages.append((page, COAHUILA_INDEX))
        dates = [f"{y}-{m}-{d}" for d, m, y in re.findall(r">(\d{2})/(\d{2})/(\d{4})<", page)]
        n += 1
        if (dates and max(dates) < since) or f"Page${n}" not in page:
            break
        form = dict(re.findall(r'id="(__VIEWSTATE|__VIEWSTATEGENERATOR|__EVENTVALIDATION)" value="([^"]*)"', page))
        form.update(__EVENTTARGET="gvAcuerdos", __EVENTARGUMENT=f"Page${n}", textoBuscar="")
        page = _get(COAHUILA_INDEX, CACHE_DIR / "coahuila" / "indice" / f"{n}.html", delay, data=form)
    return pages


def _coahuila(page, url):
    out = []
    for row in re.split(r'<tr class="rowss">', page)[1:]:
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 5 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[0]) or not cells[4].endswith(".docx"):
            continue
        d, m, y = cells[0].split("/")
        stem = cells[4][:-5]
        out.append(Entry(f"{y}-{m}-{d}", f"https://www.congresocoahuila.gob.mx/congreso/TG/debates/{stem}.pdf",
                         f"Diario de los Debates. {cells[2]}", slug(stem.split("_", 1)[-1])))
    return out


COAHUILA = Congreso(
    NAME="coahuila", state="Coahuila", institution_name="Congreso del Estado de Coahuila",
    index_urls=[], pages=_coahuila_pages, entries=_coahuila, roster=_coahuila_roster, legislature="LXIII", since_default="2024-01-01",
    prepare=_squeeze, keep=r"(?:Diputad[oa]|Dip\.)\s", officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)(?:^|(?<![a-záéíóúñ,;] )(?<=\s))(?P<label>(?:Diputad[oa]|Dip\.)(?:\s+(?:President[ea]|"
                        r"Vicepresident[ea]|Secretari[oa]))?" + _NAME + r"{0,7})\s*:"),
)


# ---------- Sinaloa: Diario de los Debates, LXV Legislatura (2024–2027) ----------

SINALOA_API = "https://gaceta.congresosinaloa.gob.mx/api/obtenerSesiones"


def _sinaloa_pages(delay=1.0):
    return [(_get(SINALOA_API, CACHE_DIR / "sinaloa" / "indice" / "sesiones-65.json", delay,
                  data={"nu_legislatura": "65"}), SINALOA_API)]


def _sinaloa(page, url):
    out = []
    for s in json.loads(page or "[]"):
        if s.get("pdf") and s.get("fecha"):
            out.append(Entry(s["fecha"][:10],
                             f"https://gaceta.congresosinaloa.gob.mx:3001/pdfs/sesiones/{s['id_legi']}/Debate_{s['id_sesion']}.pdf",
                             f"Diario de los Debates. {s['nb_nombre'].strip()} número {s['numero']}", str(s["numero"])))
    return out


SINALOA = Congreso(
    NAME="sinaloa", state="Sinaloa", institution_name="Congreso del Estado de Sinaloa",
    index_urls=[], pages=_sinaloa_pages, entries=_sinaloa, legislature="LXV", since_default="2024-09-30",
    notes="Diario narrado: «La diputada X dijo:», «…a la diputada X, quien dijo:».",
    prepare=_squeeze, keep=r"(?:El|La)\s+diputad", officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(
        r"(?:\b(?P<label>(?:El|La)\s+diputad[oa]\s+(?:President[ea]|Secretari[oa]|Vicepresident[ea]|[A-ZÁÉÍÓÚÑ][^,:\n\d]{3,80}?))"
        r",?\s+" + _SAID + r"\s*:)"
        r"|(?:\b(?:a|al|a la)\s+(?P<label2>diputad[oa]\s+[A-ZÁÉÍÓÚÑ][^,:\n\d]{3,80}?),[^:]{0,300}?quien\s+" + _SAID + r"\s*:)"),
)


# ---------- Tamaulipas: versiones estenográficas, LXVI Legislatura (2024–2027) ----------

def _tamaulipas(page, url):
    out = []
    for row in re.split(r"<tr\b", page, flags=re.I)[1:]:
        date = re.search(r">\s*(\d{2})/(\d{2})/(\d{4})", row)
        href = re.search(r'href="([^"]*/VersionesEstenograficas/([^"/]+)\.pdf)"', row, re.I)
        if date and href:
            cells = [c for c in (_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)) if c]
            title = next((c for c in cells if re.search(r"[a-z]", c) and not re.search(r"\d{2}/\d{2}", c)), "Sesión")
            number = re.match(r"(\d+)", href.group(2))
            out.append(Entry(f"{date.group(3)}-{date.group(2)}-{date.group(1)}", _abs(url, href.group(1)),
                             f"Versión estenográfica. {title}", number.group(1) if number else ""))
    return out


TAMAULIPAS = Congreso(
    NAME="tamaulipas", state="Tamaulipas", institution_name="Congreso del Estado de Tamaulipas",
    index_urls=["https://www.congresotamaulipas.gob.mx/TrabajoLegislativo/VersionesEstenograficasSesiones/"
                "VersionesEstenograficasSesiones.asp"],
    entries=_tamaulipas, legislature="LXVI", since_default="2024-10-01", prepare=_squeeze,
    keep=r"(?:President[ea]|Secretari[oa]|Vicepresident[ea]|Diputad[oa])\b", officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)^(?:(?P<label>President[ea]|Secretari[oa]|Vicepresident[ea])\s*:"
                        r"|(?P<label2>Diputad[oa]\s+" + _W + _NAME + r"{1,6})\s*\.(?=\s))"),
)


# ---------- Yucatán: Diario de los Debates, LXIV Legislatura (2024–2027) ----------

def _yucatan(page, url):
    out = []
    for row in re.split(r"<tr\b", page)[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        href = re.search(r'href="(/storage/uploadCey/(\w+)_[^"]+\.pdf)"', row, re.I)
        if len(cells) >= 4 and _text(cells[0]) == "LXIV" and href and re.fullmatch(r"20\d\d-\d\d-\d\d", _text(cells[3])):
            out.append(Entry(_text(cells[3]), _abs(url, href.group(1)), f"Diario de los Debates. {_text(cells[2])}",
                             href.group(2)))
    return out


YUCATAN = Congreso(
    NAME="yucatan", state="Yucatán", institution_name="Congreso del Estado de Yucatán",
    index_urls=["https://www.congresoyucatan.gob.mx/gaceta/diario-debates"],
    entries=_yucatan, roster=_yucatan_roster, legislature="LXIV", since_default="2024-09-01", prepare=_squeeze, officers=officers, tidy_names=True,
    min_chars=5, notes="Diario narrado: «…confirió el uso de la voz al Diputado X, quien expresó: “…”».",
    label_re=re.compile(
        r"(?:\b(?:al|a la)\s+(?P<label>Diputad[oa]\s+[A-ZÁÉÍÓÚÑ][^,:\n\d]{3,80}?),[^:]{0,300}?quien\s+" + _SAID + r"\s*:)"
        r"|(?:\b(?:La|la|El|el)\s+(?P<label2>(?i:president[ea]|secretari[oa]|vicepresident[ea])(?:\s+de\s+la\s+Mesa\s+"
        r"Directiva)?(?:\s+Diputad[oa]\s+[A-ZÁÉÍÓÚÑ][^,:\n\d]{3,60}?)?),?\s+" + _SAID + r"\s*:)"),
)


# ---------- Zacatecas: actas con la versión de las discusiones, LXV Legislatura (2024–2027) ----------

def _zacatecas(page, url):
    out = []
    for href, title in re.findall(r'<a href="(/o/(?:\d+))" class="list-group-item">\s*(Acta[^<]+)</a>', page):
        title = _text(title)
        date = spanish_date(title)
        out.append(Entry(date, _abs(url, href), f"Diario de los Debates. {title}", href.rsplit("/", 1)[1]))
    return out


def _zacatecas_directory(delay=1.0):
    page = _get("https://www.congresozac.gob.mx/65/v200", CACHE_DIR / "zacatecas" / "padron" / "directorio.html", delay,
                max_age=7 * 24 * 3600)
    return [re.sub(r"\s+", " ", n).strip() for n in re.findall(r"Dip\.\s+([A-ZÁÉÍÓÚÑ][^\d@<|]+?)\s+\d", _text(page))]


ZACATECAS = Congreso(
    NAME="zacatecas", state="Zacatecas", institution_name="Congreso del Estado de Zacatecas",
    index_urls=["https://www.congresozac.gob.mx/65/v4168"],
    entries=_zacatecas, directory=_zacatecas_directory, legislature="LXV", since_default="2024-09-07", prepare=_squeeze,
    keep=r"(?:EL|LA)\s+(?:DIP\.|DIPUTAD|C\.)", officers=officers, tidy_names=True, min_chars=5,
    notes="Las actas nombran a quien habla solo por sus apellidos («EL DIP. NOVELLA MACÍAS.-»).",
    label_re=re.compile(r"(?m)^(?P<label>(?:EL|LA)\s+(?:DIP\.|DIPUTAD[OA]|C\.)\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .]{2,80}?)\s*\.-"),
)


# ---------- Durango: actas de sesión, LXX Legislatura (2024–2027) ----------

def _durango(page, url):
    out = []
    for row in re.split(r"<tr\b", page)[1:]:
        when = re.search(r'<td class="column-1">([^<]+)</td>', row)
        href = re.search(r'href="([^"]+/LXX/ACTAS/([^"/]+)\.pdf)"', row, re.I)
        if when and href:
            out.append(Entry(spanish_date(when.group(1)), _abs(url, href.group(1)), f"Acta de sesión. {when.group(1).strip()}",
                             slug(href.group(2))))
    return out


DURANGO = Congreso(
    NAME="durango", state="Durango", institution_name="Congreso del Estado de Durango",
    index_urls=["https://congresodurango.gob.mx/actas-lxx-legislatura/"],
    entries=_durango, roster=_durango_roster, legislature="LXX", since_default="2024-09-01", prepare=_squeeze,
    keep=r"(?:President[ea]|Secretari[oa]|Vicepresident[ea]|Diputad[oa])\b", officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)^(?P<label>(?:President[ea]|Secretari[oa]|Vicepresident[ea])|Diputad[oa](?:\s+(?:President[ea]|"
                        r"Secretari[oa]|Vicepresident[ea]))?" + _NAME + r"{1,7})\s*:"),
)


# ---------- Colima: Diario de los Debates, LXI Legislatura (2024–2027) ----------

COLIMA_INDEX = "https://congresocol.gob.mx/web/www/gaceta/plantilla_datos.php?v=tdiario&l=61&ld=LXI%20Legislatura&lc=%25"


def _colima_pages(delay=1.0):
    # The gazette loads this table with a POST and no body.
    return [(_get(COLIMA_INDEX, CACHE_DIR / "colima" / "indice" / "diario-61.html", delay, data={"v": "tdiario"}),
             COLIMA_INDEX)]


def _colima(page, url):
    out = []
    for row in re.split(r'<div class="row" style="margin-bottom:20px', page)[1:]:
        date = re.search(r'title="Fecha"[^>]*>\s*(20\d\d-\d\d-\d\d)\s*<', row)
        title = re.search(r'title="Descripci[^"]*"[^>]*>(.*?)</div>', row, re.S)
        href = re.search(r"href='([^']+/Diario_Debates/([^'/]+)\.pdf)'", row, re.I)
        if date and href:
            out.append(Entry(date.group(1), _abs(url, href.group(1)), _text(title.group(1)).capitalize() if title
                             else "Diario de los Debates", slug(href.group(2))[:60]))
    return out


COLIMA = Congreso(
    NAME="colima", state="Colima", institution_name="Congreso del Estado de Colima",
    index_urls=[], pages=_colima_pages, entries=_colima, roster=_colima_roster, legislature="LXI", since_default="2024-10-01",
    prepare=_squeeze, keep=r"(?:DIPUTAD[OA]|DIP\.)\s", parse=_parse_abbreviated, officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)^(?P<label>(?:DIPUTAD[OA]|DIP\.)(?:\s+(?:PRESIDENT[EA]|SECRETARI[OA]|VICEPRESIDENT[EA]))?"
                        r"\s+[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ]{3,80}?)\.(?=\s)"),
)


# ---------- Baja California Sur: Diario de los Debates, XVII Legislatura (2024–2027) ----------

def _bcs(page, url):
    out = []
    for href in sorted(set(re.findall(r'href="(/CONGRESO/DIARIO-DEBATES/XVII-LEGISLATURA/[^"]+\.pdf)"', page, re.I))):
        name = href.rsplit("/", 1)[1]
        date = spanish_date(name.replace("-", " ").replace("_", " "))
        number = re.match(r"(\d+)-", name)
        kind = "permanente" if re.search(r"-DP\.pdf$", name, re.I) else ""
        out.append(Entry(date, _abs(url, href), "Diario de los Debates. " + name[:-4].split("-", 1)[-1].replace("-", " ").title(),
                         "-".join(x for x in (number.group(1) if number else "", kind) if x)))
    return out


BCS = Congreso(
    NAME="bcs", state="Baja California Sur", institution_name="Congreso del Estado de Baja California Sur",
    index_urls=["https://www.cbcs.gob.mx/index.php/trabajos-legislativos/diarios-debates-cbcs/474-diario-de-los-debates/"
                "diario-debates-xvii-legislatura/8087-diario-debates-xvii-legislatura"],
    entries=_bcs, legislature="XVII", since_default="2024-08-31", prepare=_squeeze,
    keep=r"(?:PRESIDENT[EA]|SECRETARI[OA]|VICEPRESIDENT[EA]|DIP\.|DIPUTAD[OA])\b", parse=_parse_abbreviated,
    officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(r"(?m)^(?P<label>(?:PRESIDENT[EA]|SECRETARI[OA]|VICEPRESIDENT[EA])|(?:DIP\.|DIPUTAD[OA])\s+"
                        r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .]{3,80}?)\s*\.-"),
)


# ---------- Chiapas: actas del Diario de Debates, LXIX Legislatura (2024–2027) ----------

CHIAPAS_TREE = "https://congresochiapas.gob.mx/web/phpplugins/global_diariodebates.php?act="


def _chiapas_pages(delay=1.0):
    """The page opens a folder tree one level per request (legislature/year/period/month); folder names travel
    base64-encoded, as the page's own script sends them."""
    root = _get(CHIAPAS_TREE + "deb_init_data", CACHE_DIR / "chiapas" / "indice" / "raiz.html", delay,
                data={"dir": "../../pdf/debates", "margin": "0", "nivel": "0"})
    queue = [d for d in (base64.b64decode(x).decode("utf-8", "replace") for x in re.findall(r'data-dirname="([^"]+)"', root))
             if "/LXIX/" in d]
    pages = []
    while queue:
        folder = queue.pop(0)
        page = _get(CHIAPAS_TREE + "deb_get_data", CACHE_DIR / "chiapas" / "indice" / f"{slug(folder)}.html", delay,
                    data={"dir": base64.b64encode(folder.encode()).decode(), "margin": "0", "nivel": str(folder.count("/"))})
        pages.append((page, CHIAPAS_TREE))
        queue += [base64.b64decode(x).decode("utf-8", "replace") for x in re.findall(r'data-dirname="([^"]+)"', page)]
    return pages


def _chiapas(page, url):
    out = []
    for href in re.findall(r'href="(https://congresochiapas\.gob\.mx/pdf/debates/LXIX/[^"?]+\.pdf)', page, re.I):
        name = htmllib.unescape(href.rsplit("/", 1)[1])[:-4]
        out.append(Entry(spanish_date(name.replace("_", " ")), href, f"Acta de sesión. {name.split('_', 1)[-1].replace('_', ' ')}",
                         slug(name.split("_", 1)[-1])[:40]))
    return out


CHIAPAS = Congreso(
    NAME="chiapas", state="Chiapas", institution_name="Congreso del Estado de Chiapas",
    index_urls=[], pages=_chiapas_pages, entries=_chiapas, legislature="LXIX", since_default="2024-10-01",
    notes="Actas narradas. La Presidencia anuncia a quien habla («TIENE EL USO DE LA PALABRA LA DIPUTADA X”.- La "
          "legisladora hizo uso de la tribuna… y expresó:»); de esa frase sale el nombre.",
    prepare=_squeeze, officers=officers, tidy_names=True, min_chars=5,
    label_re=re.compile(
        r"(?:\b(?:la|el|La|El)\s+(?P<label>Diputad[oa]\s+(?:President[ea]|Secretari[oa]|Vicepresident[ea])(?:\s+" + _W +
        r"){0,6}),?\s+" + _SAID + r"\s*:)"
        r"|(?:(?:USO\s+DE\s+LA\s+(?:PALABRA|TRIBUNA|VOZ)|PALABRA)\s+(?:A\s+|AL\s+)?(?:LA\s+|EL\s+)?(?P<label2>DIPUTAD[OA]\s+"
        r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{3,80}?)\s*(?:,[^”\"]{0,200})?[”\"]\s*\.-\s*(?:La|El)\s+(?:legisladora?|diputad[oa])"
        r"[^:]{0,250}?" + _SAID + r"\s*:)"),
)

CONGRESOS = {c.NAME: c for c in (CDMX, OAXACA, QROO, TABASCO, NUEVO_LEON, GUERRERO, VERACRUZ, EDOMEX, GUANAJUATO,
                                 COAHUILA, SINALOA, TAMAULIPAS, YUCATAN, ZACATECAS, DURANGO, COLIMA, BCS, CHIAPAS)}
