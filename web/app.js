"use strict";

/* Pleno web: a small hash-routed app over the v1 API.
   Routes: #/  ·  #/buscar?…  ·  #/persona/<id>  ·  #/ley/<id>  ·  #/documento/<id>?t=<turno>&q=<texto> */

const API = "/api/v1";
const EXAMPLES = [
  "¿Qué dijo la presidenta sobre el agua en 2025?",
  "Diputados de Movimiento Ciudadano que mencionan la Ley de Amparo",
  "¿Quién habla del Infonavit?",
  "Reforma judicial en la Cámara de Diputados en 2024",
  "Omar García Harfuch sobre extorsión",
];
const KINDS = {
  texto: { label: "Texto", param: "texto" },
  instituciones: { label: "Institución", param: "inst" },
  estados: { label: "Estado", param: "estado" },
  personas: { label: "Persona", param: "persona" },
  partidos: { label: "Partido", param: "partido" },
  cargos: { label: "Cargo", param: "cargo" },
  leyes: { label: "Ley", param: "ley" },
  medios: { label: "Medio", param: "medio" },
};
const PRESIDENCY = "presidencia de mexico";
const ROLE_PRESETS = [
  [PRESIDENCY, "Presidencia de México"], ["secretari", "Secretarios y secretarias"], ["diputad", "Diputados y diputadas"],
  ["gobernador", "Gobernadores"], ["periodista", "Periodistas"], ["presidenta de la mesa", "Mesa Directiva"],
];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MONTHS_LONG = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
  "noviembre", "diciembre"];
const STOP = new Set("de del la las los el en y a que con por para una uno sobre como mas pero sus ese esa este esta".split(" "));

const state = { labels: {}, search: null, doc: null };
const turns = new Map();          // turn id → turn, for «copiar cita» and citation previews
let routeSeq = 0, visited = 0;   // visited: in-app pages seen, so «Volver» never leaves the site

/* ---------- helpers ---------- */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = n => Number(n || 0).toLocaleString("es-MX");
const compact = n => n >= 1e6 ? `${+(n / 1e6).toFixed(1)} M` : n >= 1e4 ? `${Math.round(n / 1e3)} k` : n >= 1e3 ? `${+(n / 1e3).toFixed(1)} k` : `${+n.toFixed(1)}`;
const fold = s => String(s || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
const marked = s => esc(s).replace(/⟦/g, "<mark>").replace(/⟧/g, "</mark>");
const plain = s => String(s || "").replace(/[⟦⟧]/g, "");
const pct = (n, total) => total ? Math.round((n / total) * 100) : 0;

function fmtDate(iso, long = false) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return long ? `${d} de ${MONTHS_LONG[m - 1]} de ${y}` : `${d} ${MONTHS[m - 1]} ${y}`;
}
const fmtMonth = ym => { const [y, m] = ym.split("-").map(Number); return `${MONTHS[m - 1]} ${y}`; };

function monthRange(a, b) {
  const out = [];
  let [y, m] = a.split("-").map(Number);
  const [by, bm] = b.split("-").map(Number);
  while (y < by || (y === by && m <= bm)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    if (++m > 12) { m = 1; y++; }
  }
  return out;
}
const monthEnd = ym => { const [y, m] = ym.split("-").map(Number); return `${ym}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`; };
const addMonths = (ym, k) => { const [y, m] = ym.split("-").map(Number); const t = y * 12 + (m - 1) + k; return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`; };
const addDays = (iso, k) => { const t = new Date(`${iso}T12:00:00Z`); t.setUTCDate(t.getUTCDate() + k); return t.toISOString().slice(0, 10); };

function initials(name) {
  const words = String(name || "").split(/\s+/).filter(w => /^\p{Lu}/u.test(w));
  if (!words.length) return "·";
  const last = words.length >= 3 ? words[words.length - 2] : words[words.length - 1];
  return (words[0][0] + (words.length > 1 ? last[0] : "")).toUpperCase();
}

const cleanTitle = (t, date) => {
  let s = String(t || "").replace(/^Versi[oó]n estenogr[aá]fica[.:]?\s*(de la\s+)?/i, "").trim();
  if (date && /\s(del?|al)$/i.test(s)) s += ` ${fmtDate(date, true)}`;   // some source titles stop at «…vespertina del»
  return s ? s[0].toUpperCase() + s.slice(1) : "Documento";
};

async function call(path, body) {
  const res = await fetch(API + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    const err = new Error(res.status === 429 ? (detail || "Demasiadas consultas; espera un minuto.")
      : res.status === 404 ? "No encontramos esa página." : (typeof detail === "string" ? detail : "Algo falló al consultar la API."));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

let optionsPromise, optionsCache = null;
function options() {
  optionsPromise ||= call("/estado").then(o => { if (o.publico) document.body.dataset.publico = "1"; return (optionsCache = o); }).catch(e => { optionsPromise = null; throw e; });
  return optionsPromise;
}
const instName = id => optionsCache?.instituciones.find(i => i.id === id)?.nombre || id;

/* ---------- icons and small components ---------- */

const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  back: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  doc: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"/>',
  filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  scale: '<path d="M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0Zm12 0-3 7a3 3 0 0 0 6 0Z"/>',
  building: '<path d="M3 21h18M5 21V10M19 21V10M9 21v-6h6v6M2 10l10-6 10 6"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4Z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  rss: '<path d="M5 11a8 8 0 0 1 8 8M5 5a14 14 0 0 1 14 14"/><circle cx="6" cy="18" r="1.5"/>',
  vote: '<path d="M4 13h16v7H4zM8 13l3-9 6 2-2 7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  check: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
};
const icon = (name, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

function logoMark() {
  // A hemicycle: the seats of a plenary hall.
  const rows = [[7, 5], [10.5, 7], [14, 9]];
  let dots = "";
  for (const [r, n] of rows) {
    for (let i = 0; i < n; i++) {
      const a = Math.PI - (i / (n - 1)) * Math.PI;
      dots += `<circle cx="${(16 + r * Math.cos(a)).toFixed(2)}" cy="${(19 - r * Math.sin(a)).toFixed(2)}" r="1.45"/>`;
    }
  }
  return `<svg viewBox="0 0 32 22">${dots}<rect x="12.5" y="17" width="7" height="3" rx="1.5"/></svg>`;
}

function avatar(name, party, cls = "") {
  const style = party ? ` style="--c: var(--p-${esc(party)}, var(--p-none))"` : "";
  return `<span class="avatar ${cls}${party ? " has-party" : ""}"${style} aria-hidden="true">${esc(initials(name))}</span>`;
}
const pill = p => p ? `<span class="pill" style="--c: var(--p-${esc(p)}, var(--p-none))"><i></i>${esc(p)}</span>` : "";
const instLevel = id => {
  const i = optionsCache?.instituciones.find(x => x.id === id);
  return i ? (["judicial", "procuración"].includes(i.tipo) ? i.tipo : i.nivel) : "";
};
const instTag = (id, name) => `<span class="inst" data-inst="${esc(id)}" data-level="${esc(instLevel(id))}"><i></i>${esc(name || instName(id))}</span>`;
const SENSE_ORDER = ["A favor", "En contra", "Abstención", "Ausente"];
const senseKey = s => ({ "A favor": "favor", "En contra": "contra", "Abstención": "abst", "Ausente": "aus" }[s] || "otro");

/** Roll-call result as one stacked bar; the legend carries the numbers, so colour is never the only cue. */
function voteBar(counts, { legend = true } = {}) {
  const rows = SENSE_ORDER.map(k => [k, counts[k] || 0]).concat([["Otros", Object.entries(counts).filter(([k]) => !SENSE_ORDER.includes(k)).reduce((a, [, n]) => a + n, 0)]]).filter(([, n]) => n);
  const total = rows.reduce((a, [, n]) => a + n, 0) || 1;
  return `<div class="stack vote-stack" role="img" aria-label="${esc(rows.map(([k, n]) => `${k}: ${n}`).join(", "))}">
    ${rows.map(([k, n]) => `<span class="seg v-${senseKey(k)}" style="flex:${n}" data-tip="<b>${k}</b><span>${num(n)} · ${pct(n, total)}%</span>"></span>`).join("")}</div>
    ${legend ? `<div class="vote-legend">${rows.map(([k, n]) => `<span><i class="v-${senseKey(k)}"></i>${k} <b>${num(n)}</b></span>`).join("")}</div>` : ""}`;
}

function labelFor(key, value) {
  if (key === "instituciones") return instName(value);
  if (key === "estados") return value;
  if (key === "cargos") return ROLE_PRESETS.find(([v]) => v === value)?.[1] || value;
  return state.labels[value] || value;
}

function dateRangeLabel(desde, hasta) {
  if (desde && hasta) {
    if (desde.endsWith("-01-01") && hasta.endsWith("-12-31") && desde.slice(0, 4) === hasta.slice(0, 4)) return desde.slice(0, 4);
    if (desde.endsWith("-01") && hasta === monthEnd(hasta.slice(0, 7))) {
      return desde.slice(0, 7) === hasta.slice(0, 7) ? fmtMonth(desde.slice(0, 7)) : `${fmtMonth(desde.slice(0, 7))} – ${fmtMonth(hasta.slice(0, 7))}`;
    }
    return `${fmtDate(desde)} – ${fmtDate(hasta)}`;
  }
  return desde ? `desde ${fmtDate(desde)}` : `hasta ${fmtDate(hasta)}`;
}

/* ---------- query <-> URL ---------- */

function emptyQuery() {
  return { texto: "", instituciones: [], estados: [], personas: [], partidos: [], cargos: [], leyes: [], medios: [], desde: "", hasta: "", orden: "relevancia", limite: 20, pagina: 1 };
}

function paramsToQuery(params) {
  const q = emptyQuery();
  for (const [key, k] of Object.entries(KINDS)) {
    if (key === "texto") q.texto = params.get("texto") || "";
    else q[key] = params.getAll(k.param);
  }
  q.desde = params.get("desde") || "";
  q.hasta = params.get("hasta") || "";
  q.orden = params.get("orden") === "fecha" ? "fecha" : "relevancia";
  return q;
}

function searchHash(q, question = "") {
  const p = new URLSearchParams();
  if (question) p.set("p", question);
  for (const [key, k] of Object.entries(KINDS)) {
    if (key === "texto") { if (q.texto) p.set("texto", q.texto); }
    else (q[key] || []).forEach(v => p.append(k.param, v));
  }
  if (q.desde) p.set("desde", q.desde);
  if (q.hasta) p.set("hasta", q.hasta);
  if (q.orden === "fecha") p.set("orden", "fecha");
  return `#/buscar?${p}`;
}

const queryWith = (patch) => ({ ...emptyQuery(), ...patch });
const docHash = (docId, turnId, text) => `#/documento/${encodeURIComponent(docId)}${turnId || text ? "?" : ""}${new URLSearchParams({ ...(turnId ? { t: turnId } : {}), ...(text ? { q: text } : {}) })}`;

/** Change the current search. Narrowing keeps the original question; removing a filter drops it. */
function editQuery(fn, keepQuestion = true) {
  const s = state.search;
  const q = structuredClone(s.q);
  fn(q);
  q.pagina = 1;
  location.hash = searchHash(q, keepQuestion ? s.question : "");
}

async function ask(question) {
  question = question.trim();
  if (!question) return;
  try {
    const data = await call("/interpretar", { pregunta: question });
    data.interpretacion.forEach(n => { if (n.etiqueta) state.labels[n.valor] = n.etiqueta; });
    location.hash = searchHash({ ...emptyQuery(), ...data.consulta }, question);
  } catch (e) {
    toast(e.message);
  }
}

/* ---------- feedback: toast, tooltip, skeletons, errors ---------- */

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.classList.remove("show"); setTimeout(() => { el.hidden = true; }, 200); }, 2600);
}

const tip = {
  show(html, x, y) {
    const el = $("#tooltip");
    el.innerHTML = html;
    el.hidden = false;
    const r = el.getBoundingClientRect();
    const left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x - r.width / 2));
    const top = y - r.height - 12 < 8 ? y + 18 : y - r.height - 12;
    el.style.transform = `translate(${left}px, ${top}px)`;
  },
  hide() { $("#tooltip").hidden = true; },
};

const skLines = (n = 3) => Array.from({ length: n }, (_, i) => `<div class="sk sk-line" style="width:${[92, 100, 76, 84][i % 4]}%"></div>`).join("");
const skCards = n => Array.from({ length: n }, () => `<div class="result sk-card"><span class="avatar sk"></span><div class="result-body"><div class="sk sk-line" style="width:40%"></div>${skLines(3)}</div></div>`).join("");

function errorBox(e, retry = true) {
  return `<div class="empty"><p class="empty-title">${e.status === 404 ? "No encontrado" : "No se pudo cargar"}</p>
    <p>${esc(e.message)}</p>${retry ? `<button class="btn ghost" data-retry>Reintentar</button>` : `<a class="btn ghost" href="#/">Ir al inicio</a>`}</div>`;
}

async function copy(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done); } catch (e) { toast("No se pudo copiar."); }
}

function citation(r) {
  const who = r.person || r.speaker;
  return `«${plain(r.snippet || r.text).trim()}»\n— ${who}${r.role ? ` (${r.role})` : ""}, ${r.institution || instName(r.institution_id)}, ${fmtDate(r.date, true)}.\nFuente: ${r.source_url}`;
}

/* ---------- charts ---------- */

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map(m => m * p).find(m => m >= v);
}

