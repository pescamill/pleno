"""Versioned dataset snapshots for sale or model training: `pleno dataset`.

What goes out is decided by source licence and by privacy, not by convenience:

- Mañaneras come from a CC BY-SA 4.0 dataset, so they ship in their own split under that same licence.
- The other sources are official legislative, judicial and administrative texts, which Mexican copyright law
  leaves outside protection (LFDA art. 14, fr. VIII). They ship as «textos oficiales»; what Pleno adds on top
  (speaker, party and law links, vote discipline) is Pleno's own work.
- People who are not public officials (reporters, the public) appear by role, never by name.
- In prosecutor releases, «José “N”» becomes «Persona A “N”» (consistent within each release) and aliases are
  removed: a bulk corpus must not become a list of named detainees.
- E-mail addresses and phone numbers are masked everywhere.

Each snapshot has Parquet tables, verifiable tasks built from the structure (no model writes them), a dataset
card, a licence file and a manifest with SHA-256 per file.
"""

import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pleno import db

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "dataset"

LICENSES = {
    "cc-by-sa-4.0": "CC BY-SA 4.0 (heredada de feregrino/mananeras; atribución y compartir igual)",
    "textos-oficiales": "Textos oficiales sin protección de derecho de autor (LFDA art. 14, fr. VIII); "
                        "anotaciones de Pleno bajo la licencia del comprador o del release",
}
PRIVATE_ROLES = {"Periodista", "Público", "Voz", "Intervención"}

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?52[\s.-]?)?(?:\(?\d{2,3}\)?[\s.-]?)\d{3,4}[\s.-]?\d{4}(?!\d)")
DETAINEE_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?: [A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3}) [\"“«]N[\"”»]")
ALIAS_RE = re.compile(r"\b(alias|apodado|conocido como) [\"“«][^\"”»]{1,40}[\"”»]", re.I)


def license_of(institution_id):
    return "cc-by-sa-4.0" if institution_id == "presidencia" else "textos-oficiales"


def mask_contacts(text):
    return PHONE_RE.sub("[teléfono]", EMAIL_RE.sub("[correo]", text))


def mask_detainees(text):
    """«Juan “N” y Cecilia “N”… Juan “N”» → «Persona A “N” y Persona B “N”… Persona A “N”»."""
    letters = {}

    def sub(m):
        if m[1] not in letters:
            n = len(letters)
            letters[m[1]] = chr(65 + n) if n < 26 else str(n + 1)
        return f"Persona {letters[m[1]]} “N”"
    return ALIAS_RE.sub(lambda m: f"{m[1]} [alias]", DETAINEE_RE.sub(sub, text))


def _public_people(con):
    """People Pleno can name: anyone with an official roster entry or an official role in a turn."""
    rows = con.execute(
        "SELECT DISTINCT person_id FROM turns WHERE person_id IS NOT NULL AND COALESCE(role, '') NOT IN "
        f"({','.join('?' * len(PRIVATE_ROLES))}) AND outlet IS NULL "
        "UNION SELECT person_id FROM memberships", sorted(PRIVATE_ROLES)).fetchall()
    return {r[0] for r in rows}


def _turn_rows(con, public):
    laws = defaultdict(list)
    for tid, lid in con.execute("SELECT turn_id, law_id FROM mentions"):
        laws[tid].append(lid)
    cur = con.execute(
        "SELECT t.id, t.document_id, t.idx, t.speaker, t.role, t.person_id, t.outlet, t.text, d.institution_id, "
        "i.name, i.level, i.state, i.kind, d.kind, d.date, d.source_url, p.party "
        "FROM turns t JOIN documents d ON d.id = t.document_id JOIN institutions i ON i.id = d.institution_id "
        "LEFT JOIN people p ON p.id = t.person_id ORDER BY d.date, t.document_id, t.idx")
    for (tid, doc, idx, speaker, role, pid, outlet, text, inst, inst_name, level, state, inst_kind, doc_kind,
         date, url, party) in cur:
        private = (role or "") in PRIVATE_ROLES or outlet is not None or (pid is not None and pid not in public)
        text = mask_contacts(text)
        if inst_kind == "procuración":
            text = mask_detainees(text)
        yield {
            "id": tid, "documento": doc, "orden": idx, "fecha": date, "institucion": inst,
            "institucion_nombre": inst_name, "nivel": level, "estado": state, "tipo_documento": doc_kind,
            "orador": (role or "Participante") if private else speaker, "cargo": role or None,
            "persona_id": None if private else pid, "partido": None if private else party,
            "medio": outlet, "texto": text, "leyes": laws.get(tid, []), "fuente": url, "licencia": license_of(inst),
        }


