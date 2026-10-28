# Pleno: pitch para empresas (borrador)

## En una frase

**Pleno te dice quién dijo qué en el poder público de México, cuándo, con qué cargo y partido, y sobre qué ley, con
la fuente oficial a un clic.**

## El problema

- Lo que se dice en conferencias y sesiones mueve regulaciones, contratos e inversiones.
- Hoy está regado en miles de páginas, PDF y videos con formatos distintos. Encontrar «todo lo que diputados de MC
  dijeron sobre la Ley de Amparo» toma horas de búsqueda manual.
- El monitoreo de medios resume lo que publican los medios. Pleno va a la fuente: lo que se dijo, palabra por palabra.

## A quién le vendemos (en orden)

1. **Consultoras de asuntos públicos y relaciones gubernamentales.** Su trabajo es saber quién dijo qué y anticipar
   reformas. Compran velocidad y certeza.
2. **Equipos de relaciones gubernamentales y de cumplimiento en empresas reguladas**: energía, telecom, banca,
   farmacéutica, minería, agua. Necesitan alertas sobre sus temas.
3. **Despachos de abogados regulatorios:** historial legislativo y argumentos de cada bancada sobre una ley.
4. **Medios y periodismo de datos:** verificación rápida con cita exacta.
5. **Think tanks, academia y organismos internacionales:** análisis de discurso y series de tiempo.
6. **Inversionistas y analistas de riesgo político.**

## Demo de 3 minutos

1. Escribe «Diputados de Movimiento Ciudadano que mencionan la Ley de Amparo». Pleno lo convierte en filtros visibles.
2. Clic en una diputada: perfil, partido (con la sesión de donde sale el dato), cargos, leyes que más menciona.
3. Clic en la ley: menciones por mes, por partido y quién la menciona más.
4. «Respuesta con fuentes»: resumen de 4 oraciones con [1][2][3] y cada cita enlazada a la transcripción oficial.
5. `/docs`: la misma información por API para conectarla a sus sistemas.

## Planes (hipótesis a validar con 10 conversaciones)

| Plan | Para quién | Incluye | Precio a validar |
|---|---|---|---|
| Libre | Público, periodistas | Búsqueda y perfiles, 30 consultas/min | Gratis |
| Pro | Analista | Alertas por tema, persona o ley; exportes; API 600/min | US$99–299 al mes |
| Equipo / API | Consultoras y empresas | Varios usuarios, API con SLA, histórico completo | US$500–2,000 al mes |
| A la medida | Quien necesite un estado o un periodo | Cobertura nueva (congreso local, cabildo), backfill | Por proyecto |

## Por qué nosotros

- **Ingeniería de calidad:** cada dato tiene su procedencia y las pruebas cubren el parseo, la búsqueda y la API.
- **Limpio legalmente:** solo fuentes oficiales y datasets con licencia; se respetan `robots.txt` y los derechos de
  radiodifusión.
- **Hecho desde Guadalajara**, con cobertura estatal como siguiente paso. Ahí no hay nada estructurado.

## Siguientes pasos comerciales

1. Lista de 30 consultoras de asuntos públicos y equipos de relaciones gubernamentales (verificar cada nombre y contacto).
2. Oferta para 3 socios de diseño: 3 meses de Pro gratis a cambio de retroalimentación semanal y testimonio.
3. Meta: 10 demos → 3 socios → 1 cliente que pague antes de agregar más estados.