function barPath(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/**
 * Monthly column chart with hover tooltips, click-a-month and drag-a-range.
 * rows: [{key: "YYYY-MM", n}]; onPick(fromMonth, toMonth).
 */
function monthChart(el, rows, { onPick, unit = "intervenciones", height = 132, label = "Intervenciones por mes" } = {}) {
  if (!rows.length) { el.innerHTML = `<p class="note">Sin datos para graficar.</p>`; return; }
  const keys = monthRange(rows[0].key, rows[rows.length - 1].key);
  const byKey = Object.fromEntries(rows.map(r => [r.key, r.n]));
  const data = keys.map(k => ({ key: k, n: byKey[k] || 0 }));
  const max = niceMax(Math.max(...data.map(d => d.n)));
  let geom, drag = null, lastW = 0;

  function draw() {
    const W = Math.max(280, el.clientWidth), H = height, padL = 36, padR = 4, padT = 10, padB = 22;
    lastW = W;
    const iw = W - padL - padR, ih = H - padT - padB;
    const slot = iw / data.length, bw = Math.max(1, Math.min(24, slot - 2));
    const y = v => padT + ih - (v / max) * ih;
    geom = { W, padL, slot, iw };
    let bars = "";
    data.forEach((d, i) => {
      if (!d.n) return;
      const h = Math.max(1.5, (d.n / max) * ih);
      bars += `<path class="bar" data-i="${i}" d="${barPath(padL + i * slot + (slot - bw) / 2, padT + ih - h, bw, h, Math.min(4, bw / 2))}"/>`;
    });
    let xlab = "", lastX = -Infinity;
    const monthly = data.length <= 18;
    data.forEach((d, i) => {
      const isJan = d.key.endsWith("-01");
      if (!monthly && !isJan && i !== 0) return;
      const x = padL + i * slot + (monthly ? slot / 2 : 0);
      if (x - lastX < (monthly ? 30 : 34)) return;
      lastX = x;
      const text = monthly ? (isJan || i === 0 ? `${MONTHS[+d.key.slice(5) - 1]} ${d.key.slice(2, 4)}` : MONTHS[+d.key.slice(5) - 1]) : d.key.slice(0, 4);
      xlab += `<text x="${x}" y="${H - 6}" text-anchor="${monthly ? "middle" : "start"}">${text}</text>`;
      if (!monthly) xlab += `<line class="tick" x1="${x}" x2="${x}" y1="${padT + ih}" y2="${padT + ih + 4}"/>`;
    });
    const grid = [max, max / 2].map(v => `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text class="ylab" x="${padL - 8}" y="${y(v) + 4}">${compact(v)}</text>`).join("");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(label)}">
      ${grid}<line class="base" x1="${padL}" x2="${W - padR}" y1="${padT + ih}" y2="${padT + ih}"/>
      <text class="ylab" x="${padL - 8}" y="${padT + ih + 4}">0</text>
      <rect class="brush" y="${padT}" height="${ih}" x="0" width="0"/>
      <g class="bars">${bars}</g><g class="xlab">${xlab}</g>
      <rect class="hit" x="${padL}" y="0" width="${iw}" height="${H}"/></svg>`;
    const svg = $("svg", el);
    const index = e => {
      const r = svg.getBoundingClientRect();
      const px = (e.clientX - r.left) * (W / r.width);
      return Math.max(0, Math.min(data.length - 1, Math.floor((px - padL) / slot)));
    };
    const paint = (a, b) => {
      const lo = Math.min(a, b), hi = Math.max(a, b);
      $$(".bar", svg).forEach(p => p.classList.toggle("on", +p.dataset.i >= lo && +p.dataset.i <= hi));
      const brush = $(".brush", svg);
      brush.setAttribute("x", padL + lo * slot);
      brush.setAttribute("width", (hi - lo + 1) * slot);
    };
    const clear = () => { $$(".bar.on", svg).forEach(p => p.classList.remove("on")); $(".brush", svg).setAttribute("width", 0); };
    svg.addEventListener("pointermove", e => {
      const i = index(e);
      if (drag !== null) {
        paint(drag, i);
        const lo = Math.min(drag, i), hi = Math.max(drag, i);
        const total = data.slice(lo, hi + 1).reduce((s, d) => s + d.n, 0);
        tip.show(`<b>${fmtMonth(data[lo].key)}${hi > lo ? ` – ${fmtMonth(data[hi].key)}` : ""}</b><span>${num(total)} ${unit}</span>`, e.clientX, e.clientY);
      } else {
        paint(i, i);
        tip.show(`<b>${fmtMonth(data[i].key)}</b><span>${num(data[i].n)} ${unit}</span>${onPick ? '<em>Clic para ver este mes</em>' : ""}`, e.clientX, e.clientY);
      }
    });
    svg.addEventListener("pointerleave", () => { if (drag === null) { clear(); tip.hide(); } });
    if (onPick) {
      svg.classList.add("pickable");
      svg.addEventListener("pointerdown", e => { drag = index(e); svg.setPointerCapture(e.pointerId); e.preventDefault(); });
      svg.addEventListener("pointerup", e => {
        if (drag === null) return;
        const i = index(e), lo = Math.min(drag, i), hi = Math.max(drag, i);
        drag = null;
        tip.hide();
        onPick(data[lo].key, data[hi].key);
      });
    }
  }
  draw();
  const ro = new ResizeObserver(() => {
    if (!el.isConnected) return ro.disconnect();
    if (Math.abs(el.clientWidth - lastW) > 4) draw();
  });
  ro.observe(el);
}

function chartTable(rows, unit) {
  return `<details class="table-view"><summary>Ver como tabla</summary><div class="table-scroll"><table>
    <thead><tr><th>Mes</th><th>${esc(unit)}</th></tr></thead>
    <tbody>${rows.filter(r => r.n).map(r => `<tr><td>${fmtMonth(r.key)}</td><td>${num(r.n)}</td></tr>`).join("")}</tbody></table></div></details>`;
}

function sparkline(values, w = 92, h = 26) {
  const max = Math.max(1, ...values), step = w / Math.max(1, values.length - 1);
  const pts = values.map((v, i) => [i * step, h - 2 - (v / max) * (h - 4)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="-4 -4 ${w + 8} ${h + 8}" width="${w + 8}" height="${h + 8}" aria-hidden="true">
    <path class="area" d="${d}L${w},${h}L0,${h}Z"/><path class="line" d="${d}"/><circle cx="${lx}" cy="${ly}" r="3.5"/></svg>`;
}

/** Party split: one stacked bar plus a legend that doubles as the filter list. */
function partyBreakdown(rows, { key = "partidos", interactive = true } = {}) {
  if (!rows.length) return "";
  const total = rows.reduce((s, r) => s + r.n, 0);
  const color = r => PARTY_COLORS.has(r.id) ? `var(--p-${r.id})` : "var(--p-none)";
  const tag = interactive ? "button" : "span";
  return `<div class="stack" role="img" aria-label="${esc(rows.map(r => `${r.nombre}: ${pct(r.n, total)}%`).join(", "))}">
      ${rows.map(r => `<span class="seg" style="flex:${r.n};--c:${color(r)}" data-tip="<b>${esc(r.nombre)}</b><span>${num(r.n)} · ${pct(r.n, total)}%</span>"></span>`).join("")}
    </div>
    <div class="legend">${rows.map(r => `<${tag} class="legend-row"${interactive ? ` data-key="${key}" data-v="${esc(r.id)}" data-t="${esc(r.nombre)}"` : ""}>
      <i style="--c:${color(r)}"></i><span class="txt">${esc(r.nombre)}</span><span class="pct">${pct(r.n, total)}%</span><span class="n">${num(r.n)}</span></${tag}>`).join("")}</div>`;
}
const PARTY_COLORS = new Set(["MORENA", "PAN", "PRI", "PVEM", "PT", "MC", "PRD"]);

function barList(rows) {
  const max = Math.max(1, ...rows.map(r => r.n));
  return `<ul class="barlist">${rows.map(r => `<li><a href="${r.href}">
      <span class="bl-label">${r.lead || ""}<span class="txt">${esc(r.label)}</span>${r.extra || ""}</span>
      <span class="bl-n">${num(r.n)}</span>${r.sub ? `<span class="bl-sub${r.lead ? " indent" : ""}">${esc(r.sub)}</span>` : ""}
      <span class="bl-bar"><i style="width:${Math.max(2, (r.n / max) * 100)}%"></i></span></a></li>`).join("")}</ul>`;
}

/* ---------- result card ---------- */

function resultCard(r, { n, text } = {}) {
  turns.set(r.id, r);
  const who = r.person_id
    ? `<a class="name" href="#/persona/${encodeURIComponent(r.person_id)}">${esc(r.person)}</a>`
    : `<span class="name">${esc(r.speaker)}</span>`;
  const laws = r.leyes || [];
  const tags = laws.slice(0, 3).map(l => `<a class="tag" href="#/ley/${encodeURIComponent(l.id)}">${icon("scale")}${esc(l.nombre)}</a>`).join("")
    + (laws.length > 3 ? `<span class="tag more">+${laws.length - 3}</span>` : "");
  return `<article class="result" data-turn="${r.id}">
    ${n ? `<span class="srcnum" aria-label="Fuente ${n}">${n}</span>` : avatar(r.person || r.speaker, r.party)}
    <div class="result-body">
      <header class="who">${who}${pill(r.party)}${r.role ? `<span class="role">${esc(r.role)}</span>` : ""}</header>
      <div class="meta">${instTag(r.institution_id, r.institution)}<span>${fmtDate(r.date)}</span>${r.outlet ? `<span>${esc(r.outlet)}</span>` : ""}</div>
      <blockquote class="quote">${marked(r.snippet)}</blockquote>
      <footer class="result-foot">
        <div class="tags">${tags}</div>
        <div class="acts">
          <a href="${docHash(r.document_id, r.id, text)}">${icon("doc")}<span>Leer en contexto</span></a>
          <a href="${esc(r.source_url)}" target="_blank" rel="noopener">${icon("ext")}<span>Fuente oficial</span></a>
          <button type="button" data-copy="${r.id}">${icon("copy")}<span>Copiar cita</span></button>
        </div>
      </footer>
    </div>
  </article>`;
}

/* ---------- search box with suggestions ---------- */

function mountSearch(form, { big = false } = {}) {
  const input = $("input", form), box = $(".suggest", form);
  $(".search-ic", form).innerHTML = icon("search");
  let items = [], active = 0, timer, seq = 0;
  const close = () => { box.hidden = true; items = []; input.setAttribute("aria-expanded", "false"); };
  const draw = () => {
    let html = "", group = "";
    items.forEach((it, i) => {
      const g = { ask: "", persona: "Personas", ley: "Leyes" }[it.type];
      if (g && g !== group) { html += `<div class="sg-head">${g}</div>`; group = g; }
      const body = it.type === "ask"
        ? `${icon("search")}<span class="sg-main">Buscar «${esc(it.label)}»</span><kbd class="kbd">↵</kbd>`
        : it.type === "persona"
          ? `${avatar(it.nombre, it.partido, "sm")}<span class="sg-main">${esc(it.nombre)}</span>${pill(it.partido)}<span class="sg-n">${num(it.n)}</span>`
          : `<span class="sg-ic">${icon("scale")}</span><span class="sg-main">${esc(it.nombre)}</span><span class="sg-n">${num(it.n)}</span>`;
      html += `<div class="sg-item${i === active ? " on" : ""}" role="option" data-i="${i}">${body}</div>`;
    });
    box.innerHTML = html;
    box.hidden = !items.length;
    input.setAttribute("aria-expanded", String(!!items.length));
  };
  const choose = it => {
    close();
    if (!it || it.type === "ask") ask(input.value);
    else { input.value = ""; location.hash = it.type === "persona" ? `#/persona/${encodeURIComponent(it.id)}` : `#/ley/${encodeURIComponent(it.id)}`; }
  };
  input.setAttribute("aria-autocomplete", "list");
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const v = input.value.trim();
    if (v.length < 2) return close();
    timer = setTimeout(async () => {
      const mine = ++seq;
      const d = await call(`/sugerir?q=${encodeURIComponent(v)}`).catch(() => null);
      if (mine !== seq || input.value.trim() !== v) return;
      items = [{ type: "ask", label: v },
        ...(d?.personas || []).slice(0, big ? 4 : 3).map(p => ({ type: "persona", ...p })),
        ...(d?.leyes || []).slice(0, 3).map(l => ({ type: "ley", ...l }))];
      active = 0;
      draw();
    }, 140);
  });
  input.addEventListener("keydown", e => {
    if (box.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      draw();
    } else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 160));
  box.addEventListener("pointerdown", e => {
    const el = e.target.closest(".sg-item");
    if (el) { e.preventDefault(); choose(items[+el.dataset.i]); }
  });
  form.addEventListener("submit", e => {
    e.preventDefault();
    clearTimeout(timer);
    seq++;
    choose(box.hidden ? null : items[active]);
  });
}

/* ---------- home ---------- */

