# Qué se ha añadido, y para qué sirve

Registro de cada iteración de Pleno: lo nuevo y casos de uso concretos. Se actualiza después de cada entrega.

---

## Iteración 10 · Instalación local y código abierto (28 oct 2026)

**Qué se añadió**
- **Repositorio público**: https://github.com/pescamill/pleno (los commits usan el correo privado de GitHub).
- **Instalador de una línea** para Mac/Linux (`instalar.sh`) y Windows (`instalar.ps1`): instala `uv` (que trae su propio
  Python), descarga Pleno en la carpeta del usuario, deja **Pleno** en el Escritorio y lo abre en el navegador.
  Volver a correrlo actualiza Pleno sin borrar los datos.
- **Asistente de primera vez** (`#/instalar`): elegir **Rápido** (base lista de Hugging Face, ≈2 GB) o **Desde las
  fuentes oficiales** (horas, con la lista de fuentes y tiempos), con barra de progreso, y programar la
  actualización diaria (launchd en Mac, Programador de tareas en Windows, cron en Linux).
- **Actualización por fuente**: cada fuente se reanuda desde su último documento (menos 14 días), así una instalación
  nueva no vuelve a descargar todo cada día. Las mañaneras se actualizan desde Hugging Face sin necesidad de `git`.
- **La base se cambia sin reiniciar** (y sin sobrescribir un archivo abierto, que Windows no permite).
- `pleno abrir`: lo que corre el acceso directo; elige un puerto libre y abre el navegador.
- Se dio de baja la demo en Render (servicio y Blueprint borrados).
- **Nuevo reel** (`promo/pleno-local.mp4`, 32 s): gratis, código abierto, instalación, elección de datos, qué hace,
  actualización diaria, límites y crédito a Pablo Escamilla.

**Casos de uso**
- Un periodista o estudiante instala Pleno en 5 minutos y trabaja sin depender de un servidor ajeno.
- Alguien desconfiado de bases ajenas elige «desde las fuentes oficiales» y arma todo en su computadora.
- Un desarrollador revisa el código, propone fuentes nuevas o lo adapta: el proyecto sirve de carta de presentación.

**Probado**: instalación real desde GitHub en una carpeta aislada (uv, Python, dependencias, acceso directo,
asistente), instalación «Rápido» de punta a punta con una base de prueba, y las pruebas en Python 3.12.
**No probado**: el instalador de Windows (no hay Windows a la mano).

---

## Iteración 9 · En línea (28 oct 2026)

**Qué se añadió**
- **Demo pública en Render (gratis)**: https://pleno-x7dq.onrender.com, desplegada desde el repositorio privado
  `pescamill/pleno`; cada commit a `main` se publica solo. La base vive en el dataset público de Hugging Face
  `pescamil/pleno-datos` y se descarga en cada arranque.
- **Página «Pleno está despertando»** mientras se descarga la base (el plan gratis se duerme tras 15 min).
- **Mucho más rápido**: el intérprete de preguntas ya no compila un patrón por cada ley (verificar pasó de ~25 s a
  ~2 s en el servidor gratis); la portada se calcula una vez al arrancar y queda en memoria.
- Formulario de verificar corregido en celular.

**Casos de uso**
- Mandar el enlace a un periodista y que lo pruebe sin instalar nada.
- Poner el enlace en la bio del reel.

**Límites del plan gratis**
- Si nadie entra en 15 minutos se duerme; despertar tarda 1–2 minutos.
- 0.1 CPU: una búsqueda tarda unos segundos; con tráfico real convendría un plan pagado o un VPS.
- La base no se actualiza sola en línea: se sube de nuevo cuando quieras publicar datos nuevos.

---

## Iteración 8 · Listo para redes y para publicar (27 oct 2026)

**Qué se añadió**
- **Portada con «¿Es cierto?»**: un recuadro para pegar una afirmación y verificarla, con ejemplos.
- **Compartir el veredicto como imagen** (1080×1350, formato de feed): la afirmación, lo que muestra el registro, el
  detalle (votaciones, cifras o dónde aparece la frase) y la fuente. En celular abre el menú de compartir.
