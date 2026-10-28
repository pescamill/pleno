"""Grounded answers: retrieve turns with a structured query, then answer only from them, with citations.

The model is any OpenAI-compatible endpoint (local Ollama by default). If it is unavailable,
the answer degrades to the retrieved passages themselves, so the user always sees evidence.
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from pleno.net import SSL_CONTEXT
from pleno.search import Query, search

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"
SYSTEM = (
    "Eres un analista de actos públicos de México. Responde en español, en 3 a 6 oraciones, usando SOLO los "
    "fragmentos numerados. Cita cada afirmación con su número entre corchetes, por ejemplo [2]. "
    "Si los fragmentos no alcanzan para responder, dilo claramente. No inventes nombres, cifras ni fechas."
)


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"llm": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:3b"}}


def context_block(hits):
    lines = []
    for n, h in enumerate(hits, 1):
        who = h["person"] or h["speaker"]
        meta = ", ".join(x for x in (h["role"], h["party"], h["institution"], h["date"]) if x)
        text = re.sub(r"[⟦⟧]", "", h["snippet"])
        lines.append(f"[{n}] {who} ({meta}): «{text}»")
    return "\n".join(lines)


def call_llm(llm, question, context, timeout=180, system=SYSTEM):
    body = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Pregunta: {question}\n\nFragmentos:\n{context}"},
        ],
        "max_tokens": llm.get("max_tokens", 500),
    }
    headers = {"Content-Type": "application/json"}
    if llm.get("api_key_env"):
        key = os.environ.get(llm["api_key_env"])
        if not key:
            raise RuntimeError(f"Falta {llm['api_key_env']}")
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(llm["base_url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


def valid_citations(text, n_hits):
    """Drop citation numbers that point at nothing, and report which passages were actually used."""
    used = []

    def keep(m):
        nums = [int(x) for x in re.findall(r"\d+", m.group(0)) if 1 <= int(x) <= n_hits]
        used.extend(nums)
        return "[" + ", ".join(map(str, nums)) + "]" if nums else ""

    cleaned = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", keep, text)
    return cleaned, sorted(set(used))


def answer(con, question, q: Query, k=10):
    hits = search(con, Query.from_dict({**q.to_dict(), "limite": k, "pagina": 1, "orden": "relevancia"}))["resultados"]
    if not hits:
        return {"respuesta": "No encontré intervenciones que coincidan con esta consulta.", "citas": [], "fuentes": [],
                "modelo": None}
    llm = load_config()["llm"]
    try:
        raw = call_llm(llm, question, context_block(hits))
        text, used = valid_citations(raw, len(hits))
        model = llm["model"]
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, json.JSONDecodeError) as e:
        text = (f"No pude generar un resumen ({type(e).__name__}). Estas son las {len(hits)} intervenciones "
                "más relevantes; cada una enlaza a su fuente oficial.")
        used, model = [], None
    return {"respuesta": text, "citas": used, "fuentes": hits, "modelo": model}