async function renderHome(view, token) {
  document.title = "Pleno · Lo que se dice en el poder público";
  view.innerHTML = `
    <section class="hero">
      <div class="wrap hero-inner">
        <p class="eyebrow">Datos públicos de México · <span id="asof">actualizado a diario</span></p>
        <h1>Lo que se dice en el poder público, <em>estructurado</em>.</h1>
        <p class="lede" id="lede">Conferencias de Presidencia y sesiones de la Cámara de Diputados convertidas en datos: quién habló, con qué cargo, de qué partido y sobre qué ley. Cada resultado enlaza a su fuente oficial.</p>
        <form class="search big" id="hero-search" role="search" autocomplete="off">
          <span class="search-ic" aria-hidden="true"></span>
          <input type="search" name="q" aria-label="Pregunta en español" placeholder="Pregunta en español: ¿qué dijo la presidenta sobre el agua en 2025?">
          <button class="btn primary" type="submit">Buscar</button>
          <div class="suggest" role="listbox" hidden></div>
        </form>
        <div class="examples"><span class="examples-label">Prueba</span>${EXAMPLES.map(e => `<button type="button" class="example">${esc(e)}</button>`).join("")}</div>
        <dl class="kpis" id="kpis">${["intervenciones", "documentos", "personas", "leyes"].map(k => `<div class="kpi"><dt>${k}</dt><dd><span class="sk sk-num"></span></dd></div>`).join("")}</dl>
      </div>
    </section>
    <section class="wrap">
      <form class="verify-cta" id="home-verify">
        <div class="verify-cta-text"><p class="eyebrow">${icon("check")}Nuevo</p><h2>¿Es cierto?</h2>
          <p>Pega lo que alguien dice que se dijo, se votó o pasó. Lo cotejamos con las versiones estenográficas, las votaciones nominales y las cifras oficiales.</p></div>
        <div class="verify-cta-form"><input name="a" maxlength="500" aria-label="Afirmación a verificar" placeholder="Ej.: Bajaron los homicidios en 2025">
          <button class="btn primary" type="submit">Verificar</button></div>
        <div class="tags">${VERIFY_EXAMPLES.map(e => `<a class="tag ex" href="#/verificar?${new URLSearchParams({ a: e })}">${esc(e)}</a>`).join("")}</div>
      </form>
    </section>
    <section class="wrap home-grid">
      <div class="panel" id="trending"><div class="panel-head"><h2>Leyes en la conversación</h2></div>${skLines(6)}</div>
      <div class="panel" id="voices"><div class="panel-head"><h2>Voces más activas</h2></div>${skLines(6)}</div>
    </section>
    <section class="wrap">
      <div class="section-head"><h2>Lo más reciente</h2><a class="btn link" href="#/fuentes">Todas las fuentes ${icon("arrow")}</a></div>
      <div class="recent-grid" id="recent">${skCards(2)}</div>
    </section>
    <section class="wrap" id="home-votes" hidden>
      <div class="section-head"><h2>Votaciones recientes en la Cámara de Diputados</h2><a class="btn link" href="#/votaciones">Todas las votaciones ${icon("arrow")}</a></div>
      <div class="panel vote-list" id="home-votes-list"></div>
    </section>
    <section class="wrap how">
      <div class="section-head"><h2>Cómo funciona</h2><p class="sub">Sin cajas negras: cada paso se puede revisar.</p></div>
      <ol class="steps">
        <li><span class="step-n">1</span><h3>Preguntas en español</h3><p>«Diputados de MC que mencionan la Ley de Amparo» se traduce con reglas, no con un modelo, a filtros que ves y puedes editar.</p></li>
        <li><span class="step-n">2</span><h3>Filtras con metadatos</h3><p>Persona, partido, cargo, institución, ley y fechas. El partido sale de la propia sesión; nunca se adivina.</p></li>
        <li><span class="step-n">3</span><h3>Citas la fuente</h3><p>Cada intervención enlaza a la versión estenográfica oficial. Las respuestas resumidas citan por número y se borra lo que no tiene fuente.</p></li>
      </ol>
      <div class="api-card">
        <div><h3>API para equipos</h3><p>La misma búsqueda, en JSON. Plan gratuito sin llave; llaves con más límite para uso profesional. Exporta cualquier consulta a CSV.</p>
          <a class="btn ghost" href="/docs" target="_blank" rel="noopener">Ver documentación ${icon("arrow")}</a></div>
        <pre class="code"><code>curl -X POST ${esc(location.origin)}/api/v1/buscar \\
  -H "Content-Type: application/json" \\
  -d '{"partidos": ["MC"], "leyes": ["ley-de-amparo"]}'</code></pre>
      </div>
    </section>`;
  mountSearch($("#hero-search"), { big: true });
  $("#home-verify").onsubmit = e => {
    e.preventDefault();
    const a = e.target.a.value.trim();
    if (a.length >= 8) location.hash = `#/verificar?${new URLSearchParams({ a })}`;
  };
  $$(".example", view).forEach(b => b.onclick = () => ask(b.textContent));
  if (matchMedia("(min-width: 760px)").matches) $("#hero-search input").focus({ preventScroll: true });

  let opts, pano;
  try {
    [opts, pano] = await Promise.all([options(), call("/panorama")]);
  } catch (e) {
    if (token !== routeSeq) return;
    $("#trending").innerHTML = errorBox(e);
    return;
  }
  if (token !== routeSeq) return;
  $("#asof").textContent = `actualizado al ${fmtDate(pano.hasta, true)}`;
  const withDocs = opts.instituciones.filter(i => i.documentos);
  $("#lede").innerHTML = `${num(opts.documentos)} sesiones, conferencias y comunicados de Presidencia, la Cámara de Diputados, la Suprema Corte, la Fiscalía General y ${num(withDocs.filter(i => i.nivel === "estatal").length)} congresos estatales, convertidos en datos: quién habló, con qué cargo, de qué partido, sobre qué ley y cómo votó. Cada resultado enlaza a su fuente oficial.`;
  $("#kpis").innerHTML = [["intervenciones", opts.intervenciones], ["documentos", opts.documentos], ["personas", opts.personas], ["votaciones nominales", opts.votaciones]]
    .map(([k, v]) => `<div class="kpi"><dt>${k}</dt><dd>${num(v)}</dd></div>`).join("")
    + `<div class="kpi kpi-sources"><dt>fuentes</dt><dd><a href="#/fuentes">${num(withDocs.length)} instituciones integradas</a>
        <small>${["federal", "estatal"].map(l => `${withDocs.filter(i => i.nivel === l).length} ${l === "federal" ? "federales" : "estatales"}`).join(" · ")} · ver inventario completo</small></dd></div>`;

  const months = monthRange(addMonths(pano.hasta.slice(0, 7), -11), pano.hasta.slice(0, 7));
  $("#trending").innerHTML = `<div class="panel-head"><h2>Leyes en la conversación</h2><p class="sub">Menciones en los últimos 90 días · tendencia de 12 meses</p></div>
    <ol class="trend">${pano.leyes_en_alza.map((l, i) => {
      const delta = l.antes ? Math.round(((l.n - l.antes) / l.antes) * 100) : null;
      const d = delta === null ? `<small class="delta new">nueva</small>` : `<small class="delta">${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta)}%</small>`;
      return `<li><a href="#/ley/${encodeURIComponent(l.id)}" data-tip="<b>${esc(l.nombre)}</b><span>${num(l.n)} menciones en 90 días · ${num(l.antes)} en los 90 previos</span>">
        <span class="rank">${i + 1}</span><span class="trend-name">${esc(l.nombre)}</span>
        ${sparkline(months.map(m => l.serie[m] || 0))}<span class="trend-n"><b>${num(l.n)}</b>${d}</span></a></li>`;
    }).join("")}</ol>`;

  $("#voices").innerHTML = `<div class="panel-head"><h2>Voces más activas</h2><p class="sub">Intervenciones en los últimos 30 días</p></div>
    ${barList(pano.voces.slice(0, 8).map(v => ({
      href: `#/persona/${encodeURIComponent(v.id)}`, label: v.nombre, n: v.n,
      lead: avatar(v.nombre, v.partido, "sm"), extra: pill(v.partido), sub: v.cargo,
    })))}`;

  $("#recent").innerHTML = (pano.ultimos || []).map(d => {
    const [, m, day] = d.date.split("-");
    return `<a class="doc-card" href="${docHash(d.id)}">
      <span class="doc-date"><b>${+day}</b><span>${MONTHS[+m - 1]}</span></span>
      <span class="doc-body">${instTag(d.institution_id, d.institution)}<span class="doc-title">${esc(cleanTitle(d.title, d.date))}</span>
        <span class="doc-meta">${num(d.intervenciones)} intervenciones${d.oradores.length ? ` · ${d.oradores.map(o => esc(o.nombre)).join(", ")}` : ""}</span></span>
      ${icon("arrow", "doc-go")}</a>`;
  }).join("");
  if (pano.votaciones?.length) {
    $("#home-votes").hidden = false;
    $("#home-votes-list").innerHTML = pano.votaciones.map(voteRow).join("");
  }
}

function voteRow(v) {
  return `<a class="vote-row" href="#/votacion/${encodeURIComponent(v.id)}">
    <span class="vote-date">${fmtDate(v.date)}</span><span class="vote-title">${esc(cleanVoteTitle(v.title))}</span>
    <span class="vote-mini">${voteBar({ "A favor": v.a_favor, "En contra": v.en_contra, "Abstención": v.abstencion, "Ausente": v.ausente }, { legend: false })}
      <small>${num(v.a_favor)} · ${num(v.en_contra)} · ${num(v.abstencion)}</small></span></a>`;
}
const cleanVoteTitle = t => { const s = String(t || "").toLowerCase(); return s ? s[0].toUpperCase() + s.slice(1) : ""; };

/* ---------- search ---------- */

function querybarHtml(q, question) {
  const chips = [];
  for (const [key, k] of Object.entries(KINDS)) {
    const vals = key === "texto" ? (q.texto ? [q.texto] : []) : q[key];
    vals.forEach(v => chips.push(`<span class="chip k-${key}"><span class="chip-k">${k.label}</span><span class="chip-v">${esc(labelFor(key, v))}</span>
      <button type="button" data-remove="${key}" data-v="${esc(v)}" aria-label="Quitar ${esc(k.label)}">${icon("x")}</button></span>`));
  }
  if (q.desde || q.hasta) {
    chips.push(`<span class="chip k-fechas"><span class="chip-k">Fechas</span><span class="chip-v">${esc(dateRangeLabel(q.desde, q.hasta))}</span>
      <button type="button" data-remove="fechas" aria-label="Quitar fechas">${icon("x")}</button></span>`);
  }
  return `${question ? `<p class="interpreted">Interpretado de <q>${esc(question)}</q></p>` : ""}
    <div class="chips">${chips.join("") || `<span class="note">Todas las intervenciones</span>`}
      <span class="addwrap"><button type="button" class="btn ghost sm" id="addfilter">${icon("plus")}Filtro</button></span>
      ${chips.length ? `<button type="button" class="btn link sm" id="clearall">Limpiar</button>` : ""}</div>`;
}

function bindQuerybar() {
  $$("[data-remove]").forEach(b => b.onclick = () => editQuery(q => {
    const key = b.dataset.remove;
    if (key === "fechas") { q.desde = ""; q.hasta = ""; }
    else if (key === "texto") q.texto = "";
    else q[key] = q[key].filter(v => v !== b.dataset.v);
  }, false));
  $("#addfilter").onclick = e => { e.stopPropagation(); openFilterMenu(); };
  if ($("#clearall")) $("#clearall").onclick = () => { location.hash = searchHash(queryWith({ orden: "fecha" })); };
}

async function renderSearch(view, token, params) {
  const q = paramsToQuery(params), question = params.get("p") || "";
  document.title = `${question || q.texto || "Explorar"} · Pleno`;
  $("#top-search input").value = question || q.texto;
  const sameShell = state.search && $(".search-page", view);
  if (!sameShell) {
    view.innerHTML = `<div class="wrap search-page">
      <div class="querybar" id="querybar"></div>
      <div class="summary" id="summary"><div class="sk sk-line" style="width:260px;height:28px"></div></div>
      <figure class="chart-card" id="histcard"><div class="sk sk-chart"></div></figure>
      <div class="search-grid">
        <div class="main-col"><section class="answer-card" id="answer" hidden></section><section class="panel votes-hit" id="votehits" hidden></section><div id="results">${skCards(4)}</div></div>
        <aside class="rail" id="rail" aria-label="Refinar resultados">${skLines(8)}</aside>
      </div></div>`;
  } else {
    view.classList.add("is-loading");
  }
  await options().catch(() => null);
  $("#querybar").innerHTML = querybarHtml(q, question);
  bindQuerybar();
  state.search = { q, question, results: [], total: 0 };

  let data;
  try {
    data = await call("/buscar", { ...q, limite: 20, pagina: 1 });
  } catch (e) {
    if (token !== routeSeq) return;
    view.classList.remove("is-loading");
    $("#results").innerHTML = errorBox(e);
    return;
  }
  if (token !== routeSeq) return;
  view.classList.remove("is-loading");
  Object.assign(state.labels, data.etiquetas);
  data.facetas.personas.forEach(p => { state.labels[p.id] = p.nombre; });
  data.facetas.leyes.forEach(l => { state.labels[l.id] = l.nombre; });
  $("#querybar").innerHTML = querybarHtml(q, question);
  bindQuerybar();
  Object.assign(state.search, { total: data.total, results: data.resultados, page: 1 });

  const months = data.facetas.meses.map(m => ({ key: m.id, n: m.n }));
  $("#summary").innerHTML = `
    <p class="count"><strong>${num(data.total)}</strong> ${data.total === 1 ? "intervención" : "intervenciones"}${months.length ? `<span class="muted"> · ${fmtMonth(months[0].key)}${months.length > 1 ? ` – ${fmtMonth(months[months.length - 1].key)}` : ""}</span>` : ""}</p>
    <div class="tools">
      ${q.texto ? `<div class="seg-ctl" role="group" aria-label="Orden"><button type="button" data-order="relevancia" class="${q.orden !== "fecha" ? "on" : ""}">Relevancia</button><button type="button" data-order="fecha" class="${q.orden === "fecha" ? "on" : ""}">Recientes</button></div>` : ""}
      <button type="button" class="btn ghost sm" id="csv" ${data.total ? "" : "disabled"}>${icon("download")}CSV</button>
      <button type="button" class="btn ghost sm only-local" id="mkalert">${icon("bell")}Crear alerta</button>
      <button type="button" class="btn ghost sm" data-share>${icon("link")}Copiar enlace</button>
    </div>`;
  $$("[data-order]").forEach(b => b.onclick = () => editQuery(x => { x.orden = b.dataset.order; }));
  $("#csv").onclick = downloadCsv;
  $("#mkalert").onclick = () => createAlert(q, question);
  const vh = $("#votehits");
  vh.hidden = !data.votaciones?.total;
  if (data.votaciones?.total) {
    vh.innerHTML = `<div class="panel-head"><h2>Votaciones sobre «${esc(q.texto)}»</h2>
      <a class="btn link" href="#/votaciones?q=${encodeURIComponent(q.texto)}">${num(data.votaciones.total)} votaciones ${icon("arrow")}</a></div>
      <div class="vote-list">${data.votaciones.votaciones.slice(0, 3).map(voteRow).join("")}</div>`;
  }

  const card = $("#histcard");
  if (months.length > 1) {
    card.hidden = false;
    card.innerHTML = `<figcaption><span>Intervenciones por mes</span><span class="hint">Clic en un mes o arrastra para acotar las fechas</span></figcaption><div class="chart" id="hist"></div>${chartTable(months, "Intervenciones")}`;
    monthChart($("#hist"), months, { onPick: (a, b) => editQuery(x => { x.desde = `${a}-01`; x.hasta = monthEnd(b); }) });
  } else {
    card.hidden = true;
  }

  renderRail(data.facetas, q);
  renderAnswerCta();
  renderResults();
}

function facetRows(key, rows, q, { lead, extra, profile } = {}) {
  const max = Math.max(1, ...rows.map(r => r.n));
  return rows.map(r => {
    const on = (q[key] || []).includes(r.id);
    return `<div class="facet${on ? " on" : ""}">
      <button type="button" class="facet-btn" data-key="${key}" data-v="${esc(r.id)}" data-t="${esc(r.nombre)}" aria-pressed="${on}">
        <span class="facet-label">${lead ? lead(r) : ""}<span class="txt">${esc(labelFor(key, r.nombre))}</span>${extra ? extra(r) : ""}</span>
        <span class="facet-n">${num(r.n)}</span><span class="facet-bar"><i style="width:${Math.max(2, (r.n / max) * 100)}%"></i></span>
      </button>${profile ? `<a class="facet-go" href="${profile(r)}" aria-label="Ver perfil" data-tip="Ver perfil">${icon("arrow")}</a>` : ""}</div>`;
  }).join("");
}

function renderRail(f, q) {
  const section = (title, body, note = "") => body ? `<section class="rail-sec"><h3>${title}</h3>${note ? `<p class="note">${note}</p>` : ""}${body}</section>` : "";
  const html =
    section("Partido", partyBreakdown(f.partidos), "Entre intervenciones de personas con partido registrado.") +
    section("Quién habla", facetRows("personas", f.personas, q, {
      lead: r => avatar(r.nombre, r.partido, "xs"), extra: r => pill(r.partido), profile: r => `#/persona/${encodeURIComponent(r.id)}`,
    })) +
    section("Leyes mencionadas", facetRows("leyes", f.leyes, q, { profile: r => `#/ley/${encodeURIComponent(r.id)}` })) +
    section("Institución", facetRows("instituciones", f.instituciones, q, { lead: r => `<i class="dot" data-level="${esc(instLevel(r.id))}"></i>` })) +
    section("Estado", facetRows("estados", f.estados || [], q)) +
    section("Cargo", facetRows("cargos", f.cargos, q)) +
    section("Medio", facetRows("medios", f.medios, q), "Solo cuando el periodista lo dice en la transcripción.");
  const open = matchMedia("(min-width: 980px)").matches;
  $("#rail").innerHTML = `<details class="rail-box"${open ? " open" : ""}><summary>${icon("filter")}Refinar resultados</summary><div class="rail-body">${html || '<p class="note">Sin facetas para esta consulta.</p>'}</div></details>`;
  $$("#rail [data-key]").forEach(b => b.onclick = () => {
    const { key, v, t } = b.dataset;
    if (key === "personas" || key === "leyes") state.labels[v] = t;
    const on = (state.search.q[key] || []).includes(v);
    editQuery(x => { x[key] = on ? x[key].filter(y => y !== v) : [...x[key], v]; }, !on);
  });
}