- **Vista previa al compartir el enlace** (Open Graph): imagen y texto propios en X, WhatsApp y LinkedIn.
- **Modo público** (`PLENO_PUBLICO=1`): la demo no permite alertas compartidas entre visitantes.
- **Paquete para Hugging Face** (`deploy/`): la base como dataset y la app como Space Docker, con
  `deploy/publicar.py <usuario>`.
- **Reel** (`promo/pleno-reel.mp4`, 49 s, vertical): qué es, cuatro funciones con datos reales, alcance y límites.
  Todo lo que muestra sale de la base (`promo/datos.py`). Textos para publicar en `promo/publicacion.md`.
- La evaluación de búsqueda ahora acepta cualquier documento que contenga la frase exacta (el texto de trámite se
  repite entre sesiones); la medida estricta sigue reportándose aparte.

**Casos de uso**
- Alguien verifica un dato en su celular y comparte la tarjeta en su historia o en un grupo de WhatsApp, con la
  fuente y el nombre de Pleno: cada verificación es publicidad.
- Un enlace a Pleno pegado en X muestra «¿Lo dijo? ¿Lo votó? ¿Es cierto?» en vez de un enlace pelón.
- El reel presenta Pleno en 49 segundos sin prometer de más: incluye sus límites.

---

## Iteración 7 · Verificar, evaluaciones y cifras de delitos (27 oct 2026)

**Qué se añadió**
- **Verificar una afirmación** (página «Verificar», `pleno verificar`, `POST /api/v1/verificar`). Compara lo que alguien
  dice con el registro y responde: lo respalda, muestra otra cosa, evidencia mixta, sin evidencia o «revisar».
  - Votos: contra la votación nominal, exacto.
  - Citas textuales: contra el texto de todas las versiones estenográficas; si la dijo otra persona, dice quién.
  - Cifras de delitos: contra el SESNSP, mismos meses de ambos años, con aviso si cruza el cambio de metodología de 2026.
  - Lo demás: un modelo de lenguaje, pero solo cuentan las citas que aparecen palabra por palabra en la fuente.
- **Estadística oficial de delitos (SESNSP)**: delitos y víctimas por estado y mes, 2015 a septiembre de 2026
  (959 mil registros). Endpoint `GET /api/v1/estadistica?delito=homicidios&estado=Jalisco`.
- **Evaluaciones por iteración** (`pleno evaluar`): integridad, atribución de oradores y partidos, ruido en leyes,
  búsqueda, intérprete de preguntas y verificador. Guarda historial y marca regresiones; corre sola tras la
  actualización diaria. La primera corrida encontró y se corrigieron errores reales (personas confundidas, «Congreso
  de la Ciudad de México» leído como ley, la Fiscalía no reconocida en preguntas).

**Casos de uso**
- Una verificadora recibe «El diputado X votó a favor de la reforma judicial». En segundos ve que votó en contra, con
  enlace a la votación oficial.
- Circula una frase atribuida a la presidenta. Pleno dice si aparece en alguna mañanera, cuándo, o que la dijo otra
  persona.
- La presidenta afirma «bajaron los homicidios». Un periodista ve la cifra oficial (−21.5% en 2025 contra 2024) y la
  tabla mes a mes para graficarla.
- Pablo cambia el parser de un congreso y corre `pleno evaluar`: si empeoró la atribución o la búsqueda, lo sabe antes
  de publicar.

---

## Iteración 6 · Datos para vender o entrenar (27 oct 2026)

**Qué se añadió**
- `pleno dataset`: snapshot versionado en Parquet, separado por licencia (mañaneras CC BY-SA 4.0; textos oficiales sin
  derecho de autor), con ficha del dataset, licencias y manifiesto SHA-256.
- Privacidad en el export: periodistas y público por su papel, no por nombre; personas detenidas como «Persona A “N”»;
  correos y teléfonos ocultos.
- Dos conjuntos de tareas verificables construidas del registro: «¿cómo votó X en Y?» (141 mil) y atribución de citas
  (17 mil).

**Casos de uso**
- Una universidad o laboratorio entrena o evalúa un modelo en español político mexicano con datos de licencia clara.
- Una empresa que construye un asistente sobre información pública mide si su sistema responde bien «¿cómo votó X?»
  usando las tareas como set de evaluación.
