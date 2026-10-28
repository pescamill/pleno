"""Load source documents into the database: idempotent, incremental, with people, laws, rosters and votes
resolved. Every run is logged in `runs`, so the updater can say what is new and which source broke.
"""

import re
import time
import traceback
from collections import Counter, defaultdict

from pleno import db
from pleno.normalize import clean_person_name, edit_distance, find_laws, fold, name_tokens, slug
from pleno.sources import catalogos, diputados, fgr, mananeras, scjn, sesnsp, sitl
from pleno.sources.estatales import CONGRESOS
from pleno.sources.fiscalias import FISCALIAS

SOURCES = {"mananeras": mananeras, "diputados": diputados, "scjn": scjn, "fgr": fgr, **CONGRESOS, **FISCALIAS}
EXTRA = {"sitl", "sesnsp"}  # roster + roll-call votes, crime statistics: not transcripts
FEDERAL = {"presidencia", "diputados", "scjn", "fgr"}
AUDIT_FILE = db.ROOT / "data" / "fusiones-errata.tsv"


def upsert_institutions(con, source):
    for inst in source.INSTITUTIONS:
        con.execute(
            "INSERT INTO institutions(id, name, level, state, kind) VALUES (:id, :name, :level, :state, :kind) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, level=excluded.level, state=excluded.state, kind=excluded.kind",
            inst,
        )


def person_for(con, name, chamber):
    name = clean_person_name(name)
    if not name:
        return None
    pid = slug(name)
    con.execute("INSERT OR IGNORE INTO people(id, name, chamber) VALUES (?, ?, ?)", (pid, name, chamber))
    return pid


# ---------- laws ----------

class LawResolver:
    """Detected law name → law id, standardized against the official federal catalog.

    A name in the catalog is the federal law (with its official text). In a state congress, a name that
    is not in the catalog and does not say Federal/General/Nacional is that state's own law, so «Ley de
    Ingresos» in Oaxaca never merges with the federal one.
    """

    def __init__(self, catalog=None):
        self.catalog = {c["key"]: c for c in (catalog or [])}
        self._near = {}

    def official(self, key):
        """Catalog entry for a key, tolerating OCR typos («ley de anparo») of one or two letters."""
        if key in self.catalog:
            return self.catalog[key]
        if key not in self._near:
            limit = 1 if len(key) < 20 else 2
            self._near[key] = next((c for k, c in self.catalog.items()
                                    if k[:4] == key[:4] and edit_distance(k, key, limit) <= limit), None)
        return self._near[key]

    def ids(self, con, text, institution):
        level, state = institution
        out = []
        for name in find_laws(text, federal=level == "federal"):
            official = self.official(catalogos.law_key(name))
            key = official["key"] if official else catalogos.law_key(name)
            named = named_state(name)
            if official:
                lid, jurisdiction = slug(key), "federal"
            elif STATE_CONSTITUTION_RE.match(name) and (named or state):
                lid, jurisdiction = slug(name), named or state      # a state's constitution is never federal
            elif named:                                            # «…General del Estado de Guanajuato» is Guanajuato's
                lid, jurisdiction = slug(f"{name} {named}"), named
            elif level == "federal" or re_federal(name):
                lid, jurisdiction = slug(key), "federal"
            else:
                lid, jurisdiction = slug(f"{name} {state}"), state
            con.execute(
                "INSERT INTO laws(id, name, jurisdiction, official_name, official_url, last_reform) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET official_name = COALESCE(excluded.official_name, laws.official_name), "
                "official_url = COALESCE(excluded.official_url, laws.official_url), "
                "last_reform = COALESCE(excluded.last_reform, laws.last_reform)",
                (lid, name, jurisdiction, official and official["name"], official and official["url"],
                 official and official["last_reform"]))
            out.append(lid)
        return out


def re_federal(name):
    f = fold(name)
    return any(w in f for w in (" federal", " general ", " nacional", "de la federacion", "codigo nacional"))


