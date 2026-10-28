"""Structured queries over turns: full text + metadata filters, results, facets and entity profiles."""

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from pleno.normalize import fold

STOPWORDS = set("""
a al algo ante como con contra cual cuales cuando de del desde donde dijo dicho dijeron el ella ellos en entre era es esa ese eso esta
este esto fue ha han hay la las le les lo los mas me mi muy no nos o para pero por que quien quienes se sea segun si sin sobre son su
sus tambien te tiene un una uno unos unas y ya hablo hablaron habla menciono mencionaron mencionan dice dicen cuantas cuantos veces
""".split())
MAX_LIMIT = 100
# Exact role group: the head of the executive, not «Presidenta de la Mesa» nor «Estado de México».
PRESIDENCY = "presidencia de mexico"
PRESIDENCY_ROLES = ("presidenta de mexico", "presidente de mexico")


@dataclass
class Query:
    texto: str = ""
    instituciones: list = field(default_factory=list)
    estados: list = field(default_factory=list)       # state of the institution («Oaxaca»)
    personas: list = field(default_factory=list)      # person ids
    partidos: list = field(default_factory=list)
    cargos: list = field(default_factory=list)        # substring of role, case/accent-insensitive
    leyes: list = field(default_factory=list)         # law ids
    medios: list = field(default_factory=list)
    desde: str = ""
    hasta: str = ""
    orden: str = "relevancia"                          # relevancia | fecha
    despues_de: int = 0                                 # only turns with a larger id (alerts: «new since»)
    limite: int = 20
    pagina: int = 1

    @classmethod
    def from_dict(cls, data):
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self):
        return asdict(self)


def fts_query(text):
    """User text → safe FTS5 query: quoted terms (AND), prefix match on longer words, «phrases» kept."""
    phrases = re.findall(r'"([^"]+)"|«([^»]+)»', text)
    parts = [f'"{(a or b).strip()}"' for a, b in phrases if (a or b).strip()]
    rest = re.sub(r'"[^"]*"|«[^»]*»', " ", text)
    for word in re.findall(r"[\wáéíóúñü]+", rest.lower()):
        if len(word) < 3 or fold(word) in STOPWORDS:
            continue
        parts.append(f'"{word}"*' if len(word) >= 5 else f'"{word}"')
    return " ".join(parts)


def _where(q):
    clauses, params = [], []
    if q.instituciones:
        clauses.append(f"d.institution_id IN ({','.join('?' * len(q.instituciones))})")
        params += q.instituciones
    if q.estados:
        clauses.append(f"d.institution_id IN (SELECT id FROM institutions WHERE state IN ({','.join('?' * len(q.estados))}))")
        params += q.estados
    if q.personas:
        clauses.append(f"t.person_id IN ({','.join('?' * len(q.personas))})")
        params += q.personas
    if q.partidos:
        clauses.append(f"p.party IN ({','.join('?' * len(q.partidos))})")
        params += q.partidos
    if q.cargos:
        parts = []
        for c in q.cargos:
            if fold(c) == PRESIDENCY:
                parts.append(f"fold(t.role) IN ({','.join('?' * len(PRESIDENCY_ROLES))})")
                params += list(PRESIDENCY_ROLES)
            else:
                parts.append("fold(t.role) LIKE ?")
                params.append(f"%{fold(c)}%")
        clauses.append("(" + " OR ".join(parts) + ")")
    if q.leyes:
        clauses.append(f"t.id IN (SELECT turn_id FROM mentions WHERE law_id IN ({','.join('?' * len(q.leyes))}))")
        params += q.leyes
    if q.medios:
        clauses.append(f"t.outlet IN ({','.join('?' * len(q.medios))})")
        params += q.medios
    if q.despues_de:
        clauses.append("t.id > ?")
        params.append(int(q.despues_de))
    if q.desde:
        clauses.append("d.date >= ?")
        params.append(q.desde)
    if q.hasta:
        clauses.append("d.date <= ?")
        params.append(q.hasta)
    return clauses, params


def _base(q):
    match = fts_query(q.texto) if q.texto else ""
    clauses, params = _where(q)
    joins = "JOIN documents d ON d.id = t.document_id LEFT JOIN people p ON p.id = t.person_id"
    if match:
        joins = "JOIN turns_fts f ON f.rowid = t.id " + joins
        clauses.insert(0, "turns_fts MATCH ?")
        params.insert(0, match)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return joins, where, params, bool(match)


