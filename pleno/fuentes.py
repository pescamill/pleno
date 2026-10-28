"""Inventory of every public source reviewed, integrated or not, and why.

Checked by hand on 26–27 Oct 2026: robots.txt, whether transcripts exist, and whether their PDFs carry
text. This is what the «Fuentes» page shows, so anyone can see what Pleno covers and what it does not.

status: integrada · pendiente (allowed, needs work) · bloqueada (robots.txt forbids it) ·
        sin publicar (not online in usable form; requested via transparency) · caída (site down when checked)
"""

INTEGRADA, PENDIENTE, BLOQUEADA, SIN_PUBLICAR, CAIDA = "integrada", "pendiente", "bloqueada", "sin publicar", "caída"

REGISTRY = [
    # Federal
    {"id": "mananeras", "nombre": "Conferencias matutinas de Presidencia", "nivel": "federal", "estado": None,
     "tipo": "ejecutivo", "estatus": INTEGRADA, "url": "https://huggingface.co/datasets/feregrino/mananeras",
     "formato": "Texto (dataset CC BY-SA 4.0)", "nota": "gob.mx bloquea bots; se usa el dataset abierto que lo replica."},
    {"id": "diputados", "nombre": "Cámara de Diputados: versiones estenográficas", "nivel": "federal", "estado": None,
     "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://cronica.diputados.gob.mx", "formato": "HTML"},
    {"id": "sitl", "nombre": "Cámara de Diputados: padrón oficial y votaciones nominales", "nivel": "federal",
     "estado": None, "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://sitl.diputados.gob.mx/LXVI_leg/",
     "formato": "HTML", "nota": "Partido, distrito, curul, comisiones y el sentido de cada voto."},
    {"id": "leyes-federales", "nombre": "Catálogo de leyes federales vigentes", "nivel": "federal", "estado": None,
     "tipo": "catálogo", "estatus": INTEGRADA, "url": "https://www.diputados.gob.mx/LeyesBiblio/",
     "formato": "HTML + PDF", "nota": "Estandariza los nombres de ley y enlaza al texto oficial."},
    {"id": "scjn", "nombre": "Suprema Corte: versiones taquigráficas del Pleno", "nivel": "federal", "estado": None,
     "tipo": "judicial", "estatus": INTEGRADA, "url": "https://www.scjn.gob.mx/multimedia/versiones-taquigraficas",
     "formato": "PDF con texto"},
    {"id": "fgr", "nombre": "Fiscalía General de la República: comunicados", "nivel": "federal", "estado": None,
     "tipo": "procuración", "estatus": INTEGRADA, "url": "https://fgr.org.mx/en/FGR/Prensa", "formato": "HTML",
     "nota": "Detenciones, vinculaciones a proceso, sentencias y extradiciones. Los nombres se guardan como los "
             "publica la FGR («José “N”»); no se completan ni se crean perfiles de personas detenidas."},
    {"id": "sesnsp", "nombre": "SESNSP: incidencia delictiva por estado (datos abiertos)", "nivel": "federal", "estado": None,
     "tipo": "estadística", "estatus": INTEGRADA,
     "url": "https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva",
     "formato": "CSV en ZIP (enlaces públicos de SharePoint)",
     "nota": "Delitos y víctimas por estado y mes, 2015 a la fecha. Sirve para cotejar afirmaciones como «bajaron los "
             "homicidios». En 2026 cambió la metodología; las comparaciones que la cruzan lo advierten."},
    {"id": "fgr-historico", "nombre": "FGR: archivo de prensa en gob.mx (hasta 2023)", "nivel": "federal", "estado": None,
     "tipo": "procuración", "estatus": PENDIENTE, "url": "https://www.gob.mx/fgr/es/archivo/prensa", "formato": "HTML",
     "nota": "robots.txt no lo restringe, pero gob.mx respondió 500 a la consulta automatizada al revisarlo de nuevo "
             "(27 oct 2026), como con las mañaneras. Comunicados anteriores a 2023."},
    {"id": "fgjcdmx", "nombre": "Fiscalía de la Ciudad de México: comunicados", "nivel": "estatal",
     "estado": "Ciudad de México", "tipo": "procuración", "estatus": INTEGRADA,
     "url": "https://www.fgjcdmx.gob.mx/comunicacion/tipo/boletin", "formato": "HTML",
     "nota": "Boletines, tarjetas informativas y discursos de la fiscal general desde 2025. Nombres como los publica "
             "la Fiscalía («Atzin “N”»); no se completan ni se crean perfiles de personas detenidas."},
    {"id": "carpetas-cdmx", "nombre": "Carpetas de investigación FGJ CDMX (datos abiertos)", "nivel": "estatal",
     "estado": "Ciudad de México", "tipo": "estadística", "estatus": PENDIENTE,
     "url": "https://datos.cdmx.gob.mx/dataset/carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico",
     "formato": "CSV por año (2016–2024)",
     "nota": "Registros anonimizados: delito, fecha, alcaldía, colonia, coordenadas. Los CSV se descargan sin "
             "restricción de archivo.datos.cdmx.gob.mx (la API del portal está vedada por su robots.txt). El último "
             "archivo es de agosto de 2024; 2025 y 2026 no están publicados. Falta una tabla propia por alcaldía: la de "
             "incidencia del SESNSP se reemplaza completa en cada carga."},
    {"id": "fiscalia-jalisco", "nombre": "Fiscalía del Estado de Jalisco: boletines de prensa", "nivel": "estatal",
     "estado": "Jalisco", "tipo": "procuración", "estatus": INTEGRADA,
     "url": "https://fiscalia.jalisco.gob.mx/comunicacion-social/boletines-de-prensa/",
     "formato": "JSON (API del portal)",
     "nota": "Sin robots.txt. Boletines desde 2025 leídos de la API del propio portal. Nombres como los publica la "
             "Fiscalía; no se completan ni se crean perfiles de personas detenidas."},
    {"id": "fiscalia-edomex", "nombre": "Fiscalía del Estado de México", "nivel": "estatal", "estado": "Estado de México",
     "tipo": "procuración", "estatus": CAIDA, "url": "https://fgjem.edomex.gob.mx", "formato": "—",
     "nota": "No respondió (tiempo de espera agotado) el 27 de octubre de 2026, ni la portada ni robots.txt; reintentar."},
    {"id": "fiscalia-guerrero", "nombre": "Fiscalía del Estado de Guerrero: noticias", "nivel": "estatal",
     "estado": "Guerrero", "tipo": "procuración", "estatus": INTEGRADA,
     "url": "https://fiscaliaguerrero.gob.mx", "formato": "JSON (WordPress)",
     "nota": "Solo la categoría NOTICIAS (desde febrero de 2026). Se dejan fuera a propósito Alerta Amber, «¿Has visto "
             "a…?» y Protocolo Alba: son fichas de personas desaparecidas, a menudo menores."},
    {"id": "fiscalia-nl", "nombre": "Fiscalía de Nuevo León", "nivel": "estatal", "estado": "Nuevo León",
     "tipo": "procuración", "estatus": BLOQUEADA, "url": "https://fiscalianl.gob.mx", "formato": "—",
     "nota": "robots.txt prohíbe bots y el sitio tiene reto anti-bot. Solicitud por transparencia."},
    {"id": "senado", "nombre": "Senado de la República", "nivel": "federal", "estado": None, "tipo": "legislativo",
     "estatus": BLOQUEADA, "url": "https://www.senado.gob.mx", "formato": "—",
     "nota": "robots.txt prohíbe bots. Solicitud por la Plataforma Nacional de Transparencia."},
    {"id": "ine", "nombre": "INE: Consejo General", "nivel": "federal", "estado": None, "tipo": "autónomo",
     "estatus": PENDIENTE, "url": "https://www.ine.mx", "formato": "PDF (Gaceta Electoral)",
     "nota": "robots.txt lo permite; falta localizar las versiones estenográficas de las sesiones."},
    {"id": "dof", "nombre": "Diario Oficial de la Federación", "nivel": "federal", "estado": None, "tipo": "catálogo",
     "estatus": BLOQUEADA, "url": "https://dof.gob.mx", "formato": "HTML",
     "nota": "El certificado solo vale sin «www». Su robots.txt prohíbe /nota_detalle.php, donde se publica cada nota. "
             "Solicitud por transparencia (o datos abiertos de SIDOF, por revisar)."},
    # States with transcripts integrated
    {"id": "cdmx", "nombre": "Congreso de la Ciudad de México", "nivel": "estatal", "estado": "Ciudad de México",
     "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://www.congresocdmx.gob.mx/diario-los-debates-207-4.html",
     "formato": "PDF con texto (Diario de los Debates)"},
    {"id": "oaxaca", "nombre": "Congreso de Oaxaca", "nivel": "estatal", "estado": "Oaxaca", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.congresooaxaca.gob.mx/version_estenografs.html",
     "formato": "PDF con texto (versiones estenográficas)", "nota": "También hay versiones de la LXIV (2018–2021)."},
    {"id": "qroo", "nombre": "Congreso de Quintana Roo", "nivel": "estatal", "estado": "Quintana Roo",
     "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://www.congresoqroo.gob.mx/sesiones/",
     "formato": "PDF con texto (versiones estenográficas)"},
    {"id": "tabasco", "nombre": "Congreso de Tabasco", "nivel": "estatal", "estado": "Tabasco", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://congresotabasco.gob.mx/diario-de-debates/", "formato": "PDF con texto (narrado)"},
    {"id": "nl", "nombre": "Congreso de Nuevo León", "nivel": "estatal", "estado": "Nuevo León", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.hcnl.gob.mx/trabajo_legislativo/diario_debates.php",
     "formato": "PDF con texto (narrado)", "nota": "Archivo desde 2006 (2,127 sesiones); se carga la LXXVII. "
     "Publica también votaciones por sesión (pendiente)."},
    {"id": "guerrero", "nombre": "Congreso de Guerrero", "nivel": "estatal", "estado": "Guerrero", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://congresogro.gob.mx/64/sesiones/debates.php", "formato": "PDF con texto",
     "nota": "Su padrón por partido da el partido oficial de cada diputada y diputado."},
    {"id": "veracruz", "nombre": "Congreso de Veracruz", "nivel": "estatal", "estado": "Veracruz", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.legisver.gob.mx/Inicio.php?p=sesiones",
     "formato": "PDF con texto (versiones estenográficas)",
     "nota": "Una versión por sesión de la LXVII; también publica el Diario de los Debates mensual."},
    {"id": "edomex", "nombre": "Congreso del Estado de México", "nivel": "estatal", "estado": "Estado de México",
     "tipo": "legislativo", "estatus": INTEGRADA,
     "url": "https://legislacion.congresoedomex.gob.mx/asuntosparlamentarios/debates", "formato": "PDF con texto (Diario de Debates)",
     "nota": "Tomos en secretariadeasuntosparlamentarios.gob.mx (sin robots.txt). Se publican con meses de rezago: "
             "al revisarlo llegaban a enero de 2026."},
    {"id": "guanajuato", "nombre": "Congreso de Guanajuato", "nivel": "estatal", "estado": "Guanajuato",
     "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://www.congresogto.gob.mx/trabajos_legislativos",
     "formato": "PDF con texto (Diario de los Debates)",
     "nota": "Los PDF están en congreso-gto.s3.amazonaws.com; el /uploads que prohíbe el robots.txt es el del sitio "
             "principal. Las versiones preliminares no traen los oradores y se cargan al publicarse la final."},
    {"id": "coahuila", "nombre": "Congreso de Coahuila", "nivel": "estatal", "estado": "Coahuila", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.congresocoahuila.gob.mx/coahuila/congreso/debates.aspx",
     "formato": "PDF con texto (Diario de los Debates)", "nota": "Sin robots.txt. LXIII Legislatura (2024–2026)."},
    {"id": "sinaloa", "nombre": "Congreso de Sinaloa", "nivel": "estatal", "estado": "Sinaloa", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.congresosinaloa.gob.mx/debates/", "formato": "PDF con texto (narrado)",
     "nota": "Índice de la Gaceta (gaceta.congresosinaloa.gob.mx), sin robots.txt."},
    {"id": "tamaulipas", "nombre": "Congreso de Tamaulipas", "nivel": "estatal", "estado": "Tamaulipas",
     "tipo": "legislativo", "estatus": INTEGRADA,
     "url": "https://www.congresotamaulipas.gob.mx/TrabajoLegislativo/VersionesEstenograficasSesiones/"
            "VersionesEstenograficasSesiones.asp", "formato": "PDF con texto (versiones estenográficas)",
     "nota": "Su robots.txt solo trae las señales de contenido de Cloudflare, sin reglas ni restricciones."},
    {"id": "yucatan", "nombre": "Congreso de Yucatán", "nivel": "estatal", "estado": "Yucatán", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://www.congresoyucatan.gob.mx/gaceta/diario-debates",
     "formato": "PDF con texto (narrado)",
     "nota": "Las sesiones de la Diputación Permanente sin intervenciones no generan documento."},
    {"id": "zacatecas", "nombre": "Congreso de Zacatecas", "nivel": "estatal", "estado": "Zacatecas",
     "tipo": "legislativo", "estatus": INTEGRADA, "url": "https://www.congresozac.gob.mx/65/v4168",
     "formato": "PDF con texto (actas con las discusiones)",
     "nota": "Las actas nombran a quien habla solo por sus apellidos («EL DIP. NOVELLA MACÍAS»)."},
    {"id": "durango", "nombre": "Congreso de Durango", "nivel": "estatal", "estado": "Durango", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://congresodurango.gob.mx/actas-lxx-legislatura/",
     "formato": "PDF con texto (actas con las intervenciones)"},
    {"id": "colima", "nombre": "Congreso de Colima", "nivel": "estatal", "estado": "Colima", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://congresocol.gob.mx/web/www/gaceta/index.php",
     "formato": "PDF con texto (Diario de los Debates)", "nota": "Sin robots.txt. LXI Legislatura (2024–2027)."},
    {"id": "bcs", "nombre": "Congreso de Baja California Sur", "nivel": "estatal", "estado": "Baja California Sur",
     "tipo": "legislativo", "estatus": INTEGRADA,
     "url": "https://www.cbcs.gob.mx/index.php/trabajos-legislativos/diarios-debates-cbcs",
     "formato": "PDF con texto (Diario de los Debates)",
     "nota": "Sin robots.txt. Publicado de agosto de 2024 a marzo de 2025; algunos enlaces dan 404."},
    # States pending
    {"id": "jalisco", "nombre": "Congreso de Jalisco", "nivel": "estatal", "estado": "Jalisco", "tipo": "legislativo",
     "estatus": SIN_PUBLICAR, "url": "https://infolej.congresojal.gob.mx/consulta/DiarioDeDebates.php",
     "formato": "—", "nota": "La consulta del Diario de los Debates no devuelve documentos y la Gaceta solo publica la "
     "agenda. Solicitud por transparencia."},
    {"id": "bc", "nombre": "Congreso de Baja California", "nivel": "estatal", "estado": "Baja California",
     "tipo": "legislativo", "estatus": PENDIENTE, "url": "https://www.congresobc.gob.mx/TrabajoLegislativo/ActasSesiones",
     "formato": "PDF escaneado", "nota": "Requiere OCR."},
    {"id": "aguascalientes", "nombre": "Congreso de Aguascalientes", "nivel": "estatal", "estado": "Aguascalientes",
     "tipo": "legislativo", "estatus": PENDIENTE,
     "url": "https://congresoags.gob.mx/agenda_legislativa/versiones_estenograficas", "formato": "PDF escaneado",
     "nota": "Sin robots.txt. Publica 143 versiones estenográficas de la LXVI (índice en /LegislativeAgenda/GetPagedData), "
             "pero son imágenes sin texto. Requiere OCR."},
    {"id": "chiapas", "nombre": "Congreso de Chiapas", "nivel": "estatal", "estado": "Chiapas", "tipo": "legislativo",
     "estatus": INTEGRADA, "url": "https://web.congresochiapas.gob.mx/trabajo-legislativo/diario-de-debates-versiones-estenograficas",
     "formato": "PDF con texto (actas narradas)",
     "nota": "robots.txt lo permite. Las actas narran las intervenciones; el nombre de quien habla se toma del anuncio "
             "de la Presidencia («TIENE EL USO DE LA PALABRA LA DIPUTADA X»). Cobertura parcial de oradores."},
    {"id": "sonora", "nombre": "Congreso de Sonora", "nivel": "estatal", "estado": "Sonora", "tipo": "legislativo",
     "estatus": SIN_PUBLICAR, "url": "https://congresoson.gob.mx/gacetas", "formato": "—",
     "nota": "Solo publica la Gaceta Parlamentaria (orden del día y documentos), no versiones estenográficas ni Diario "
             "de los Debates. Solicitud por transparencia."},
    {"id": "hidalgo", "nombre": "Congreso de Hidalgo", "nivel": "estatal", "estado": "Hidalgo", "tipo": "legislativo",
     "estatus": SIN_PUBLICAR, "url": "https://congresohidalgo.gob.mx/acervo/public/view-gaceta", "formato": "PDF escaneado (actas)",
     "nota": "La Gaceta trae actas escaneadas (sin texto) y videos; no publica versiones estenográficas. Solicitud por "
             "transparencia."},
    {"id": "tlaxcala", "nombre": "Congreso de Tlaxcala", "nivel": "estatal", "estado": "Tlaxcala", "tipo": "legislativo",
     "estatus": SIN_PUBLICAR, "url": "https://congresodetlaxcala.gob.mx/sesiones-congreso/", "formato": "PDF escaneado (actas)",
     "nota": "Publica convocatorias, listas de asistencia y actas escaneadas; no versiones estenográficas. Solicitud por "
             "transparencia."},
    {"id": "nayarit", "nombre": "Congreso de Nayarit", "nivel": "estatal", "estado": "Nayarit", "tipo": "legislativo",
     "estatus": SIN_PUBLICAR, "url": "https://procesolegislativo.congresonayarit.gob.mx/sesiones-del-congreso/",
     "formato": "—",
     "nota": "La tabla de sesiones (con su Diario de los Debates) se sirve desde utics.congresonayarit.gob.mx, que "
             "responde 401 (exige iniciar sesión). Solicitud por transparencia."},
    {"id": "slp", "nombre": "Congreso de San Luis Potosí", "nivel": "estatal", "estado": "San Luis Potosí",
     "tipo": "legislativo", "estatus": BLOQUEADA, "url": "https://congresosanluis.gob.mx", "formato": "—",
     "nota": "robots.txt lo permite (con Crawl-delay de 10 s), pero el sitio pone un reto anti-bot (Sucuri) antes de "
             "cualquier página. No se evade. Solicitud por transparencia."},
    {"id": "campeche", "nombre": "Congreso de Campeche", "nivel": "estatal", "estado": "Campeche", "tipo": "legislativo",
     "estatus": BLOQUEADA, "url": "https://www.congresocam.gob.mx", "formato": "PDF",
     "nota": "robots.txt prohíbe bots. Solicitud por transparencia."},
    {"id": "chihuahua", "nombre": "Congreso de Chihuahua", "nivel": "estatal", "estado": "Chihuahua",
     "tipo": "legislativo", "estatus": BLOQUEADA, "url": "https://www.congresochihuahua.gob.mx", "formato": "—",
     "nota": "robots.txt prohíbe bots. Solicitud por transparencia."},
    {"id": "puebla", "nombre": "Congreso de Puebla", "nivel": "estatal", "estado": "Puebla", "tipo": "legislativo",
     "estatus": BLOQUEADA, "url": "https://www.congresopuebla.gob.mx", "formato": "—",
     "nota": "robots.txt prohíbe bots y el sitio responde 403. Solicitud por transparencia."},
    *[{"id": key, "nombre": f"Congreso de {state}", "nivel": "estatal", "estado": state, "tipo": "legislativo",
       "estatus": CAIDA, "url": url, "formato": "—", "nota": "No respondió al revisarlo; reintentar."}
      for key, state, url in [
          ("michoacan", "Michoacán", "https://congresomich.gob.mx"),
          ("queretaro", "Querétaro", "https://www.legislaturaqueretaro.gob.mx"),
          ("morelos", "Morelos", "https://congresomorelos.gob.mx")]],
    # Municipal
    {"id": "guadalajara", "nombre": "Ayuntamiento de Guadalajara (cabildo)", "nivel": "municipal", "estado": "Jalisco",
     "tipo": "municipal", "estatus": PENDIENTE, "url": "https://transparencia.guadalajara.gob.mx", "formato": "Actas",
     "nota": "El portal de transparencia volvió a responder el 27 oct 2026 (robots.txt lo permite); falta localizar "
             "las actas de cabildo."},
    {"id": "zapopan", "nombre": "Ayuntamiento de Zapopan", "nivel": "municipal", "estado": "Jalisco", "tipo": "municipal",
     "estatus": PENDIENTE, "url": "https://gobierno.zapopan.gob.mx/agenda-edilicia/", "formato": "Agenda + datos abiertos"},
    {"id": "monterrey", "nombre": "Ayuntamiento de Monterrey", "nivel": "municipal", "estado": "Nuevo León",
     "tipo": "municipal", "estatus": PENDIENTE, "url": "https://www.monterrey.gob.mx/transparencia/Sesiones/sesiones.asp",
     "formato": "Actas de cabildo"},
]


def registry(con):
    """The inventory plus live coverage (documents, dates, last run) for integrated sources."""
    coverage = {r["institution_id"]: dict(r) for r in con.execute(
        "SELECT institution_id, COUNT(*) AS documentos, MIN(date) AS desde, MAX(date) AS hasta FROM documents GROUP BY 1")}
    runs = {r["source"]: dict(r) for r in con.execute(
        "SELECT source, MAX(started) AS ultima, finished, new, error FROM runs GROUP BY source")}
    inst_of = {"mananeras": "presidencia", "diputados": "diputados", "scjn": "scjn", "fgr": "fgr", "fgjcdmx": "fgjcdmx",
               "fiscalia-jalisco": "fiscalia-jalisco", "fiscalia-guerrero": "fiscalia-guerrero"}
    out = []
    for item in REGISTRY:
        row = dict(item)
        inst = inst_of.get(item["id"], f"congreso-{item['id']}")
        row["cobertura"] = coverage.get(inst)
        row["ultima_corrida"] = runs.get(item["id"])
        if item["id"] == "sesnsp":
            row["cobertura"] = dict(con.execute(
                "SELECT COUNT(*) AS documentos, MIN(printf('%04d-%02d-01', year, month)) AS desde, "
                "MAX(printf('%04d-%02d-01', year, month)) AS hasta FROM crime_stats").fetchone())
        if item["id"] == "sitl":
            row["cobertura"] = dict(con.execute(
                "SELECT COUNT(*) AS documentos, MIN(date) AS desde, MAX(date) AS hasta FROM votes").fetchone())
        out.append(row)
    return out
