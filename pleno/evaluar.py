"""Quality evals for every iteration: `pleno evaluar`.

Each run measures the database and the query layer, appends the result to data/evals/historial.jsonl and
compares it with the previous run, so a change that makes the structure worse shows up as a regression.

The gold answers come from the records themselves (the official roster, the roll-call votes, the exact text of
each turn) or from hand-written cases in evals/; no model writes or grades them.
"""

import datetime as dt
import json
import random
import re
import statistics
import time
from pathlib import Path

from pleno import db, nlq
from pleno.normalize import fold
from pleno.search import Query, search

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "evals" / "historial.jsonl"
GOLD_DIR = ROOT / "evals"
PRIVATE_ROLES = ("Periodista", "Público", "Voz", "Intervención")

# name → (better: "alto" | "bajo", tolerance before a change counts as a regression)
METRICS = {
    "integridad.documentos_sin_intervenciones": ("bajo", 0),
    "integridad.fechas_imposibles": ("bajo", 0),
    "integridad.votaciones_fuera_de_legislatura": ("bajo", 0),
    "integridad.intervenciones_vacias": ("bajo", 0),
    "integridad.votos_con_partido_desconocido": ("bajo", 0),
    "atribucion.con_persona_pct": ("alto", 0.5),
    "atribucion.legisladores_con_partido_pct": ("alto", 0.5),
    "atribucion.partido_coincide_con_padron_pct": ("alto", 0.5),
    "atribucion.nombres_sospechosos": ("bajo", 5),
    "leyes.menciones_federales_en_catalogo_pct": ("alto", 0.5),
    "leyes.nombres_con_ruido": ("bajo", 10),
    "busqueda.cita_encontrada_recall10_pct": ("alto", 1.0),
    "busqueda.cita_documento_exacto_pct": ("alto", 3.0),
    "busqueda.latencia_p50_ms": ("bajo", 75),
    "nlq.exactitud_pct": ("alto", 0),
    "verificacion.exactitud_pct": ("alto", 0),
    "reportes.corregidos_pct": ("alto", 0),
}


