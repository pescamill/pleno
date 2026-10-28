"""«Verificar si X es cierto»: compare a claim with the public record.

Pleno never says a claim is true or false; it says what the record shows:

- respaldada: the record contains what the claim says;
- contradicha: the record shows something else (another vote, another speaker);
- mixta: some evidence supports it and some contradicts it;
- sin_evidencia: nothing in the record matches;
- revisar: there are related passages, but a person has to read them.

Two kinds of claims are checked exactly, without a model:
  votes («X votó a favor de la reforma judicial») against the roll call, and
  quotes («X dijo "…"») against the exact text of every turn.
Anything else goes to the language model, which only sees retrieved passages and must copy the words it relies
on; a quote that is not literally in the passage is thrown away.
"""

import json
import random
import re
from collections import Counter
import urllib.error

from pleno import answer as rag
from pleno import db, estadistica, nlq
from pleno.normalize import fold
from pleno.search import Query, fts_query, search
from pleno.sources.transcript import spanish_date

VERDICTS = ("respaldada", "contradicha", "mixta", "sin_evidencia", "revisar")
LABELS = {
    "respaldada": "El registro lo respalda",
    "contradicha": "El registro muestra otra cosa",
    "mixta": "Evidencia mixta",
    "sin_evidencia": "Sin evidencia en el registro",
    "revisar": "Hay pasajes relacionados: léelos",
}
PRESIDENCY_RE = re.compile(r"\b(la presidenta|el presidente|sheinbaum|lopez obrador|amlo)\b")
FIGURE_LABELS = {
    "respaldada": "Las cifras oficiales lo respaldan",
    "contradicha": "Las cifras oficiales muestran otra cosa",
    "mixta": "La tendencia coincide, la cifra no",
    "revisar": "Estas son las cifras oficiales",
}
CAST_SENSES = ("A favor", "En contra", "Abstención")
VOTE_RE = re.compile(r"\b(?:vot[oó]|votaron)\s+(a favor|en contra)\b|\bse abstuvo\b", re.I)
QUOTE_RE = re.compile(r"[«\"“]([^»\"”]{12,300})[»\"”]")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2} de [a-záéíóú]+ de \d{4})\b", re.I)
SYSTEM = (
    "Comparas una afirmación con fragmentos numerados de versiones estenográficas oficiales de México. "
    "No juzgas si la afirmación es verdadera en el mundo: solo si estos fragmentos la respaldan o la contradicen. "
    "Responde SOLO con JSON: {\"evidencias\": [{\"n\": número, \"postura\": \"respalda\"|\"contradice\"|\"relacionada\", "
    "\"cita\": \"palabras copiadas EXACTAMENTE del fragmento\"}], \"resumen\": \"2 a 4 oraciones en español\"}. "
    "Incluye solo fragmentos pertinentes. Si ninguno sirve, devuelve evidencias vacías."
)


def _people(con, claim, q):
    """Who the claim is about: someone named in full first, otherwise what the question parser found."""
    folded = fold(claim)
    best = []
    places = {w for words in nlq.STATE_WORDS.values() for w in words}
    for pid, name in con.execute("SELECT id, name FROM people"):
        tokens = fold(name).split()
        if fold(name) in places:     # transcripts sometimes label a speaker «Baja California»
            continue
        if len(tokens) >= 2 and all(re.search(rf"\b{re.escape(t)}\b", folded) for t in tokens):
            best.append((len(tokens), pid))
    return [max(best)[1]] if best else q.personas


def _date(claim):
    m = DATE_RE.search(claim)
    if not m:
        return None
    return m[1] or spanish_date(m[2])


def _words(text):
    return re.findall(r"[\wáéíóúñü]+", fold(text))


def _overlap(a, b):
    sa, sb = set(_words(a)) - {"de", "la", "el", "los", "las", "y", "en", "del", "que", "por", "se", "a"}, set(_words(b))
    return len(sa & sb) / max(1, len(sa))