def _vote_tables(con):
    votes = [dict(r) for r in con.execute(
        "SELECT id, institution_id AS institucion, legislature AS legislatura, date AS fecha, title AS titulo, "
        "source_url AS fuente, a_favor, en_contra, abstencion, ausente, otros FROM votes ORDER BY date")]
    casts = [dict(r) for r in con.execute(
        "SELECT c.vote_id AS votacion, c.person_id AS persona_id, p.name AS nombre, c.party AS partido, "
        "c.sense AS sentido FROM vote_casts c LEFT JOIN people p ON p.id = c.person_id")]
    majority = defaultdict(Counter)
    for c in casts:
        if c["sentido"] in ("A favor", "En contra", "Abstención"):
            majority[c["votacion"], c["partido"]][c["sentido"]] += 1
    for c in casts:
        top = majority[c["votacion"], c["partido"]].most_common(1)
        c["contra_bancada"] = bool(top) and c["sentido"] in ("A favor", "En contra", "Abstención") \
            and c["sentido"] != top[0][0]
    return votes, casts


def vote_tasks(votes, casts):
    """Exact questions with one checkable answer: how did X vote on Y. Built from the roll call, not written by
    a model, so they work as an evaluation set for retrieval over Mexican public records."""
    by_id = {v["id"]: v for v in votes}
    for c in casts:
        v = by_id.get(c["votacion"])
        if not v or not c["nombre"]:
            continue
        yield {
            "tarea": "voto_nominal",
            "pregunta": f"¿Cómo votó {c['nombre']} en la votación del {v['fecha']} sobre «{v['titulo'][:160]}»?",
            "respuesta": c["sentido"], "partido": c["partido"], "contra_bancada": c["contra_bancada"],
            "votacion": v["id"], "fuente": v["fuente"],
        }


def quote_tasks(turns, per_institution=2000, seed=7):
    """«Who said this, where and when?»: a quote from an official, answered by the record."""
    import random
    rng = random.Random(seed)
    pools = defaultdict(list)
    for t in turns:
        if t["persona_id"] and len(t["texto"]) > 200:
            pools[t["institucion"]].append(t)
    for inst, pool in sorted(pools.items()):
        for t in rng.sample(pool, min(per_institution, len(pool))):
            words = t["texto"].split()
            start = rng.randrange(0, max(1, len(words) - 40))
            yield {
                "tarea": "atribucion_cita", "cita": " ".join(words[start:start + 40]),
                "respuesta": {"orador": t["orador"], "cargo": t["cargo"], "institucion": t["institucion_nombre"],
                              "fecha": t["fecha"]},
                "documento": t["documento"], "fuente": t["fuente"], "licencia": t["licencia"],
            }