def register(con):
    con.create_function("fold", 1, lambda s: fold(s) if s else "", deterministic=True)


def search(con, q, max_limit=MAX_LIMIT, full_text=False):
    register(con)
    limit = max(1, min(int(q.limite or 20), max_limit))
    offset = (max(1, int(q.pagina or 1)) - 1) * limit
    joins, where, params, has_text = _base(q)
    snippet = "snippet(turns_fts, 0, '⟦', '⟧', '…', 48)" if has_text and not full_text else "t.text"
    order = "bm25(turns_fts)" if has_text and q.orden != "fecha" else "d.date DESC, t.idx"
    rows = con.execute(
        f"""SELECT t.id, t.document_id, t.idx, t.speaker, t.role, t.person_id, t.outlet, {snippet} AS snippet,
                   d.date, d.title, d.source_url, d.institution_id, i.name AS institution,
                   p.name AS person, p.party
            FROM turns t {joins} JOIN institutions i ON i.id = d.institution_id
            {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    total = con.execute(f"SELECT COUNT(*) FROM turns t {joins} {where}", params).fetchone()[0]
    results = [dict(r) for r in rows]
    if not has_text and not full_text:
        names = [r[0] for r in con.execute(
            f"SELECT name FROM laws WHERE id IN ({','.join('?' * len(q.leyes))})", q.leyes)] if q.leyes else []
        for r in results:
            r["snippet"] = window(r["snippet"], names)
    attach_laws(con, results)
    return {"total": total, "pagina": q.pagina, "limite": limit, "resultados": results}


def attach_laws(con, turns):
    """Add the laws each turn mentions, so a result can link straight to them."""
    ids = [t["id"] for t in turns]
    by_turn = defaultdict(list)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for turn_id, lid, name in con.execute(
                f"""SELECT m.turn_id, l.id, l.name FROM mentions m JOIN laws l ON l.id = m.law_id
                    WHERE m.turn_id IN ({','.join('?' * len(chunk))}) ORDER BY l.name""", chunk):
            by_turn[turn_id].append({"id": lid, "nombre": name})
    for t in turns:
        t["leyes"] = by_turn.get(t["id"], [])
    return turns


def labels(con, q):
    """Display names for the person and law ids in a query, so a shared link renders without guessing."""
    out = {}
    for table, ids in (("people", q.personas), ("laws", q.leyes)):
        if ids:
            out.update(con.execute(
                f"SELECT id, name FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall())
    return out


def window(text, needles, size=360):
    """Excerpt around the first needle found (highlighted), or the opening of the text."""
    for needle in needles:
        i = text.find(needle)
        if i >= 0:
            lo = max(0, i - size // 2)
            hi = min(len(text), i + len(needle) + size // 2)
            return (("…" if lo else "") + text[lo:i] + "⟦" + needle + "⟧" + text[i + len(needle):hi]
                    + ("…" if hi < len(text) else ""))
    return text[:size] + ("…" if len(text) > size else "")


def facets(con, q, top=10):
    register(con)
    joins, where, params, _ = _base(q)
    scope = f"SELECT t.id FROM turns t {joins} {where}"

    def group(sql):
        return [dict(r) for r in con.execute(sql, params).fetchall()]

    return {
        "estados": group(f"""SELECT i.state AS id, i.state AS nombre, COUNT(*) AS n
            FROM turns t JOIN documents d ON d.id = t.document_id JOIN institutions i ON i.id = d.institution_id
            WHERE t.id IN ({scope}) AND i.state IS NOT NULL GROUP BY 1 ORDER BY n DESC"""),
        "instituciones": group(f"""SELECT d.institution_id AS id, i.name AS nombre, COUNT(*) AS n
            FROM turns t JOIN documents d ON d.id = t.document_id JOIN institutions i ON i.id = d.institution_id
            WHERE t.id IN ({scope}) GROUP BY 1 ORDER BY n DESC"""),
        "partidos": group(f"""SELECT p.party AS id, p.party AS nombre, COUNT(*) AS n
            FROM turns t JOIN people p ON p.id = t.person_id
            WHERE t.id IN ({scope}) AND p.party IS NOT NULL GROUP BY 1 ORDER BY n DESC"""),
        "personas": group(f"""SELECT p.id, p.name AS nombre, p.party AS partido, COUNT(*) AS n
            FROM turns t JOIN people p ON p.id = t.person_id
            WHERE t.id IN ({scope}) GROUP BY 1 ORDER BY n DESC LIMIT {top}"""),
        "cargos": group(f"""SELECT t.role AS id, t.role AS nombre, COUNT(*) AS n FROM turns t
            WHERE t.id IN ({scope}) AND t.role IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT {top}"""),
        "leyes": group(f"""SELECT l.id, l.name AS nombre, COUNT(*) AS n FROM mentions m JOIN laws l ON l.id = m.law_id
            WHERE m.turn_id IN ({scope}) GROUP BY 1 ORDER BY n DESC LIMIT {top}"""),
        "medios": group(f"""SELECT t.outlet AS id, t.outlet AS nombre, COUNT(*) AS n FROM turns t
            WHERE t.id IN ({scope}) AND t.outlet IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT {top}"""),
        "meses": group(f"""SELECT substr(d.date, 1, 7) AS id, COUNT(*) AS n
            FROM turns t JOIN documents d ON d.id = t.document_id
            WHERE t.id IN ({scope}) GROUP BY 1 ORDER BY 1"""),
    }


def person(con, pid, recent=8):
    row = con.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if not row:
        return None
    roles = con.execute(
        """SELECT t.role, d.institution_id, MIN(d.date) AS desde, MAX(d.date) AS hasta, COUNT(*) AS n
           FROM turns t JOIN documents d ON d.id = t.document_id WHERE t.person_id = ?
           GROUP BY 1, 2 ORDER BY hasta DESC""", (pid,)).fetchall()
    laws = con.execute(
        """SELECT l.id, l.name AS nombre, COUNT(*) AS n FROM mentions m JOIN laws l ON l.id = m.law_id
           JOIN turns t ON t.id = m.turn_id WHERE t.person_id = ? GROUP BY 1 ORDER BY n DESC LIMIT 10""", (pid,)).fetchall()
    stats = con.execute(
        """SELECT COUNT(*) AS intervenciones, COUNT(DISTINCT t.document_id) AS documentos,
                  MIN(d.date) AS primera, MAX(d.date) AS ultima
           FROM turns t JOIN documents d ON d.id = t.document_id WHERE t.person_id = ?""", (pid,)).fetchone()
    timeline = con.execute(
        """SELECT substr(d.date, 1, 7) AS mes, COUNT(*) AS n FROM turns t JOIN documents d ON d.id = t.document_id
           WHERE t.person_id = ? GROUP BY 1 ORDER BY 1""", (pid,)).fetchall()
    latest = search(con, Query(personas=[pid], orden="fecha", limite=recent))["resultados"]
    memberships = [dict(r) for r in con.execute(
        """SELECT m.*, i.name AS institution FROM memberships m JOIN institutions i ON i.id = m.institution_id
           WHERE m.person_id = ? ORDER BY m.legislature DESC""", (pid,))]
    for m in memberships:
        m["committees"] = json.loads(m["committees"] or "[]")
    return {"persona": dict(row), "estadisticas": dict(stats), "cargos": [dict(r) for r in roles],
            "leyes": [dict(r) for r in laws], "linea_de_tiempo": [dict(r) for r in timeline], "recientes": latest,
            "padron": memberships, "votaciones": person_votes(con, pid)}


def person_votes(con, pid, recent=12):
    """How a member voted: totals, the latest votes, and the ones against their own group's majority."""
    totals = dict(con.execute("SELECT sense, COUNT(*) FROM vote_casts WHERE person_id = ? GROUP BY 1", (pid,)).fetchall())
    if not totals:
        return None
    rows = con.execute(
        f"""WITH majority AS (
                SELECT vote_id, party, sense, ROW_NUMBER() OVER (PARTITION BY vote_id, party ORDER BY COUNT(*) DESC) AS r
                FROM vote_casts WHERE sense IN ('A favor', 'En contra', 'Abstención') GROUP BY vote_id, party, sense)
            SELECT v.id, v.date, v.title, c.sense, c.party, m.sense AS bancada
            FROM vote_casts c JOIN votes v ON v.id = c.vote_id
            LEFT JOIN majority m ON m.vote_id = c.vote_id AND m.party = c.party AND m.r = 1
            WHERE c.person_id = ? ORDER BY v.date DESC, v.id DESC""", (pid,)).fetchall()
    rows = [dict(r) for r in rows]
    against = [r for r in rows if r["bancada"] and r["sense"] in ("A favor", "En contra", "Abstención")
               and r["sense"] != r["bancada"]]
    return {"totales": totals, "recientes": rows[:recent], "contra_bancada": against[:recent],
            "n_contra_bancada": len(against), "n": len(rows)}


def votes_search(con, text="", limit=20, offset=0):
    if text and fts_query(text):
        rows = con.execute(
            """SELECT v.* FROM votes_fts f JOIN votes v ON v.rowid = f.rowid WHERE votes_fts MATCH ?
               ORDER BY v.date DESC LIMIT ? OFFSET ?""", (fts_query(text), limit, offset)).fetchall()
        total = con.execute("SELECT COUNT(*) FROM votes_fts WHERE votes_fts MATCH ?", (fts_query(text),)).fetchone()[0]
    else:
        rows = con.execute("SELECT * FROM votes ORDER BY date DESC, rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        total = con.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
    return {"total": total, "votaciones": [dict(r) for r in rows]}


def vote(con, vid):
    row = con.execute("SELECT v.*, i.name AS institution FROM votes v JOIN institutions i ON i.id = v.institution_id "
                      "WHERE v.id = ?", (vid,)).fetchone()
    if not row:
        return None
    by_party = defaultdict(lambda: defaultdict(int))
    for party, sense, n in con.execute("SELECT party, sense, COUNT(*) FROM vote_casts WHERE vote_id = ? GROUP BY 1, 2", (vid,)):
        by_party[party][sense] = n
    casts = [dict(r) for r in con.execute(
        """SELECT c.sense, c.party, c.person_id, COALESCE(p.name, c.official_id) AS nombre FROM vote_casts c
           LEFT JOIN people p ON p.id = c.person_id WHERE c.vote_id = ? ORDER BY c.sense, p.name""", (vid,))]
    majority = {party: max(((s, n) for s, n in senses.items() if s in ("A favor", "En contra", "Abstención")),
                           key=lambda x: x[1], default=(None, 0))[0] for party, senses in by_party.items()}
    for c in casts:
        c["contra_bancada"] = c["sense"] in ("A favor", "En contra", "Abstención") and c["sense"] != majority.get(c["party"])
    return {"votacion": dict(row), "por_partido": {p: dict(v) for p, v in by_party.items()}, "votos": casts}


def law(con, lid, recent=8):
    row = con.execute("SELECT * FROM laws WHERE id = ?", (lid,)).fetchone()
    if not row:
        return None
    by_party = con.execute(
        """SELECT COALESCE(p.party, 'Sin partido registrado') AS nombre, COUNT(*) AS n FROM mentions m
           JOIN turns t ON t.id = m.turn_id LEFT JOIN people p ON p.id = t.person_id
           WHERE m.law_id = ? GROUP BY 1 ORDER BY n DESC""", (lid,)).fetchall()
    speakers = con.execute(
        """SELECT p.id, p.name AS nombre, p.party AS partido, COUNT(*) AS n FROM mentions m
           JOIN turns t ON t.id = m.turn_id JOIN people p ON p.id = t.person_id
           WHERE m.law_id = ? GROUP BY 1 ORDER BY n DESC LIMIT 10""", (lid,)).fetchall()
    timeline = con.execute(
        """SELECT substr(d.date, 1, 7) AS mes, COUNT(*) AS n FROM mentions m JOIN turns t ON t.id = m.turn_id
           JOIN documents d ON d.id = t.document_id WHERE m.law_id = ? GROUP BY 1 ORDER BY 1""", (lid,)).fetchall()
    stats = con.execute(
        """SELECT COUNT(*) AS menciones, COUNT(DISTINCT t.person_id) AS personas,
                  COUNT(DISTINCT t.document_id) AS documentos, MIN(d.date) AS primera, MAX(d.date) AS ultima
           FROM mentions m JOIN turns t ON t.id = m.turn_id JOIN documents d ON d.id = t.document_id
           WHERE m.law_id = ?""", (lid,)).fetchone()
    latest = search(con, Query(leyes=[lid], orden="fecha", limite=recent))["resultados"]
    return {"ley": dict(row), "estadisticas": dict(stats), "por_partido": [dict(r) for r in by_party],
            "por_institucion": [dict(r) for r in con.execute(
                """SELECT i.id, i.name AS nombre, COUNT(*) AS n FROM mentions m JOIN turns t ON t.id = m.turn_id
                   JOIN documents d ON d.id = t.document_id JOIN institutions i ON i.id = d.institution_id
                   WHERE m.law_id = ? GROUP BY 1 ORDER BY n DESC""", (lid,))],
            "personas": [dict(r) for r in speakers], "linea_de_tiempo": [dict(r) for r in timeline], "recientes": latest}


def document(con, doc_id):
    row = con.execute(
        "SELECT d.*, i.name AS institution FROM documents d JOIN institutions i ON i.id = d.institution_id WHERE d.id = ?",
        (doc_id,)).fetchone()
    if not row:
        return None
    turns = con.execute(
        """SELECT t.id, t.idx, t.speaker, t.role, t.person_id, t.outlet, t.text, p.name AS person, p.party
           FROM turns t LEFT JOIN people p ON p.id = t.person_id WHERE t.document_id = ? ORDER BY t.idx""",
        (doc_id,)).fetchall()
    return {"documento": dict(row), "intervenciones": attach_laws(con, [dict(r) for r in turns])}


def find_people(con, text, limit=10):
    """Autocomplete: every query token must appear in the folded name."""
    tokens = [t for t in fold(text).split() if t]
    if not tokens:
        return []
    register(con)
    clauses = " AND ".join("fold(p.name) LIKE ?" for _ in tokens)
    rows = con.execute(
        f"""SELECT p.id, p.name AS nombre, p.party AS partido, p.chamber AS institucion, COUNT(t.id) AS n
            FROM people p LEFT JOIN turns t ON t.person_id = p.id WHERE {clauses}
            GROUP BY p.id ORDER BY n DESC LIMIT ?""", [f"%{t}%" for t in tokens] + [limit]).fetchall()
    return [dict(r) for r in rows]


def find_laws(con, text, limit=10):
    tokens = [t for t in fold(text).split() if t and t not in STOPWORDS]
    register(con)
    clauses = " AND ".join("fold(l.name) LIKE ?" for _ in tokens) or "1"
    rows = con.execute(
        f"""SELECT l.id, l.name AS nombre, COUNT(m.turn_id) AS n FROM laws l LEFT JOIN mentions m ON m.law_id = l.id
            WHERE {clauses} GROUP BY l.id ORDER BY n DESC LIMIT ?""", [f"%{t}%" for t in tokens] + [limit]).fetchall()
    return [dict(r) for r in rows]


def options(con):
    return {
        "instituciones": [dict(r) for r in con.execute(
            """SELECT i.id, i.name AS nombre, i.level AS nivel, i.state AS estado, i.kind AS tipo,
                      COUNT(d.id) AS documentos, MIN(d.date) AS desde,
                      MAX(d.date) AS hasta FROM institutions i LEFT JOIN documents d ON d.institution_id = i.id GROUP BY i.id""")],
        "partidos": [r[0] for r in con.execute("SELECT DISTINCT party FROM people WHERE party IS NOT NULL ORDER BY 1")],
        "estados": [r[0] for r in con.execute(
            "SELECT DISTINCT i.state FROM institutions i JOIN documents d ON d.institution_id = i.id "
            "WHERE i.state IS NOT NULL ORDER BY 1")],
        "votaciones": con.execute("SELECT COUNT(*) FROM votes").fetchone()[0],
    }


def suggest(con, text, limit=5):
    """One autocomplete call for the search box: people and laws together."""
    return {"personas": find_people(con, text, limit), "leyes": find_laws(con, text, limit) if text.strip() else []}


_panorama = {}


def panorama(con, ttl=600):
    """Home page: what is new, which laws are being discussed, who speaks most. Cached for `ttl` seconds."""
    if _panorama.get("at", 0) > time.time() - ttl:
        return _panorama["data"]
    register(con)
    last = con.execute("SELECT MAX(date) FROM documents").fetchone()[0] or date.today().isoformat()
    end = date.fromisoformat(last)
    day = lambda n: (end - timedelta(days=n)).isoformat()

    recent = {}
    for (inst,) in con.execute("SELECT id FROM institutions"):
        docs = [dict(r) for r in con.execute(
            """SELECT d.id, d.date, d.title, d.kind, d.institution_id, i.name AS institution,
                      (SELECT COUNT(*) FROM turns t WHERE t.document_id = d.id) AS intervenciones
               FROM documents d JOIN institutions i ON i.id = d.institution_id
               WHERE d.institution_id = ? ORDER BY d.date DESC LIMIT 3""", (inst,))]
        for d in docs:
            d["oradores"] = [dict(r) for r in con.execute(
                """SELECT p.id, p.name AS nombre, p.party AS partido, COUNT(*) AS n FROM turns t
                   JOIN people p ON p.id = t.person_id WHERE t.document_id = ? GROUP BY 1 ORDER BY n DESC LIMIT 4""",
                (d["id"],))]
        recent[inst] = docs

    rows = con.execute(
        """SELECT l.id, l.name AS nombre,
                  SUM(d.date > ?) AS n, SUM(d.date <= ? AND d.date > ?) AS antes
           FROM mentions m JOIN laws l ON l.id = m.law_id JOIN turns t ON t.id = m.turn_id
           JOIN documents d ON d.id = t.document_id WHERE d.date > ?
           GROUP BY l.id HAVING n > 0 ORDER BY n DESC LIMIT 10""", (day(90), day(90), day(180), day(180))).fetchall()
    trending = []
    first_month = day(365)[:7]
    for r in rows:
        series = dict(con.execute(
            """SELECT substr(d.date, 1, 7), COUNT(*) FROM mentions m JOIN turns t ON t.id = m.turn_id
               JOIN documents d ON d.id = t.document_id WHERE m.law_id = ? AND substr(d.date, 1, 7) >= ?
               GROUP BY 1""", (r["id"], first_month)).fetchall())
        trending.append({**dict(r), "serie": series})

    voices = [dict(r) for r in con.execute(
        """SELECT p.id, p.name AS nombre, p.party AS partido, COUNT(*) AS n,
                  (SELECT t2.role FROM turns t2 WHERE t2.person_id = p.id AND t2.role IS NOT NULL
                   ORDER BY t2.id DESC LIMIT 1) AS cargo
           FROM turns t JOIN people p ON p.id = t.person_id JOIN documents d ON d.id = t.document_id
           WHERE d.date > ? GROUP BY p.id ORDER BY n DESC LIMIT 12""", (day(30),))]

    latest = [dict(r) for r in con.execute(
        """SELECT d.id, d.date, d.title, d.institution_id, i.name AS institution, i.level AS nivel, i.state AS estado,
                  (SELECT COUNT(*) FROM turns t WHERE t.document_id = d.id) AS intervenciones
           FROM documents d JOIN institutions i ON i.id = d.institution_id
           WHERE d.id IN (SELECT id FROM documents d2 WHERE d2.institution_id = d.institution_id ORDER BY date DESC LIMIT 2)
           ORDER BY d.date DESC LIMIT 12""")]
    for d in latest:
        d["oradores"] = [dict(r) for r in con.execute(
            """SELECT p.id, p.name AS nombre, p.party AS partido, COUNT(*) AS n FROM turns t
               JOIN people p ON p.id = t.person_id WHERE t.document_id = ? GROUP BY 1 ORDER BY n DESC LIMIT 3""", (d["id"],))]
    votes = [dict(r) for r in con.execute("SELECT * FROM votes ORDER BY date DESC, rowid DESC LIMIT 5")]
    data = {"hasta": last, "recientes": recent, "ultimos": latest, "votaciones": votes,
            "leyes_en_alza": trending, "voces": voices,
            "ventanas": {"leyes": [day(90), last], "voces": [day(30), last]}}
    _panorama.update(at=time.time(), data=data)
    return data
