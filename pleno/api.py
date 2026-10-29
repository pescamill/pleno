"""HTTP API (v1) + web UI. Free tier by IP; API keys with per-plan limits for paid use later."""

import csv
import io
import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi import Query as Query_
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pleno import answer as rag
from pleno import actualizar as updater
from pleno import db, fuentes, nlq, search
from pleno.search import Query

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
KEYS_FILE = ROOT / "data" / "keys.json"   # {"<key>": {"cliente": "...", "plan": "pro"}}
PLANS = {"anonimo": 30, "gratis": 60, "pro": 600}  # requests per minute
EXPORT_ROWS = {"anonimo": 500, "gratis": 2000, "pro": 20000}
PUBLIC = os.environ.get("PLENO_PUBLICO") == "1"   # hosted demo: read-only, no shared alerts
LIGHT_FACTOR = 5  # autocomplete gets its own, larger bucket so typing does not spend the search quota

app = FastAPI(
    title="Pleno API",
    version="0.1.0",
    description="Actos públicos de México (conferencias, sesiones legislativas) estructurados: quién dijo qué, "
                "cuándo, en qué institución, de qué partido y sobre qué ley. Cada resultado enlaza a su fuente oficial.",
)
_local = threading.local()
_windows = defaultdict(deque)
_lock = threading.Lock()


def con():
    if getattr(_local, "gen", None) != db.GENERATION:
        if hasattr(_local, "con"):
            _local.con.close()
        _local.con, _local.gen = db.connect(), db.GENERATION
    return _local.con


def load_keys():
    return json.loads(KEYS_FILE.read_text(encoding="utf-8")) if KEYS_FILE.exists() else {}


def plan_for(request):
    key = request.headers.get("x-api-key")
    if not key:
        return "anonimo", f"ip:{request.client.host if request.client else 'local'}"
    client = load_keys().get(key)
    if not client:
        raise HTTPException(401, "API key inválida")
    return (client.get("plan") if client.get("plan") in PLANS else "gratis"), f"key:{key}"


def _limit(request, bucket="", factor=1):
    plan, ident = plan_for(request)
    ident, limit = ident + bucket, PLANS[plan] * factor
    now = time.monotonic()
    with _lock:
        window = _windows[ident]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(429, f"Límite de {limit} consultas por minuto. Pide una API key para más.")
        window.append(now)


def rate_limit(request: Request):
    _limit(request)


def rate_limit_light(request: Request):
    _limit(request, ":ligero", LIGHT_FACTOR)


class QueryIn(BaseModel):
    texto: str = ""
    instituciones: list[str] = []
    estados: list[str] = []
    personas: list[str] = []
    partidos: list[str] = []
    cargos: list[str] = []
    leyes: list[str] = []
    medios: list[str] = []
    desde: str = ""
    hasta: str = ""
    orden: str = Field("relevancia", pattern="^(relevancia|fecha)$")
    limite: int = Field(20, ge=1, le=100)
    pagina: int = Field(1, ge=1, le=500)


class InstallIn(BaseModel):
    modo: str = Field(..., pattern="^(rapido|fuentes)$")
    fuentes: list[str] = []
    diario: bool = True


class Claim(BaseModel):
    afirmacion: str = Field(..., min_length=8, max_length=500)
    sin_modelo: bool = False


class Question(BaseModel):
    pregunta: str = Field(..., min_length=2, max_length=400)
    consulta: QueryIn | None = None


api = Depends(rate_limit)
light = Depends(rate_limit_light)


@app.get("/api/v1/estado", dependencies=[api])
def estado():
    c = con()
    count = lambda sql: c.execute(sql).fetchone()[0]
    return {
        "publico": PUBLIC,
        "instalacion_necesaria": not PUBLIC and count("SELECT COUNT(*) FROM documents") == 0,
        "documentos": count("SELECT COUNT(*) FROM documents"),
        "intervenciones": count("SELECT COUNT(*) FROM turns"),
        "personas": count("SELECT COUNT(*) FROM people"),
        "leyes": count("SELECT COUNT(*) FROM laws"),
        **search.options(c),
    }