STATE_CONSTITUTION_RE = re.compile(r"Constitución Política (?:del Estado|de la Ciudad de México|de la )")
STATE_NAMES = sorted(["Aguascalientes", "Baja California Sur", "Baja California", "Campeche", "Chiapas", "Chihuahua",
                      "Coahuila", "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "Michoacán",
                      "Morelos", "Nayarit", "Nuevo León", "Oaxaca", "Puebla", "Querétaro", "Quintana Roo",
                      "San Luis Potosí", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatán",
                      "Zacatecas"], key=len, reverse=True)


def named_state(name):
    """The state a law's own name places it in («…del Estado de Guanajuato», «…de la Ciudad de México», «…del
    Distrito Federal»), whatever «General» or «Federal» it also says; None when it names none."""
    f = fold(name)
    if "ciudad de mexico" in f or "distrito federal" in f:
        return "Ciudad de México"
    m = re.search(r"\bestado (?:libre y soberano )?de (.+)", f)
    if not m:
        return None
    rest = m.group(1)
    if rest.startswith("mexico"):
        return "Estado de México"
    return next((s for s in STATE_NAMES if rest.startswith(fold(s))), None)


def load_document(con, doc, chamber, laws=None, institution=("federal", None)):
    """Insert or replace one document. Returns False when it was already loaded unchanged."""
    laws = laws or LawResolver()
    sha = doc.sha1()
    row = con.execute("SELECT sha1 FROM documents WHERE id = ?", (doc.id,)).fetchone()
    if row and row["sha1"] == sha:
        return False
    if row:
        con.execute("DELETE FROM documents WHERE id = ?", (doc.id,))
    con.execute(
        "INSERT INTO documents(id, institution_id, kind, date, title, legislature, source_url, sha1) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc.id, doc.institution_id, doc.kind, doc.date, doc.title, doc.legislature, doc.source_url, sha),
    )
    for idx, turn in enumerate(doc.turns):
        pid = person_for(con, turn.name, chamber)
        cur = con.execute(
            "INSERT INTO turns(document_id, idx, speaker, role, person_id, outlet, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc.id, idx, turn.speaker, turn.role, pid, turn.outlet, turn.text),
        )
        for lid in laws.ids(con, turn.text, institution):
            con.execute("INSERT OR IGNORE INTO mentions(turn_id, law_id) VALUES (?, ?)", (cur.lastrowid, lid))
    return True


# ---------- people: resolve variants, never across unrelated bodies ----------

def fold_person(con, src, dst):
    """Move everything that points at `src` to `dst` and delete `src`."""
    con.execute("UPDATE turns SET person_id = ? WHERE person_id = ?", (dst, src))
    con.execute("UPDATE vote_casts SET person_id = ? WHERE person_id = ?", (dst, src))
    con.execute("UPDATE OR IGNORE memberships SET person_id = ? WHERE person_id = ?", (dst, src))
    con.execute("DELETE FROM people WHERE id = ?", (src,))


def bodies(con):
    """person → institutions where they speak or hold a seat."""
    out = defaultdict(set)
    for pid, inst in con.execute(
            """SELECT DISTINCT t.person_id, d.institution_id FROM turns t JOIN documents d ON d.id = t.document_id
               WHERE t.person_id IS NOT NULL
               UNION SELECT person_id, institution_id FROM memberships"""):
        out[pid].add(inst)
    return out


def compatible(a, b, where):
    """Two name variants may be one person only if they share a body, or both appear in federal ones.
    «Juan Pérez» in Oaxaca's congress is never folded into «Juan Pérez López» in Tabasco's."""
    wa, wb = where.get(a, set()), where.get(b, set())
    return bool(wa & wb) or bool(wa & FEDERAL and wb & FEDERAL) or not wa or not wb


def turn_counts(con):
    return dict(con.execute("SELECT person_id, COUNT(*) FROM turns WHERE person_id IS NOT NULL GROUP BY 1").fetchall())


