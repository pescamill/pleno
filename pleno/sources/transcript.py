"""Shared parsing for stenographic versions published as PDF: clean the extracted text, then split it into
speaker turns with a label pattern that each source configures.

Every congress writes speakers differently («LA C. DIPUTADA X.-», «DIPUTADA PRESIDENTA X:»,
«SEÑOR MINISTRO X:»), but the rest is the same: drop running headers, rejoin wrapped lines, read the
label into a role and a name.
"""

import re
from collections import Counter

from pleno.normalize import fold, title_name
from pleno.sources.base import Turn

# Ligatures and soft hyphens that PDF extraction leaves behind.
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "\u00ad": ""})

OFFICES = {"presidente", "presidenta", "vicepresidente", "vicepresidenta", "secretario", "secretaria",
           "prosecretario", "prosecretaria"}
MEMBERS = {"diputado": "Diputado", "diputada": "Diputada", "dip": "Diputado", "diputados": "Diputado",
           "senador": "Senador", "senadora": "Senadora", "ministro": "Ministro", "ministra": "Ministra",
           "magistrado": "Magistrado", "magistrada": "Magistrada", "consejero": "Consejero", "consejera": "Consejera",
           "regidor": "Regidor", "regidora": "Regidora", "sindico": "Síndico", "sindica": "Síndica"}
FILLER = {"el", "la", "los", "las", "c", "ciudadano", "ciudadana", "senor", "senora", "lic", "licenciado",
          "licenciada", "mtro", "mtra", "maestro", "maestra", "dr", "dra", "doctor", "doctora", "ing", "de", "del",
          "mesa", "directiva", "en", "funciones", "turno", "al", "a", "sesion", "instaladora", "comision"}


def clean(text, keep=None):
    """Extracted PDF text → paragraphs: no running headers or page numbers, no hyphenated breaks.

    keep: pattern for lines that repeat on many pages but are not headers («PRESIDENTA DIP. MARTHA
    AZUCENA», the first line of a speaker label that wraps)."""
    text = text.translate(LIGATURES).replace("\r", "")
    pages = text.split("\f")
    # A line that repeats on many pages (ignoring digits) is a header or footer.
    seen = Counter()
    for page in pages:
        for line in {re.sub(r"\d+", "#", l.strip()) for l in page.splitlines() if l.strip()}:
            seen[line] += 1
    limit = max(3, len(pages) // 4)
    running = {line for line, n in seen.items() if n >= limit and len(line) < 160
               and not (keep and re.match(keep, line))}
    lines = []
    for page in pages:
        for line in page.splitlines():
            stripped = line.strip()
            if not stripped or re.sub(r"\d+", "#", stripped) in running:
                continue
            if re.fullmatch(r"(?:p[áa]g(?:ina)?\.?\s*)?[-–—\s]*\d{1,4}[-–—\s]*(?:de\s+\d+)?", stripped, re.I):
                continue
            lines.append(stripped)
    out = []
    for line in lines:
        if out and out[-1].endswith("-") and not out[-1].endswith(" -") and line[:1].islower():
            out[-1] = out[-1][:-1] + line                      # «pala-» + «bra»
        elif out and not re.search(r"[.:;?!»”\"')]$", out[-1]):
            out[-1] = f"{out[-1]} {line}"                     # wrapped line
        else:
            out.append(line)
    return "\n".join(re.sub(r"\s{2,}", " ", l) for l in out)


def parse_label(label):
    """«LA C. DIPUTADA CLAUDIA SUSANA PÉREZ ROMERO» → ("Diputada", "Claudia Susana Pérez Romero");
    «LA C. PRESIDENTA DIPUTADA X» → ("Presidenta de la Mesa (Diputada)", "X"); «SEÑOR MINISTRO PRESIDENTE» →
    ("Ministro Presidente", None)."""
    label = re.sub(r"\([^)]*\)", " ", label)
    label = re.sub(r"[.\-–—:,]+\s*$", "", label.strip()).strip(" -–—")
    words = re.findall(r"[\wÁÉÍÓÚÑÜáéíóúñü'-]+\.?", label)
    office = member = None
    rest = []
    for w in words:
        f = fold(w).rstrip(".")
        if not rest and f in OFFICES and not office:
            office = f
        elif not rest and f in MEMBERS and not member:
            member = MEMBERS[f]
        elif not rest and f in FILLER:
            continue
        else:
            rest.append(w.rstrip(".") if w.endswith(".") and len(w) <= 3 else w)
    while rest and fold(rest[-1]) in OFFICES | set(MEMBERS) | FILLER:
        tail = fold(rest.pop())
        office = office or (tail if tail in OFFICES else None)
    if member == "Diputado" and re.match(r"(?i)^\s*(?:a\s+)?la\b", label):   # «A LA C. DIP. …»
        member = "Diputada"
    name = " ".join(rest).strip(" ,.")
    if name.isupper() or name.islower():
        name = title_name(name)
    if member in {"Ministro", "Ministra"}:
        role = f"{member} Presidente" if office in {"presidente", "presidenta"} else member
        if office == "presidenta":
            role = "Ministra Presidenta"
    elif office and member:
        role = f"{office.capitalize()} de la Mesa ({member})"
    elif office:
        role = f"{office.capitalize()} de la Mesa"
    else:
        role = member
    return role, (name if len(name.split()) >= 2 else None)


def split_turns(text, label_re, parse=parse_label, min_chars=2):
    """Cut cleaned text at every speaker label. `label_re` names its label group(s) «label», «label2»…"""
    marks = list(label_re.finditer(text))
    turns = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip(" \n:.-–—")
        if len(body) < min_chars:
            continue
        raw = next(v for k, v in m.groupdict().items() if k.startswith("label") and v)
        label = re.sub(r"\s+", " ", raw).strip()
        role, name = parse(label)
        turns.append(Turn(speaker=label.rstrip(".-: "), text=body, role=role, name=name))
    return turns


SPANISH_MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
SPANISH_MONTHS["setiembre"] = 9


def spanish_date(text):
    """First «5 de octubre de 2026» / «5 octubre 2026» / «05/10/2026» in text, as ISO, or ''."""
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
                  r"octubre|noviembre|diciembre)\s*(?:de[l]?\s+)?(\d{4})", fold(text))
    if m:
        return f"{int(m.group(3)):04d}-{SPANISH_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})[/_.-](\d{1,2})[/_.-](20\d{2})\b", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""