@app.post("/api/v1/interpretar", dependencies=[api])
def interpretar(body: Question):
    q, notes = nlq.interpret(body.pregunta, db.DB_FILE)
    return {"consulta": q.to_dict(), "interpretacion": notes}


@app.post("/api/v1/buscar", dependencies=[api])
def buscar(body: QueryIn):
    q = Query.from_dict(body.model_dump())
    c = con()
    votos = search.votes_search(c, q.texto, 5) if q.texto and not (q.personas or q.estados) else None
    return {**search.search(c, q), "facetas": search.facets(c, q), "etiquetas": search.labels(c, q), "votaciones": votos}


@app.post("/api/v1/exportar", dependencies=[api])
def exportar(body: QueryIn, request: Request):
    """CSV with the full text of every matching turn (row cap depends on the plan)."""
    cap = EXPORT_ROWS[plan_for(request)[0]]
    q = Query.from_dict({**body.model_dump(), "limite": cap, "pagina": 1})
    rows = search.search(con(), q, max_limit=cap, full_text=True)["resultados"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["fecha", "institucion", "orador", "persona", "partido", "cargo", "medio", "leyes", "texto",
                     "documento", "fuente"])
    for r in rows:
        writer.writerow([r["date"], r["institution"], r["speaker"], r["person"] or "", r["party"] or "", r["role"] or "",
                         r["outlet"] or "", "; ".join(l["nombre"] for l in r["leyes"]), r["snippet"], r["document_id"],
                         r["source_url"]])
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="pleno.csv"'})


@app.get("/api/v1/fuentes", dependencies=[api])
def lista_fuentes():
    """Every public source reviewed: integrated, pending, blocked by robots.txt or not published online."""
    return fuentes.registry(con())


@app.get("/api/v1/votaciones", dependencies=[api])
def votaciones(q: str = "", pagina: int = Query_(1, ge=1, le=500), limite: int = Query_(20, ge=1, le=100)):
    """Roll-call votes of the Chamber of Deputies, newest first, optionally matching text in the title."""
    return search.votes_search(con(), q, limite, (pagina - 1) * limite)


@app.get("/api/v1/votaciones/{vid:path}", dependencies=[api])
def votacion(vid: str):
    data = search.vote(con(), vid)
    if not data:
        raise HTTPException(404, "Votación no encontrada")
    return data


class AlertIn(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)
    consulta: QueryIn


def _local_only():
    if PUBLIC:
        raise HTTPException(403, "Las alertas están disponibles en la versión local de Pleno.")


@app.get("/api/v1/alertas", dependencies=[api, Depends(_local_only)])
def alertas():
    return updater.list_alerts(con())


@app.post("/api/v1/alertas", dependencies=[api, Depends(_local_only)])
def crear_alerta(body: AlertIn):
    aid = updater.create_alert(con(), body.nombre, body.consulta.model_dump())
    return {"id": aid, "rss": f"/api/v1/alertas/{aid}.rss"}


@app.delete("/api/v1/alertas/{aid}", dependencies=[api, Depends(_local_only)])
def borrar_alerta(aid: str):
    if not updater.delete_alert(con(), aid):
        raise HTTPException(404, "Alerta no encontrada")
    return {"ok": True}


@app.get("/api/v1/alertas/{aid}.rss", dependencies=[api])
def alerta_rss(aid: str):
    row = con().execute("SELECT * FROM alerts WHERE id = ?", (aid,)).fetchone()
    if not row:
        raise HTTPException(404, "Alerta no encontrada")
    alert = {**dict(row), "query": json.loads(row["query"])}
    return Response(updater.rss(con(), alert), media_type="application/rss+xml; charset=utf-8")


@app.get("/api/v1/panorama", dependencies=[api])
def panorama():
    """What is new, which laws are being discussed and who speaks most, for the home page."""
    # It scans the whole base (seconds on a small host) and only changes when new data is loaded.
    now = time.time()
    if not _panorama or now - _panorama[0] > PANORAMA_TTL:
        _panorama[:] = [now, search.panorama(con())]
    return _panorama[1]


_panorama = []
PANORAMA_TTL = 24 * 3600 if PUBLIC else 600


