"""Plain Spanish question → structured Query, with an explanation of every filter it inferred.

Rule-based on purpose: every inference is visible, editable and reproducible.
"""

import re
from collections import Counter
from functools import lru_cache

from pleno.normalize import CONNECTORS, fold, name_tokens
from pleno.search import PRESIDENCY, STOPWORDS, Query

INSTITUTION_WORDS = {
    "presidencia": ["mananera", "mananeras", "conferencia matutina", "presidencia", "palacio nacional"],
    "diputados": ["camara de diputados", "san lazaro", "camara baja", "diputados", "diputadas",
                  "diputados federales", "diputadas federales"],
    "scjn": ["suprema corte", "scjn", "la corte", "ministros de la corte", "ministras de la corte", "ministra", "ministro"],
    "fgr": ["fiscalia general de la republica", "fiscalia general", "fgr", "la fiscalia", "fiscalia"],
}
# State → the name used in institutions.state. «México» alone is the country, never the state.
STATE_WORDS = {
    "Ciudad de México": ["ciudad de mexico", "cdmx", "congreso capitalino", "capital del pais"],
    "Estado de México": ["estado de mexico", "edomex", "mexiquense"],
    **{name: [fold(name)] for name in (
        "Aguascalientes", "Baja California Sur", "Baja California", "Campeche", "Chiapas", "Chihuahua", "Coahuila",
        "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "Michoacán", "Morelos", "Nayarit",
        "Nuevo León", "Oaxaca", "Puebla", "Querétaro", "Quintana Roo", "San Luis Potosí", "Sinaloa", "Sonora",
        "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatán", "Zacatecas")},
}
LOCAL_WORDS = ["congreso local", "congresos locales", "congreso estatal", "congresos estatales", "diputados locales",
               "diputadas locales", "legislatura local", "congreso de", "congreso del estado"]
PARTY_WORDS = {
    "MORENA": ["morena"], "PAN": ["pan", "accion nacional", "panistas", "panista"],
    "PRI": ["pri", "revolucionario institucional", "priistas", "priista"],
    "PVEM": ["pvem", "partido verde", "verde ecologista"], "PT": ["pt", "partido del trabajo"],
    "MC": ["mc", "movimiento ciudadano"], "PRD": ["prd"],
}
ROLE_WORDS = {
    "diputad": ["diputado", "diputada", "diputados", "diputadas", "legisladores", "legisladoras"],
    "secretari": ["secretario", "secretaria", "secretarios", "gabinete"],
    "gobernador": ["gobernador", "gobernadora", "gobernadores"],
    "periodista": ["periodista", "periodistas", "reportero", "reportera", "prensa"],
}
MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
QUESTION_WORDS = set("""que quien quienes cual cuales cuando donde como cuanto cuanta cuantos cuantas dijo dijeron dice dicen
hablo hablaron habla hablan menciono mencionaron mencionan opina opinan opino declaro declararon sobre acerca respecto
tema temas veces todo todos todas han ha sido fue fueron hizo hicieron propuso propusieron ultimo ultima ultimos ultimas""".split())


_WORD = set("abcdefghijklmnopqrstuvwxyz0123456789")


def _contains(folded, phrase):
    """`phrase` appears in `folded` as whole words. Plain `find`, not a regex: it runs once per law name
    (thousands) on every question, and compiling a pattern each time made a question take seconds."""
    i = folded.find(phrase)
    while i != -1:
        j = i + len(phrase)
        if (i == 0 or folded[i - 1] not in _WORD) and (j == len(folded) or folded[j] not in _WORD):
            return True
        i = folded.find(phrase, i + 1)
    return False


@lru_cache(maxsize=1)
def _people_index(db_path):
    from pleno import db
    con = db.connect(db_path)
    rows = con.execute(
        "SELECT p.id, p.name, p.party, COUNT(t.id) AS n, EXISTS (SELECT 1 FROM memberships m WHERE m.person_id = p.id) AS "
        "official FROM people p LEFT JOIN turns t ON t.person_id = p.id GROUP BY p.id HAVING n >= 3 OR official").fetchall()
    # Descriptions that the transcripts used as a name («Derechohabiente del Programa de Vivienda…») are not people
    # anyone asks for by name, and their words («vivienda», «Oaxaca») would hijack the question.
    rows = [r for r in rows if r["official"] or (len(r["name"].split()) <= 6 and not re.search(r"[\d,]", r["name"]))]
    people = [(r["id"], r["name"], set(name_tokens(r["name"])), r["n"]) for r in rows]
    surname_owners = Counter(tok for _, _, toks, _ in people for tok in toks)
    laws = con.execute(
        "SELECT l.id, l.name, COUNT(*) AS n FROM laws l JOIN mentions m ON m.law_id = l.id GROUP BY l.id").fetchall()
    return people, surname_owners, [(r["id"], r["name"], fold(r["name"]), r["n"]) for r in laws]