def _one(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def _pct(a, b):
    return round(100 * a / b, 2) if b else None


def integrity(con):
    today = dt.date.today().isoformat()
    return {
        "documentos_sin_intervenciones": _one(
            con, "SELECT COUNT(*) FROM documents d WHERE NOT EXISTS (SELECT 1 FROM turns t WHERE t.document_id = d.id)"),
        "fechas_imposibles": _one(con, "SELECT COUNT(*) FROM documents WHERE date IS NULL OR date < '2018-01-01' "
                                       "OR date > ?", today),
        "votaciones_fuera_de_legislatura": _one(con, "SELECT COUNT(*) FROM votes WHERE date < '2024-09-01' OR date > ?",
                                                today),
        "intervenciones_vacias": _one(con, "SELECT COUNT(*) FROM turns WHERE LENGTH(TRIM(text)) < 5"),
        # Every roll-call vote must carry a party acronym (MORENA, PAN… or IND), never the site's internal id.
        "votos_con_partido_desconocido": _one(con, "SELECT COUNT(*) FROM vote_casts WHERE party IS NULL "
                                                   "OR party NOT GLOB '[A-Z]*'"),
    }


def attribution(con):
    marks = ",".join("?" * len(PRIVATE_ROLES))
    official = _one(con, f"SELECT COUNT(*) FROM turns WHERE COALESCE(role, '') NOT IN ({marks}) AND outlet IS NULL",
                    *PRIVATE_ROLES)
    with_person = _one(con, f"SELECT COUNT(*) FROM turns WHERE person_id IS NOT NULL AND COALESCE(role, '') NOT IN "
                            f"({marks}) AND outlet IS NULL", *PRIVATE_ROLES)
    legislators = con.execute(
        "SELECT p.party FROM people p WHERE EXISTS (SELECT 1 FROM turns t WHERE t.person_id = p.id AND "
        "(t.role LIKE 'Diputad%' OR t.role LIKE 'Senador%'))").fetchall()
    roster = con.execute("SELECT p.party, m.party FROM memberships m JOIN people p ON p.id = m.person_id "
                         "WHERE m.party IS NOT NULL").fetchall()
    names = [r[0] for r in con.execute("SELECT name FROM people")]
    suspicious = [n for n in names if len(n.split()) < 2 or re.search(r"\d", n) or n.isupper()]
    return {
        "con_persona_pct": _pct(with_person, official),
        "legisladores_con_partido_pct": _pct(sum(1 for (p,) in legislators if p), len(legislators)),
        "partido_coincide_con_padron_pct": _pct(sum(1 for a, b in roster if a == b), len(roster)),
        "nombres_sospechosos": len(suspicious),
        "ejemplos_nombres_sospechosos": suspicious[:10],
    }


LAW_NOISE_RE = re.compile(r"\d|\b[A-ZÁÉÍÓÚÑ]{4,}\b.*\b[A-ZÁÉÍÓÚÑ]{4,}\b|\b(de|del|la|y|para)$|"
                          r"\b(\w+ \w+ \w+)\b.*\b\1\b")


def laws(con):
    federal = _one(con, "SELECT COUNT(*) FROM mentions m JOIN laws l ON l.id = m.law_id WHERE l.jurisdiction = 'federal'")
    in_catalog = _one(con, "SELECT COUNT(*) FROM mentions m JOIN laws l ON l.id = m.law_id "
                           "WHERE l.jurisdiction = 'federal' AND l.official_url IS NOT NULL")
    names = [r[0] for r in con.execute("SELECT name FROM laws")]
    noisy = [n for n in names if LAW_NOISE_RE.search(n)]
    return {"menciones_federales_en_catalogo_pct": _pct(in_catalog, federal), "nombres_con_ruido": len(noisy),
            "ejemplos_ruido": noisy[:10]}


def retrieval(con, n=300, seed=11):
    """A 12-word piece of a real turn must bring back, among the first 10 results, a document that contains it."""
    rng = random.Random(seed)
    top = _one(con, "SELECT MAX(id) FROM turns")
    from pleno.verificar import phrase_turns
    found = exact = tried = 0
    latencies, misses = [], []
    for _ in range(n * 20):          # bounded: a small database may not have n long turns
        if tried >= n:
            break
        row = con.execute("SELECT id, document_id, text FROM turns WHERE id >= ? AND LENGTH(text) > 300 LIMIT 1",
                          (rng.randrange(1, top),)).fetchone()
        if not row:
            continue
        words = re.findall(r"[\wáéíóúñü]+", row[2])
        if len(words) < 40:
            continue
        start = rng.randrange(0, len(words) - 12)
        text = " ".join(words[start:start + 12])
        t = time.perf_counter()
        hits = search(con, Query(texto=text, limite=10))["resultados"]
        latencies.append((time.perf_counter() - t) * 1000)
        tried += 1
        docs = {h["document_id"] for h in hits}
        if row[1] in docs:
            exact += 1
        # Procedural text repeats across sessions («se tiene de primera lectura…»): any document that contains the
        # exact phrase is a right answer, not only the one the phrase was taken from.
        if row[1] in docs or docs & {t["document_id"] for t in phrase_turns(con, text, limit=500)}:
            found += 1
        elif len(misses) < 5:
            misses.append({"consulta": text, "documento": row[1]})
    return {"cita_encontrada_recall10_pct": _pct(found, tried), "cita_documento_exacto_pct": _pct(exact, tried),
            "latencia_p50_ms": round(statistics.median(latencies), 1) if latencies else None, "ejemplos_fallidos": misses}


def nlq_accuracy():
    """Hand-written questions with the filters they must produce (evals/nlq.json)."""
    cases = json.loads((GOLD_DIR / "nlq.json").read_text(encoding="utf-8"))
    ok, failures = 0, []
    for case in cases:
        q = nlq.interpret(case["pregunta"], db.DB_FILE)[0].to_dict()
        wrong = {k: q.get(k) for k, v in case["espera"].items()
                 if (sorted(q.get(k) or []) != sorted(v) if isinstance(v, list)
                     else sorted(fold(q.get(k) or "").split()) != sorted(fold(v).split()))}
        if wrong:
            failures.append({"pregunta": case["pregunta"], "obtuvo": wrong, "espera": case["espera"]})
        else:
            ok += 1
    return {"exactitud_pct": _pct(ok, len(cases)), "casos": len(cases), "fallos": failures}


def verification_accuracy(con, llm=True):
    """Claims built from the records (true ones and altered copies) must get the expected verdict."""
    from pleno import verificar
    cases = verificar.gold_claims(con)
    ok, failures = 0, []
    for case in cases:
        got = verificar.verify(con, case["afirmacion"], use_llm=llm)["veredicto"]
        if got == case["espera"]:
            ok += 1
        elif len(failures) < 8:
            failures.append({"afirmacion": case["afirmacion"], "obtuvo": got, "espera": case["espera"]})
    return {"exactitud_pct": _pct(ok, len(cases)), "casos": len(cases), "fallos": failures}


def reports(con, cases=None):
    """Errors people reported and that were fixed (evals/reportes.json) must stay fixed.

    Each confirmed report becomes a case, so the same mistake cannot come back unnoticed."""
    if cases is None:
        path = GOLD_DIR / "reportes.json"
        cases = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    ok, failures = 0, []
    for case in cases:
        got = _report_value(con, case)
        if got == case["espera"]:
            ok += 1
        else:
            failures.append({"id": case["id"], "tipo": case["tipo"], "obtuvo": got, "espera": case["espera"]})
    return {"corregidos_pct": _pct(ok, len(cases)), "casos": len(cases), "fallos": failures}


def _report_value(con, case):
    kind = case["tipo"]
    if kind == "partido_voto":
        row = con.execute("SELECT party FROM vote_casts WHERE vote_id = ? AND person_id = ?",
                          (case["votacion"], case["persona"])).fetchone()
        return row[0] if row else None
    if kind == "persona_intervencion":
        row = con.execute("SELECT person_id FROM turns WHERE document_id = ? AND text LIKE ? LIMIT 1",
                          (case["documento"], f"%{case['texto']}%")).fetchone()
        return row[0] if row else None
    if kind == "veredicto":
        from pleno import verificar
        return verificar.verify(con, case["afirmacion"], use_llm=False)["veredicto"]
    raise ValueError(f"tipo de reporte desconocido: {kind}")


def run(con=None, llm=False, save=True):
    con = con or db.connect()
    started = time.time()
    result = {
        "fecha": dt.datetime.now().isoformat(timespec="seconds"),
        "integridad": integrity(con), "atribucion": attribution(con), "leyes": laws(con),
        "busqueda": retrieval(con), "nlq": nlq_accuracy(), "verificacion": verification_accuracy(con, llm=llm),
        "reportes": reports(con),
        "tamano": {"documentos": _one(con, "SELECT COUNT(*) FROM documents"),
                   "intervenciones": _one(con, "SELECT COUNT(*) FROM turns"),
                   "personas": _one(con, "SELECT COUNT(*) FROM people"),
                   "leyes": _one(con, "SELECT COUNT(*) FROM laws"), "votaciones": _one(con, "SELECT COUNT(*) FROM votes")},
    }
    result["segundos"] = round(time.time() - started, 1)
    previous = last_run()
    result["regresiones"] = regressions(previous, result) if previous else []
    if save:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result, previous


def last_run():
    if not HISTORY.exists():
        return None
    lines = HISTORY.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1]) if lines else None


def value(result, name):
    group, key = name.split(".")
    return (result.get(group) or {}).get(key)


def regressions(before, after):
    out = []
    for name, (better, tolerance) in METRICS.items():
        a, b = value(before, name), value(after, name)
        if a is None or b is None:
            continue
        worse = b < a - tolerance if better == "alto" else b > a + tolerance
        if worse:
            out.append({"metrica": name, "antes": a, "ahora": b})
    return out


def report(result, previous):
    lines = [f"Evaluación {result['fecha']} ({result['segundos']} s)"]
    for name, (better, _) in METRICS.items():
        b = value(result, name)
        a = value(previous, name) if previous else None
        delta = "" if a is None or b is None or a == b else f"  ({'+' if b > a else ''}{round(b - a, 2)})"
        lines.append(f"  {name:<52} {'' if b is None else b}{delta}  [mejor {better}]")
    for r in result["regresiones"]:
        lines.append(f"  REGRESIÓN {r['metrica']}: {r['antes']} → {r['ahora']}")
    for group in ("nlq", "verificacion", "reportes"):
        for f in result[group].get("fallos", [])[:5]:
            lines.append(f"  falla {group}: {json.dumps(f, ensure_ascii=False)}")
    return "\n".join(lines)
