"""SQLite schema: institutions → documents → turns, plus people and the laws they mention.

Everything a user can ask about is a column or a join here, so every answer can cite
the exact turn, document and source it came from.
"""

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = ROOT / "data" / "actual.txt"   # name of the database in use, written by the installer


def current_file():
    """The database in use. The installer downloads a new file and points to it instead of overwriting the
    open one (Windows cannot replace a file that is open)."""
    if POINTER.exists():
        candidate = ROOT / "data" / POINTER.read_text(encoding="utf-8").strip()
        if candidate.exists():
            return candidate
    return ROOT / "data" / "pleno.db"


DB_FILE = Path(os.environ["PLENO_DB"]) if os.environ.get("PLENO_DB") else current_file()
GENERATION = 0   # bumped when DB_FILE changes, so open connections reconnect

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT NOT NULL,          -- federal | estatal | municipal
    state TEXT,                   -- for estatal/municipal
    kind TEXT NOT NULL            -- ejecutivo | legislativo | judicial | municipal
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,          -- <source>:<native id>
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    kind TEXT NOT NULL,           -- conferencia | sesion | ...
    date TEXT,                    -- ISO yyyy-mm-dd
    title TEXT,
    legislature TEXT,
    source_url TEXT NOT NULL,
    sha1 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_date ON documents(date);
CREATE INDEX IF NOT EXISTS documents_inst ON documents(institution_id);

CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,          -- slug of the normalised name
    name TEXT NOT NULL,
    party TEXT,
    state TEXT,
    chamber TEXT,                 -- senado | ejecutivo | ...
    profile_url TEXT,
    source TEXT                   -- where the party/state came from
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    speaker TEXT NOT NULL,        -- as written in the source
    role TEXT,                    -- Presidenta, Senadora, Periodista, Secretario de …
    person_id TEXT REFERENCES people(id),
    outlet TEXT,                  -- news outlet, for press questions
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_doc ON turns(document_id);
CREATE INDEX IF NOT EXISTS turns_person ON turns(person_id);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    text, content='turns', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS laws (
    id TEXT PRIMARY KEY,          -- slug of the canonical name (+ state for state laws)
    name TEXT NOT NULL,
    jurisdiction TEXT,            -- «federal» or the state's name
    official_name TEXT,           -- as listed in the official catalog, when it matched
    official_url TEXT,            -- official text (PDF)
    last_reform TEXT
);

CREATE TABLE IF NOT EXISTS mentions (
    turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    law_id TEXT NOT NULL REFERENCES laws(id),
    PRIMARY KEY (turn_id, law_id)
);
CREATE INDEX IF NOT EXISTS mentions_law ON mentions(law_id);

-- Official rosters: who belongs to which body, for which party, from where. Beats anything inferred.
CREATE TABLE IF NOT EXISTS memberships (
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    legislature TEXT NOT NULL,
    party TEXT,
    state TEXT,
    district TEXT,                -- «Dtto. 1», «Circ. 5»
    principle TEXT,               -- Mayoría Relativa | Representación Proporcional
    seat TEXT,
    committees TEXT,              -- JSON list
    official_id TEXT,             -- the body's own id for this member
    source_url TEXT,
    PRIMARY KEY (person_id, institution_id, legislature)
);
CREATE INDEX IF NOT EXISTS memberships_official ON memberships(institution_id, official_id);

-- Roll-call votes and how each member voted.
CREATE TABLE IF NOT EXISTS votes (
    id TEXT PRIMARY KEY,          -- <institution>:<legislature>:<native id>
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    legislature TEXT,
    date TEXT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    a_favor INTEGER, en_contra INTEGER, abstencion INTEGER, ausente INTEGER, otros INTEGER
);
CREATE INDEX IF NOT EXISTS votes_date ON votes(date);
CREATE TABLE IF NOT EXISTS vote_casts (
    vote_id TEXT NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    person_id TEXT REFERENCES people(id),
    official_id TEXT NOT NULL,
    party TEXT,
    sense TEXT NOT NULL,          -- A favor | En contra | Abstención | Ausente | Solo asistencia | …
    PRIMARY KEY (vote_id, official_id)
);
CREATE INDEX IF NOT EXISTS vote_casts_person ON vote_casts(person_id);
CREATE VIRTUAL TABLE IF NOT EXISTS votes_fts USING fts5(
    title, content='votes', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);

-- Each ingestion run, so the updater can report what is new and when a source broke.
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT,
    seen INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0,
    error TEXT
);

-- Saved searches that become alerts (RSS) when the updater finds new matching turns.
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query TEXT NOT NULL,          -- JSON of a search Query
    created TEXT NOT NULL,
    last_turn_id INTEGER DEFAULT 0
);

-- Official crime statistics (SESNSP), one row per month and category. Replaced whole on every load,
-- because the SESNSP revises past months.
CREATE TABLE IF NOT EXISTS crime_stats (
    series TEXT NOT NULL,         -- delitos | victimas
    methodology TEXT NOT NULL,    -- 2015-2025 | 2026
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    state TEXT NOT NULL,
    bien TEXT, tipo TEXT, subtipo TEXT, modalidad TEXT, sexo TEXT,
    value INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS crime_stats_q ON crime_stats(series, subtipo, year, month);
"""


def connect(path=None):
    path = path or DB_FILE
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    migrate(con)
    return con


def migrate(con):
    """Columns added after a database was first built."""
    have = {r[1] for r in con.execute("PRAGMA table_info(laws)")}
    for col in ("jurisdiction", "official_name", "official_url", "last_reform"):
        if col not in have:
            con.execute(f"ALTER TABLE laws ADD COLUMN {col} TEXT")