def check_vote(con, claim, people):
    m = VOTE_RE.search(claim)
    said = "Abstención" if m[0].lower().startswith("se abst") else ("A favor" if "favor" in m[1].lower() else "En contra")
    topic = re.sub(r"[«»\"“”]", " ", claim[m.end():])
    topic = DATE_RE.sub(" ", re.sub(r"^\s*(?:de|en|sobre|por|a)\s+(?:la|el|los|las)?\s*", "", topic))
    when = _date(claim)
    rows = con.execute("SELECT v.id, v.date, v.title, v.source_url, c.sense FROM vote_casts c JOIN votes v ON v.id = c.vote_id "
                       f"WHERE c.person_id IN ({','.join('?' * len(people))})" + (" AND v.date = ?" if when else ""),
                       (*people, *([when] if when else []))).fetchall()
    scored = sorted(((_overlap(topic, r["title"]), dict(r)) for r in rows), key=lambda x: -x[0])
    if not scored or scored[0][0] < 0.5:
        return {"veredicto": "sin_evidencia", "texto": "No encontré una votación nominal de esa persona sobre ese tema.",
                "votaciones": []}
    best = [r for s, r in scored if s >= scored[0][0] - 0.05][:5]
    senses = {r["sense"] for r in best}
    if senses == {said}:
        verdict = "respaldada"
    elif said in senses:
        verdict = "mixta"
    else:
        verdict = "contradicha"
    tally = ", ".join(f"{s} en {n}" for s, n in Counter(r["sense"] for r in best).most_common())
    text = (f"Dice «{said}». En {len(best)} votación(es) nominal(es) que coinciden con el tema, el registro muestra: "
            f"{tally}.")
    return {"veredicto": verdict, "texto": text, "votaciones": best}


def phrase_turns(con, phrase, limit=50, people=()):
    q = fts_query(f'"{" ".join(_words(phrase))}"')
    if not q:
        return []
    who = f" AND t.person_id IN ({','.join('?' * len(people))})" if people else ""
    return [dict(r) for r in con.execute(
        "SELECT t.id, t.document_id, t.person_id, COALESCE(p.name, t.speaker) AS speaker, t.role, d.date, d.source_url, "
        "i.name AS institution FROM turns_fts f JOIN turns t ON t.id = f.rowid JOIN documents d ON d.id = t.document_id "
        "JOIN institutions i ON i.id = d.institution_id LEFT JOIN people p ON p.id = t.person_id "
        f"WHERE turns_fts MATCH ?{who} ORDER BY d.date LIMIT ?", (q, *people, limit))]


def check_quote(con, phrase, people):
    mine = phrase_turns(con, phrase, people=people) if people else []
    if mine:
        t = mine[0]
        return {"veredicto": "respaldada", "apariciones": mine[:10],
                "texto": f"La frase aparece {len(mine)} vez(veces); la primera, {t['date']} en {t['institution']}."}
    found = phrase_turns(con, phrase)
    if not found:
        return {"veredicto": "sin_evidencia", "texto": "Esa frase no aparece en ninguna versión estenográfica.",
                "apariciones": []}
    if not people:
        return {"veredicto": "respaldada", "apariciones": found[:10],
                "texto": f"La frase aparece; la primera vez, {found[0]['date']}, dicha por {found[0]['speaker']}."}
    others = list(dict.fromkeys(t["speaker"] for t in found))
    return {"veredicto": "contradicha", "apariciones": found[:10],
            "texto": f"La frase sí aparece, pero dicha por: {', '.join(others[:5])}."}


def _llm_judge(con, claim, hits):
    llm = rag.load_config()["llm"]
    context = rag.context_block(hits)
    body = rag.call_llm({**llm, "max_tokens": 900}, claim, context, system=SYSTEM)
    data = json.loads(re.search(r"\{.*\}", body, re.S)[0])
    texts = {h["id"]: con.execute("SELECT text FROM turns WHERE id = ?", (h["id"],)).fetchone()[0] for h in hits}
    kept = []
    for e in data.get("evidencias", []):
        n = int(e.get("n", 0))
        cita = (e.get("cita") or "").strip()
        if 1 <= n <= len(hits) and cita and " ".join(cita.split()) in " ".join(texts[hits[n - 1]["id"]].split()):
            kept.append({"n": n, "postura": e.get("postura"), "cita": cita})
    return kept, data.get("resumen", ""), llm["model"]