function renderResults() {
  const s = state.search, box = $("#results");
  if (!s.results.length) {
    const removable = [...Object.keys(KINDS).flatMap(key => key === "texto" ? (s.q.texto ? [[key, s.q.texto]] : []) : s.q[key].map(v => [key, v])),
      ...(s.q.desde || s.q.hasta ? [["fechas", ""]] : [])];
    box.innerHTML = `<div class="empty"><p class="empty-title">Sin resultados</p><p>Prueba quitando un filtro:</p>
      <div class="chips">${removable.map(([k, v]) => `<button type="button" class="chip-btn" data-remove="${k}" data-v="${esc(v)}">${icon("x")}${esc(k === "fechas" ? dateRangeLabel(s.q.desde, s.q.hasta) : labelFor(k, v))}</button>`).join("")}</div></div>`;
    bindQuerybar();
    return;
  }
  box.innerHTML = s.results.map(r => resultCard(r, { text: s.q.texto })).join("") + moreButton();
  bindMore();
}

const moreButton = () => {
  const s = state.search;
  return s.results.length < s.total
    ? `<button type="button" class="btn ghost more" id="more">Cargar más <span class="muted">· quedan ${num(s.total - s.results.length)}</span></button>`
    : `<p class="end">Fin de los resultados</p>`;
};

function bindMore() {
  const b = $("#more");
  if (!b) return;
  b.onclick = async () => {
    const s = state.search, token = routeSeq;
    b.disabled = true;
    b.innerHTML = `<span class="spinner"></span>Cargando…`;
    try {
      const data = await call("/buscar", { ...s.q, limite: 20, pagina: s.page + 1 });
      if (token !== routeSeq) return;
      s.page += 1;
      s.results = s.results.concat(data.resultados);
      b.insertAdjacentHTML("beforebegin", data.resultados.map(r => resultCard(r, { text: s.q.texto })).join(""));
      b.outerHTML = moreButton();
      bindMore();
    } catch (e) {
      b.disabled = false;
      b.textContent = "Reintentar";
      toast(e.message);
    }
  };
}

async function downloadCsv() {
  const s = state.search;
  toast("Preparando CSV…");
  try {
    const res = await fetch(`${API}/exportar`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...s.q, limite: 20, pagina: 1 }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "No se pudo exportar.");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `pleno-${new Date().toISOString().slice(0, 10)}.csv` });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(s.total > 500 ? "CSV con las primeras 500 filas. Con una llave de API puedes exportar más." : "CSV descargado.");
  } catch (e) {
    toast(e.message);
  }
}

async function createAlert(q, question) {
  const name = prompt("Nombre de la alerta (te avisará de nuevas intervenciones que coincidan):", question || q.texto || "Mi alerta");
  if (!name || name.trim().length < 2) return;
  try {
    await call("/alertas", { nombre: name.trim(), consulta: { ...q, limite: 20, pagina: 1 } });
    toast("Alerta creada. Revisa la página de Alertas o suscríbete a su RSS.");
  } catch (e) {
    toast(e.message);
  }
}

/* ---------- answer with sources ---------- */

function renderAnswerCta() {
  const box = $("#answer");
  box.hidden = !state.search.total;
  box.innerHTML = `<div class="answer-cta"><span class="answer-ic">${icon("spark")}</span>
    <div><b>Respuesta con fuentes</b><p>Un resumen de las intervenciones más relevantes. Cada afirmación cita su fuente y las citas que no existen se borran.</p></div>
    <button type="button" class="btn primary" id="gen">Generar</button></div>`;
  $("#gen").onclick = generateAnswer;
}

async function generateAnswer() {
  const s = state.search, token = routeSeq, box = $("#answer");
  box.innerHTML = `<div class="answer-head"><span class="answer-ic">${icon("spark")}</span><b>Respuesta con fuentes</b></div>
    <p class="loading"><span class="spinner"></span>Leyendo las 10 intervenciones más relevantes…</p>${skLines(4)}`;
  try {
    const data = await call("/responder", {
      pregunta: s.question || s.q.texto || "Resume lo que se dijo en estas intervenciones", consulta: { ...s.q, limite: 20, pagina: 1 },
    });
    if (token !== routeSeq) return;
    data.fuentes.forEach(r => turns.set(r.id, r));
    const cited = new Set(data.citas);
    const text = esc(data.respuesta)
      .replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_, nums) => nums.split(/\s*,\s*/).map(n => `<button type="button" class="cite" data-src="${n}">${n}</button>`).join(""))
      .split(/\n{2,}/).map(p => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
    box.innerHTML = `<div class="answer-head"><span class="answer-ic">${icon("spark")}</span><b>Respuesta con fuentes</b>
        <span class="muted">${data.modelo ? `${esc(data.modelo)} · ` : ""}${data.fuentes.length} fuentes</span></div>
      <div class="answer-text">${text}</div>
      <details class="sources"${data.modelo ? "" : " open"}><summary>Ver las ${data.fuentes.length} fuentes</summary><ol>
        ${data.fuentes.map((r, i) => `<li class="${cited.has(i + 1) ? "cited" : ""}" id="src-${i + 1}"><a href="${docHash(r.document_id, r.id, s.q.texto)}">
          <span class="srcnum">${i + 1}</span><span><b>${esc(r.person || r.speaker)}</b> <span class="muted">${esc(r.role || "")} · ${fmtDate(r.date)}</span>
          <span class="src-snip">${esc(plain(r.snippet).slice(0, 220))}…</span></span></a></li>`).join("")}</ol></details>
      <p class="note">Texto generado automáticamente a partir de las fuentes. Verifica en la versión oficial antes de citar.</p>`;
    $$(".cite", box).forEach(b => {
      const r = data.fuentes[+b.dataset.src - 1];
      if (!r) return;
      b.dataset.tip = `<b>${esc(r.person || r.speaker)}</b><span>${esc(r.role || "")} · ${fmtDate(r.date)}</span><em>${esc(plain(r.snippet).slice(0, 180))}…</em>`;
      b.onclick = () => { location.hash = docHash(r.document_id, r.id, s.q.texto); };
    });
  } catch (e) {
    if (token !== routeSeq) return;
    box.innerHTML = errorBox(e);
  }
}

/* ---------- add-filter popover ---------- */

function closeMenu() { $("#fmenu")?.remove(); }

function openFilterMenu() {
  closeMenu();
  const tabs = [["personas", "Persona"], ["leyes", "Ley"], ["partidos", "Partido"], ["instituciones", "Institución"], ["estados", "Estado"], ["cargos", "Cargo"], ["fechas", "Fechas"], ["texto", "Texto"]];
  const menu = document.createElement("div");
  menu.className = "popover";
  menu.id = "fmenu";
  menu.innerHTML = `<div class="pop-tabs" role="tablist">${tabs.map(([k, l], i) => `<button type="button" role="tab" data-kind="${k}" class="${i ? "" : "on"}">${l}</button>`).join("")}</div><div class="pop-body" id="fbody"></div>`;
  $(".addwrap").appendChild(menu);
  menu.addEventListener("click", e => e.stopPropagation());
  $$(".pop-tabs button", menu).forEach(b => b.onclick = () => {
    $$(".pop-tabs button", menu).forEach(x => x.classList.toggle("on", x === b));
    filterBody(b.dataset.kind);
  });
  filterBody("personas");
}

function addFilter(key, value, text) {
  if (text) state.labels[value] = text;
  closeMenu();
  editQuery(q => {
    if (key === "texto") q.texto = value;
    else if (!q[key].includes(value)) q[key].push(value);
  });
}