class NameIndex:
    """Find people whose full name contains every token of a shorter form, without an n² scan."""

    def __init__(self, rows):
        self.rows = {r["id"]: r["name"] for r in rows}
        self.tokens = {pid: set(name_tokens(name)) for pid, name in self.rows.items()}
        self.postings = defaultdict(set)
        for pid, toks in self.tokens.items():
            for tok in toks:
                self.postings[tok].add(pid)

    def containing(self, name, exclude=None):
        toks = set(name_tokens(name))
        if len(toks) < 2:
            return []
        ids = set.intersection(*(self.postings.get(t, set()) for t in toks))
        ids.discard(exclude)
        ids &= self.rows.keys()  # people merged away earlier in this pass
        return sorted(ids, key=lambda pid: len(self.rows[pid]), reverse=True)


def merge_reordered(con):
    """Fold the same words in another order («Alonso Que Erubiel Lorenzo») into the most-used ordering."""
    turns, where = turn_counts(con), bodies(con)
    groups = defaultdict(list)
    for pid, name in con.execute("SELECT id, name FROM people").fetchall():
        toks = frozenset(name_tokens(name))
        if len(toks) >= 2:
            groups[toks].append(pid)
    merged = 0
    for ids in groups.values():
        if len(ids) < 2:
            continue
        keep = max(ids, key=lambda i: (turns.get(i, 0), i))
        for pid in ids:
            if pid != keep and compatible(pid, keep, where):
                fold_person(con, pid, keep)
                merged += 1
    return merged


def merge_short_names(con, ratio=10):
    """Fold short forms into the most-used full form («Kenia López» → «Kenia López Rabadán»).

    The target is the variant with the most turns, never just the longest. When the short form
    dominates instead (3+ name tokens and `ratio`× the turns), it absorbs the rare fuller variants:
    «Omar Hamid García Harfuch» (1 turn) → «Omar García Harfuch» (585).
    """
    index = NameIndex(con.execute("SELECT id, name FROM people").fetchall())
    turns, where = turn_counts(con), bodies(con)
    merged = 0

    def fold_into(src, dst):
        nonlocal merged
        fold_person(con, src, dst)
        turns[dst] = turns.get(dst, 0) + turns.pop(src, 0)
        where[dst] |= where.pop(src, set())
        del index.rows[src]
        merged += 1

    for pid, name in sorted(index.rows.items(), key=lambda kv: len(kv[1])):
        if pid not in index.rows:
            continue
        size = len(index.tokens[pid])
        longer = [c for c in index.containing(name, exclude=pid)
                  if size < len(index.tokens[c]) <= size + 3 and compatible(pid, c, where)]
        if not longer:
            continue
        target = max(longer, key=lambda c: turns.get(c, 0))
        if turns.get(target, 0) >= turns.get(pid, 0):
            fold_into(pid, target)
        elif size >= 3:
            for c in longer:
                if c in index.rows and turns.get(pid, 0) >= ratio * max(1, turns.get(c, 0)):
                    fold_into(c, pid)
    return merged


def merge_typos(con, max_turns=5, ratio=20):
    """Fold rare misspellings («Claudia Sheibaum Pardo») into a much more frequent name one typo away."""
    index = NameIndex(con.execute("SELECT id, name FROM people").fetchall())
    turns, where = turn_counts(con), bodies(con)
    merged, audit = 0, ["variante\tse_unió_a\tintervenciones_variante\tintervenciones_destino"]
    for pid, toks in list(index.tokens.items()):
        if turns.get(pid, 0) > max_turns or pid not in index.rows:
            continue
        candidates = set()
        for tok in toks:
            candidates |= index.postings.get(tok, set())
        for other in candidates - {pid}:
            if other not in index.rows or turns.get(other, 0) < ratio * max(1, turns.get(pid, 0)):
                continue
            a, b = sorted(toks), sorted(index.tokens[other])
            if len(a) != len(b) or not compatible(pid, other, where):
                continue
            diff = set(a) ^ set(b)
            if len(diff) == 2 and edit_distance(*sorted(diff)) <= 2:
                audit.append(f"{index.rows[pid]}\t{index.rows[other]}\t{turns.get(pid, 0)}\t{turns.get(other, 0)}")
                fold_person(con, pid, other)
                del index.rows[pid]
                merged += 1
                break
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_FILE.write_text("\n".join(audit) + "\n", encoding="utf-8")
    return merged


