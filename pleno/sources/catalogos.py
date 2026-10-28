"""Official catalogs that standardize what transcripts mention by name.

Federal laws: the Chamber of Deputies' list of laws in force (diputados.gob.mx/LeyesBiblio), with the
official PDF and the date of the last reform. A law detected in a transcript that matches this list
becomes «federal, vigente» and links to its official text.
"""

import html as htmllib
import re

from pleno.normalize import fold
from pleno.sources.base import CACHE_DIR, fetch_cached

LEYES_URL = "https://www.diputados.gob.mx/LeyesBiblio/"


def _nice(name):
    """«LEY de Amparo, Reglamentaria…» → «Ley de Amparo, Reglamentaria…»."""
    words = name.split()
    if words and words[0].isupper():
        words[0] = words[0].capitalize()
    return " ".join(words)


def law_key(name):
    """Matching key: the name before its first comma or «Reglamentaria», folded."""
    short = re.split(r",|\s+reglamentaria\b", name, maxsplit=1, flags=re.I)[0]
    return re.sub(r"[^a-z0-9 ]", "", fold(short)).strip()


def federal_laws(delay=1.0):
    """[{name, key, url, last_reform}] for every federal law in force."""
    raw = fetch_cached(LEYES_URL + "index.htm", CACHE_DIR / "catalogos" / "leyes-federales.html", delay=delay,
                       max_age=7 * 24 * 3600)
    if not raw:
        return []
    page = raw.decode("cp1252", "replace")
    out = []
    for row in re.split(r"<tr\b", page, flags=re.I)[1:]:
        name = re.search(r'href="ref/[^"]+"[^>]*>\s*(?:<[^>]+>\s*)*([^<]+)', row, re.I)
        pdf = re.search(r'href="(pdf/[^"]+\.pdf)"', row, re.I)
        if not (name and pdf):
            continue
        dates = re.findall(r"DOF\s+(\d{2})/(\d{2})/(\d{4})", row)
        full = _nice(re.sub(r"\s+", " ", htmllib.unescape(name.group(1))).strip())
        out.append({"name": full, "key": law_key(full), "url": LEYES_URL + pdf.group(1),
                    "last_reform": f"{dates[-1][2]}-{dates[-1][1]}-{dates[-1][0]}" if dates else None})
    return out