function filterBody(kind) {
  const body = $("#fbody");
  const opts = optionsCache;
  if (kind === "personas" || kind === "leyes") {
    body.innerHTML = `<input class="input" id="fq" placeholder="${kind === "personas" ? "Escribe un nombre…" : "Nombre de la ley…"}" autocomplete="off"><div class="pop-list" id="fs"><p class="note">Escribe al menos dos letras.</p></div>`;
    const input = $("#fq");
    let timer;
    input.oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const v = input.value.trim();
        if (v.length < 2) { $("#fs").innerHTML = `<p class="note">Escribe al menos dos letras.</p>`; return; }
        const d = await call(`/sugerir?q=${encodeURIComponent(v)}`).catch(() => ({ personas: [], leyes: [] }));
        const rows = d[kind] || [];
        $("#fs").innerHTML = rows.map(r => `<button type="button" class="pop-item" data-v="${esc(r.id)}" data-t="${esc(r.nombre)}">
          ${kind === "personas" ? avatar(r.nombre, r.partido, "xs") : icon("scale")}<span class="txt">${esc(r.nombre)}</span>${pill(r.partido)}<span class="n">${num(r.n)}</span></button>`).join("")
          || `<p class="note">Sin coincidencias.</p>`;
        $$("#fs .pop-item").forEach(b => b.onclick = () => addFilter(kind, b.dataset.v, b.dataset.t));
      }, 150);
    };
    input.focus();
  } else if (kind === "partidos" || kind === "instituciones" || kind === "estados") {
    const rows = kind === "partidos" ? opts.partidos.map(p => [p, pill(p)])
      : kind === "estados" ? opts.estados.map(e => [e, `<span class="txt">${esc(e)}</span>`])
      : opts.instituciones.filter(i => i.documentos).map(i => [i.id, `${instTag(i.id, i.nombre)}<span class="n">${num(i.documentos)} documentos</span>`]);
    body.innerHTML = `<div class="pop-list">${rows.map(([v, html]) => `<button type="button" class="pop-item" data-v="${esc(v)}">${html}</button>`).join("")}</div>`;
    $$(".pop-item", body).forEach(b => b.onclick = () => addFilter(kind, b.dataset.v));
  } else if (kind === "cargos") {
    body.innerHTML = `<div class="pop-list">${ROLE_PRESETS.map(([v, l]) => `<button type="button" class="pop-item" data-v="${esc(v)}"><span class="txt">${esc(l)}</span></button>`).join("")}</div>
      <form class="pop-form" id="ff"><input class="input" placeholder="Otro cargo: subsecretario, alcaldesa…"><button class="btn primary sm">Agregar</button></form>`;
    $$(".pop-item", body).forEach(b => b.onclick = () => addFilter("cargos", b.dataset.v));
    $("#ff").onsubmit = e => { e.preventDefault(); const v = $("input", e.target).value.trim(); if (v) addFilter("cargos", v); };
  } else if (kind === "fechas") {
    const last = opts.instituciones.map(i => i.hasta).sort().pop() || new Date().toISOString().slice(0, 10);
    const presets = [
      ["Últimos 30 días", addDays(last, -30), ""], ["Últimos 12 meses", addDays(last, -365), ""],
      [`Este año (${last.slice(0, 4)})`, `${last.slice(0, 4)}-01-01`, ""],
      ["Sexenio de Sheinbaum", "2024-10-01", ""], ["Sexenio de López Obrador", "2018-12-01", "2024-09-30"],
      ["LXVI Legislatura", "2024-09-01", ""],
    ];
    const q = state.search.q;
    body.innerHTML = `<div class="pop-list">${presets.map(([l, a, b]) => `<button type="button" class="pop-item" data-a="${a}" data-b="${b}"><span class="txt">${l}</span><span class="n">${dateRangeLabel(a, b)}</span></button>`).join("")}</div>
      <form class="pop-form dates" id="ff"><label>Desde<input class="input" type="date" name="a" value="${q.desde}"></label><label>Hasta<input class="input" type="date" name="b" value="${q.hasta}"></label><button class="btn primary sm">Aplicar</button></form>`;
    const apply = (a, b) => { closeMenu(); editQuery(x => { x.desde = a; x.hasta = b; }); };
    $$(".pop-item", body).forEach(b => b.onclick = () => apply(b.dataset.a, b.dataset.b));
    $("#ff").onsubmit = e => { e.preventDefault(); apply(e.target.a.value, e.target.b.value); };
  } else {
    body.innerHTML = `<form class="pop-form" id="ff"><input class="input" placeholder="palabras o «frase exacta»" value="${esc(state.search.q.texto)}"><button class="btn primary sm">Aplicar</button></form>
      <p class="note">Las palabras largas también encuentran variantes: «reform» encuentra reforma y reformas.</p>`;
    $("#ff input").focus();
    $("#ff").onsubmit = e => { e.preventDefault(); addFilter("texto", $("input", e.target).value.trim()); };
  }
}

/* ---------- person ---------- */

const backLink = () => `<a class="back" href="#/" data-back>${icon("back")}Volver</a>`;

async function renderPerson(view, token, pid) {
  view.innerHTML = `<div class="wrap page">${skLines(2)}<div class="sk sk-chart"></div>${skCards(3)}</div>`;
  let d;
  try { [d] = await Promise.all([call(`/personas/${encodeURIComponent(pid)}`), options()]); }
  catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e, e.status !== 404)}</div>`; return; }
  if (token !== routeSeq) return;
  const p = d.persona, s = d.estadisticas, last = d.cargos[0];
  state.labels[p.id] = p.name;
  document.title = `${p.name} · Pleno`;
  const all = searchHash(queryWith({ personas: [p.id], orden: "fecha" }));
  view.innerHTML = `<div class="wrap page">
    ${backLink()}
    <header class="profile">
      ${avatar(p.name, p.party, "xl")}
      <div class="profile-main">
        <p class="eyebrow">${icon("user")}Persona</p>
        <h1>${esc(p.name)}</h1>
        <p class="profile-sub">${pill(p.party)}${last?.role ? `<span>${esc(last.role)}</span>` : ""}${last ? instTag(last.institution_id) : ""}</p>
        ${p.party ? `<p class="note">${p.source === "padrón oficial" ? "Partido según el padrón oficial de la Cámara de Diputados (SITL)."
          : `Partido tomado de la propia versión estenográfica («…del Grupo Parlamentario de ${esc(p.party)}»), no de una base externa.`}</p>` : ""}
      </div>
      <div class="profile-actions"><a class="btn primary" href="${all}">Todas sus intervenciones ${icon("arrow")}</a>
        <button type="button" class="btn ghost" data-share>${icon("link")}Copiar enlace</button></div>
    </header>
    <dl class="kpis compact">
      <div class="kpi"><dt>intervenciones</dt><dd>${num(s.intervenciones)}</dd></div>
      <div class="kpi"><dt>sesiones y conferencias</dt><dd>${num(s.documentos)}</dd></div>
      <div class="kpi"><dt>primera vez</dt><dd>${fmtDate(s.primera)}</dd></div>
      <div class="kpi"><dt>más reciente</dt><dd>${fmtDate(s.ultima)}</dd></div>
    </dl>
    <div class="page-grid">
      <div class="main-col">
        <section class="panel"><div class="panel-head"><h2>Actividad por mes</h2><p class="sub">Clic en un mes para leer sus intervenciones.</p></div><div class="chart" id="pchart"></div>
          ${chartTable(d.linea_de_tiempo.map(t => ({ key: t.mes, n: t.n })), "Intervenciones")}</section>
        <section class="panel"><div class="panel-head"><h2>Buscar en lo que ha dicho</h2></div>
          <form class="inline-search" id="within"><span class="search-ic">${icon("search")}</span><input class="input" name="t" placeholder="agua, salario mínimo, «reforma judicial»…"><button class="btn primary">Buscar</button></form></section>
        ${d.votaciones ? votesPanel(d.votaciones) : ""}
        <div class="section-head"><h2>Intervenciones recientes</h2><a class="btn link" href="${all}">Ver todas ${icon("arrow")}</a></div>
        ${d.recientes.map(r => resultCard(r)).join("")}
      </div>
      <aside class="side-col">
        ${d.padron.map(m => `<section class="panel"><div class="panel-head"><h2>Padrón oficial</h2><p class="sub">${esc(m.institution)} · Legislatura ${esc(m.legislature)}</p></div>
          <dl class="facts">
            <div><dt>Partido</dt><dd>${pill(m.party)}</dd></div>
            ${m.state ? `<div><dt>Entidad</dt><dd>${esc(m.state)}</dd></div>` : ""}
            ${m.district ? `<div><dt>Elección</dt><dd>${esc(m.district)}${m.principle ? ` · ${esc(m.principle)}` : ""}</dd></div>` : ""}
            ${m.seat ? `<div><dt>Curul</dt><dd>${esc(m.seat)}</dd></div>` : ""}
          </dl>
          ${m.committees.length ? `<h3 class="mini-h">Comisiones</h3><ul class="plain">${m.committees.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
          <a class="btn link" href="${esc(m.source_url)}" target="_blank" rel="noopener">${icon("ext")}Ficha oficial</a></section>`).join("")}
        <section class="panel"><div class="panel-head"><h2>Cargos con que aparece</h2></div>
          <ol class="roles">${d.cargos.map(c => `<li><b>${esc(c.role || "Sin cargo en la transcripción")}</b>
            <span>${instTag(c.institution_id)}</span><span class="muted">${fmtDate(c.desde)} – ${fmtDate(c.hasta)} · ${num(c.n)}</span></li>`).join("")}</ol></section>
        ${d.leyes.length ? `<section class="panel"><div class="panel-head"><h2>Leyes que más menciona</h2></div>
          ${barList(d.leyes.map(l => ({ href: `#/ley/${encodeURIComponent(l.id)}`, label: l.nombre, n: l.n })))}</section>` : ""}
      </aside>
    </div></div>`;
  monthChart($("#pchart"), d.linea_de_tiempo.map(t => ({ key: t.mes, n: t.n })), {
    label: `Intervenciones de ${p.name} por mes`,
    onPick: (a, b) => { location.hash = searchHash(queryWith({ personas: [p.id], desde: `${a}-01`, hasta: monthEnd(b), orden: "fecha" })); },
  });
  $("#within").onsubmit = e => {
    e.preventDefault();
    const t = e.target.t.value.trim();
    location.hash = searchHash(queryWith({ personas: [p.id], texto: t, orden: t ? "relevancia" : "fecha" }));
  };
}

function votesPanel(v) {
  const rows = r => `<a class="vote-row" href="#/votacion/${encodeURIComponent(r.id)}"><span class="vote-date">${fmtDate(r.date)}</span>
    <span class="vote-title">${esc(cleanVoteTitle(r.title))}</span><span class="sense s-${senseKey(r.sense)}">${esc(r.sense)}${r.bancada && r.bancada !== r.sense && SENSE_ORDER.slice(0, 3).includes(r.sense) ? `<small>bancada: ${esc(r.bancada)}</small>` : ""}</span></a>`;
  return `<section class="panel"><div class="panel-head"><h2>Cómo vota</h2><p class="sub">${num(v.n)} votaciones nominales en el Pleno de la Cámara de Diputados.</p></div>
    ${voteBar(v.totales)}
    <p class="discipline"><b>${num(v.n_contra_bancada)}</b> veces votó distinto a la mayoría de su grupo parlamentario.</p>
    ${v.contra_bancada.length ? `<h3 class="mini-h">Votos contra su bancada</h3><div class="vote-list">${v.contra_bancada.map(rows).join("")}</div>` : ""}
    <h3 class="mini-h">Votos recientes</h3><div class="vote-list">${v.recientes.map(rows).join("")}</div></section>`;
}

/* ---------- law ---------- */

async function renderLaw(view, token, lid) {
  view.innerHTML = `<div class="wrap page">${skLines(2)}<div class="sk sk-chart"></div>${skCards(3)}</div>`;
  let d;
  try { [d] = await Promise.all([call(`/leyes/${encodeURIComponent(lid)}`), options()]); }
  catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e, e.status !== 404)}</div>`; return; }
  if (token !== routeSeq) return;
  const law = d.ley, s = d.estadisticas;
  state.labels[law.id] = law.name;
  document.title = `${law.name} · Pleno`;
  const all = searchHash(queryWith({ leyes: [law.id], orden: "fecha" }));
  const parties = d.por_partido.map(r => ({ id: r.nombre, nombre: r.nombre, n: r.n }));
  view.innerHTML = `<div class="wrap page">
    ${backLink()}
    <header class="profile">
      <span class="law-mark" aria-hidden="true">${icon("scale")}</span>
      <div class="profile-main">
        <p class="eyebrow">Ley mencionada${law.jurisdiction ? ` · ${law.jurisdiction === "federal" ? "federal" : `estatal (${esc(law.jurisdiction)})`}` : ""}</p>
        <h1>${esc(law.name)}</h1>
        ${law.official_url ? `<p class="official">${icon("doc")}Ley federal vigente: <a href="${esc(law.official_url)}" target="_blank" rel="noopener">${esc(law.official_name)}</a>${law.last_reform ? ` · última reforma ${fmtDate(law.last_reform)}` : ""}</p>` : ""}
        <p class="note">Menciones detectadas por nombre en las transcripciones${law.official_url ? " y vinculadas al catálogo oficial de leyes federales de la Cámara de Diputados" : ""}. Una intervención cuenta una vez aunque la nombre varias veces.</p>
      </div>
      <div class="profile-actions"><a class="btn primary" href="${all}">Todas las menciones ${icon("arrow")}</a>
        <button type="button" class="btn ghost" data-share>${icon("link")}Copiar enlace</button></div>
    </header>
    <dl class="kpis compact">
      <div class="kpi"><dt>menciones</dt><dd>${num(s.menciones)}</dd></div>
      <div class="kpi"><dt>personas que la mencionan</dt><dd>${num(s.personas)}</dd></div>
      <div class="kpi"><dt>primera mención</dt><dd>${fmtDate(s.primera)}</dd></div>
      <div class="kpi"><dt>más reciente</dt><dd>${fmtDate(s.ultima)}</dd></div>
    </dl>
    <div class="page-grid">
      <div class="main-col">
        <section class="panel"><div class="panel-head"><h2>Menciones por mes</h2><p class="sub">Clic en un mes o arrastra para leer esas menciones.</p></div><div class="chart" id="lchart"></div>
          ${chartTable(d.linea_de_tiempo.map(t => ({ key: t.mes, n: t.n })), "Menciones")}</section>
        <div class="section-head"><h2>Menciones recientes</h2><a class="btn link" href="${all}">Ver todas ${icon("arrow")}</a></div>
        ${d.recientes.map(r => resultCard(r, { text: `«${law.name}»` })).join("")}
      </div>
      <aside class="side-col">
        ${d.por_institucion.length > 1 ? `<section class="panel"><div class="panel-head"><h2>Dónde se menciona</h2></div>
          ${barList(d.por_institucion.map(r => ({ href: searchHash(queryWith({ leyes: [law.id], instituciones: [r.id], orden: "fecha" })), label: r.nombre, n: r.n })))}</section>` : ""}
        <section class="panel"><div class="panel-head"><h2>Por partido</h2><p class="sub">Partido de quien la menciona.</p></div>${partyBreakdown(parties, { interactive: false })}</section>
        <section class="panel"><div class="panel-head"><h2>Quién la menciona más</h2></div>
          ${barList(d.personas.map(r => ({ href: `#/persona/${encodeURIComponent(r.id)}`, label: r.nombre, n: r.n, lead: avatar(r.nombre, r.partido, "xs"), extra: pill(r.partido) })))}</section>
      </aside>
    </div></div>`;
  monthChart($("#lchart"), d.linea_de_tiempo.map(t => ({ key: t.mes, n: t.n })), {
    unit: "menciones", label: `Menciones de ${law.name} por mes`,
    onPick: (a, b) => { location.hash = searchHash(queryWith({ leyes: [law.id], desde: `${a}-01`, hasta: monthEnd(b), orden: "fecha" })); },
  });
}

/* ---------- document reader ---------- */

function termRegex(text) {
  const words = (String(text || "").match(/«[^»]+»|"[^"]+"|[\p{L}\d]+/gu) || [])
    .map(w => w.replace(/[«»"]/g, "").trim()).filter(w => w.length >= 3 && !STOP.has(fold(w)));
  if (!words.length) return null;
  const cls = { a: "[aáàä]", e: "[eéèë]", i: "[iíìï]", o: "[oóòö]", u: "[uúùü]", n: "[nñ]" };
  const pat = words.map(w => fold(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/[aeioun]/g, c => cls[c]).replace(/ /g, "\\s+")
    + (w.length >= 5 && !w.includes(" ") ? "\\p{L}*" : "")).join("|");
  return new RegExp(`(?<![\\p{L}\\d])(?:${pat})`, "giu");
}
const highlight = (text, rx) => marked(rx ? text.replace(rx, m => `⟦${m}⟧`) : text);

function turnHtml(t, doc, focus, rx) {
  const key = t.person_id || `s:${t.speaker}`;
  const who = t.person_id ? `<a class="name" href="#/persona/${encodeURIComponent(t.person_id)}">${esc(t.person)}</a>` : `<span class="name">${esc(t.speaker)}</span>`;
  return `<section class="turn${t.id === focus ? " focus" : ""}" id="turn-${t.id}" data-spk="${esc(key)}" data-laws="${esc(t.leyes.map(l => l.id).join(" "))}">
    <div class="turn-gutter">${avatar(t.person || t.speaker, t.party, "sm")}</div>
    <div class="turn-main">
      <header class="who">${who}${pill(t.party)}${t.role ? `<span class="role">${esc(t.role)}</span>` : ""}${t.outlet ? `<span class="role">· ${esc(t.outlet)}</span>` : ""}
        <span class="turn-tools"><a href="${docHash(doc.id, t.id)}" data-tip="Enlace a esta intervención" aria-label="Enlace a esta intervención">${icon("link")}</a>
        <button type="button" data-copy="${t.id}" data-tip="Copiar cita" aria-label="Copiar cita">${icon("copy")}</button></span></header>
      <div class="turn-text">${t.text.split(/\n+/).map(p => `<p>${highlight(p, rx)}</p>`).join("")}</div>
      ${t.leyes.length ? `<div class="tags">${t.leyes.map(l => `<a class="tag" href="#/ley/${encodeURIComponent(l.id)}">${icon("scale")}${esc(l.nombre)}</a>`).join("")}</div>` : ""}
    </div></section>`;
}

async function renderDocument(view, token, docId, params) {
  view.innerHTML = `<div class="wrap page">${skLines(3)}${skCards(4)}</div>`;
  let d;
  try { [d] = await Promise.all([call(`/documentos/${encodeURIComponent(docId)}`), options()]); }
  catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e, e.status !== 404)}</div>`; return; }
  if (token !== routeSeq) return;
  const doc = d.documento, ts = d.intervenciones;
  const focus = Number(params.get("t")) || null, query = params.get("q") || "";
  document.title = `${cleanTitle(doc.title, doc.date)} · Pleno`;
  ts.forEach(t => turns.set(t.id, { ...t, snippet: t.text, date: doc.date, institution: doc.institution, institution_id: doc.institution_id, source_url: doc.source_url, document_id: doc.id }));

  const speakers = new Map(), laws = new Map();
  for (const t of ts) {
    const key = t.person_id || `s:${t.speaker}`;
    const s = speakers.get(key) || { key, name: t.person || t.speaker, party: t.party, role: t.role, n: 0 };
    s.n++;
    speakers.set(key, s);
    t.leyes.forEach(l => laws.set(l.id, { ...l, n: (laws.get(l.id)?.n || 0) + 1 }));
  }
  const spk = [...speakers.values()].sort((a, b) => b.n - a.n);
  const lawList = [...laws.values()].sort((a, b) => b.n - a.n);
  state.doc = { speaker: null, law: null, find: "", highlight: query };

  view.innerHTML = `<div class="wrap page doc-page">
    ${backLink()}
    <header class="doc-head">
      <p class="eyebrow">${instTag(doc.institution_id, doc.institution)}<span>${fmtDate(doc.date, true)}</span>${doc.legislature ? `<span>Legislatura ${esc(doc.legislature)}</span>` : ""}</p>
      <h1>${esc(cleanTitle(doc.title, doc.date))}</h1>
      <div class="doc-actions">
        <a class="btn ghost" href="${esc(doc.source_url)}" target="_blank" rel="noopener">${icon("ext")}Versión oficial</a>
        <button type="button" class="btn ghost" data-share>${icon("link")}Copiar enlace</button>
        <span class="muted">${num(ts.length)} intervenciones · ${num(spk.length)} oradores${lawList.length ? ` · ${num(lawList.length)} leyes` : ""}</span>
      </div>
    </header>
    <div class="doc-grid">
      <aside class="doc-side"><div class="doc-side-inner">
        <label class="find"><span class="search-ic">${icon("search")}</span><input class="input" id="find" type="search" placeholder="Buscar en esta transcripción"></label>
        <p class="note" id="findcount"></p>
        <h3>Oradores</h3>
        <div class="spk-list">${spk.map(s => `<button type="button" class="spk" data-spk="${esc(s.key)}">${avatar(s.name, s.party, "xs")}<span class="txt">${esc(s.name)}</span><span class="n">${num(s.n)}</span></button>`).join("")}</div>
        ${lawList.length ? `<h3>Leyes mencionadas</h3><div class="spk-list">${lawList.map(l => `<button type="button" class="spk" data-law="${esc(l.id)}"><span class="txt">${esc(l.nombre)}</span><span class="n">${num(l.n)}</span></button>`).join("")}</div>` : ""}
      </div></aside>
      <article class="transcript" id="transcript">${ts.map(t => turnHtml(t, doc, focus, termRegex(query))).join("")}</article>
    </div></div>`;

  const apply = () => {
    const st = state.doc, rx = termRegex(st.find), mark = rx || termRegex(st.highlight);
    let shown = 0, hits = 0;
    for (const t of ts) {
      const el = document.getElementById(`turn-${t.id}`);
      const match = !rx || (rx.lastIndex = 0, rx.test(t.text));
      const ok = (!st.speaker || el.dataset.spk === st.speaker) && (!st.law || el.dataset.laws.split(" ").includes(st.law)) && match;
      el.hidden = !ok;
      if (ok) shown++;
      if (rx && match) hits++;
      $(".turn-text", el).innerHTML = t.text.split(/\n+/).map(p => `<p>${highlight(p, mark)}</p>`).join("");
    }
    $$(".spk").forEach(b => b.classList.toggle("on", b.dataset.spk ? b.dataset.spk === st.speaker : b.dataset.law === st.law));
    $("#findcount").textContent = rx || st.speaker || st.law ? `${num(shown)} de ${num(ts.length)} intervenciones${rx ? ` · ${num(hits)} con «${st.find}»` : ""}` : "";
  };
  $$(".spk[data-spk]").forEach(b => b.onclick = () => { state.doc.speaker = state.doc.speaker === b.dataset.spk ? null : b.dataset.spk; apply(); });
  $$(".spk[data-law]").forEach(b => b.onclick = () => { state.doc.law = state.doc.law === b.dataset.law ? null : b.dataset.law; apply(); });
  let timer;
  $("#find").oninput = e => { clearTimeout(timer); timer = setTimeout(() => { state.doc.find = e.target.value; apply(); }, 200); };
  if (focus) requestAnimationFrame(() => document.getElementById(`turn-${focus}`)?.scrollIntoView({ block: "start" }));
}

