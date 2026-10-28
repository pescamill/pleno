"""Render the reel to MP4, frame by frame, with Chrome and ffmpeg.

    .venv/bin/python promo/render.py                 → promo/pleno-reel.mp4 (1080×1920, 30 fps)
    .venv/bin/python promo/render.py --fotos 2,15,27 → PNG stills of those seconds, to check a scene
"""

import argparse
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "reel.html").as_uri()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--fotos", help="segundos separados por coma")
    ap.add_argument("--salida", default=str(HERE / "pleno-reel.mp4"))
    ap.add_argument("--carpeta-fotos", default=str(HERE / "fotos"))
    args = ap.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(PAGE)
        page.evaluate("window.ready")
        page.wait_for_timeout(300)
        if args.fotos:
            out = Path(args.carpeta_fotos)
            out.mkdir(parents=True, exist_ok=True)
            for s in args.fotos.split(","):
                page.evaluate(f"window.render({float(s)})")
                page.screenshot(path=str(out / f"t{float(s):05.1f}.png"))
            print(f"fotos en {out}")
            return
        duration = page.evaluate("window.DURATION")
        frames = int(duration * args.fps)
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(args.fps), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-crf", "16", "-preset", "slow",
             "-movflags", "+faststart", args.salida], stdin=subprocess.PIPE)
        for i in range(frames):
            page.evaluate(f"window.render({i / args.fps})")
            ffmpeg.stdin.write(page.screenshot(type="png"))
            if i % 150 == 0:
                print(f"{i}/{frames}", flush=True)
        ffmpeg.stdin.close()
        ffmpeg.wait()
        browser.close()
    print(f"listo: {args.salida}")


if __name__ == "__main__":
    main()
