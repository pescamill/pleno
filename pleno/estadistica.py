"""Official crime figures (SESNSP) for questions and claims: «¿bajaron los homicidios en 2025?».

Periods are always compared month for month: 2026 runs through September, so «2026» is compared with
January–September 2025, never with the whole year. A comparison that crosses the SESNSP's 2026 change of
methodology says so.
"""

import re

from pleno.normalize import fold
from pleno.sources.sesnsp import SOURCE_NOTE

# Words in a question → (column, value, series). Victims are the usual base for crimes against persons.
CRIMES = [
    (["feminicidio", "feminicidios"], ("subtipo", "Feminicidio", "victimas")),
    (["homicidio doloso", "homicidios dolosos", "homicidio", "homicidios", "asesinato", "asesinatos"],
     ("subtipo", "Homicidio doloso", "victimas")),
    (["secuestro", "secuestros"], ("tipo", "Secuestro", "victimas")),
    (["extorsion", "extorsiones"], ("tipo", "Extorsión", "victimas")),
    (["robo de vehiculo", "robo de vehiculos", "robo de auto", "robo de autos"],
     ("subtipo", "Robo de vehículo automotor", "delitos")),
    (["robo", "robos"], ("tipo", "Robo", "delitos")),
    (["narcomenudeo"], ("tipo", "Narcomenudeo", "delitos")),
    (["violencia familiar"], ("tipo", "Violencia familiar", "delitos")),
]
DOWN = r"\b(baj\w*|disminu\w*|reduj\w*|reducc\w*|redu\w*|cay\w*|descend\w*|menos)\b"
UP = r"\b(subi\w*|suben|sube|aument\w*|increment\w*|crec\w*|alza)\b"
PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por ciento)")


def crime_in(text):
    folded = fold(text)
    for words, target in CRIMES:
        if any(re.search(rf"\b{w}\b", folded) for w in words):
            return target
    return None


def monthly(con, column, value, series, state=None):
    assert column in ("tipo", "subtipo")
    sql = (f"SELECT year, month, methodology, SUM(value) FROM crime_stats WHERE series = ? AND {column} = ?"
           + (" AND state = ?" if state else "") + " GROUP BY year, month, methodology ORDER BY year, month")
    return [{"anio": y, "mes": m, "metodologia": meth, "valor": v}
            for y, m, meth, v in con.execute(sql, (series, value, *([state] if state else [])))]


def compare(rows, year):
    """Months of `year` that have data, against the same months of the previous year."""
    months = {r["mes"] for r in rows if r["anio"] == year}
    if not months:
        return None
    now = sum(r["valor"] for r in rows if r["anio"] == year)
    before = sum(r["valor"] for r in rows if r["anio"] == year - 1 and r["mes"] in months)
    methods = {r["metodologia"] for r in rows if r["anio"] in (year, year - 1) and r["mes"] in months}
    return {"anio": year, "meses": sorted(months), "valor": now, "anio_anterior": before,
            "cambio_pct": round(100 * (now - before) / before, 1) if before else None,
            "cambio_de_metodologia": len(methods) > 1}


def check_claim(con, claim, q, states=()):
    """The official figure behind a claim about crime going up or down. None if the claim is not about that."""
    target = crime_in(claim)
    folded = re.sub(r"\bbaja california\b", " ", fold(claim))   # «Baja» there is a name, not a direction
    direction = "baja" if re.search(DOWN, folded) else "alza" if re.search(UP, folded) else None
    if not target:
        return None
    column, value, series = target
    state = states[0] if len(states) == 1 else None
    rows = monthly(con, column, value, series, state)
    if not rows:
        return None
    year = int(q.desde[:4]) if q.desde else max(r["anio"] for r in rows)
    cmp = compare(rows, year)
    if not cmp or cmp["cambio_pct"] is None:
        return None
    actual = "baja" if cmp["cambio_pct"] < 0 else "alza" if cmp["cambio_pct"] > 0 else "igual"
    pct = PCT_RE.search(claim)
    if not direction:
        verdict = "revisar"
    elif direction != actual:
        verdict = "contradicha"
    elif pct and abs(abs(float(pct[1].replace(",", "."))) - abs(cmp["cambio_pct"])) > 3:
        verdict = "mixta"            # right direction, figure off by more than 3 points
    else:
        verdict = "respaldada"
    span = (f"enero–{_MONTHS[max(cmp['meses']) - 1]}" if len(cmp["meses"]) < 12 else "todo el año")
    where = f" en {state}" if state else " en el país"
    text = (f"{value} ({'víctimas' if series == 'victimas' else 'carpetas de investigación'}){where}, {span}: "
            f"{cmp['valor']:,} en {year} contra {cmp['anio_anterior']:,} en {year - 1} "
            f"({'+' if cmp['cambio_pct'] > 0 else ''}{cmp['cambio_pct']}%).")
    if verdict == "mixta":
        text += f" La dirección coincide, pero la cifra dicha ({pct[1]}%) se aleja de la oficial."
    if cmp["cambio_de_metodologia"]:
        text += " Ojo: el SESNSP cambió de metodología en 2026; la comparación cruza ese cambio."
    return {"veredicto": verdict, "texto": text, "delito": value, "serie": series, "estado": state,
            "comparacion": cmp, "mensual": [r for r in rows if r["anio"] >= year - 1], "fuente": SOURCE_NOTE,
            "fuente_url": "https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva"}


_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"]