/* ---------- votes ---------- */

async function renderVotes(view, token, params) {
  const text = params.get("q") || "", page = Math.max(1, +params.get("p") || 1);
  document.title = "Votaciones · Pleno";
  view.innerHTML = `<div class="wrap page">${skLines(3)}</div>`;
  let d;
  try { [d] = await Promise.all([call(`/votaciones?q=${encodeURIComponent(text)}&pagina=${page}&limite=30`), options()]); }
  catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e)}</div>`; return; }
  if (token !== routeSeq) return;
  const pages = Math.ceil(d.total / 30);
  view.innerHTML = `<div class="wrap page">
    <header class="page-head"><p class="eyebrow">${icon("vote")}Cámara de Diputados · LXVI Legislatura</p>
      <h1>Votaciones nominales</h1>
      <p class="lede-sm">Cada votación del Pleno con el sentido del voto de cada diputada y diputado, según el Sistema de Información Legislativa.</p>
      <form class="inline-search" id="vq"><span class="search-ic">${icon("search")}</span><input class="input" name="q" value="${esc(text)}" placeholder="reforma judicial, Guardia Nacional, presupuesto…"><button class="btn primary">Buscar</button></form>
    </header>
    <p class="count"><strong>${num(d.total)}</strong> votaciones${text ? ` sobre «${esc(text)}»` : ""}</p>
    <div class="panel vote-list">${d.votaciones.map(voteRow).join("") || '<p class="empty">Sin votaciones.</p>'}</div>
    ${pages > 1 ? `<nav class="pager">${page > 1 ? `<a class="btn ghost sm" href="#/votaciones?${new URLSearchParams({ q: text, p: page - 1 })}">Anteriores</a>` : ""}
      <span class="muted">Página ${page} de ${pages}</span>${page < pages ? `<a class="btn ghost sm" href="#/votaciones?${new URLSearchParams({ q: text, p: page + 1 })}">Siguientes</a>` : ""}</nav>` : ""}
  </div>`;
  $("#vq").onsubmit = e => { e.preventDefault(); location.hash = `#/votaciones?${new URLSearchParams({ q: e.target.q.value.trim() })}`; };
}