def related(con, q, k=12):
    """Passages about the claim. Every keyword must match, so when that finds nothing we relax step by step:
    first the dates, then keep only the most specific words."""
    base = {**q.to_dict(), "limite": k, "pagina": 1, "orden": "relevancia"}
    words = sorted(q.texto.split(), key=len, reverse=True)
    for attempt in (base, {**base, "desde": "", "hasta": ""},
                    {**base, "texto": " ".join(words[:2])}, {**base, "texto": words[0] if words else ""}):
        hits = search(con, Query.from_dict(attempt))["resultados"]
        if hits:
            return hits
    return []


def check_general(con, claim, q, use_llm=True):
    hits = related(con, q)
    if not hits:
        return {"veredicto": "sin_evidencia", "texto": "No encontré intervenciones relacionadas.", "fuentes": []}
    if not use_llm:
        return {"veredicto": "revisar", "texto": "Estas intervenciones tratan el tema; léelas para juzgar.",
                "fuentes": hits}
    try:
        kept, summary, model = _llm_judge(con, claim, hits)
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, ValueError, TypeError) as e:
        return {"veredicto": "revisar", "fuentes": hits,
                "texto": f"No pude comparar automáticamente ({type(e).__name__}); estas son las intervenciones relacionadas."}
    stances = Counter(e["postura"] for e in kept)
    verdict = ("mixta" if stances["respalda"] and stances["contradice"] else "respaldada" if stances["respalda"]
               else "contradicha" if stances["contradice"] else "revisar")
    if not kept:
        # The model's prose is only shown when at least one of its quotes is literally in the record.
        return {"veredicto": "revisar", "fuentes": hits, "modelo": model, "evidencias": [],
                "texto": "El modelo no aportó citas comprobables; estas son las intervenciones relacionadas."}
    count = f"{stances['respalda']} fragmento(s) la respaldan y {stances['contradice']} la contradicen."
    return {"veredicto": verdict, "texto": f"{count} {summary}".strip(), "evidencias": kept, "fuentes": hits,
            "modelo": model}


SAYING_RE = re.compile(r"\b(dijo|dice|afirm\w*|asegur\w*|declar\w*|sostuvo|seg[uú]n|anunci\w*|inform\w*)\b", re.I)


def verify(con, claim, use_llm=True):
    q, notes = nlq.interpret(claim, db.DB_FILE)
    people = _people(con, claim, q)
    states = [s for s, words in nlq.STATE_WORDS.items() if any(re.search(rf"\b{w}\b", fold(claim)) for w in words)]
    figures = estadistica.check_claim(con, claim, q, states)
    attributed = bool(people or SAYING_RE.search(claim) or PRESIDENCY_RE.search(fold(claim)))
    if VOTE_RE.search(claim) and people:
        result, method = check_vote(con, claim, people), "registro nominal"
    elif QUOTE_RE.search(claim):
        result, method = check_quote(con, QUOTE_RE.search(claim)[1], people), "texto exacto"
    elif figures and not attributed:
        # A bare fact about crime («bajaron los homicidios en 2025»): the official figures decide.
        result, method = {k: figures[k] for k in ("veredicto", "texto")}, "cifras oficiales (SESNSP)"
    else:
        result, method = check_general(con, claim, q, use_llm), "modelo con citas verificadas" if use_llm else "búsqueda"
    if figures:
        figures["etiqueta"] = FIGURE_LABELS[figures["veredicto"]]
    label = figures["etiqueta"] if method.startswith("cifras") else LABELS[result["veredicto"]]
    return {"afirmacion": claim, "metodo": method, "etiqueta": label, "personas": people,
            "consulta": q.to_dict(), "interpretacion": notes, "cifras": figures, **result}


