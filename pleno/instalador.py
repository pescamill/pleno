"""First run on someone's computer: get the data, then keep it fresh every day.

Two ways to get the data, chosen in the browser:
- rápido: the ready-made database from Hugging Face (≈2 GB). Minutes, depending on the connection.
- fuentes: download and process each source from the official sites. Hours; Pleno can be used meanwhile.
Either way, the daily update afterwards reads only what is new from the official sources.
"""

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from pleno import db
from pleno.net import SSL_CONTEXT

DB_URL = os.environ.get("PLENO_DB_URL", "https://huggingface.co/datasets/pescamil/pleno-datos/resolve/main/pleno.db")
LOG = db.ROOT / "data" / "logs" / "instalacion.log"
# What the person can pick in «desde las fuentes oficiales», with an honest estimate of the time it takes.
FUENTES = [
    {"id": "mananeras", "nombre": "Conferencias matutinas (desde 2018)", "tiempo": "15–30 min", "pre": True},
    {"id": "diputados", "nombre": "Cámara de Diputados: versiones estenográficas", "tiempo": "20–40 min", "pre": True},
    {"id": "sitl", "nombre": "Cámara de Diputados: padrón y votaciones nominales", "tiempo": "30–45 min", "pre": True},
    {"id": "scjn", "nombre": "Suprema Corte", "tiempo": "10–20 min", "pre": True},
    {"id": "sesnsp", "nombre": "Cifras oficiales de delitos (SESNSP)", "tiempo": "2–5 min", "pre": True},
    {"id": "fgr", "nombre": "Fiscalía General de la República", "tiempo": "3–5 h", "pre": False},
    {"id": "estatales", "nombre": "Congresos y fiscalías estatales", "tiempo": "4–8 h", "pre": False},
]
_state = {"activo": False, "modo": None, "etapa": "", "progreso": None, "bytes": 0, "total": 0, "error": None,
          "terminado": False, "inicio": None}
_lock = threading.Lock()


def needed(con):
    return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def status():
    s = dict(_state)
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        s["bitacora"] = [line for line in lines if line.strip() and not line.startswith(" ")][-8:]
    return s


def _set(**kw):
    with _lock:
        _state.update(kw)


def start(mode, sources=None):
    if _state["activo"]:
        raise RuntimeError("Ya hay una instalación en curso.")
    _set(activo=True, modo=mode, etapa="Empezando…", progreso=0, bytes=0, total=0, error=None, terminado=False,
         inicio=time.time())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    target = _quick if mode == "rapido" else _from_sources
    threading.Thread(target=target, args=(sources,) if mode != "rapido" else (), daemon=True).start()


def _quick():
    """Download the ready-made database next to the current one, then switch to it."""
    name = f"pleno-{time.strftime('%Y%m%d-%H%M%S')}.db"
    dest = db.ROOT / "data" / name
    part = dest.with_suffix(".db.part")
    try:
        _set(etapa="Descargando la base lista (≈2 GB)…")
        req = urllib.request.Request(DB_URL, headers={"User-Agent": "Pleno-instalador"})
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp, part.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                _set(bytes=done, total=total, progreso=round(100 * done / total, 1) if total else None)
        os.replace(part, dest)
        _repair(dest)
        _switch(dest)
        _set(etapa="Listo: la base está cargada.", progreso=100, terminado=True, activo=False)
    except Exception as e:
        part.unlink(missing_ok=True)
        _set(error=f"{type(e).__name__}: {e}", etapa="La descarga falló.", activo=False)


def _repair(path):
    """Fixes found after the ready-made database was published, so a quick install gets them at once."""
    from pleno import ingest
    con = sqlite3.connect(path)
    try:
        ingest.repair_vote_parties(con)
        con.commit()
    finally:
        con.close()


def _switch(path):
    """Point Pleno at a new database file without restarting it."""
    old = Path(db.DB_FILE)
    db.POINTER.write_text(path.name, encoding="utf-8")
    db.DB_FILE = path
    db.GENERATION += 1
    from pleno import api, nlq
    nlq._people_index.cache_clear()
    api._panorama.clear()
    # The empty database it replaces is removed on a later start, once nothing holds it open.
    (db.ROOT / "data" / "borrar.txt").write_text(old.name, encoding="utf-8")


def cleanup():
    """At start-up: delete the database a previous install replaced (Windows cannot while it is open)."""
    note = db.ROOT / "data" / "borrar.txt"
    if note.exists():
        old = db.ROOT / "data" / note.read_text(encoding="utf-8").strip()
        if old != Path(db.DB_FILE):
            for suffix in ("", "-wal", "-shm"):
                Path(str(old) + suffix).unlink(missing_ok=True)
        note.unlink(missing_ok=True)


def _from_sources(sources):
    """Run the regular ingest for the chosen sources, in a separate process, logging to a file."""
    from pleno.sources.estatales import CONGRESOS
    from pleno import ingest
    names = []
    for s in sources or [f["id"] for f in FUENTES if f["pre"]]:
        if s == "estatales":
            names += [n for n in ingest.SOURCES if n in CONGRESOS or n in ingest.FISCALIAS]
        else:
            names.append(s)
    try:
        if "mananeras" in names:
            _set(etapa="Descargando las conferencias matutinas…")
            from pleno import actualizar
            with LOG.open("a", encoding="utf-8") as log:
                log.write(f"mananeras: {actualizar.pull_mananeras()}\n")
        _set(etapa=f"Procesando {len(names)} fuente(s) desde los sitios oficiales… (puedes usar Pleno mientras)")
        with LOG.open("a", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, "-u", "-m", "pleno", "ingerir", *names], cwd=db.ROOT,
                                    stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PLENO_DB": str(db.DB_FILE)})
            done = 0
            while proc.poll() is None:
                time.sleep(2)
                text = LOG.read_text(encoding="utf-8", errors="replace")
                done = sum(1 for n in names if re.search(rf"^{re.escape(n)}: (\d+ vistos|ERROR)", text, re.M))
                _set(progreso=round(100 * done / len(names), 1))
        if proc.returncode:
            raise RuntimeError(f"el proceso terminó con código {proc.returncode}")
        db.GENERATION += 1
        from pleno import api, nlq
        nlq._people_index.cache_clear()
        api._panorama.clear()
        _set(etapa="Listo: las fuentes están cargadas.", progreso=100, terminado=True, activo=False)
    except Exception as e:
        _set(error=f"{type(e).__name__}: {e}", etapa="La carga se detuvo.", activo=False)


def schedule_daily(hour=7, minute=0):
    """Run `pleno actualizar` every day: launchd on Mac, Task Scheduler on Windows, cron elsewhere."""
    if sys.platform == "darwin":
        from pleno import actualizar
        actualizar.programar(hour, minute)
        return f"Se actualizará cada día a las {hour:02d}:{minute:02d} (si la Mac está encendida)."
    if sys.platform.startswith("win"):
        cmd = f'"{sys.executable}" -m pleno actualizar'
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", "Pleno", "/ST", f"{hour:02d}:{minute:02d}",
                        "/TR", f'cmd /c cd /d "{db.ROOT}" && {cmd}'], check=True, capture_output=True)
        return f"Se actualizará cada día a las {hour:02d}:{minute:02d} (si la computadora está encendida)."
    line = f"{minute} {hour} * * * cd '{db.ROOT}' && '{sys.executable}' -m pleno actualizar\n"
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    if "pleno actualizar" not in current:
        subprocess.run(["crontab", "-"], input=current + line, text=True, check=True)
    return f"Se actualizará cada día a las {hour:02d}:{minute:02d}."
