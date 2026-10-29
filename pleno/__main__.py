"""python -m pleno <comando>"""

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pleno", description="Actos públicos de México, estructurados.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingerir", help="descarga y carga fuentes en data/pleno.db")
    p.add_argument("fuentes", nargs="*", help="mananeras, diputados (todas si se omite)")
    p.add_argument("--desde", help="solo documentos desde esta fecha (AAAA-MM-DD)")
    p.add_argument("--limite", type=int)
    sub.add_parser("estado", help="cuántos documentos, personas y leyes hay")
    p = sub.add_parser("descargar", help="solo baja y extrae (llena la caché) sin tocar la base; un proceso por fuente")
    p.add_argument("fuente")
    p.add_argument("--desde")
    p = sub.add_parser("actualizar", help="baja lo nuevo de todas las fuentes y revisa las alertas")
    p.add_argument("fuentes", nargs="*")
    p = sub.add_parser("programar", help="corre «actualizar» cada día (LaunchAgent de macOS)")
    p.add_argument("--hora", default="07:00", help="HH:MM (por defecto 07:00)")
    p.add_argument("--quitar", action="store_true", help="desinstala la tarea diaria")
    sub.add_parser("alertas", help="lista las alertas guardadas y cuántas coincidencias nuevas tienen")
    sub.add_parser("fuentes", help="inventario de fuentes revisadas y su estado")
    p = sub.add_parser("evaluar", help="mide la calidad de los datos y consultas, y la compara con la corrida anterior")
    p.add_argument("--con-modelo", action="store_true", help="incluye el modelo en la verificación (más lento)")
    p = sub.add_parser("verificar", help="compara una afirmación con el registro público")
    p.add_argument("afirmacion")
    p.add_argument("--sin-modelo", action="store_true")
    p = sub.add_parser("dataset", help="snapshot versionado en Parquet para venta o entrenamiento (data/dataset/)")
    p.add_argument("--version", help="etiqueta del snapshot (por defecto, la fecha de hoy)")
    sub.add_parser("abrir", help="abre Pleno en tu navegador (y te guía la primera vez)")
    p = sub.add_parser("servir", help="API + interfaz en http://127.0.0.1:8780")
    p.add_argument("--puerto", type=int, default=8780)
    args = parser.parse_args(argv)

    if args.cmd == "ingerir":
        from pleno import ingest
        ingest.run(args.fuentes or None, since=args.desde, limit=args.limite)
    elif args.cmd == "estado":
        from pleno import db, ingest
        ingest.stats(db.connect())
    elif args.cmd == "descargar":
        import time
        from pleno import ingest
        from pleno.sources import sitl
        t, n = time.time(), 0
        if args.fuente == "sitl":
            n = len(sitl.roster()) + sum(1 for _ in sitl.votes(since=args.desde))
        else:
            source = ingest.SOURCES[args.fuente]
            for doc in source.documents(since=args.desde) if args.desde else source.documents():
                n += 1
                if n % 20 == 0:
                    print(f"{args.fuente}: {n} documentos ({time.time() - t:.0f}s)", flush=True)
        print(f"{args.fuente}: listo, {n} en {time.time() - t:.0f}s", flush=True)
    elif args.cmd == "actualizar":
        from pleno import actualizar
        actualizar.actualizar(sources=args.fuentes or None)
    elif args.cmd == "programar":
        from pleno import actualizar
        hour, minute = (int(x) for x in args.hora.split(":"))
        path = actualizar.programar(hour, minute, remove=args.quitar)
        print("tarea diaria quitada" if args.quitar else f"tarea diaria a las {args.hora}: {path}")
    elif args.cmd == "evaluar":
        from pleno import evaluar
        result, previous = evaluar.run(llm=args.con_modelo)
        print(evaluar.report(result, previous))
        sys.exit(1 if result["regresiones"] else 0)
    elif args.cmd == "verificar":
        from pleno import db, verificar
        r = verificar.verify(db.connect(), args.afirmacion, use_llm=not args.sin_modelo)
        print(f"{r['etiqueta']} ({r['metodo']})\n{r['texto']}")
        for e in r.get("evidencias", []):
            h = r["fuentes"][e["n"] - 1]
            print(f"  [{e['postura']}] {h['person'] or h['speaker']}, {h['date']}: «{e['cita']}» {h['source_url']}")
        for t in r.get("apariciones", [])[:5]:
            print(f"  {t['speaker']}, {t['date']}, {t['institution']}: {t['source_url']}")
        for v in r.get("votaciones", []):
            print(f"  {v['date']} {v['sense']}: {v['source_url']}")
    elif args.cmd == "dataset":
        from pleno import dataset
        out, stats = dataset.build(version=args.version)
        for name, n in stats["filas"].items():
            print(f"  {name:<32} {n:>9,}")
        print(f"listo: {out}")
    elif args.cmd == "alertas":
        from pleno import actualizar, db
        for a in actualizar.list_alerts(db.connect()):
            print(f"{a['id']:<40} {a['nuevas']:>5} nuevas  {a['name']}")
    elif args.cmd == "fuentes":
        from pleno import db, fuentes
        for f in fuentes.registry(db.connect()):
            cov = f["cobertura"] or {}
            print(f"{f['estatus']:<13} {f['nombre']:<58} {cov.get('documentos') or '':>6} {cov.get('desde') or ''}–{cov.get('hasta') or ''}")
    elif args.cmd == "abrir":
        abrir()
    elif args.cmd == "servir":
        import uvicorn
        uvicorn.run("pleno.api:app", host="127.0.0.1", port=args.puerto)
    return 0


def abrir():
    """What the desktop shortcut runs: start Pleno on this computer and open it in the browser."""
    import socket
    import threading
    import time
    import webbrowser

    import uvicorn

    from pleno import db, instalador

    instalador.cleanup()
    port = 8780
    for candidate in range(8780, 8800):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", candidate)) != 0:
                port = candidate
                break
    first = instalador.needed(db.connect())
    if not first:
        from pleno import actualizar
        if actualizar.pendiente():
            # Off at the daily hour, or never scheduled: catch up now, in the background, while Pleno is used.
            actualizar.en_segundo_plano()
            print("  Bajando lo nuevo de las fuentes oficiales en segundo plano; puedes usar Pleno mientras.")
    url = f"http://127.0.0.1:{port}/" + ("#/instalar" if first else "")
    print("\n  Pleno está abierto en tu navegador:", url)
    print("  Deja esta ventana abierta mientras lo usas; ciérrala para apagar Pleno.\n")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run("pleno.api:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
