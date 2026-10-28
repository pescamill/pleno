"""Cámara de Diputados, Sistema de Información Legislativa (sitl.diputados.gob.mx): the official roster
(party, state, district, election principle, seat, committees) and every roll-call vote of the LXVI
Legislature with how each deputy voted.

Votes never change once published, so their pages are cached forever; rosters and period indexes are
re-read after a day. Birth dates and e-mail addresses on the profile pages are deliberately not stored.
"""

import html as htmllib
import json
import re

from pleno.normalize import title_name
from pleno.sources.base import CACHE_DIR, fetch_cached
from pleno.sources.transcript import spanish_date

NAME = "sitl"
LEGISLATURE = "LXVI"
BASE = "https://sitl.diputados.gob.mx/LXVI_leg/"
# listado_diputados_gpnp.php?tipot=N lists one parliamentary group; N is the site's own party id.
GROUPS = {14: "MORENA", 3: "PAN", 5: "PVEM", 4: "PT", 1: "PRI", 6: "MC", 9: "IND"}
# Every party id the vote summaries have used, including groups that no longer have a bench.
SITE_PARTIES = {**GROUPS, 2: "PRD"}


def summary_parties(summary, vid):
    """{site party id: acronym} as the vote's own summary labels each listing link.

    The label is the record of that day: a deputy listed under «PRD» in September 2024 stays PRD there even if the
    roster now says PRI. (The listing pages' own headings are not used: some say «Movimiento Regeneración
    Nacional» above the PVEM bench.)"""
    links = re.findall(r'listados_votacionesnplxvi\.php\?partidot=(\d+)&(?:amp;)?votaciont=' + vid + r'"[^>]*>\s*([^<]*?)\s*<',
                       summary)
    out = {}
    for pid, label in links:
        label = label.strip().upper()
        out.setdefault(pid, label if re.fullmatch(r"[A-ZÑ]{2,8}", label) else SITE_PARTIES.get(int(pid)))
    return out


def roster(delay=0.5):
    """Every current deputy with official party and constituency."""
    out = []
    for tipot, party in GROUPS.items():
        page = _get(f"listado_diputados_gpnp.php?tipot={tipot}", f"grupos/{tipot}.html", max_age=DAY, delay=delay)
        for dipt in dict.fromkeys(re.findall(r"curricula\.php\?dipt=(\d+)", page)):
            prof = _get(f"curricula.php?dipt={dipt}", f"curricula/{dipt}.html", max_age=7 * DAY, delay=delay)
            name = re.search(r"Dip\.\s*([^<]+)<", prof)
            if not name:
                continue
            ordinary = prof.split("GRUPO DE AMISTAD")[0]       # friendship groups are not committees
            committees = [_text(c).replace("\u00ad", "") for c in
                          re.findall(r"integrantes_de_comisionlxvi\.php\?comt=\d+[^>]*>(.*?)</a>", ordinary, re.S)]
            district = _field(prof, "Distrito")
            district = f"Distrito {district}" if district else None
            circ = _field(prof, "Circunscripci(?:&oacute;|ó)n")
            district = district or (f"Circunscripción {circ}" if circ else None)
            principle = _field(prof, r"Principio de elecci(?:&oacute;|ó)n")
            out.append({
                "official_id": dipt, "name": htmllib.unescape(name.group(1)).strip(), "party": party,
                "state": _field(prof, "Entidad"), "district": district, "principle": principle,
                "seat": _field(prof, "Curul"), "committees": json.dumps([c for c in committees if c], ensure_ascii=False),
                "source_url": BASE + f"curricula.php?dipt={dipt}",
            })
    return out


SENSES = {"a favor": "A favor", "en contra": "En contra", "abstencion": "Abstención", "abstención": "Abstención",
          "ausente": "Ausente", "solo asistencia": "Solo asistencia", "quorum": "Quórum"}


def votes(since=None, delay=0.5):
    """Roll-call votes: dicts with totals and `casts` [(official_id, name, party, sense)]."""
    index = _get("votaciones_por_periodonplxvi.php", "votaciones/periodos.html", max_age=DAY / 2, delay=delay)
    for pert in sorted(set(re.findall(r"votacionesxperiodonplxvi\.php\?pert=(\d+)", index)), key=int):
        period = _get(f"votacionesxperiodonplxvi.php?pert={pert}", f"votaciones/periodo-{pert}.html",
                      max_age=DAY / 2, delay=delay)
        for vid, title in dict.fromkeys(re.findall(
                r'estadistico_votacionnplxvi\.php\?votaciont=(\d+)"[^>]*>\s*\d+\s*</a>\s*</td>\s*<td[^>]*>(.*?)</td>',
                period, re.S)):
            title = _text(title)
            summary = _get(f"estadistico_votacionnplxvi.php?votaciont={vid}", f"votaciones/{vid}/resumen.html", delay=delay)
            # The vote date is written «24-Septiembre-2024»; the title may cite older dates in prose, so only
            # that form counts.
            stamp = re.search(r"(\d{1,2})-([A-Za-zé]+)-(\d{4})", _text(summary))
            when = spanish_date(f"{stamp[1]} de {stamp[2]} de {stamp[3]}") if stamp else None
            if since and when and when < since:
                continue
            casts = []
            parties = summary_parties(summary, vid)
            for partidot in dict.fromkeys(re.findall(r"listados_votacionesnplxvi\.php\?partidot=(\d+)&(?:amp;)?votaciont=" + vid, summary)):
                listing = _get(f"listados_votacionesnplxvi.php?partidot={partidot}&votaciont={vid}",
                               f"votaciones/{vid}/{partidot}.html", delay=delay)
                party = parties.get(partidot) or SITE_PARTIES.get(int(partidot))
                for iddipt, name, sense in re.findall(
                        r"iddipt=(\d+)[^>]*>([^<]+)</a>.*?<span[^>]*>\s*([^<]+?)\s*</span>\s*</td>\s*</tr>", listing, re.S):
                    casts.append((iddipt, title_name(htmllib.unescape(name).strip()), party,
                                  SENSES.get(sense.strip().lower(), sense.strip())))
            total = {s: sum(1 for c in casts if c[3] == s) for s in ("A favor", "En contra", "Abstención", "Ausente")}
            yield {"id": f"diputados:{LEGISLATURE.lower()}:{vid}", "date": when, "title": title, "casts": casts,
                   "source_url": BASE + f"estadistico_votacionnplxvi.php?votaciont={vid}", **total,
                   "otros": len(casts) - sum(total.values())}
