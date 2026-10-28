"""Federal executive: the morning press conferences, from feregrino/mananeras (CC BY-SA 4.0)."""

import os
import re
from pathlib import Path

from pleno.normalize import STATES, fold, title_name
from pleno.sources.base import ROOT, Document, Turn

NAME = "mananeras"
DATASET = "https://huggingface.co/datasets/feregrino/mananeras"
_AUTHOR_CLONE = ROOT.parent / "neta" / "data" / "raw" / "mananeras"
CORPUS_DIR = Path(os.environ.get("PLENO_MANANERAS_DIR")
                  or (_AUTHOR_CLONE if _AUTHOR_CLONE.exists() else ROOT / "data" / "mananeras"))
REPO_ID = "feregrino/mananeras"
INSTITUTIONS = [
    {"id": "presidencia", "name": "Presidencia de la República", "level": "federal", "state": None, "kind": "ejecutivo"},
]

MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
DATE_RE = re.compile(r"(\d{1,2}) de (\w+) de (\d{4})")

# Headers that are a role, never a person.
GENERIC = {
    "pregunta": "Periodista", "interlocutor": "Periodista", "interlocutora": "Periodista",
    "moderador": "Moderación", "moderadora": "Moderación", "asistentes": "Público",
    "voces a coro": "Público", "voz hombre": "Voz", "voz mujer": "Voz",
    "intervencion": "Intervención", "intervencion hombre": "Intervención", "intervencion mujer": "Intervención",
}
ROLE_WORDS = (
    "secretari", "subsecretari", "director", "directora", "fiscal", "procurador", "procuradora", "coordinador",
    "coordinadora", "gobernador", "gobernadora", "titular", "presidente", "presidenta", "jefe", "jefa",
    "comandante", "vocero", "vocera", "general", "almirante", "comisionad", "embajador", "embajadora",
    "senador", "senadora", "diputad", "alcalde", "alcaldesa", "rector", "rectora", "consejer", "ministr",
    "administrador", "administradora", "encargad", "subdirector", "subdirectora", "responsable", "comisari",
    "gerente", "investigador", "investigadora", "integrante", "representante", "delegad", "magistrad",
)
# «Juan Pérez, de La Jornada.» at the start of a press question.
OUTLET_RE = re.compile(
    r"(?<![\wáéíóúñ])(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+ ){1,3}[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+, (?:de|del|soy de|vengo de|reportero de|reportera de) "
    r"((?:la |el |los |las )?[A-ZÁÉÍÓÚÑ0-9][^.,;:?¿!¡()]{1,60}?)(?:[.,;:?]| y | para )"
)


# «PRESIDENTA DE MÉXICO, X», «PRESIDENTE X»; not «PRESIDENTA MUNICIPAL DE…» nor «PRESIDENTE DEL INE…».
HEAD_OF_STATE_RE = re.compile(
    r"(?i)^(presidente|presidenta)(?:\s+(?:constitucional(?: de los estados unidos mexicanos)?|de m[ée]xico))*\s*,?\s*(.+)$")
NOT_HEAD_OF_STATE = {"municipal", "del", "de", "ejecutivo", "ejecutiva", "nacional", "consejero", "consejera",
                     "electo", "electa", "interino", "interina", "honorario", "honoraria", "y"}


def parse_date(line):
    m = DATE_RE.search(line)
    if not m or m.group(2).lower() not in MONTHS:
        return ""
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def is_role(text):
    folded = fold(text)
    return any(folded.startswith(w) or f" {w}" in f" {folded}"[:40] for w in ROLE_WORDS)


def parse_speaker(header):
    """Return (role, name) from headers like «SECRETARIA DE GOBERNACIÓN, ROSA ICELA RODRÍGUEZ VELÁZQUEZ»."""
    header = re.sub(r"\s+", " ", header).strip()
    key = fold(header)
    if key in GENERIC:
        return GENERIC[key], None
    if key.startswith(("voz ", "voces", "intervencion", "asistente", "publico", "nino", "nina", "video")):
        return "Voz", None
    head = HEAD_OF_STATE_RE.match(header)
    if head and fold(head.group(2)).split(" ")[0] not in NOT_HEAD_OF_STATE:
        role = "Presidenta de México" if fold(head.group(1)) == "presidenta" else "Presidente de México"
        return role, title_name(head.group(2))
    if "," in header:
        left, right = (p.strip() for p in header.rsplit(",", 1))
        if is_role(left) and not is_role(right):
            return title_name(left), title_name(right)
        return title_name(right), title_name(left)
    if is_role(header):
        return title_name(header), None
    return None, title_name(header)


def find_outlet(text):
    m = OUTLET_RE.search(text[:300])
    outlet = m.group(1).strip() if m else None
    return None if outlet and fold(outlet) in STATES else outlet


def parse_transcript(text, rel_path):
    blocks = [b.strip() for b in text.split("\n---")]
    header = blocks[0].splitlines()
    title = header[0].strip() if header else ""
    date = next((d for d in map(parse_date, header) if d), "")
    turns, last_outlet = [], None
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        speaker = lines[0].strip()
        body = "\n".join(line.strip() for line in lines[1:] if line.strip())
        if not body:
            continue
        role, name = parse_speaker(speaker)
        outlet = None
        if role == "Periodista":
            # «PREGUNTA» opens a new reporter; «INTERLOCUTOR(A)» is the same reporter following up.
            outlet = find_outlet(body) or (None if fold(speaker) == "pregunta" else last_outlet)
            last_outlet = outlet
        turns.append(Turn(speaker=speaker, text=body, role=role, name=name, outlet=outlet))
    return Document(
        id=f"mananeras:{Path(rel_path).with_suffix('').as_posix()}",
        institution_id="presidencia",
        kind="conferencia",
        date=date,
        title=title,
        source_url=f"{DATASET}/blob/main/{rel_path}",
        turns=turns,
    )


def documents(corpus_dir=CORPUS_DIR, since=None):
    for path in sorted(Path(corpus_dir).rglob("*.txt")):
        rel = path.relative_to(corpus_dir).as_posix()
        doc = parse_transcript(path.read_text(encoding="utf-8", errors="ignore"), rel)
        if since and doc.date and doc.date < since:
            continue
        yield doc