def gold_claims(con, n=15, seed=5):
    """Claims built from the record, with the verdict they must get: true copies, altered copies (other sense,
    other speaker) and phrases nobody said. Built by code, so they test the structure, not a model."""
    rng = random.Random(seed)
    cases = []
    casts = con.execute(
        "SELECT c.person_id, p.name, c.sense, v.id, v.date, v.title FROM vote_casts c JOIN people p ON p.id = c.person_id "
        "JOIN votes v ON v.id = c.vote_id WHERE c.sense IN ('A favor', 'En contra') ORDER BY c.vote_id, c.person_id").fetchall()
    same_day = {}
    for r in con.execute("SELECT date, SUBSTR(title, 1, 60) FROM votes"):
        same_day[r[0], r[1]] = same_day.get((r[0], r[1]), 0) + 1
    casts = [c for c in casts if same_day[c["date"], c["title"][:60]] == 1]
    for c in rng.sample(casts, min(n, len(casts))):
        title = " ".join(c["title"].split()[:18])
        flip = "en contra" if c["sense"] == "A favor" else "a favor"
        cases.append({"afirmacion": f"{c['name']} votó {c['sense'].lower()} de «{title}» el {c['date']}", "espera": "respaldada"})
        cases.append({"afirmacion": f"{c['name']} votó {flip} de «{title}» el {c['date']}", "espera": "contradicha"})

    # Crime figures: the direction of the change, read straight from the table, in plain words.
    words = {"Homicidio doloso": "los homicidios", "Feminicidio": "los feminicidios", "Secuestro": "los secuestros",
             "Extorsión": "las extorsiones"}
    states = [r[0] for r in con.execute("SELECT DISTINCT state FROM crime_stats ORDER BY state")]
    for _ in range(n if states else 0):
        crime, state, year = rng.choice(sorted(words)), rng.choice(states), rng.choice(range(2017, 2026))
        column = "subtipo" if crime in ("Homicidio doloso", "Feminicidio") else "tipo"
        total = lambda y: con.execute(f"SELECT SUM(value) FROM crime_stats WHERE series = 'victimas' AND {column} = ? "
                                      "AND state = ? AND year = ?", (crime, state, y)).fetchone()[0] or 0
        now, before = total(year), total(year - 1)
        if now == before or not before:
            continue
        said = rng.choice(["Bajaron", "Aumentaron"])
        actual = "Bajaron" if now < before else "Aumentaron"
        cases.append({"afirmacion": f"{said} {words[crime]} en {state} en {year}",
                      "espera": "respaldada" if said == actual else "contradicha"})

    top = con.execute("SELECT MAX(id) FROM turns").fetchone()[0]
    quotes = 0
    while quotes < n:
        row = con.execute("SELECT t.id, t.text, t.person_id, p.name, d.institution_id FROM turns t JOIN people p ON p.id = t.person_id "
                          "JOIN documents d ON d.id = t.document_id WHERE t.id >= ? AND LENGTH(t.text) > 400 "
                          "AND d.institution_id <> 'fgr' LIMIT 1", (rng.randrange(1, top),)).fetchone()
        if not row:
            continue
        words = row["text"].split()
        start = rng.randrange(0, len(words) - 12)
        phrase = " ".join(w.strip("«»\"“”") for w in words[start:start + 12])
        found = phrase_turns(con, phrase)
        if not found or len({t["person_id"] for t in found}) > 1:
            continue
        other = con.execute("SELECT p.id, p.name FROM people p JOIN turns t ON t.person_id = p.id JOIN documents d "
                            "ON d.id = t.document_id WHERE d.institution_id = ? AND p.id <> ? GROUP BY p.id "
                            "ORDER BY COUNT(*) DESC LIMIT 1 OFFSET ?", (row["institution_id"], row["person_id"],
                                                                         rng.randrange(0, 20))).fetchone()
        if not other:
            continue
        cases.append({"afirmacion": f"{row['name']} dijo «{phrase}»", "espera": "respaldada"})
        cases.append({"afirmacion": f"{other['name']} dijo «{phrase}»", "espera": "contradicha"})
        mixed = " ".join(phrase.split()[:6] + rng.choice(casts)["title"].split()[3:9])
        if not phrase_turns(con, mixed, 1):
            cases.append({"afirmacion": f"{row['name']} dijo «{mixed}»", "espera": "sin_evidencia"})
        quotes += 1
    return cases
