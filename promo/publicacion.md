# Publicación

## Reel actual: instalación local

Archivo: `promo/pleno-local.mp4` (1080×1920, 30 fps, 32 s, sin audio; agrega un sonido en tendencia desde la app).
Se vuelve a generar con `.venv/bin/python promo/render.py --reel local` (las cifras salen de la base: `promo/datos.py`).

### Texto para Instagram

¿Lo dijo? ¿Lo votó? ¿Es cierto? 🏛️

Hice Pleno: un buscador de lo que se dice en el poder público de México que vive en tu computadora.
Mañaneras, Cámara de Diputados, Suprema Corte, fiscalías, 18 congresos estatales y cifras oficiales de delitos,
con la fuente oficial de cada resultado.

✅ Gratis y de código abierto
💻 Se instala pegando una línea (Mac, Windows, Linux)
⬇️ Tú eliges: base lista (≈2 GB, minutos) o descargar directo de las fuentes oficiales
🔄 Se actualiza solo cada día
🔎 Verifica votos, citas textuales y cifras

Lo que NO hace: no decide qué es verdad (muestra el registro), no tiene todo (el Senado bloquea robots) y puede
fallar: siempre abre la fuente antes de publicar.

Link en la bio → pescamill.github.io/pleno

#México #DatosAbiertos #Periodismo #FactCheck #Transparencia #CódigoAbierto #Python

### Comentario fijado

Cómo instalarlo: en Mac abre Terminal y pega
curl -LsSf https://raw.githubusercontent.com/pescamill/pleno/main/instalar.sh | sh
En Windows abre PowerShell y pega
irm https://raw.githubusercontent.com/pescamill/pleno/main/instalar.ps1 | iex

### Antes de publicar

1. Pon `https://pescamill.github.io/pleno/` en tu bio (la página de presentación; el código sigue en
   github.com/pescamill/pleno).
2. Si alguien comenta un error, agradécelo y corrígelo en público: es parte del valor del proyecto.

## Reel anterior (demo en línea)

`promo/pleno-reel.mp4` presentaba la demo en línea, que ya se dio de baja. No lo publiques tal cual: su cierre dice
«Link en la bio» pensando en esa demo.
