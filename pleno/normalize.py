"""Name, slug and law normalisation shared by every source."""

import re
import unicodedata

CONNECTORS = {"de", "del", "la", "las", "los", "y", "e", "para", "en", "sobre", "a", "el"}
HONORIFICS = {"c", "ciudadano", "ciudadana", "sen", "dip", "lic", "licenciado", "licenciada",
              "doctor", "doctora", "dr", "dra", "ing", "mtro", "mtra", "maestro", "maestra"}


def fold(text):
    """Lowercase, no accents, single spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def title_name(text):
    """«ANDRÉS MANUEL LÓPEZ OBRADOR» → «Andrés Manuel López Obrador»."""
    words = []
    for w in re.sub(r"\s+", " ", text).strip().split(" "):
        low = w.lower()
        words.append(low if low in CONNECTORS and words else low[:1].upper() + low[1:])
    return " ".join(words)


LEADING_TITLES = {"constitucional", "ciudadano", "ciudadana", "licenciado", "licenciada", "doctor", "doctora",
                  "maestro", "maestra", "ingeniero", "ingeniera", "senador", "senadora", "diputado", "diputada",
                  "presidente", "presidenta", "president"}
# Labels for people the transcript does not name: «Beneficiaria del Programa…», «Habitante de Tlaxiaco».
UNNAMED_ROLES = {"beneficiario", "beneficiaria", "divulgador", "divulgadora", "participante", "estudiante", "habitante",
                 "madre", "padre", "enfermero", "enfermera", "medico", "medica", "comandante", "integrante", "alumno",
                 "alumna", "trabajador", "trabajadora", "productor", "productora", "vecino", "vecina", "usuario",
                 "usuaria", "paciente", "joven", "nino", "nina", "representante", "vocero", "vocera", "invitado",
                 "invitada", "asistente", "ganador", "ganadora", "familiar", "docente", "jornalero", "jornalera"}
STATES = {fold(s) for s in """Aguascalientes|Baja California|Baja California Sur|Campeche|Chiapas|Chihuahua|Ciudad de México|
Coahuila|Colima|Durango|Estado de México|Guanajuato|Guerrero|Hidalgo|Jalisco|Michoacán|Morelos|Nayarit|Nuevo León|Oaxaca|
Puebla|Querétaro|Quintana Roo|San Luis Potosí|Sinaloa|Sonora|Tabasco|Tamaulipas|Tlaxcala|Veracruz|Yucatán|Zacatecas|
México|CDMX|Monterrey|Guadalajara|Tijuana|Mérida|Cancún|Acapulco|Ciudad Juárez|Mexicali|Hermosillo|Culiacán""".replace("\n", "").split("|")}


def clean_person_name(name):
    """Drop parentheticals and leftover titles; keep only the first of «A y el diputado B». None if not a name."""
    if not name:
        return None
    name = re.sub(r"\([^)]*\)?", " ", name)
    name = re.split(r"\s+y\s+(?:el|la|los|las)\s+", name)[0]
    words = name.split()
    while words and fold(words[0]) in LEADING_TITLES | {"de", "mexico"}:
        words.pop(0)
    name = " ".join(words).strip(" ,.;:")
    if words and fold(words[0]) in UNNAMED_ROLES:
        return None
    return name if len(name_tokens(name)) >= 2 else None


def name_tokens(name):
    return [t for t in re.split(r"[^a-z]+", fold(name)) if t and t not in CONNECTORS and t not in HONORIFICS]


def same_person(short, full):
    """True when every token of the shorter form appears in the full name (order-free).

    «Mariana Gómez del Campo» matches «Mariana Gómez del Campo Gurza»; needs 2+ tokens to avoid
    matching on a single surname.
    """
    a, b = set(name_tokens(short)), set(name_tokens(full))
    return len(a) >= 2 and a <= b


# «Ley General de Aguas», «Ley Federal del Trabajo», «Código Nacional de Procedimientos Penales»…
LAW_RE = re.compile(
    r"\b((?:Ley|Código|Reglamento)(?: (?:General|Federal|Orgánica|Nacional|Reglamentaria))?"
    r"(?: (?:de(?:l| la| los| las)?|para(?: el| la)?|sobre|en materia de)) "
    r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?: (?:(?:de(?:l| la| los| las)?|y|e|para(?: el| la)?|en|a|al|sobre(?: el| la| los| las)?) )?[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+){0,9})"
)
CONSTITUTION_RE = re.compile(r"\bConstituci[oó]n(?: Pol[ií]tica)?(?: de los Estados Unidos Mexicanos)?\b")
FEDERAL_CONSTITUTION = "Constitución Política de los Estados Unidos Mexicanos"
FEDERAL_CONSTITUTION_RE = re.compile(r"\bConstituci[oó]n Pol[ií]tica de los Estados Unidos Mexicanos|"
                                     r"\bConstituci[oó]n [Ff]ederal|\bCarta Magna")
STATE_CONSTITUTION_RE = re.compile(
    r"\bConstituci[oó]n Pol[ií]tica (?:del Estado(?: Libre y Soberano)? de |de la )"
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?: (?:de )?[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){0,3})")


LAW_CONNECTORS = {"de", "del", "la", "los", "las", "y", "e", "para", "el", "en", "a", "al", "sobre", "materia"}
# Capitalized words that never continue a law name; in PDFs they come from the next heading or sentence.
LAW_STOP = {"La", "El", "Los", "Las", "Lo", "Doc", "Artículo", "Artículos", "Art", "Que", "En", "Con", "Por",
            "Se", "Su", "Sus", "Este", "Esta", "Dicha", "Dicho", "Asimismo", "Además", "Texto", "Vigente"}
# Page furniture: never part of a name, even right after «de».
LAW_NOISE = {"Doc", "Página", "Pág", "Artículo", "Texto", "Vigente", "Propuesto"}
SECOND_LAW_RE = re.compile(r" (?:y|e) (?=(?:Ley|Código|Reglamento) )")


def trim_law(name):
    """Drop what a PDF glues onto a law name: footnote numbers («México20»), table headings in capitals
    («TEXTO VIGENTE»), the start of the next sentence («… Federal La»)."""
    out = []
    for i, word in enumerate(name.split()):
        bare = re.sub(r"\d+$", "", word)
        after_connector = bool(out) and out[-1] in LAW_CONNECTORS
        if bare in LAW_NOISE or (i > 2 and not after_connector and (bare in LAW_STOP or (len(bare) > 1 and bare.isupper()))):
            break
        if bare:
            out.append(bare)
        if bare != word:
            break
    while out and (out[-1] in LAW_CONNECTORS or out[-1] == "Número"):
        out.pop()
    return " ".join(out) if len(out) >= 3 else ""   # «Ley Orgánica» alone names nothing


def find_laws(text, federal=True):
    """Canonical law names mentioned in a turn.

    `federal`: the speaker is in a federal body. There a bare «la Constitución» is the federal one; in a
    state congress it is ambiguous (usually the state's own), so only an explicit federal mention counts.
    """
    found = {trim_law(part) for m in LAW_RE.finditer(text) for part in SECOND_LAW_RE.split(m.group(1).strip())}
    found.discard("")
    for m in STATE_CONSTITUTION_RE.finditer(text):
        found.add(f"Constitución Política {'de la' if ' de la ' in m.group(0) else 'del Estado de'} {m.group(1)}")
    if FEDERAL_CONSTITUTION_RE.search(text) or (federal and CONSTITUTION_RE.search(text)
                                                  and not STATE_CONSTITUTION_RE.search(text)):
        found.add(FEDERAL_CONSTITUTION)
    return sorted(found)


def edit_distance(a, b, limit=3):
    """Levenshtein distance, stopping early once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]