def _write_parquet(rows, path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
    return len(rows)


def _write_jsonl(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def _sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(con=None, out=None, version=None):
    con = con or db.connect()
    version = version or dt.date.today().isoformat()
    out = Path(out or OUT_DIR / f"pleno-{version}")
    public = _public_people(con)
    turns = list(_turn_rows(con, public))
    counts = {}

    for lic in LICENSES:
        rows = [t for t in turns if t["licencia"] == lic]
        counts[f"intervenciones/{lic}"] = _write_parquet(rows, out / "intervenciones" / f"{lic}.parquet")

    docs = [dict(r) for r in con.execute(
        "SELECT d.id, d.institution_id AS institucion, d.kind AS tipo, d.date AS fecha, d.title AS titulo, "
        "d.legislature AS legislatura, d.source_url AS fuente, d.sha1 AS sha1_pdf, COUNT(t.id) AS intervenciones "
        "FROM documents d LEFT JOIN turns t ON t.document_id = d.id GROUP BY d.id ORDER BY d.date")]
    for d in docs:
        d["licencia"] = license_of(d["institucion"])
        if d["institucion"] == "fgr":
            d["titulo"] = mask_detainees(d["titulo"] or "")
    counts["documentos"] = _write_parquet(docs, out / "documentos.parquet")

    people = [dict(r) for r in con.execute(
        "SELECT id, name AS nombre, party AS partido, state AS estado FROM people ORDER BY id") if r["id"] in public]
    counts["personas"] = _write_parquet(people, out / "personas.parquet")
    counts["padron"] = _write_parquet([dict(r) for r in con.execute(
        "SELECT person_id AS persona_id, institution_id AS institucion, legislature AS legislatura, party AS partido, "
        "state AS estado, district AS distrito, principle AS principio, seat AS curul, committees AS comisiones, "
        "source_url AS fuente FROM memberships")], out / "padron.parquet")
    counts["leyes"] = _write_parquet([dict(r) for r in con.execute(
        "SELECT id, name AS nombre, jurisdiction AS jurisdiccion, official_name AS nombre_oficial, "
        "official_url AS texto_oficial, last_reform AS ultima_reforma FROM laws ORDER BY id")], out / "leyes.parquet")

    votes, casts = _vote_tables(con)
    counts["votaciones"] = _write_parquet(votes, out / "votaciones.parquet")
    counts["votos"] = _write_parquet(casts, out / "votos.parquet")

    counts["tareas/voto_nominal"] = _write_jsonl(vote_tasks(votes, casts), out / "tareas" / "voto_nominal.jsonl")
    counts["tareas/atribucion_cita"] = _write_jsonl(quote_tasks(turns), out / "tareas" / "atribucion_cita.jsonl")

    stats = {
        "version": version, "filas": counts,
        "tokens_aprox": {lic: sum(len(t["texto"]) for t in turns if t["licencia"] == lic) // 4 for lic in LICENSES},
        "por_institucion": Counter(t["institucion"] for t in turns),
        "desde": min(t["fecha"] for t in turns if t["fecha"]), "hasta": max(t["fecha"] for t in turns if t["fecha"]),
    }
    (out / "README.md").write_text(card(stats), encoding="utf-8")
    (out / "LICENCIAS.md").write_text(licenses_text(), encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    stats["archivos"] = {str(p.relative_to(out)): {"bytes": p.stat().st_size, "sha256": _sha256(p)} for p in files}
    (out / "manifest.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    return out, stats


def card(s):
    rows = "\n".join(f"| `{k}` | {v:,} |" for k, v in s["filas"].items())
    insts = "\n".join(f"| {k} | {v:,} |" for k, v in s["por_institucion"].most_common())
    tok = s["tokens_aprox"]
    return f"""---
license: other
language: [es]
pretty_name: Pleno — lo que se dice en el poder público de México
configs:
  - config_name: mananeras
    data_files: intervenciones/cc-by-sa-4.0.parquet
  - config_name: textos_oficiales
    data_files: intervenciones/textos-oficiales.parquet
---

# Pleno {s['version']}

Intervenciones en el poder público de México ({s['desde']} – {s['hasta']}), con orador, cargo, partido,
institución, leyes mencionadas y enlace a la fuente oficial; votaciones nominales de la Cámara de Diputados con
el sentido de cada voto; padrón oficial; catálogo de leyes; y dos conjuntos de tareas verificables.

## Contenido

| Tabla | Filas |
|---|---|
{rows}

| Institución | Intervenciones |
|---|---|
{insts}

Tokens aproximados (caracteres / 4): mañaneras {tok['cc-by-sa-4.0']:,} · textos oficiales {tok['textos-oficiales']:,}.

## Licencias

Dos divisiones con licencias distintas; ver `LICENCIAS.md`. La división `mananeras` es CC BY-SA 4.0 y
cualquier derivado debe conservar esa licencia y la atribución a feregrino/mananeras.

## Privacidad

- Periodistas y público aparecen por su papel («Periodista»), nunca por nombre.
- En comunicados de la FGR, «José “N”» se sustituye por «Persona A “N”» y los alias se eliminan.
- Correos y teléfonos enmascarados. No hay fechas de nacimiento ni datos de contacto del padrón.

## Tareas

- `tareas/voto_nominal.jsonl`: «¿Cómo votó X en la votación Y?», respuesta exacta del registro nominal.
- `tareas/atribucion_cita.jsonl`: una cita de 40 palabras; respuesta: orador, cargo, institución y fecha.

Ambas se construyen de la estructura de los datos; ningún modelo escribe preguntas ni respuestas.

## Limitaciones

- Orador y partido se asignan automáticamente; las fusiones de nombres se auditan en `fusiones-errata.tsv`.
- `leyes` se detecta por patrones: hay nombres imperfectos, sobre todo en congresos estatales.
- `partido` en intervenciones es el partido actual de la persona, no necesariamente el de esa fecha.
- Cobertura desigual por fuente y periodo; ver el inventario de fuentes en Pleno.
- Pleno no califica afirmaciones como verdaderas o falsas.
"""


def licenses_text():
    return "# Licencias por división\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in LICENSES.items()) + """

## Fundamento

- **Mañaneras.** Se toman de [feregrino/mananeras](https://huggingface.co/datasets/feregrino/mananeras),
  publicado bajo CC BY-SA 4.0. La versión estructurada es una obra derivada: se distribuye con la misma licencia
  y atribución. Se puede vender, pero quien la compre puede redistribuirla.
- **Textos oficiales.** La Ley Federal del Derecho de Autor (art. 14, fr. VIII) excluye de protección los textos
  legislativos, reglamentarios, administrativos y judiciales; si se publican deben apegarse al texto oficial y no
  confieren derecho exclusivo de edición. Por eso el texto se conserva tal cual y cada fila enlaza a su fuente.
- **Datos personales.** Se tratan datos que figuran en fuentes de acceso público (LFPDPPP 2025, art. 9, fr. II),
  limitados a servidores públicos en ejercicio de su función; el resto se presenta por papel o se seudonimiza.

Esta nota no es asesoría legal; revísala con un abogado antes de firmar contratos de licencia.
"""
