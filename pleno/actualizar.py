"""Daily update and alerts.

`pleno actualizar` pulls the mañaneras dataset, re-reads every source (caches make it incremental: only
new index entries and new PDFs are downloaded), re-resolves people and parties, and then checks every
saved search for new matching turns. Matches go to an RSS feed per alert and to a dated digest.

`pleno programar` installs a macOS LaunchAgent that runs it every morning.
"""

import json
import os
import plistlib
import secrets
import subprocess
import sys
import time
from datetime import date, timedelta
from email.utils import formatdate
from pathlib import Path
from xml.sax.saxutils import escape

from pleno import db, ingest, search
from pleno.normalize import slug
from pleno.search import Query
from pleno.sources import mananeras

ALERTS_DIR = db.ROOT / "data" / "alertas"
LOG_FILE = db.ROOT / "data" / "actualizaciones.log"
PUBLIC_URL = os.environ.get("PLENO_URL", "http://127.0.0.1:8780")
AGENT = "mx.pleno.actualizar"
AGENT_FILE = Path.home() / "Library" / "LaunchAgents" / f"{AGENT}.plist"


# ---------- alerts ----------

def create_alert(con, name, query):
    """Save a search. Only turns loaded after this moment count as new."""
    q = Query.from_dict(query).to_dict()
    for k in ("pagina", "limite", "despues_de"):
        q.pop(k, None)
    aid = f"{slug(name)[:40] or 'alerta'}-{secrets.token_hex(3)}"
    last = con.execute("SELECT COALESCE(MAX(id), 0) FROM turns").fetchone()[0]
    con.execute("INSERT INTO alerts(id, name, query, created, last_turn_id) VALUES (?, ?, ?, ?, ?)",
                (aid, name.strip()[:120], json.dumps(q, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S"), last))
    con.commit()
    return aid


def list_alerts(con):
    out = []
    for r in con.execute("SELECT * FROM alerts ORDER BY created DESC").fetchall():
        a = dict(r)
        a["query"] = json.loads(a["query"])
        a["nuevas"] = search.search(con, _alert_query(a, since_last=True, limit=1))["total"]
        out.append(a)
    return out


def delete_alert(con, aid):
    n = con.execute("DELETE FROM alerts WHERE id = ?", (aid,)).rowcount
    con.commit()
    return n


def _alert_query(alert, since_last=False, limit=50):
    q = Query.from_dict({**alert["query"], "orden": "fecha", "limite": limit, "pagina": 1})
    if since_last:
        q.despues_de = alert["last_turn_id"]
        # A source fix reloads old documents with new ids; only recent sessions count as news.
        recent = (date.today() - timedelta(days=45)).isoformat()
        q.desde = max(q.desde or "", recent)
    return q


def matches(con, alert, since_last=False, limit=50):
    return search.search(con, _alert_query(alert, since_last, limit), max_limit=200)["resultados"]


def rss(con, alert):
    """RSS 2.0 feed: newest matching turns first; each item links to the turn in its transcript."""
    items = []
    for r in matches(con, alert, limit=50):
        who = r["person"] or r["speaker"]
        link = f"{PUBLIC_URL}/#/documento/{_q(r['document_id'])}?t={r['id']}"
        text = r["snippet"].replace("⟦", "").replace("⟧", "")
        y, m, d = (int(x) for x in r["date"].split("-"))
        items.append(f"""<item><title>{escape(who)}{escape(' · ' + r['role']) if r['role'] else ''} · {escape(r['institution'])}</title>
<link>{escape(link)}</link><guid isPermaLink="false">pleno-turno-{r['id']}</guid>
<pubDate>{formatdate(time.mktime((y, m, d, 12, 0, 0, 0, 0, -1)), usegmt=True)}</pubDate>
<description>{escape(text[:600])}</description><source url="{escape(r['source_url'])}">Fuente oficial</source></item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Pleno · {escape(alert['name'])}</title>
<link>{escape(PUBLIC_URL)}</link><description>Nuevas intervenciones que coinciden con «{escape(alert['name'])}».</description>
<language>es-mx</language>{''.join(items)}</channel></rss>"""


def _q(text):
    from urllib.parse import quote
    return quote(text, safe="")


# ---------- update ----------

def pull_mananeras():
    """The dataset is a git clone of the Hugging Face repo: fast-forward it."""
    corpus = Path(mananeras.CORPUS_DIR)
    root = next((p for p in [corpus, *corpus.parents] if (p / ".git").exists()), None)
    if not root:
        return "sin repositorio git; se usa la copia local"
    proc = subprocess.run(["git", "-C", str(root), "pull", "--ff-only", "--quiet"], capture_output=True, text=True,
                          timeout=900)
    return "actualizado" if proc.returncode == 0 else f"git pull falló: {proc.stderr.strip()[:200]}"


def actualizar(con=None, sources=None, notify=True):
    started = time.time()
    con = con or db.connect()
    lines = [f"# Actualización {time.strftime('%Y-%m-%d %H:%M')}", ""]
    status = pull_mananeras()
    lines.append(f"- Mañaneras (dataset): {status}")
    summary = ingest.run(sources, con=con)
    errors = {r["source"]: r["error"] for r in con.execute(
        "SELECT source, error FROM runs WHERE started >= ? AND error IS NOT NULL",
        (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),))}
    for name, new in summary.items():
        lines.append(f"- {name}: {new} nuevos o cambiados" + (f" · ERROR {errors[name]}" if name in errors else ""))
    lines += ["", "## Alertas", ""]
    total_hits = 0
    newest = con.execute("SELECT COALESCE(MAX(id), 0) FROM turns").fetchone()[0]
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    for row in con.execute("SELECT * FROM alerts").fetchall():
        alert = dict(row)
        alert["query"] = json.loads(alert["query"])
        hits = matches(con, alert, since_last=True, limit=200)
        total_hits += len(hits)
        lines.append(f"### {alert['name']} — {len(hits)} nuevas")
        for r in hits[:10]:
            lines.append(f"- {r['date']} · {r['person'] or r['speaker']} ({r['institution']}): "
                         f"«{r['snippet'][:180].replace('⟦', '').replace('⟧', '')}…» "
                         f"{PUBLIC_URL}/#/documento/{_q(r['document_id'])}?t={r['id']}")
        (ALERTS_DIR / f"{alert['id']}.xml").write_text(rss(con, alert), encoding="utf-8")
        con.execute("UPDATE alerts SET last_turn_id = ? WHERE id = ?", (newest, alert["id"]))
    con.commit()
    try:   # quality check after every update; a regression shows up in the digest
        from pleno import evaluar
        result, _ = evaluar.run(con)
        lines += ["", "## Calidad", ""] + [f"- REGRESIÓN {r['metrica']}: {r['antes']} → {r['ahora']}"
                                          for r in result["regresiones"]] + (["- Sin regresiones."] if not result["regresiones"] else [])
    except Exception as e:  # never block the update on the evaluation
        lines += ["", f"Evaluación no disponible: {type(e).__name__}: {e}"]
    lines.append(f"\nDuración: {time.time() - started:.0f} s")
    digest = ALERTS_DIR / f"resumen-{date.today().isoformat()}.md"
    digest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(" | ".join(lines[2:2 + len(summary) + 1]) + f" | alertas: {total_hits}\n")
    if notify and sys.platform == "darwin" and (total_hits or errors):
        msg = f"{total_hits} coincidencias nuevas en tus alertas" + (f"; {len(errors)} fuentes con error" if errors else "")
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Pleno"'], capture_output=True)
    print("\n".join(lines))
    return digest


# ---------- schedule (macOS) ----------

def programar(hour=7, minute=0, remove=False):
    """Install (or remove) a LaunchAgent that runs `pleno actualizar` daily. It runs only while the Mac is
    awake; if it was asleep at that hour, launchd runs it on wake."""
    uid = os.getuid()
    if AGENT_FILE.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(AGENT_FILE)], capture_output=True)
    if remove:
        AGENT_FILE.unlink(missing_ok=True)
        return None
    log = db.ROOT / "data" / "actualizar.out.log"
    plist = {
        "Label": AGENT,
        "ProgramArguments": ["/usr/bin/caffeinate", "-i", sys.executable, "-m", "pleno", "actualizar"],
        "WorkingDirectory": str(db.ROOT),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    }
    AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_FILE.write_bytes(plistlib.dumps(plist))
    proc = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(AGENT_FILE)], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return AGENT_FILE