async function renderVote(view, token, vid) {
  view.innerHTML = `<div class="wrap page">${skLines(4)}</div>`;
  let d;
  try { [d] = await Promise.all([call(`/votaciones/${encodeURIComponent(vid)}`), options()]); }
  catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e, e.status !== 404)}</div>`; return; }
  if (token !== routeSeq) return;
  const v = d.votacion, rebels = d.votos.filter(c => c.contra_bancada);
  document.title = `${cleanVoteTitle(v.title).slice(0, 60)} · Pleno`;
  const parties = Object.entries(d.por_partido).sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y, 0) - Object.values(a[1]).reduce((x, y) => x + y, 0));
  const groups = SENSE_ORDER.concat(["Otros"]).map(sense => [sense, d.votos.filter(c => sense === "Otros" ? !SENSE_ORDER.includes(c.sense) : c.sense === sense)]).filter(([, l]) => l.length);
  const who = c => c.person_id ? `<a href="#/persona/${encodeURIComponent(c.person_id)}">${esc(c.nombre)}</a>` : esc(c.nombre);
  view.innerHTML = `<div class="wrap page">
    ${backLink()}
    <header class="page-head"><p class="eyebrow">${icon("vote")}${esc(v.institution)} · ${fmtDate(v.date, true)}</p>
      <h1 class="vote-h1">${esc(cleanVoteTitle(v.title))}</h1>
      <div class="doc-actions"><a class="btn ghost" href="${esc(v.source_url)}" target="_blank" rel="noopener">${icon("ext")}Fuente oficial</a>
        <button type="button" class="btn ghost" data-share>${icon("link")}Copiar enlace</button></div></header>
    <section class="panel"><div class="panel-head"><h2>Resultado</h2></div>${voteBar({ "A favor": v.a_favor, "En contra": v.en_contra, "Abstención": v.abstencion, "Ausente": v.ausente, ...(v.otros ? { Otros: v.otros } : {}) })}</section>
    <div class="page-grid">
      <div class="main-col">
        <section class="panel"><div class="panel-head"><h2>Por grupo parlamentario</h2></div>
          <div class="party-votes">${parties.map(([party, senses]) => `<div class="pv-row"><span class="pv-name">${pill(party)}</span>${voteBar(senses, { legend: false })}
            <span class="pv-n">${SENSE_ORDER.slice(0, 3).map(k => `${num(senses[k] || 0)}`).join(" · ")}</span></div>`).join("")}</div>
          <p class="note">A favor · en contra · abstención.</p></section>
        ${groups.map(([sense, list]) => `<section class="panel"><div class="panel-head"><h2>${sense} <span class="muted">${num(list.length)}</span></h2></div>
          <ul class="name-grid">${list.map(c => `<li class="${c.contra_bancada ? "rebel" : ""}">${pill(c.party)}${who(c)}</li>`).join("")}</ul></section>`).join("")}
      </div>
      <aside class="side-col">
        <section class="panel"><div class="panel-head"><h2>Votaron distinto a su bancada</h2><p class="sub">Contra el sentido mayoritario de su propio grupo.</p></div>
          ${rebels.length ? `<ul class="plain">${rebels.map(c => `<li>${pill(c.party)} ${who(c)} <span class="sense s-${senseKey(c.sense)}">${esc(c.sense)}</span></li>`).join("")}</ul>` : '<p class="note">Nadie: todos votaron con su grupo o no votaron.</p>'}</section>
      </aside>
    </div></div>`;
}

/* ---------- sources inventory ---------- */

const STATUS = {
  "integrada": ["ok", "Integrada"], "pendiente": ["pend", "Pendiente"], "bloqueada": ["block", "Bloqueada por robots.txt"],
  "sin publicar": ["nopub", "No publicada en línea"], "caída": ["down", "Sitio caído"],
};

async function renderSources(view, token) {
  document.title = "Fuentes · Pleno";
  view.innerHTML = `<div class="wrap page">${skLines(6)}</div>`;
  let list;
  try { list = await call("/fuentes"); } catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e)}</div>`; return; }
  if (token !== routeSeq) return;
  const count = st => list.filter(f => f.estatus === st).length;
  const card = f => {
    const [cls, label] = STATUS[f.estatus] || ["pend", f.estatus];
    const cov = f.cobertura;
    return `<article class="source s-${cls}">
      <header><span class="status ${cls}">${label}</span><span class="muted">${esc(f.nivel)}${f.estado ? ` · ${esc(f.estado)}` : ""}</span></header>
      <h3>${esc(f.nombre)}</h3>
      ${cov?.documentos ? `<p class="cov"><b>${num(cov.documentos)}</b> ${f.id === "sitl" ? "votaciones" : f.id === "sesnsp" ? "registros mensuales" : "documentos"} · ${fmtDate(cov.desde)} – ${fmtDate(cov.hasta)}</p>` : ""}
      <p class="muted">${esc(f.formato || "")}</p>
      ${f.nota ? `<p class="note">${esc(f.nota)}</p>` : ""}
      ${f.ultima_corrida ? `<p class="note">Última revisión ${esc(f.ultima_corrida.ultima.replace("T", " "))}${f.ultima_corrida.error ? ` · <span class="err">error: ${esc(f.ultima_corrida.error)}</span>` : ""}</p>` : ""}
      <a href="${esc(f.url)}" target="_blank" rel="noopener">${icon("ext")}Sitio oficial</a></article>`;
  };
  const section = (title, items) => items.length ? `<h2 class="group-h">${title}</h2><div class="source-grid">${items.map(card).join("")}</div>` : "";
  view.innerHTML = `<div class="wrap page">
    <header class="page-head"><p class="eyebrow">Transparencia sobre la cobertura</p><h1>Fuentes</h1>
      <p class="lede-sm">Todas las fuentes públicas que revisamos, integradas o no, y por qué. Solo usamos sitios oficiales o datasets con licencia, y respetamos <code>robots.txt</code>: lo que un sitio prohíbe se pide por la Plataforma Nacional de Transparencia.</p>
      <div class="status-sum">${Object.entries(STATUS).map(([k, [cls, label]]) => count(k) ? `<span class="status ${cls}">${label} · ${count(k)}</span>` : "").join("")}</div></header>
    ${section("Federales", list.filter(f => f.nivel === "federal"))}
    ${section("Congresos estatales", list.filter(f => f.nivel === "estatal").sort((a, b) => Object.keys(STATUS).indexOf(a.estatus) - Object.keys(STATUS).indexOf(b.estatus) || a.estado.localeCompare(b.estado)))}
    ${section("Municipales", list.filter(f => f.nivel === "municipal"))}
  </div>`;
}

/* ---------- alerts ---------- */

async function renderAlerts(view, token) {
  document.title = "Alertas · Pleno";
  view.innerHTML = `<div class="wrap page">${skLines(4)}</div>`;
  let list;
  try { [list] = await Promise.all([call("/alertas"), options()]); } catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e)}</div>`; return; }
  if (token !== routeSeq) return;
  const chips = q => Object.entries(KINDS).flatMap(([k, def]) => (k === "texto" ? (q.texto ? [q.texto] : []) : q[k] || [])
    .map(v => `<span class="tag">${def.label}: ${esc(labelFor(k, v))}</span>`)).join("") + (q.desde || q.hasta ? `<span class="tag">Fechas: ${esc(dateRangeLabel(q.desde, q.hasta))}</span>` : "");
  view.innerHTML = `<div class="wrap page">
    <header class="page-head"><p class="eyebrow">${icon("bell")}Monitoreo</p><h1>Alertas</h1>
      <p class="lede-sm">Guarda cualquier búsqueda con «Crear alerta». Cada mañana el actualizador baja lo nuevo de todas las fuentes y te dice qué intervenciones nuevas coinciden. Cada alerta tiene su RSS para tu lector de noticias, Slack o correo.</p></header>
    ${list.length ? `<div class="alert-list">${list.map(a => `<article class="panel alert-card">
      <div class="alert-main"><h3><a href="${searchHash({ ...emptyQuery(), ...a.query, orden: "fecha" })}">${esc(a.name)}</a></h3>
        <div class="tags">${chips({ ...emptyQuery(), ...a.query })}</div>
        <p class="note">Creada ${esc(a.created.slice(0, 10))}</p></div>
      <div class="alert-side"><span class="alert-n ${a.nuevas ? "hot" : ""}"><b>${num(a.nuevas)}</b> nuevas</span>
        <a class="btn ghost sm" href="/api/v1/alertas/${encodeURIComponent(a.id)}.rss" target="_blank" rel="noopener">${icon("rss")}RSS</a>
        <button type="button" class="btn link sm" data-del="${esc(a.id)}">${icon("trash")}Borrar</button></div></article>`).join("")}</div>`
      : `<div class="empty"><p class="empty-title">Aún no tienes alertas</p><p>Haz una búsqueda y pulsa «Crear alerta».</p><a class="btn primary" href="#/">Ir a buscar</a></div>`}
  </div>`;
  $$("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("¿Borrar esta alerta?")) return;
    await fetch(`${API}/alertas/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
    route();
  });
}

/* ---------- first run on someone's computer ---------- */

const fmtBytes = n => n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${Math.round(n / 1e6)} MB`;

async function renderInstall(view, token) {
  document.title = "Bienvenido · Pleno";
  let info;
  try { info = await call("/instalacion"); } catch (e) { if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e)}</div>`; return; }
  if (token !== routeSeq) return;
  const running = info.estado.activo || info.estado.terminado || info.estado.error;
  view.innerHTML = `<div class="wrap page install">
    <header class="page-head"><p class="eyebrow">${icon("spark")}Bienvenido</p><h1>Vamos a traer los datos</h1>
      <p class="lede-sm">Pleno vive en tu computadora. Elige cómo conseguir los datos públicos; puedes cambiar de opinión después.</p></header>
    <div id="install-body">${running ? "" : installChoices(info)}</div>
  </div>`;
  if (running) return installProgress(token);
  $$(".choice input[name=modo]").forEach(r => r.onchange = () => {
    $("#src-list").hidden = $("input[name=modo]:checked").value !== "fuentes";
  });
  $("#install-form").onsubmit = async e => {
    e.preventDefault();
    const modo = $("input[name=modo]:checked").value;
    const fuentes = $$("#src-list input:checked").map(i => i.value);
    const btn = $("#install-go");
    btn.disabled = true; btn.textContent = "Empezando…";
    try {
      const r = await call("/instalacion", { modo, fuentes, diario: $("#daily").checked });
      if (r.diario) state.installNote = r.diario;
      installProgress(token);
    } catch (err) { btn.disabled = false; btn.textContent = "Empezar"; $("#install-body").insertAdjacentHTML("beforeend", errorBox(err, false)); }
  };
}

function installChoices(info) {
  return `<form id="install-form" class="install-form">
    <label class="choice panel"><input type="radio" name="modo" value="rapido" checked>
      <span><b>Rápido <em class="pill-rec">recomendado</em></b>
      <span class="muted">Descarga la base ya armada (≈2 GB) desde Hugging Face. Tarda unos minutos, según tu internet. Después, cada día, Pleno trae lo nuevo directo de las fuentes oficiales.</span></span></label>
    <label class="choice panel"><input type="radio" name="modo" value="fuentes">
      <span><b>Desde las fuentes oficiales</b>
      <span class="muted">Tu computadora descarga y procesa cada fuente desde los sitios oficiales. Tarda horas; puedes usar Pleno mientras avanza.</span></span></label>
    <div id="src-list" class="panel src-list" hidden>
      ${info.fuentes.map(f => `<label><input type="checkbox" value="${esc(f.id)}" ${f.pre ? "checked" : ""}> <span>${esc(f.nombre)}</span> <span class="muted">${esc(f.tiempo)}</span></label>`).join("")}
    </div>
    <label class="daily"><input type="checkbox" id="daily" checked> Actualizar cada día a las 7:00 con lo nuevo de las fuentes oficiales</label>
    <p class="note">Respetamos las reglas de cada sitio (robots.txt) y descargamos despacio para no saturarlos. Los datos se quedan en tu computadora.</p>
    <button class="btn primary big-btn" id="install-go" type="submit">Empezar</button>
  </form>`;
}

async function installProgress(token) {
  const body = $("#install-body");
  const tick = async () => {
    if (token !== routeSeq) return;
    let info;
    try { info = await call("/instalacion"); } catch (e) { setTimeout(tick, 3000); return; }
    const st = info.estado, pct = st.progreso ?? 0;
    body.innerHTML = `<div class="panel install-progress">
      <p class="install-stage">${esc(st.etapa || "Preparando…")}</p>
      <div class="bar"><span style="width:${pct}%"></span></div>
      <p class="muted">${st.total ? `${fmtBytes(st.bytes)} de ${fmtBytes(st.total)} · ` : ""}${pct ? `${pct}%` : ""}</p>
      ${state.installNote ? `<p class="note">${esc(state.installNote)}</p>` : ""}
      ${st.bitacora?.length ? `<pre class="install-log">${esc(st.bitacora.join("\n"))}</pre>` : ""}
      ${st.error ? `<div class="error-box"><p><b>Algo falló:</b> ${esc(st.error)}</p><p>Revisa tu conexión y vuelve a intentarlo.</p><button class="btn ghost" id="install-retry">Volver a intentar</button></div>` : ""}
      ${st.terminado ? `<a class="btn primary big-btn" href="#/" id="install-done">Explorar Pleno ${icon("arrow")}</a>` : ""}
      ${st.modo === "fuentes" && !st.terminado && !st.error ? `<a class="btn ghost" href="#/">Usar Pleno mientras termina</a>` : ""}
    </div>`;
    if (st.terminado) { optionsPromise = null; optionsCache = null; return; }
    if (st.error) { $("#install-retry").onclick = () => { location.hash = "#/instalar"; route(); }; return; }
    setTimeout(tick, 1500);
  };
  tick();
}

/* ---------- verify a claim ---------- */

const VERIFY_EXAMPLES = [
  "Kenia López Rabadán votó en contra de la reforma judicial",
  "Claudia Sheinbaum dijo «no somos iguales»",
  "La presidenta dijo que bajaron los homicidios en 2025",
  "Aumentaron los feminicidios en Jalisco en 2026",
];
const VERDICT_TONE = { respaldada: "ok", contradicha: "no", mixta: "mixed", sin_evidencia: "none", revisar: "none" };

