"""Official crime statistics (SESNSP): monthly crimes and victims per state, from the open-data page.

The page on gob.mx (whose robots.txt sets no rule for other agents) links to public SharePoint files; each is
one download, refreshed monthly. Files are «Términos de Libre Uso MX» open data: cite the source.

Two series and a methodology break:
- «delitos» counts investigation files (carpetas); «victimas» counts victims, the usual base for homicides;
- from 2026 the SESNSP uses a new methodology (new age ranges, new subtypes). Comparisons that cross from
  2025 into 2026 are flagged as such; Pleno never hides that break.

Victims are summed over age ranges (they differ between methodologies), keeping sex.
"""

import csv
import http.cookiejar
import io
import re
import time
import urllib.parse
import urllib.request
import zipfile

from pleno.net import SSL_CONTEXT
from pleno.normalize import fold
from pleno.sources.base import CACHE_DIR

NAME = "sesnsp"
PAGE = "https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva"
UA = "Pleno/0.1 (datos abiertos; contacto en el sitio)"
# Link text on the page → (series, methodology).
WANTED = {
    "Estatal-Delitos-2015-2025": ("delitos", "2015-2025"),
    "Estatal-Victimas-2015-2025": ("victimas", "2015-2025"),
    "Delitos_Estatal-2026": ("delitos", "2026"),
    "Victimas_Estatal-2026": ("victimas", "2026"),
}
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
STATE_NAMES = {"Coahuila de Zaragoza": "Coahuila", "Michoacán de Ocampo": "Michoacán", "México": "Estado de México",
               "Veracruz de Ignacio de la Llave": "Veracruz"}
SOURCE_NOTE = "SESNSP, Incidencia delictiva del fuero común (datos abiertos, gob.mx)"


def _opener():
    # The share links set an anonymous session cookie on the first redirect; without it the file is refused.
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                       urllib.request.HTTPSHandler(context=SSL_CONTEXT))


def _get(url, opener=None, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with (opener or _opener()).open(req, timeout=timeout) as resp:
        return resp.read(), resp.geturl()


def download(max_age=20 * 24 * 3600, delay=2.0):
    """Fetch the zips if the cached copies are older than `max_age`. Returns the cached paths by key."""
    folder = CACHE_DIR / NAME
    folder.mkdir(parents=True, exist_ok=True)
    cached = {key: next(iter(sorted(folder.glob(f"*{key}*.zip"))), None) for key in WANTED}
    if all(p and time.time() - p.stat().st_mtime < max_age for p in cached.values()):
        return cached
    page = _get(PAGE)[0].decode("utf-8", "replace")
    (folder / "pagina.html").write_text(page, encoding="utf-8")
    for link in dict.fromkeys(re.findall(r'https://sspcgob-my\.sharepoint\.com/[^"]+', page)):
        opener = _opener()
        try:
            data, final = _get(link.replace("&amp;", "&") + "&download=1", opener)
        except OSError:
            continue
        name = urllib.parse.unquote(final.split("?")[0].rsplit("/", 1)[-1])
        name = name.replace("í", "i").replace("Í", "I")
        key = next((k for k in WANTED if k in name), None)
        if key and data[:2] == b"PK":
            for old in folder.glob(f"*{key}*.zip"):
                old.unlink()
            (folder / name).write_bytes(data)
            cached[key] = folder / name
        time.sleep(delay)
    return cached


def _rows(path):
    with zipfile.ZipFile(path) as z:
        member = next(i for i in z.infolist() if i.filename.lower().endswith(".csv"))
        raw = z.read(member)
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("latin1")
    return csv.DictReader(io.StringIO(text))


def records(paths=None):
    """Monthly values: (series, methodology, year, month, state, bien, tipo, subtipo, modalidad, sexo, value)."""
    paths = paths or download()
    for key, (series, method) in WANTED.items():
        path = paths.get(key)
        if not path:
            continue
        # «…-sep2026.zip»: data runs through September 2026; later months of that year are placeholders (0).
        cut = re.search(r"([a-z]{3})(\d{4})\.zip$", path.name.lower())
        cutoff = (int(cut[2]), MONTHS.index(next(m for m in MONTHS if m.startswith(cut[1]))) + 1) if cut else (9999, 12)
        totals = {}
        for row in _rows(path):
            row = {fold(k).replace(" ", "_"): v for k, v in row.items()}
            state = STATE_NAMES.get(row["entidad"], row["entidad"])
            base = (series, method, int(row["ano"]), state, row["bien_juridico_afectado"], row["tipo_de_delito"],
                    row["subtipo_de_delito"], row["modalidad"], row.get("sexo") or None)
            for m, month in enumerate(MONTHS, 1):
                value = (row.get(month) or "").strip()
                if value == "" or (base[2], m) > cutoff:
                    continue
                k = base[:3] + (m,) + base[3:]
                totals[k] = totals.get(k, 0) + int(float(value))
        yield from (k + (v,) for k, v in totals.items())