- Publicar la parte abierta en Hugging Face como carta de presentación del proyecto.

---

## Iteración 5 · Carga completa y limpieza (27 oct 2026)

**Qué se añadió**
- Base nueva con todas las fuentes: 11,927 documentos y 345 mil intervenciones.
- Limpieza de nombres de leyes que los PDF estatales ensuciaban, y erratas asociadas a la ley oficial
  («Ley de Anparo» → Ley de Amparo).
- Fechas de votaciones corregidas (tomaban la fecha citada en el título del decreto).
- Actualización diaria instalada en la Mac a las 7:00.

**Casos de uso**
- Buscar una ley y encontrar todas sus menciones aunque el PDF la escriba mal.
- Abrir Pleno cada mañana con lo de ayer ya cargado, sin hacer nada.

---

## Iteración 4 · Fiscalía General de la República (27 oct 2026)

**Qué se añadió**
- Comunicados de la FGR (6,387 desde noviembre de 2025), clasificados: sentencia, vinculación a proceso, orden de
  aprehensión, detención, aseguramiento, extradición, investigación; con lugar y fecha.
- Regla fija: nombres como los publica la FGR («José “N”»); nunca se completan ni se arman perfiles de detenidos.
- Si el sitio de la FGR rechaza conexiones, Pleno se detiene y retoma al día siguiente.

**Casos de uso**
- Contrastar lo anunciado en la mañanera («detuvieron al jefe de plaza X») con lo que la FGR documentó después
  (vinculación a proceso, sentencia).
- Contar sentencias por delito o estado en un periodo.

---

## Iteración 3 · Expansión de fuentes y estandarización (27 oct 2026)

**Qué se añadió**
- Suprema Corte y 6 congresos estatales (CDMX, Oaxaca, Quintana Roo, Tabasco, Nuevo León, Guerrero).
- Padrón oficial de la Cámara de Diputados (partido, distrito, curul, comisiones) y votaciones nominales con el voto de
  cada diputado; quién votó contra su bancada.
- Catálogo oficial de 317 leyes federales: los nombres de ley se estandarizan y enlazan al texto oficial; leyes
  estatales separadas de las federales.
- Unificación de nombres de personas (orden, erratas), sin mezclar congresos distintos; auditada en un archivo.
- Alertas con RSS y resumen diario; inventario público de fuentes (integradas, pendientes, bloqueadas y por qué).
- Borradores de solicitudes de transparencia para lo bloqueado; plan de periodismo (`docs/periodismo.md`).

**Casos de uso**
- «¿Quiénes votaron contra su bancada en la LXVI?» para una nota o un hilo en X.
- Un reportero de Oaxaca filtra por estado y ve qué se dijo en su congreso sobre agua.
- Una consultoría crea una alerta «Ley de Aguas Nacionales» y la recibe en Slack vía RSS.

---

## Iteración 2 · Interfaz renovada (26 oct 2026)

**Qué se añadió**
- Nueva interfaz: búsqueda con autocompletado y filtros, páginas de persona, ley, documento y votación, gráfica por
  mes, modo oscuro, diseño para celular, «Copiar cita» y exportar CSV.

**Casos de uso**
- Encontrar una cita, copiarla con su fuente y pegarla en una nota en menos de un minuto.

---

## Iteración 1 · Base (26 oct 2026)

**Qué se añadió**
- Mañaneras (dataset abierto, desde 2018) y versiones estenográficas de la Cámara de Diputados.
- Búsqueda estructurada (quién, cargo, partido, ley, fechas), preguntas en español, respuesta con fuentes y API con
  claves y límites.

**Casos de uso**
- «¿Qué dijo la presidenta sobre el agua en 2025?» y llegar directo a las intervenciones con enlace oficial.

---

## En curso

- Sesión aparte integrando las fuentes pendientes: ~18 congresos estatales, fiscalías de CDMX, Jalisco, Edomex y
  Guerrero, carpetas de investigación de la CDMX y ayuntamientos.
- Pendiente de decisión: modelo de lenguaje para la verificación general y hospedaje público.