@app.get("/api/v1/sugerir", dependencies=[light])
def sugerir(q: str = Query_(..., min_length=2, max_length=80)):
    return search.suggest(con(), q)


@app.post("/api/v1/responder", dependencies=[api])
def responder(body: Question):
    q = Query.from_dict(body.consulta.model_dump()) if body.consulta else nlq.interpret(body.pregunta, db.DB_FILE)[0]
    return {"consulta": q.to_dict(), **rag.answer(con(), body.pregunta, q)}


@app.get("/api/v1/instalacion", dependencies=[light])
def instalacion():
    """First-run state: whether data is needed, the choices, and the progress of a running install."""
    from pleno import instalador
    if PUBLIC:
        raise HTTPException(403, "No disponible en la demo pública.")
    return {"necesaria": instalador.needed(con()), "fuentes": instalador.FUENTES, "estado": instalador.status()}


@app.get("/api/v1/actualizacion", dependencies=[light])
def actualizacion():
    """Whether new data is being pulled right now, and when the last update finished."""
    from pleno import actualizar
    if PUBLIC:
        return {"en_curso": False, "ultima": None}
    last = actualizar.ultima()
    return {"en_curso": actualizar.en_curso(),
            "ultima": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last)) if last else None}


@app.post("/api/v1/instalacion", dependencies=[api])
def instalar(body: InstallIn):
    from pleno import instalador
    if PUBLIC:
        raise HTTPException(403, "No disponible en la demo pública.")
    try:
        instalador.start(body.modo, body.fuentes or None)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    diario = None
    if body.diario:
        try:
            diario = instalador.schedule_daily()
        except Exception as e:  # the data still installs; the person can schedule later
            diario = f"No se pudo programar la actualización diaria ({type(e).__name__})."
    return {"ok": True, "diario": diario}


@app.post("/api/v1/verificar", dependencies=[api])
def verificar_afirmacion(body: Claim):
    """What the public record shows about a claim: respaldada, contradicha, mixta, sin_evidencia or revisar.
    Votes and quotes are checked exactly; anything else by a model whose quotes are checked word for word."""
    from pleno import verificar
    return verificar.verify(con(), body.afirmacion, use_llm=not body.sin_modelo)


@app.get("/api/v1/estadistica", dependencies=[api])
def estadistica_delitos(delito: str = Query_(..., min_length=3, max_length=60), estado: str | None = None):
    """Monthly official figures (SESNSP) for a crime named in plain words («homicidios», «feminicidio»)."""
    from pleno import estadistica
    target = estadistica.crime_in(delito)
    if not target:
        raise HTTPException(404, "No reconozco ese delito; prueba «homicidios», «feminicidio», «secuestro», «extorsión» o «robo».")
    column, value, series = target
    return {"delito": value, "serie": series, "estado": estado, "fuente": estadistica.SOURCE_NOTE,
            "mensual": estadistica.monthly(con(), column, value, series, estado)}


@app.get("/api/v1/personas", dependencies=[api])
def personas(q: str):
    return search.find_people(con(), q)


@app.get("/api/v1/personas/{pid}", dependencies=[api])
def persona(pid: str):
    data = search.person(con(), pid)
    if not data:
        raise HTTPException(404, "Persona no encontrada")
    return data


@app.get("/api/v1/leyes", dependencies=[api])
def leyes(q: str = ""):
    return search.find_laws(con(), q)


@app.get("/api/v1/leyes/{lid}", dependencies=[api])
def ley(lid: str):
    data = search.law(con(), lid)
    if not data:
        raise HTTPException(404, "Ley no encontrada")
    return data


@app.get("/api/v1/documentos/{doc_id:path}", dependencies=[api])
def documento(doc_id: str):
    data = search.document(con(), doc_id)
    if not data:
        raise HTTPException(404, "Documento no encontrado")
    return data


@app.get("/", include_in_schema=False)
def index(request: Request):
    # Link previews (X, WhatsApp, LinkedIn) need absolute URLs in the Open Graph tags.
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https":
        base = base.replace("http://", "https://", 1)
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{URL}}", base)
    return Response(html, media_type="text/html; charset=utf-8")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
