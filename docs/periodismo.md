# Pleno y el periodismo: cómo capitalizarlo

## La respuesta corta

El periodismo es tu **mejor canal y tu peor cliente**.

**Las redacciones mexicanas pagan poco.** Las grandes tienen presupuesto apretado y las independientes viven de donativos. Los periodistas a título personal casi nunca pagan software.

**Pero un periodista que cita "Datos: Pleno" en una nota vale más que cualquier anuncio:**
- Le da credibilidad a la herramienta.
- Tu nombre llega a miles de lectores.
- Te hace visible para quienes sí pagan: consultorías de asuntos públicos, áreas de relaciones gubernamentales de empresas, despachos regulatorios, embajadas y centros de análisis.

La estrategia es:
1. **Gratis para periodistas, con atribución.** Así se crea la reputación.
2. **De pago para quien usa la información para decidir o vender.** Así se gana dinero.
3. **Tu cuenta de X como laboratorio.** Publicas hallazgos que solo Pleno puede producir rápido.

## Qué hay en el mercado (verificado)

- **[Integralia](https://integralia.com.mx/web/wp-content/uploads/2025/02/Brochure-sintetico-Integralia_15-Anos-1.pdf)** vende monitoreo legislativo y regulatorio con análisis humano, y publica un *Reporte Legislativo* desde 2011.
  - **Qué es:** tu competencia directa del lado de pago.
  - **Qué no hace:** no es un buscador, no da la cita exacta con fuente en segundos y no cubre congresos estatales ni la Corte día a día.
- **SPIN (Luis Estrada)** analizó a mano las mañaneras minuto a minuto y reportó más de 61,000 afirmaciones falsas o engañosas para 2021 ([Expansión](https://politica.expansion.mx/mexico/2021/09/01/amlo-61-000-afirmaciones-falsas-conferencias)).
  - **Qué demuestra:** que hay demanda y atención mediática por este tipo de conteo.
  - **Qué hace distinto Pleno:** no clasifica mentiras, que es un juicio editorial. Da la materia prima estructurada para que cualquiera verifique rápido.

Lo que Pleno tiene y no vi en otro lado: **cita exacta con fuente oficial + votación nominal + quién votó contra su bancada + congresos estatales + Corte**, todo en un mismo buscador, con API y alertas.

## Productos para periodistas (ya construidos o a un paso)

| Necesidad del periodista | Qué le da Pleno | Estado |
|---|---|---|
| "¿Dónde dijo eso? Necesito la cita textual" | Búsqueda → cita con enlace a la versión estenográfica oficial y botón «Copiar cita» | Listo |
| "Avísame cuando alguien hable de X" | Alertas con RSS (lector de noticias, Slack, correo) | Listo |
| "¿Cómo votó el diputado X? ¿Quién rompió con su bancada?" | Votaciones nominales y disciplina partidista por persona y por votación | Listo |
| "¿Qué dijo la Corte / el congreso de mi estado?" | SCJN y 6 congresos estatales, filtro por estado | Listo |
| "Necesito los datos para graficar" | Exportar CSV y API | Listo |
| "Quiero insertar la gráfica en mi nota" | Widget incrustable con enlace "Datos: Pleno" | Por hacer (1–2 días) |
| "Resúmeme la sesión de ayer" | Respuesta con fuentes (hoy con modelo local pequeño) | Mejorable con un modelo más fuerte |

**El widget incrustable** es la pieza viral: cada nota que inserte una gráfica de Pleno (votación por partido, menciones de una ley por mes) lleva un enlace de regreso. Es SEO y distribución gratis.

## Cómo se gana dinero (hipótesis, a validar)

1. **Plan Redacción (pago bajo o patrocinado):** alertas ilimitadas, CSV sin límite, API con cuota mayor, widgets sin marca. Precio a validar; quizá la primera redacción mediana lo obtenga gratis a cambio de testimonio y atribución.
2. **Plan Profesional (donde está el dinero):** consultorías, empresas reguladas y despachos.
   - Monitoreo de temas (agua, energía, fintech, salud).
   - Reporte semanal automático por cliente.
   - Alertas por persona y por ley, y cómo votó cada legislador en sus temas.

   Aquí compites con Integralia a menor precio y con más velocidad; ellos ponen el análisis humano, tú la cobertura y el tiempo real.
3. **Boletín semanal gratuito con patrocinio:** «Lo que se dijo en el poder esta semana», hecho con los mismos datos. Crece la audiencia y vende patrocinio.
4. **Fondos y alianzas:** herramientas cívicas para periodismo suelen financiarse con donativos. No encontré una convocatoria abierta hoy (octubre 2026); vale vigilar Google News Initiative, JournalismAI y fundaciones de periodismo de la región, y aliarse con una redacción independiente como socia de solicitud.

> Los precios no están investigados: son hipótesis. Valídalos con 10 conversaciones antes de publicarlos.

## Plan de 30 días

1. **Semana 1. Contenido en X, dos piezas por semana**, cada una con capturas y enlace a la fuente oficial:
   - «Los 10 diputados que más votaron contra su bancada en la LXVI».
   - «Lo que dijo la Corte esta semana sobre amparo».
   - «¿Cuántas veces mencionó la presidenta el agua, mes por mes?».
2. **Semana 2. Diez conversaciones**, empezando por verificadores (El Sabueso de Animal Político, Verificado, AFP Factual), mesas de datos y reporteros de fuente legislativa. Pregunta: ¿qué buscaste la última vez y cuánto tardaste? Muéstrales la búsqueda en vivo.
3. **Semana 3. Hospedaje público** (Hugging Face Space o un VPS pequeño) para que puedan usarlo sin tu Mac encendida. Requiere tu aprobación y cuenta.
4. **Semana 4. Medir:** cuántos crean alertas, cuántos vuelven en la semana, cuántas notas citan «Datos: Pleno». Si nadie vuelve, el problema es el producto, no el precio.

## Riesgos y límites (honestos)

- **Exactitud.** Un error de atribución (orador equivocado) en una nota publicada daña tu reputación y la del medio. Cada resultado enlaza a la fuente oficial y la interfaz pide verificar; mantén eso visible. Las fusiones de nombres quedan auditadas en `data/fusiones-errata.tsv`.
- **Neutralidad.** Pleno no califica afirmaciones como falsas ni verdaderas. Esa es una decisión editorial que conviene dejar a los medios; te protege legal y políticamente.
- **Periodistas.** No se construyen perfiles de reporteros (México es peligroso para la prensa). El medio solo aparece cuando la persona lo dice en la transcripción.
- **Cobertura.** El Senado y algunos congresos (Campeche, Chihuahua, Puebla, Jalisco) faltan por `robots.txt` o porque no publican. Las solicitudes de transparencia están en `docs/solicitudes-transparencia.md`; publicarlas en X también es contenido.
