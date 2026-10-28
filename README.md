# Pleno · ¿Lo dijo? ¿Lo votó? ¿Es cierto?

Pleno junta lo que se dice en el poder público de México (conferencias matutinas, Cámara de Diputados, Suprema Corte,
Fiscalía General, fiscalías y congresos estatales, cifras oficiales de delitos) y lo vuelve **buscable y cotejable**:
quién habló, con qué cargo, de qué partido, sobre qué ley, cómo votó. Cada resultado enlaza a su fuente oficial.

Es gratis, de código abierto y **vive en tu computadora**: los datos se descargan ahí, no en un servidor ajeno.

## Instalar (5 minutos)

Presentación con capturas y video: https://pescamill.github.io/pleno/

**Mac** — abre la app **Terminal**, pega esta línea y presiona Enter:

```bash
curl -LsSf https://raw.githubusercontent.com/pescamill/pleno/main/instalar.sh | sh
```

**Windows** — abre **PowerShell** (búscalo en el menú Inicio), pega esta línea y presiona Enter:

```powershell
irm https://raw.githubusercontent.com/pescamill/pleno/main/instalar.ps1 | iex
```

Linux: la misma línea que en Mac.

Qué pasa después:
1. Se instala todo lo necesario (incluido Python, sin tocar el que ya tengas) en la carpeta `Pleno` de tu usuario.
2. Aparece **Pleno** en tu Escritorio y se abre en tu navegador.
3. La primera vez te pregunta **cómo traer los datos**:
   - **Rápido** (recomendado): la base ya armada, ≈2 GB, en minutos.
   - **Desde las fuentes oficiales**: tu computadora descarga y procesa cada sitio oficial; tarda horas y puedes usar
     Pleno mientras avanza.
4. Si lo eliges, **se actualiza cada día a las 7:00** con lo nuevo de las fuentes oficiales.

Para abrirlo otra vez: doble clic en **Pleno** en tu Escritorio. Para apagarlo: cierra la ventana negra que se abre
junto. Para actualizar Pleno a la versión más nueva: vuelve a pegar la misma línea (tus datos se conservan).

### Qué hace y qué no

- **Buscar** en español: «¿Qué dijo la presidenta sobre el agua en 2025?».
- **Verificar** una afirmación: votos contra la votación nominal, citas contra el texto exacto, cifras de delitos
  contra el SESNSP. Te muestra la evidencia y la fuente.
- **Votaciones**: cómo votó cada diputado y quién votó distinto a su bancada.
- **Alertas** con RSS, **exportar** a CSV y una **API** local.

Límites: Pleno **no decide qué es verdad**; muestra lo que dice el registro oficial. **No está todo**: el Senado y
algunos congresos prohíben robots y se piden por transparencia. **Es automático y puede fallar**: antes de publicar,
abre la fuente oficial.

## Qué hay hoy