# ---------- parties: official roster first, then what the session itself says ----------

def deputy_for(index, in_body, name):
    """The person a session means by «la diputada <name>»: someone who speaks in that body, whose name
    contains the stated one, or is a 3+ token short form of it (after «… Sánchez Cordero Dávila» was merged)."""
    toks = set(name_tokens(name))
    found = index.containing(name)
    if not found and len(toks) >= 3:
        found = [pid for pid in set().union(*(index.postings.get(t, set()) for t in toks))
                 if pid in index.rows and len(index.tokens[pid]) >= 3 and index.tokens[pid] <= toks]
    found = [pid for pid in found if in_body.get(pid)]
    if not found:
        return None
    return max(found, key=lambda pid: (index.tokens[pid] == toks, in_body[pid]))


def assign_parties(con):
    """Party = the official roster when there is one; otherwise what the transcripts of the person's own
    legislature say most often («…del Grupo Parlamentario de Morena», «…de la fracción parlamentaria del PRD»)."""
    official = apply_memberships(con)
    index = NameIndex(con.execute("SELECT id, name FROM people").fetchall())
    votes = defaultdict(Counter)
    for (inst,) in con.execute("SELECT id FROM institutions WHERE kind = 'legislativo'").fetchall():
        in_body = dict(con.execute(
            """SELECT t.person_id, COUNT(*) FROM turns t JOIN documents d ON d.id = t.document_id
               WHERE d.institution_id = ? AND t.person_id IS NOT NULL GROUP BY 1""", (inst,)).fetchall())
        for (text,) in con.execute(
                "SELECT t.text FROM turns t JOIN documents d ON d.id = t.document_id WHERE d.institution_id = ?", (inst,)):
            for name, party in diputados.party_mentions(text):
                pid = deputy_for(index, in_body, name)
                if pid and pid not in official:
                    votes[pid][party] += 1
    for pid, counter in votes.items():
        party, _ = counter.most_common(1)[0]
        con.execute("UPDATE people SET party = ?, source = 'mencionado en sesión' WHERE id = ?", (party, pid))
    return len(official) + len(votes)


def apply_memberships(con):
    """Copy the latest official membership (party, state) onto each person."""
    rows = con.execute(
        """SELECT m.person_id, m.party, m.state, m.institution_id FROM memberships m
           ORDER BY m.legislature""").fetchall()
    done = set()
    for pid, party, state, inst in rows:
        con.execute("UPDATE people SET party = ?, state = COALESCE(?, state), chamber = ?, "
                    "source = 'padrón oficial' WHERE id = ?", (party, state, inst, pid))
        done.add(pid)
    return done


# ---------- official roster and roll-call votes ----------

def load_roster(con, rows, institution="diputados", legislature=sitl.LEGISLATURE, create=True):
    """Match each official member to the person already speaking in that body (any name order), or add them
    (only when the roster gives names in natural order, as SITL does)."""
    index = NameIndex(con.execute("SELECT id, name FROM people").fetchall())
    in_body = dict(con.execute(
        """SELECT t.person_id, COUNT(*) FROM turns t JOIN documents d ON d.id = t.document_id
           WHERE d.institution_id = ? AND t.person_id IS NOT NULL GROUP BY 1""", (institution,)).fetchall())
    for r in rows:
        pid = deputy_for(index, in_body, r["name"]) or (person_for(con, r["name"], institution) if create else None)
        if not pid:
            continue
        con.execute(
            """INSERT INTO memberships(person_id, institution_id, legislature, party, state, district, principle, seat,
                                       committees, official_id, source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(person_id, institution_id, legislature) DO UPDATE SET party=excluded.party,
                 state=excluded.state, district=excluded.district, principle=excluded.principle, seat=excluded.seat,
                 committees=excluded.committees, official_id=excluded.official_id, source_url=excluded.source_url""",
            (pid, institution, legislature, r["party"], r["state"], r["district"], r["principle"], r["seat"],
             r["committees"], r["official_id"], r["source_url"]))
    return len(rows)


