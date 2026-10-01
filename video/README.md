# Vídeos de ofertas — CRIBA / Achadinhos no Zap

Genera vídeos verticales (9:16) de las ofertas, para TikTok, Reels y Shorts.

## Cómo funciona

```
oferta de achados.json
      ↓
HTML por escena  (texto nítido, es lo que vende)
      ↓
Chrome headless --screenshot  →  PNG 1080x1920
      ↓
ffmpeg (zoompan + fundido)     →  MP4 h264 30fps
```

**Por qué HTML y no texto pintado con Pillow:** la skill `video` avisa de que
los modelos de IA no renderizan texto legible. Pintando el precio en HTML, Chrome
lo saca perfecto — y el precio es justo lo que hay que leer.

**Por qué Chrome y no Hyperframes:** Chromium ya estaba instalado, así que no hay
que descargar nada. Hyperframes añadiría una dependencia más para el mismo
resultado a esta escala.

**Por qué ffmpeg:** no venía en el sistema. Se instaló en `tools/ffmpeg/`
(ffmpeg 9.0.2, build essentials de gyan.dev).

## Instalación

```powershell
# ffmpeg (solo la primera vez, ~110 MB)
# ya está en tools/ffmpeg/, no hace falta repetir
```

Si algún día falta:

```powershell
Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile ffmpeg.zip
Expand-Archive ffmpeg.zip -DestinationPath tools\ffmpeg
```

## Uso

```powershell
python video/generar_video.py --listar      # ofertas con más gancho
python video/generar_video.py --uno 1       # un vídeo concreto
python video/generar_video.py --lote 5      # los 5 mejores
```

Salida: `video/salida/oferta_NN.mp4`

## Las 5 escenas

| # | Escena | Duración | Qué hace |
|---|--------|----------|----------|
| 1 | **Gancho** | 2,6 s | MAYÚSCULA, máximo 3 palabras. Es lo que decide si siguen viendo |
| 2 | **Producto** | 5,0 s | Foto + título + precio grande |
| 3 | **Precios** | 5,5 s | No Pix y Com cupom, **solo si son más bajos de verdad** |
| 4 | **Diferencial** | 3,4 s | "PREÇO CONFERIDO — o cupom que aparece é o cupom que aplica" |
| 5 | **CTA** | 4,5 s | "ENTRA NO GRUPO" |

Total: ~21 s. Duración correcta para TikTok y Reels (15-30 s es el rango que
mejor retiene).

## Detalle que evita un error real

`pix_real()` **no muestra la línea de Pix si el precio no baja**. Se detectó al
listar las ofertas: varias tenían `ml_precio_pix` igual al `precio`
(R$ 98,91 vs R$ 98,91). Enseñar "No Pix: R$ 98,91" cuando es el mismo número
insinúa un ahorro que no existe — exactamente el tipo de dato falso que ya costó
caro en este proyecto.

## Verificación

```powershell
# datos reales del MP4
& tools\ffmpeg\*\bin\ffprobe.exe -v error -show_format -show_streams video\salida\oferta_01.mp4
```

Medido en `oferta_01.mp4`:
```
duración  : 19,0 s
resolución: 1080x1920
fps       : 30  (570 frames)
códec     : h264
bitrate   : 1581 kbps
tamaño    : 3668 KB
```

Y las escenas **no están en blanco**: analizando un frame por segundo con Pillow,
las 6 muestras dan variación de píxeles entre 49 y 95 (una imagen plana daría
cerca de 0).

## Pendiente

- **Audio**: ahora mismo los vídeos van mudos. La skill `video` recuerda que el
  85% del vídeo social se ve sin sonido, así que el texto ya lo cubre — pero
  añadir música sube la retención.
- **Vídeo "GRUPO"**: pantalla con varias ofertas cayendo. Diseñado en
  `guiones.json` como `plantilla_grupo`, sin implementar todavía.
- **Subtítulos quemados**: en algunos casos conviene, aunque aquí el texto ya va
  en pantalla por diseño.
- **Lote diario automático**: engancharlo al workflow para que genere los vídeos
  del día sin intervención.
