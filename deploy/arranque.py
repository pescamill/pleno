"""Entry point for hosted demos (Render, Hugging Face): serve at once, fetch the database in the background.

Free hosts wipe the disk when the app sleeps, so every wake-up downloads the database again (≈2 GB from the
Hugging Face dataset). The port opens immediately and visitors see a «waking up» page until the data is ready.
"""

import os
import shutil
import threading
import traceback

TARGET = os.environ.setdefault("PLENO_DB", "/tmp/pleno.db")
REPO = os.environ.get("PLENO_DB_REPO", "pescamil/pleno-datos")
ready = threading.Event()
failed = []

WAKING = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="8"><title>Pleno · despertando</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#141110;color:#f3ede6;font:17px/1.5 system-ui,sans-serif;text-align:center;padding:24px}
h1{font:500 44px/1.1 Georgia,serif;margin:0 0 10px}p{color:#a2978d;max-width:420px}i{display:inline-block;width:10px;height:10px;border-radius:50%;background:#ff7a9c;margin:0 3px;animation:b 1s infinite alternate}
i:nth-child(2){animation-delay:.2s}i:nth-child(3){animation-delay:.4s}@keyframes b{to{opacity:.2}}</style></head>
<body><div><h1>Pleno está despertando</h1><p>Es una demo gratuita: cuando nadie la usa se apaga. Estamos cargando los datos; tarda alrededor de un minuto y esta página se recarga sola.</p><p><i></i><i></i><i></i></p></div></body></html>""".encode()


def fetch():
    try:
        if not os.path.exists(TARGET):
            from huggingface_hub import hf_hub_download
            print(f"Descargando la base desde {REPO}…", flush=True)
            shutil.copy(hf_hub_download(REPO, "pleno.db", repo_type="dataset"), TARGET)
        print("Base lista.", flush=True)
        ready.set()
    except Exception:
        failed.append(traceback.format_exc())
        print(failed[-1], flush=True)


from pleno.api import app as pleno_app  # noqa: E402  (after PLENO_DB is set)


async def app(scope, receive, send):
    # Static files need no data, so the host's health check passes while the database downloads.
    if scope["type"] == "http" and not ready.is_set() and not scope["path"].startswith("/static/"):
        status = 500 if failed else 503
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"retry-after", b"10")]})
        await send({"type": "http.response.body", "body": WAKING})
        return
    await pleno_app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=fetch, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)), proxy_headers=True,
                forwarded_allow_ips="*")