| Fuente | Qué es | Cobertura |
|---|---|---|
| Presidencia | Conferencias matutinas, vía [feregrino/mananeras](https://huggingface.co/datasets/feregrino/mananeras) (CC BY-SA 4.0) | dic 2018 → hoy |
| Cámara de Diputados | Versiones estenográficas por sesión (`cronica.diputados.gob.mx`) | LXVI, sept 2024 → hoy |
| Cámara de Diputados (SITL) | Padrón oficial (partido, distrito, curul, comisiones) y **votaciones nominales** | LXVI |
| Suprema Corte | Versiones taquigráficas del Pleno (`scjn.gob.mx`) | sept 2024 → hoy |
| Congresos estatales | CDMX, Oaxaca, Quintana Roo, Tabasco, Nuevo León, Guerrero (PDF con texto) | legislatura actual |
| Catálogo de leyes federales | Leyes vigentes de la Cámara de Diputados: estandariza nombres y enlaza al texto oficial | vigente |

El inventario completo de lo revisado, incluidas las fuentes bloqueadas por `robots.txt` y las que no publican, está en
`pleno/fuentes.py` y en la página **Fuentes** (`#/fuentes`). Las solicitudes de transparencia para lo que falta están en
`docs/solicitudes-transparencia.md`.

## Modelo de datos

```
institutions ─┐
              └─ documents (sesión / conferencia: fecha, legislatura, fuente)
                    └─ turns (intervención: texto, orador, cargo, medio)
                          ├─ people (nombre, partido + de dónde salió ese dato)
                          └─ mentions ── laws (leyes citadas; federal o estatal, con liga oficial si está en el catálogo)
memberships (padrón oficial: persona × órgano × legislatura) · votes ── vote_casts (sentido de cada voto)
runs (bitácora de cada corrida) · alerts (búsquedas guardadas)
```

- **Partido:** se toma de lo que dice la propia sesión («…del Grupo Parlamentario de Morena»). Nunca se adivina, y el
  campo `source` dice de dónde salió.
- **Personas:** «Kenia López» se une con «Kenia López Rabadán» solo si todos los tokens coinciden (dos o más); el
  mismo nombre en otro orden se une; una forma corta dominante (3+ palabras, 10× las intervenciones) absorbe variantes
  largas raras. Etiquetas sin nombre («Beneficiaria del Programa…», «Habitante de…») no se vuelven personas.
- **Medio:** solo cuando el periodista lo dice en la transcripción. Nunca se crean perfiles de periodistas.
- **Leyes:** se detectan por nombre («Ley de Amparo», «Código Nacional de…», «Constitución Política…»).

## Consultas

Una pregunta en español se traduce a una **consulta estructurada visible y editable**:

```
«Diputados de Movimiento Ciudadano que mencionan la Ley de Amparo»
→ {instituciones: [diputados], partidos: [MC], leyes: [ley-de-amparo]}
```

La traducción usa reglas, no un modelo: es reproducible y se ve como chips en la interfaz. La pestaña
**Respuesta con fuentes** usa un LLM (local con Ollama, o cualquier endpoint compatible) que solo puede usar las
intervenciones recuperadas y debe citarlas por número. Si cita algo inexistente, la cita se borra.

## Estandarización

- **Partido:** padrón oficial primero (SITL); si no hay, lo que dice la sesión de la propia legislatura.
- **Personas:** variantes de nombre se unen solo dentro del mismo órgano o entre órganos federales; nunca entre
  congresos de estados distintos.
- **Leyes:** se comparan con el catálogo oficial de leyes federales. En un congreso estatal, «Ley de Ingresos» es la
  del estado (`ley-de-ingresos-oaxaca`) y «la Constitución» sin más no se asume federal.
- **Preguntas:** «diputados de Oaxaca» filtra el congreso de Oaxaca; «la presidenta sobre Jalisco» busca Jalisco como tema.

## Actualización y alertas

```bash
.venv/bin/python -m pleno actualizar          # baja solo lo nuevo de cada fuente y revisa las alertas
.venv/bin/python -m pleno programar           # lo corre cada día a las 7:00 (LaunchAgent de macOS)
.venv/bin/python -m pleno programar --quitar  # lo desinstala
.venv/bin/python -m pleno fuentes             # inventario y cobertura
```

Cada corrida queda en la tabla `runs`; una fuente que falla se registra y no detiene a las demás. Las alertas
(«Crear alerta» en la búsqueda) generan un RSS por alerta (`/api/v1/alertas/<id>.rss`) y un resumen diario en
`data/alertas/resumen-AAAA-MM-DD.md`, con notificación de macOS si hay coincidencias.

## Desarrollo

```bash
uv sync --extra dev                          # o: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pleno ingerir            # descarga y carga (Diputados ~15 min la primera vez; luego incremental)
.venv/bin/python -m pleno servir             # http://127.0.0.1:8780  ·  documentación de la API en /docs
.venv/bin/python -m pytest
```

Las mañaneras se leen de `data/mananeras` (se descargan de Hugging Face), de `../neta/data/raw/mananeras` si existe,
o de `PLENO_MANANERAS_DIR`. `pleno abrir` es lo que corre el acceso directo: elige un puerto libre y abre el navegador.

## Interfaz

Una sola página sin compilación (`web/`), con rutas que se pueden compartir:

- `#/` inicio: leyes en la conversación (90 días contra los 90 previos), voces más activas, lo más reciente por fuente.
- `#/buscar?…` resultados: consulta en chips editables, gráfica por mes (clic en un mes o arrastra para acotar
  fechas), facetas por partido, persona, ley, institución, cargo y medio, respuesta con fuentes citadas, CSV.
- `#/persona/<id>`, `#/ley/<id>`: perfil, actividad por mes, cargos, leyes, quién la menciona.
- `#/documento/<id>?t=<turno>`: la transcripción completa con filtro por orador o ley y búsqueda dentro.

La caja de búsqueda sugiere personas y leyes mientras escribes (`/` la enfoca). Tema claro y oscuro.

## API

`/docs` muestra la documentación interactiva (OpenAPI). Endpoints `v1`:
`POST /buscar`, `POST /interpretar`, `POST /responder`, `POST /exportar` (CSV), `GET /panorama`, `GET /sugerir`,
`GET /votaciones`, `GET /votaciones/{id}`, `GET /fuentes`, `GET|POST /alertas`, `GET /alertas/{id}.rss`,
`GET /personas`, `GET /personas/{id}`, `GET /leyes`, `GET /leyes/{id}`, `GET /documentos/{id}`, `GET /estado`.

- Sin llave: 30 consultas por minuto por IP; el autocompletado tiene su propia cuota (5×).
- Con `X-API-Key` (en `data/keys.json`): límite por plan (`gratis` 60/min, `pro` 600/min). El cobro se conecta después.
- Exportar CSV: hasta 500 filas sin llave, 2,000 con `gratis` y 20,000 con `pro`.

## Verificar, evaluar y exportar

- **`pleno verificar "afirmación"`** (y la página «Verificar», `POST /api/v1/verificar`): compara la afirmación con el
  registro y responde respaldada, contradicha, mixta, sin evidencia o «revisar». Votos y citas textuales se cotejan
  exactamente, sin modelo. Cifras de delitos («bajaron los homicidios en 2025») se cotejan con el SESNSP, comparando
  los mismos meses de ambos años. Lo demás pasa por el modelo, y solo cuentan las citas que aparecen literalmente en
  la fuente. Pleno no dice si algo es verdad en el mundo: dice qué muestra el registro oficial.
- **`pleno evaluar`**: mide integridad, atribución de oradores y partidos, ruido en leyes, búsqueda (recall@10 de una
  cita a su documento), intérprete de preguntas (`evals/nlq.json`) y verificador (casos construidos del propio
  registro) y que los errores reportados sigan corregidos (`evals/reportes.json`). Guarda cada corrida en `data/evals/historial.jsonl` y marca regresiones contra la anterior; sale con
  código 1 si hay alguna. Corre sola después de cada actualización diaria.
- **`pleno dataset`**: snapshot en Parquet para venta o entrenamiento (`data/dataset/pleno-AAAA-MM-DD/`), separado por
  licencia (mañaneras CC BY-SA 4.0; textos oficiales, LFDA art. 14 fr. VIII), con periodistas por papel y no por nombre,
  personas detenidas seudonimizadas, ficha del dataset, licencias y manifiesto SHA-256.
- **`GET /api/v1/estadistica?delito=homicidios&estado=Jalisco`**: serie mensual oficial del SESNSP.

## Reportar un error

En Pleno, cada resultado, verificación, votación, persona y documento tiene **Reportar un error**. Abre un reporte en
[GitHub](https://github.com/pescamill/pleno/issues/new?template=error-de-datos.yml) con lo que estás viendo ya escrito
(o lo copia, si no tienes cuenta). Cada error confirmado se corrige en el código y se agrega como caso a
`evals/reportes.json`: `pleno evaluar` falla si vuelve a aparecer.

## Hospedaje

Hoy corre en tu Mac (la base pesa menos de 2 GB). El `Dockerfile` está listo para un Space de Hugging Face
(puerto 7860). La base se puede publicar como dataset para que el Space la descargue al iniciar.
Publicar es un paso público: se hace solo cuando lo decidas.

## Reglas

- Solo fuentes oficiales o datasets con licencia. Se respeta `robots.txt`: el Senado lo prohíbe y por eso no se
  incluye (pendiente: datos abiertos o solicitud de transparencia).
- No se extraen redes sociales, ni señales de televisión o radio. Los organismos de radiodifusión tienen derechos
  sobre la fijación de sus señales (LFDA art. 144).
- Los textos de los actos oficiales no están protegidos (LFDA art. 14 fr. VIII, por confirmar con un abogado).
  Pleno vende estructura, búsqueda, alertas y API, no exclusividad sobre los textos.

## Licencia

Código: [MIT](LICENSE). Los datos conservan la licencia de su fuente (ver `pleno dataset`).

## Siguiente

- Congresos estatales: Oaxaca (PDF), Guanajuato (PDF) y cabildo de Guadalajara (portal de transparencia).
- Whisper local para sesiones que solo existen en video, desde sitios oficiales.
- Alertas («avísame cuando alguien mencione X»), exportes CSV y servidor MCP para agentes.