def interpret(question, db_path):
    q, notes = Query(), []
    folded = fold(question)
    consumed = set()

    for inst, words in INSTITUTION_WORDS.items():
        hit = next((w for w in words if _contains(folded, w)), None)
        if hit:
            q.instituciones.append(inst)
            consumed.update(hit.split())
            notes.append({"filtro": "institución", "valor": inst, "por": hit})

    states = []
    for state, words in STATE_WORDS.items():
        hit = next((w for w in words if _contains(folded, w)), None)
        if hit and not any(_contains(folded, o) and hit in o and o != hit for ws in STATE_WORDS.values() for o in ws):
            states.append(state)
            consumed.update(hit.split())
            notes.append({"filtro": "estado", "valor": state, "por": hit})
    local = any(_contains(folded, w) for w in LOCAL_WORDS) or (bool(states) and _contains(folded, "diputad"))
    if states or local:
        # «diputados de Oaxaca», «congreso local»: the state's legislature, not the federal Chamber.
        if "diputados" in q.instituciones and not _contains(folded, "camara de diputados") and not _contains(folded, "federal"):
            q.instituciones.remove("diputados")
            notes[:] = [n for n in notes if not (n["filtro"] == "institución" and n["valor"] == "diputados")]
        consumed.update({"congreso", "congresos", "local", "locales", "estatal", "estatales", "diputados", "diputadas",
                         "estado", "legislatura"})
    q.estados = states

    for party, words in PARTY_WORDS.items():
        hit = next((w for w in words if _contains(folded, w)), None)
        if hit and not (hit == "pan" and _contains(folded, "pan de")):
            q.partidos.append(party)
            consumed.update(hit.split())
            notes.append({"filtro": "partido", "valor": party, "por": hit})

    for role, words in ROLE_WORDS.items():
        hit = next((w for w in words if _contains(folded, w)), None)
        if hit and not (role == "diputad" and "diputados" in q.instituciones):
            q.cargos.append(role)
            consumed.add(hit)
            notes.append({"filtro": "cargo", "valor": role, "por": hit})

    people, owners, laws = _people_index(str(db_path))
    tokens = set(re.findall(r"[a-z]+", folded)) - CONNECTORS - consumed   # «Cámara» is the chamber, not a surname
    scored = []
    for pid, name, toks, n in people:
        common = toks & tokens
        unique_surname = any(owners[t] == 1 and len(t) > 3 for t in common)
        if len(common) >= 2 or unique_surname:
            scored.append((len(common), n, pid, name, common))
    full = [s for s in scored if s[4] == set(name_tokens(s[3]))]
    scored = full or scored          # someone named in full beats partial matches («Diana … Orozco»)
    if scored:
        best = max(s[0] for s in scored)
        for _, n, pid, name, common in sorted(scored, key=lambda s: (-s[0], -s[1]))[:3]:
            if len(common) == best:
                q.personas.append(pid)
                consumed.update(common)
                notes.append({"filtro": "persona", "valor": pid, "etiqueta": name, "por": " ".join(sorted(common))})

    if not q.personas and re.search(r"\b(la presidenta|el presidente|presidenta de mexico|presidente de mexico)\b", folded):
        q.cargos.append(PRESIDENCY)
        notes.append({"filtro": "cargo", "valor": PRESIDENCY, "etiqueta": "Presidencia de México", "por": "presidenta/presidente"})
        consumed.add("mexico")

    # Laws named in full first, longest first; only then the distinctive part of a name.
    for lid, name, lname, n in sorted(laws, key=lambda l: (not _contains(folded, l[2]), -len(l[2]))):
        # The distinctive part of the name: «ley general de aguas» → «aguas», «ley del agua» → «agua».
        core = re.sub(r"^(?:ley|codigo|reglamento)(?: general| federal| nacional| organica)?"
                      r"(?: de la| de los| de las| del| de| para| sobre)? ", "", lname)
        # Matching on the core alone needs the question to talk about a law: «Congreso de la Ciudad de México»
        # is not «Ley Orgánica del Congreso de la Ciudad de México», and «Guardia Nacional» is a topic.
        if len(core) > 4 and (_contains(folded, lname) or (len(core.split()) >= 2 and _contains(folded, core)
                                                           and re.search(r"\b(ley|leyes|codigo|reglamento)\b", folded))):
            q.leyes.append(lid)
            consumed.update(lname.split())
            notes.append({"filtro": "ley", "valor": lid, "etiqueta": name, "por": name})
            break

    # A state next to a federal actor («la presidenta sobre Jalisco») is a topic, not a filter.
    if q.estados and not local and (q.personas or PRESIDENCY in q.cargos or set(q.instituciones) & {"presidencia", "scjn"}):
        for state in q.estados:
            consumed.difference_update(fold(state).split())
        notes[:] = [n for n in notes if n["filtro"] != "estado"]
        q.estados = []

    years = re.findall(r"\b(20[12]\d)\b", folded)
    month = next((m for m in MONTHS if _contains(folded, m)), None)
    if len(years) >= 2 and ("entre" in folded or " y " in folded or " a " in folded):
        q.desde, q.hasta = f"{min(years)}-01-01", f"{max(years)}-12-31"
    elif years and month:
        y, m = years[0], MONTHS[month]
        q.desde, q.hasta = f"{y}-{m:02d}-01", f"{y}-{m:02d}-31"
        consumed.add(month)
    elif years and re.search(r"\b(desde|a partir de)\b", folded):
        q.desde = f"{years[0]}-01-01"
    elif years:
        q.desde, q.hasta = f"{years[0]}-01-01", f"{years[0]}-12-31"
    if q.desde or q.hasta:
        consumed.update(years)
        notes.append({"filtro": "fechas", "valor": f"{q.desde or '…'} → {q.hasta or '…'}", "por": " ".join(years)})

    words = [w for w in re.findall(r"«[^»]+»|\"[^\"]+\"|[\wáéíóúñü]+", question)
             if fold(w) not in consumed and fold(w) not in STOPWORDS and fold(w) not in QUESTION_WORDS
             and fold(w) not in {"partido", "grupo", "parlamentario", "presidenta", "presidente", "ley", "de", "del"}
             and not re.fullmatch(r"20[12]\d", w)]
    q.texto = " ".join(words)
    if q.texto:
        notes.insert(0, {"filtro": "texto", "valor": q.texto, "por": "palabras clave"})
    return q, notes