def load_crime_stats(con, rows):
    """Replace the whole statistics table: the SESNSP revises past months in every release."""
    con.execute("DELETE FROM crime_stats")
    n = 0
    for chunk in iter(lambda: [r for _, r in zip(range(5000), rows)], []):
        con.executemany("INSERT INTO crime_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", chunk)
        n += len(chunk)
    con.commit()
    return n


def repair_vote_parties(con):
    """Older databases stored the site's numeric party id when it was not in the list; name it."""
    n = 0
    for pid, party in sitl.SITE_PARTIES.items():
        n += con.execute("UPDATE vote_casts SET party = ? WHERE party = ?", (party, str(pid))).rowcount
    return n


def load_votes(con, votes, institution="diputados", legislature=sitl.LEGISLATURE):
    members = dict(con.execute("SELECT official_id, person_id FROM memberships WHERE institution_id = ? AND legislature = ?",
                               (institution, legislature)).fetchall())
    seen = new = 0
    for v in votes:
        seen += 1
        exists = con.execute("SELECT 1 FROM votes WHERE id = ?", (v["id"],)).fetchone()
        con.execute(
            """INSERT OR REPLACE INTO votes(id, institution_id, legislature, date, title, source_url, a_favor, en_contra,
                                            abstencion, ausente, otros) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (v["id"], institution, legislature, v["date"], v["title"], v["source_url"], v["A favor"], v["En contra"],
             v["Abstención"], v["Ausente"], v["otros"]))
        con.execute("DELETE FROM vote_casts WHERE vote_id = ?", (v["id"],))
        con.executemany(
            "INSERT OR IGNORE INTO vote_casts(vote_id, person_id, official_id, party, sense) VALUES (?, ?, ?, ?, ?)",
            [(v["id"], members.get(oid), oid, party, sense) for oid, _, party, sense in v["casts"]])
        # A party id the site never labelled: the deputy's party in the official roster is the best record left.
        con.execute("""UPDATE vote_casts SET party = (SELECT m.party FROM memberships m WHERE m.institution_id = ?
                         AND m.legislature = ? AND m.official_id = vote_casts.official_id)
                       WHERE vote_id = ? AND (party IS NULL OR party GLOB '[0-9]*')""", (institution, legislature, v["id"]))
        new += not exists
        if seen % 50 == 0:
            con.commit()
            print(f"  votaciones: {seen} ({new} nuevas)")
    con.execute("INSERT INTO votes_fts(votes_fts) VALUES ('rebuild')")
    return seen, new


# ---------- runs ----------

def _log_start(con, source):
    cur = con.execute("INSERT INTO runs(source, started) VALUES (?, ?)", (source, time.strftime("%Y-%m-%dT%H:%M:%S")))
    con.commit()
    return cur.lastrowid


def _log_end(con, run_id, seen, new, error=None):
    con.execute("UPDATE runs SET finished = ?, seen = ?, new = ?, error = ? WHERE id = ?",
                (time.strftime("%Y-%m-%dT%H:%M:%S"), seen, new, error, run_id))
    con.commit()


def relink_laws(con, catalog):
    """Recompute every law mention from the stored turns (after improving law detection), without
    downloading anything again."""
    laws = LawResolver(catalog)
    con.execute("DELETE FROM mentions")
    con.execute("DELETE FROM laws")
    rows = con.execute("SELECT t.id, t.text, i.level, i.state FROM turns t JOIN documents d ON d.id = t.document_id "
                       "JOIN institutions i ON i.id = d.institution_id").fetchall()
    for tid, text, level, state in rows:
        for lid in laws.ids(con, text, (level, state)):
            con.execute("INSERT OR IGNORE INTO mentions(turn_id, law_id) VALUES (?, ?)", (tid, lid))
    con.commit()
    return con.execute("SELECT COUNT(*) FROM laws").fetchone()[0]


def resume_dates(con, margin_days=14):
    """Per source, the date to resume from: its newest document minus a margin (late corrections). A source
    with nothing loaded gets no date, so it starts from its own default."""
    import datetime as dt
    out = {}
    for name, source in SOURCES.items():
        last = con.execute("SELECT MAX(date) FROM documents WHERE institution_id = ?",
                           (source.INSTITUTIONS[0]["id"],)).fetchone()[0]
        if last:
            out[name] = (dt.date.fromisoformat(last) - dt.timedelta(days=margin_days)).isoformat()
    last = con.execute("SELECT MAX(date) FROM votes").fetchone()[0]
    if last:
        out["sitl"] = (dt.date.fromisoformat(last) - dt.timedelta(days=margin_days)).isoformat()
    return out


def run(names=None, since=None, limit=None, con=None):
    """Ingest sources (all by default). One failing source is logged and skipped, never fatal.
    `since` is one date for all sources or a {source: date} map."""
    con = con or db.connect()
    names = names or [*SOURCES, *EXTRA]
    try:
        catalog = catalogos.federal_laws()
    except Exception as e:  # offline: laws still load, just without the official link
        print(f"catálogo de leyes no disponible ({type(e).__name__})")
        catalog = []
    laws = LawResolver(catalog)
    summary = {}
    for name in names:
        run_id = _log_start(con, name)
        started, loaded, seen = time.time(), 0, 0
        src_since = since.get(name) if isinstance(since, dict) else since
        try:
            if name == "sesnsp":
                seen = loaded = load_crime_stats(con, sesnsp.records())
            elif name == "sitl":
                upsert_institutions(con, diputados)
                load_roster(con, sitl.roster())
                seen, loaded = load_votes(con, sitl.votes(since=src_since))
                repair_vote_parties(con)
            else:
                source = SOURCES[name]
                upsert_institutions(con, source)
                inst = source.INSTITUTIONS[0]
                chamber = inst["id"]
                for doc in source.documents(since=src_since) if src_since else source.documents():
                    seen += 1
                    loaded += load_document(con, doc, chamber, laws, (inst["level"], inst["state"]))
                    if seen % 100 == 0:
                        con.commit()
                        print(f"  {name}: {seen} documentos ({loaded} nuevos)")
                    if limit and seen >= limit:
                        break
                if getattr(source, "roster", None):
                    con.commit()
                    load_roster(con, source.roster(), institution=chamber, legislature=source.legislature, create=False)
            con.commit()
            _log_end(con, run_id, seen, loaded)
            print(f"{name}: {seen} vistos, {loaded} nuevos o cambiados, {time.time() - started:.0f}s")
        except Exception as e:
            con.rollback()
            _log_end(con, run_id, seen, loaded, f"{type(e).__name__}: {e}")
            print(f"{name}: ERROR {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
        summary[name] = loaded
    print(f"nombres en otro orden unificados: {merge_reordered(con)}")
    print(f"personas unificadas: {merge_short_names(con)}")
    print(f"variantes con errata unificadas: {merge_typos(con)}")
    orphans = con.execute(
        """DELETE FROM people WHERE id NOT IN (SELECT DISTINCT person_id FROM turns WHERE person_id IS NOT NULL)
           AND id NOT IN (SELECT person_id FROM memberships)""").rowcount
    print(f"personas sin intervenciones eliminadas: {orphans}")
    print(f"personas con partido: {assign_parties(con)}")
    con.commit()
    stats(con)
    return summary


def stats(con):
    q = lambda sql: con.execute(sql).fetchone()[0]
    print(f"documentos {q('SELECT COUNT(*) FROM documents')} · intervenciones {q('SELECT COUNT(*) FROM turns')} · "
          f"personas {q('SELECT COUNT(*) FROM people')} · leyes {q('SELECT COUNT(*) FROM laws')} · "
          f"menciones {q('SELECT COUNT(*) FROM mentions')} · votaciones {q('SELECT COUNT(*) FROM votes')}")
    for inst, n, last in con.execute(
            "SELECT institution_id, COUNT(*), MAX(date) FROM documents GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {inst:<20} {n:>5} documentos · último {last}")
