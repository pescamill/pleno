"""Real figures for the promo reel, read from the database: nothing in the reel is invented.

    .venv/bin/python promo/datos.py   → promo/datos.js (window.DATA)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pleno import db, estadistica, nlq, search, verificar  # noqa: E402

OUT = Path(__file__).with_name("datos.js")
QUESTION = "¿Qué dijo la presidenta sobre el agua en 2025?"
QUOTE_START = "La única concesión de agua que no paga derechos"
CLAIM_VOTE = "Kenia López Rabadán votó en contra de la reforma judicial"
CLAIM_FIGURE = "Bajaron los homicidios en 2025"


def main():
    con = db.connect()
    q, _ = nlq.interpret(QUESTION, db.DB_FILE)
    total = search.search(con, q)["total"]
    row = con.execute("SELECT t.text, d.date FROM turns t JOIN documents d ON d.id = t.document_id "
                      "WHERE t.text LIKE ? LIMIT 1", (f"%{QUOTE_START}%",)).fetchone()
    start = row["text"].index(QUOTE_START)
    quote = row["text"][start:row["text"].index(".", start) + 1]

    vote_check = verificar.verify(con, CLAIM_VOTE, use_llm=False)
    first = vote_check["votaciones"][0]
    vote = search.vote(con, first["id"])
    parties = [{"partido": p, **senses} for p, senses in vote["por_partido"].items()
               if p in ("MORENA", "PVEM", "PT", "PAN", "PRI", "MC")]

    fig = estadistica.check_claim(con, CLAIM_FIGURE, nlq.interpret(CLAIM_FIGURE, db.DB_FILE)[0])
    states = con.execute("SELECT COUNT(DISTINCT institution_id) FROM documents WHERE institution_id LIKE 'congreso-%'").fetchone()[0]
    prosecutors = con.execute("SELECT COUNT(DISTINCT institution_id) FROM documents WHERE institution_id LIKE 'fiscalia-%' "
                              "OR institution_id = 'fgjcdmx'").fetchone()[0]
    data = {
        "pregunta": QUESTION, "resultados": total,
        "cita": {"texto": quote, "fecha": row["date"], "persona": "Claudia Sheinbaum Pardo", "cargo": "Presidenta de México"},
        "voto": {"afirmacion": CLAIM_VOTE, "etiqueta": vote_check["etiqueta"], "fecha": first["date"],
                 "sentido": first["sense"], "a_favor": vote["votacion"]["a_favor"], "en_contra": vote["votacion"]["en_contra"],
                 "ausente": vote["votacion"]["ausente"], "partidos": parties},
        "cifra": {"afirmacion": CLAIM_FIGURE, "anio": fig["comparacion"]["anio"], "valor": fig["comparacion"]["valor"],
                  "anterior": fig["comparacion"]["anio_anterior"], "cambio": fig["comparacion"]["cambio_pct"]},
        "documentos": con.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "intervenciones": con.execute("SELECT COUNT(*) FROM turns").fetchone()[0],
        "congresos": states, "fiscalias": prosecutors,
    }
    OUT.write_text("window.DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
