"""Publish the Pleno demo to Hugging Face: the database as a dataset and the app as a Docker Space.

Requires a Hugging Face login with a write token (`hf auth login`, or the HF_TOKEN environment variable).

    .venv/bin/python deploy/publicar.py <usuario-de-hugging-face>
"""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def public_db(dest):
    """A consistent copy of the database without the private tables (saved alerts, run log)."""
    src = sqlite3.connect(ROOT / "data" / "pleno.db")
    src.execute("VACUUM INTO ?", (str(dest),))
    src.close()
    con = sqlite3.connect(dest)
    con.execute("DELETE FROM alerts")
    con.execute("DELETE FROM runs")
    con.commit()
    con.execute("VACUUM")
    con.close()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    user = sys.argv[1]
    api = HfApi()
    data_repo, space_repo = f"{user}/pleno-datos", f"{user}/pleno"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("1/4 Copiando la base pública…")
        public_db(tmp / "pleno.db")
        shutil.copy(HERE / "README-datos.md", tmp / "README.md")
        print(f"2/4 Subiendo la base a {data_repo} (≈2 GB, puede tardar)…")
        api.create_repo(data_repo, repo_type="dataset", exist_ok=True)
        api.upload_folder(repo_id=data_repo, repo_type="dataset", folder_path=tmp, allow_patterns=["pleno.db", "README.md"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("3/4 Armando la app…")
        shutil.copytree(ROOT / "pleno", tmp / "pleno", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "web", tmp / "web")
        for name in ("Dockerfile", "requirements.txt", "arranque.py"):
            shutil.copy(HERE / name, tmp / name)
        shutil.copy(HERE / "README-space.md", tmp / "README.md")
        print(f"4/4 Publicando el Space {space_repo}…")
        api.create_repo(space_repo, repo_type="space", space_sdk="docker", exist_ok=True)
        api.add_space_variable(space_repo, "PLENO_DB_REPO", data_repo)
        api.upload_folder(repo_id=space_repo, repo_type="space", folder_path=tmp)
    print(f"Listo: https://huggingface.co/spaces/{space_repo} (tarda unos minutos en construir la primera vez)")


if __name__ == "__main__":
    main()
