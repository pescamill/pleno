"""What every source adapter produces: documents made of speaker turns, all in one shape."""

import hashlib
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from pleno.net import SSL_CONTEXT

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
USER_AGENT = "Pleno/0.1 (datos públicos de México; github.com/pescamill)"


@dataclass
class Turn:
    speaker: str                 # exactly as written in the source
    text: str
    role: str | None = None      # Presidenta, Diputada, Periodista, Secretario de Salud…
    name: str | None = None      # person's name when the source gives one
    outlet: str | None = None    # news outlet, for press questions


@dataclass
class Document:
    id: str
    institution_id: str
    kind: str
    date: str
    title: str
    source_url: str
    legislature: str | None = None
    turns: list = field(default_factory=list)

    def sha1(self):
        h = hashlib.sha1()
        for t in self.turns:
            # Parsed fields are part of the fingerprint, so parser fixes reload affected documents.
            h.update(f"{t.speaker}\x00{t.role}\x00{t.name}\x00{t.outlet}\x00{t.text}\x01".encode())
        return h.hexdigest()


class NotFound(Exception):
    pass


RETRYABLE = (ConnectionError, TimeoutError, urllib.error.URLError)


def http_get(url, data=None, timeout=90, attempts=3):
    """GET/POST with retries (2 s, 8 s) on dropped connections and 5xx; 404 raises NotFound at once."""
    for attempt in range(attempts):
        try:
            return _http_get(url, data, timeout)
        except NotFound:
            raise
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == attempts - 1:
                raise
        except RETRYABLE:
            if attempt == attempts - 1:
                raise
        time.sleep(2 * 4 ** attempt)


def _http_get(url, data=None, timeout=90):
    """GET (or POST form `data`). Many government sites serve an incomplete certificate chain that Python
    cannot complete; for those we fall back to the system curl, which still verifies the certificate."""
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*")
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from e
        raise
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    cmd = ["curl", "-sSfL", "--max-time", str(timeout), "-A", USER_AGENT, url]
    if data:
        cmd[1:1] = ["--data", urllib.parse.urlencode(data)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 22 and b"404" in proc.stderr:
        raise NotFound(url)
    if proc.returncode:
        raise urllib.error.URLError(proc.stderr.decode(errors="replace").strip())
    return proc.stdout


def fetch_cached(url, cache_path, delay=1.0, missing_ok=True, max_age=None, retry_missing_after=None, data=None):
    """GET with an on-disk cache (including remembered 404s) and a polite delay between live requests.

    max_age: seconds after which a cached copy is fetched again (index pages that grow).
    retry_missing_after: seconds after which a remembered 404 is tried again (a session published late).
    """
    cache_path = Path(cache_path)
    missing = cache_path.with_suffix(cache_path.suffix + ".404")
    now = time.time()
    if cache_path.exists() and (max_age is None or now - cache_path.stat().st_mtime < max_age):
        return cache_path.read_bytes()
    if missing.exists():
        if retry_missing_after is None or now - missing.stat().st_mtime < retry_missing_after:
            return None
        missing.unlink()
    time.sleep(delay)
    try:
        body = http_get(url, data=data)
    except NotFound:
        if not missing_ok:
            raise
        missing.parent.mkdir(parents=True, exist_ok=True)
        missing.touch()
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(body)
    return body


def pdf_text(url, cache_path, delay=1.0):
    """Text of an official PDF, cached as .txt plus a .json receipt (URL, SHA-1 of the PDF, pages).

    The PDF itself is not kept: the receipt's hash proves what the document said when it was read.
    Pages are separated by form feeds so parsers can drop running headers.
    """
    cache_path = Path(cache_path)
    txt, receipt = cache_path.with_suffix(".txt"), cache_path.with_suffix(".json")
    if txt.exists():
        return txt.read_text(encoding="utf-8")
    if cache_path.with_suffix(".404").exists():
        return None
    time.sleep(delay)
    try:
        raw = http_get(url)
    except NotFound:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.with_suffix(".404").touch()
        return None
    import io
    import logging
    from pdfminer.high_level import extract_text   # keeps words whole where pypdf splits them («SENTEN CIA»)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        text = extract_text(io.BytesIO(raw))       # pages separated by form feeds
    except Exception as e:  # a corrupt or encrypted PDF should not stop the whole source
        text = ""
        print(f"  PDF ilegible ({type(e).__name__}): {url}")
    pages = text.split("\f")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(text, encoding="utf-8")
    receipt.write_text(json.dumps({"url": url, "sha1": hashlib.sha1(raw).hexdigest(), "bytes": len(raw),
                                   "paginas": len(pages), "leido": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                  ensure_ascii=False), encoding="utf-8")
    return text


def legislature_for(date):
    """Federal legislatures start on 1 September of every third year (LXVI: 2024–2027)."""
    if not date:
        return None
    year, month = int(date[:4]), int(date[5:7])
    start = year if month >= 9 else year - 1
    number = 66 + (start - 2024) // 3
    return to_roman(number)


def to_roman(n):
    out = ""
    for value, sym in ((50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sym
            n -= value
    return out