async function renderVerify(view, token, params) {
  document.title = "Verificar · Pleno";
  const claim = params.get("a") || "";
  view.innerHTML = `<div class="wrap page verify">
    <header class="page-head"><p class="eyebrow">${icon("check")}Cotejo con el registro</p><h1>Verificar una afirmación</h1>
      <p class="lede-sm">Escribe lo que alguien dice que se dijo o se votó. Pleno lo compara con las versiones estenográficas y las votaciones nominales, y te muestra la evidencia. No califica si algo es verdad en el mundo: dice qué muestra el registro oficial.</p></header>
    <form class="verify-form panel" id="verify-form">
      <label for="claim" class="sr-only">Afirmación</label>
      <textarea id="claim" rows="3" maxlength="500" placeholder="Ej.: Kenia López Rabadán votó en contra de la reforma judicial">${esc(claim)}</textarea>
      <div class="verify-actions"><div class="tags">${VERIFY_EXAMPLES.map(e => `<button type="button" class="tag ex" data-ex="${esc(e)}">${esc(e)}</button>`).join("")}</div>
        <button class="btn primary" type="submit">${icon("check")}Verificar</button></div>
    </form>
    <div id="verdict"></div>
  </div>`;
  $("#verify-form").onsubmit = e => {
    e.preventDefault();
    const a = $("#claim").value.trim();
    if (a.length >= 8) location.hash = `#/verificar?${new URLSearchParams({ a })}`;
  };
  $$("[data-ex]").forEach(b => b.onclick = () => { location.hash = `#/verificar?${new URLSearchParams({ a: b.dataset.ex })}`; });
  if (!claim) return;
  const out = $("#verdict");
  out.innerHTML = `<div class="panel">${skLines(4)}<p class="note">Buscando en el registro… si hace falta el modelo, puede tardar.</p></div>`;
  let r;
  try { r = await call("/verificar", { afirmacion: claim }); } catch (e) { if (token === routeSeq) out.innerHTML = errorBox(e); return; }
  if (token !== routeSeq) return;
  const sources = r.fuentes || [];
  const evidence = (r.evidencias || []).map(e => {
    const h = sources[e.n - 1];
    return `<li class="ev ev-${esc(e.postura)}"><span class="ev-tag">${esc(e.postura)}</span>
      <blockquote>«${esc(e.cita)}»</blockquote>
      <p class="meta">${esc(h.person || h.speaker)} · ${instTag(h.institution_id, h.institution)} · ${fmtDate(h.date)}
        · <a href="${docHash(h.document_id, h.id, e.cita)}">Leer en contexto</a> · <a href="${esc(h.source_url)}" target="_blank" rel="noopener">Fuente oficial ${icon("ext")}</a></p></li>`;
  }).join("");
  const appearances = (r.apariciones || []).map(t => `<li><b>${esc(t.speaker)}</b> · ${esc(t.institution)} · ${fmtDate(t.date)}
      · <a href="${docHash(t.document_id, t.id)}">Leer en contexto</a> · <a href="${esc(t.source_url)}" target="_blank" rel="noopener">Fuente oficial ${icon("ext")}</a></li>`).join("");
  const votes = (r.votaciones || []).map(v => `<li class="ev-vote"><span class="sense s-${senseKey(v.sense)}">${esc(v.sense)}</span>
      <a href="#/votacion/${encodeURIComponent(v.id)}">${esc(cleanVoteTitle(v.title))}</a> <span class="muted">${fmtDate(v.date)}</span></li>`).join("");
  const related = !r.evidencias?.length && sources.length ? sources.slice(0, 6).map(h => `<li><b>${esc(h.person || h.speaker)}</b> · ${fmtDate(h.date)}
      <blockquote>«${esc(h.snippet.replace(/[⟦⟧]/g, ""))}»</blockquote><a href="${docHash(h.document_id, h.id)}">Leer en contexto</a></li>`).join("") : "";
  const fig = r.cifras;
  const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const figures = fig ? (() => {
    const y = fig.comparacion.anio, by = {};
    fig.mensual.forEach(m => { (by[m.mes] ||= {})[m.anio] = m.valor; });
    const max = Math.max(1, ...fig.mensual.map(m => m.valor));
    const rowsHtml = fig.comparacion.meses.map(m => `<tr><th scope="row">${MES[m - 1]}</th>
      <td><span class="fig-bar prev" style="width:${(100 * (by[m]?.[y - 1] || 0) / max).toFixed(1)}%"></span><span>${num(by[m]?.[y - 1] || 0)}</span></td>
      <td><span class="fig-bar" style="width:${(100 * (by[m]?.[y] || 0) / max).toFixed(1)}%"></span><span>${num(by[m]?.[y] || 0)}</span></td></tr>`).join("");
    return `<section class="panel figures" data-tone="${VERDICT_TONE[fig.veredicto] || "none"}">
      <h2>Cifras oficiales</h2>${r.metodo.startsWith("cifras") ? "" : `<p class="verdict-sub">${esc(fig.etiqueta)}</p><p>${esc(fig.texto)}</p>`}
      <table class="fig-table"><thead><tr><th></th><th>${y - 1}</th><th>${y}</th></tr></thead><tbody>${rowsHtml}</tbody></table>
      <p class="note">Fuente: <a href="${esc(fig.fuente_url)}" target="_blank" rel="noopener">${esc(fig.fuente)} ${icon("ext")}</a>. Se comparan los mismos meses de ambos años.</p></section>`;
  })() : "";
  out.innerHTML = `<article class="panel verdict" data-tone="${VERDICT_TONE[r.veredicto] || "none"}">
      <p class="verdict-label">${icon("check")}${esc(r.etiqueta)}</p>
      <p class="verdict-text">${esc(r.texto || "")}</p>
      <p class="note">Método: ${esc(r.metodo)}${r.modelo ? ` (${esc(r.modelo)})` : ""}. Verifica siempre en la fuente oficial antes de publicar.</p>
      <div class="share-row"><button type="button" class="btn primary sm" id="share-img">${icon("download")}Compartir imagen</button>
        <button type="button" class="btn ghost sm" id="share-link">${icon("link")}Copiar enlace</button></div>
    </article>
    ${r.metodo.startsWith("cifras") ? "" : figures}${r.metodo.startsWith("cifras") ? figures : ""}
    ${votes ? `<section class="panel"><h2>Votación nominal</h2><ul class="ev-list">${votes}</ul></section>` : ""}
    ${evidence ? `<section class="panel"><h2>Evidencia citada</h2><ul class="ev-list">${evidence}</ul></section>` : ""}
    ${appearances ? `<section class="panel"><h2>Dónde aparece la frase</h2><ul class="ev-list">${appearances}</ul></section>` : ""}
    ${related ? `<section class="panel"><h2>Intervenciones relacionadas</h2><ul class="ev-list">${related}</ul></section>` : ""}`;
  $("#share-link").onclick = async e => {
    try { await navigator.clipboard.writeText(location.href); e.target.closest("button").lastChild.textContent = "Enlace copiado"; } catch (err) { prompt("Copia el enlace:", location.href); }
  };
  $("#share-img").onclick = () => shareVerdict(r);
}

// A 1080×1350 card (the feed format of Instagram and X) with the claim, what the record shows and the source.
function wrapLines(ctx, text, maxWidth, maxLines) {
  const words = String(text).split(/\s+/), lines = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (ctx.measureText(next).width > maxWidth && line) { lines.push(line); line = w; } else line = next;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, "…"); }
  return lines;
}
async function shareVerdict(r) {
  await Promise.all(["600 60px Newsreader", "500 40px Newsreader", "600 30px Inter", "400 30px Inter"].map(f => document.fonts.load(f)));
  const W = 1080, H = 1350, c = document.createElement("canvas");
  c.width = W; c.height = H;
  const x = c.getContext("2d"), tone = { ok: "#2f8a57", no: "#c8402e", mixed: "#c79a1e", none: "#7a7169" }[VERDICT_TONE[r.veredicto] || "none"];
  x.fillStyle = "#f6f3ee"; x.fillRect(0, 0, W, H);
  x.fillStyle = "#8c1d40"; x.fillRect(0, 0, W, 14);
  x.fillStyle = "#8c1d40"; x.font = "700 28px Inter"; x.fillText("PLENO · COTEJO CON EL REGISTRO OFICIAL", 80, 110);
  const fig = r.cifras && r.metodo.startsWith("cifras") ? r.cifras : null;
  const body = fig ? fig.texto : r.texto;
  const details = fig ? [`${fig.comparacion.anio - 1}: ${fig.comparacion.anio_anterior.toLocaleString("es-MX")}`, `${fig.comparacion.anio}: ${fig.comparacion.valor.toLocaleString("es-MX")}`]
    : (r.votaciones || []).slice(0, 3).map(v => `${fmtDate(v.date)} · ${v.sense}`)
      .concat((r.apariciones || []).slice(0, 3).map(t => `${t.speaker} · ${fmtDate(t.date)}`));
  const src = fig ? fig.fuente : r.votaciones?.length ? "Sistema de Información Legislativa (votación nominal)"
    : r.apariciones?.length ? "Versiones estenográficas oficiales" : "Versiones estenográficas y registros oficiales";
  // Measure first, then center the block between the header and the footer.
  x.font = "500 60px Newsreader"; const claim = wrapLines(x, `«${r.afirmacion}»`, W - 160, 5);
  x.font = "400 34px Inter"; const lines = wrapLines(x, body || "", W - 240, 6);
  x.font = "400 26px Inter"; const srcLines = wrapLines(x, `Fuente: ${src}.`, W - 240, 2);
  const cardH = 130 + lines.length * 50 + (details.length ? 30 + details.length * 46 : 0) + 30 + srcLines.length * 36 + 40;
  const blockH = claim.length * 74 + 50 + cardH;
  let y = Math.max(180, 150 + (H - 300 - blockH) / 2);
  x.fillStyle = "#1b1714"; x.font = "500 60px Newsreader";
  for (const l of claim) { x.fillText(l, 80, y + 50); y += 74; }
  y += 50;
  x.fillStyle = "#ffffff"; x.beginPath(); x.roundRect(60, y, W - 120, cardH, 28); x.fill();
  x.fillStyle = tone; x.fillRect(60, y, 14, cardH);
  x.font = "600 58px Newsreader"; x.fillText(r.etiqueta, 110, y + 92);
  let yy = y + 160;
  x.fillStyle = "#4b443d"; x.font = "400 34px Inter";
  for (const l of lines) { x.fillText(l, 110, yy); yy += 50; }
  if (details.length) {
    yy += 20;
    x.font = "600 32px Inter"; x.fillStyle = "#1b1714";
    for (const d of details) { x.fillStyle = tone; x.fillRect(110, yy - 22, 10, 10); x.fillStyle = "#1b1714"; x.fillText(d, 136, yy); yy += 46; }
  }
  yy += 20;
  x.fillStyle = "#7a7169"; x.font = "400 26px Inter";
  for (const l of srcLines) { x.fillText(l, 110, yy); yy += 36; }
  x.fillStyle = "#8c1d40"; x.font = "600 46px Newsreader"; x.fillText("Pleno", 80, H - 90);
  x.fillStyle = "#7a7169"; x.font = "400 26px Inter"; x.fillText("No dice si algo es verdad: muestra lo que dice el registro.", 80, H - 50);
  x.textAlign = "right"; x.fillText(location.host, W - 80, H - 90); x.textAlign = "left";
  const blob = await new Promise(res => c.toBlob(res, "image/png"));
  const file = new File([blob], "pleno-verificacion.png", { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    try { await navigator.share({ files: [file], text: `${r.etiqueta}: «${r.afirmacion}» ${location.href}` }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = file.name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------- router ---------- */

async function route() {
  const token = ++routeSeq, view = $("#view");
  visited++;
  const raw = location.hash.slice(1) || "/";
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(qs || "");
  const page = parts[0] || "inicio";
  const prev = document.body.dataset.page;
  document.body.dataset.page = page;
  closeMenu();
  tip.hide();
  view.classList.remove("is-loading");
  if (page !== "buscar") state.search = null;
  if (!(page === "buscar" && prev === "buscar")) window.scrollTo(0, 0);
  if (page !== "buscar") $("#top-search input").value = "";
  try {
    if (page !== "instalar") {
      const o = await options().catch(() => null);
      if (o?.instalacion_necesaria && token === routeSeq) { location.hash = "#/instalar"; return; }
    }
    if (page === "buscar") await renderSearch(view, token, params);
    else if (page === "persona" && parts[1]) await renderPerson(view, token, parts[1]);
    else if (page === "ley" && parts[1]) await renderLaw(view, token, parts[1]);
    else if (page === "votaciones") await renderVotes(view, token, params);
    else if (page === "votacion" && parts[1]) await renderVote(view, token, parts.slice(1).join("/"));
    else if (page === "fuentes") await renderSources(view, token);
    else if (page === "alertas") await renderAlerts(view, token);
    else if (page === "verificar") await renderVerify(view, token, params);
    else if (page === "instalar") await renderInstall(view, token);
    else if (page === "documento" && parts[1]) await renderDocument(view, token, parts.slice(1).join("/"), params);
    else { document.body.dataset.page = "inicio"; await renderHome(view, token); }
  } catch (e) {
    if (token === routeSeq) view.innerHTML = `<div class="wrap page">${errorBox(e)}</div>`;
    console.error(e);
  }
}

function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("pleno-tema", t) : localStorage.removeItem("pleno-tema"); } catch (e) { /* private mode */ }
  paintThemeButton();
}
function currentTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function paintThemeButton() { $("#theme").innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon"); }

function init() {
  $$(".logo-mark").forEach(el => { el.innerHTML = logoMark(); });
  mountSearch($("#top-search"));
  paintThemeButton();
  $("#theme").onclick = () => setTheme(currentTheme() === "dark" ? "light" : "dark");
  options().catch(() => {});

  document.addEventListener("click", e => {
    const t = e.target.closest("[data-copy], [data-share], [data-back], [data-retry]");
    if (!e.target.closest("#fmenu") && !e.target.closest("#addfilter")) closeMenu();
    if (!t) return;
    if (t.matches("[data-copy]")) { const r = turns.get(+t.dataset.copy); if (r) copy(citation(r), "Cita copiada con su fuente."); }
    else if (t.matches("[data-share]")) copy(location.href, "Enlace copiado.");
    else if (t.matches("[data-retry]")) route();
    else if (t.matches("[data-back]")) {
      e.preventDefault();
      if (visited > 1) history.back(); else location.hash = "#/";
    }
  });
  document.addEventListener("mouseover", e => {
    const t = e.target.closest("[data-tip]");
    if (t) { const r = t.getBoundingClientRect(); tip.show(t.dataset.tip, r.left + r.width / 2, r.top); }
  });
  document.addEventListener("mouseout", e => { if (e.target.closest("[data-tip]")) tip.hide(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeMenu(); tip.hide(); }
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      (document.body.dataset.page === "inicio" ? $("#hero-search input") : $("#top-search input"))?.focus();
    }
  });
  window.addEventListener("hashchange", route);
  route();
}

init();
