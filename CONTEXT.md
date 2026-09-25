# CRIBA — Contexto Completo del Proyecto

> **Lee este archivo completo antes de hacer cualquier cambio.** Contiene toda la información necesaria para entender el proyecto, las reglas de negocio, las credenciales, los bugs conocidos y las decisiones de diseño.

---

## 1. ¿Qué es CRIBA?

**CRIBA** es un bot automatizado de afiliados brasileño que:
1. **Cosecha ofertas** de Mercado Livre y Amazon Brasil cada 15 minutos
2. **Publica ofertas al WhatsApp** (grupo "🔥Achadinhos no Zap") con foto + precio limpio + cupón + link de afiliado
3. **Mantiene un sitio web** en `achadinhosnozap.com.br` (GitHub Pages) con un catálogo de ofertas auto-actualizado

### Stack
- **Lenguaje:** Python 3.12
- **CI/CD:** GitHub Actions (cron cada 15 min)
- **WhatsApp API:** Green API (REST)
- **Links cortos ML:** API interna de afiliados de Mercado Livre (`meli.la`)
- **Hosting web:** GitHub Pages (repo `Gollop33/criba`)
- **Dominio:** `achadinhosnozap.com.br`

---

## 2. Credenciales y Secrets

### Variables de Entorno (GitHub Secrets + `.env` local)
| Variable | Valor | Uso |
|---|---|---|
| `GREEN_API_ID` | `710722744667` | ID de instancia Green API |
| `GREEN_API_TOKEN` | `672209385b104b06a04fc568b20d75426f1e3ad757ac461183` | Token de autenticación Green API |
| `WHATSAPP_CHAT_ID` | `120363413395651443@g.us` | ID del grupo WhatsApp "🔥Achadinhos no Zap" |
| `ML_PORTAL_COOKIE` | *(cookie larga de sesión ML)* | Cookie de sesión del portal de afiliados Mercado Livre. Se vence y hay que renovarla periódicamente |
| `TELEGRAM_BOT_TOKEN` | *(en GitHub Secrets)* | Bot de Telegram para alertas internas |
| `TELEGRAM_CHAT_ID` | *(en GitHub Secrets)* | Chat de Telegram para alertas |
| `DEALEE_API_KEY` | *(en GitHub Secrets)* | API de ofertas Dealee |
| `GEMINI_API_KEY` | *(en GitHub Secrets)* | API de Google Gemini para curación IA |

### Tags de Afiliado
| Plataforma | Tag | Formato del link |
|---|---|---|
| **Mercado Livre** | `ja20250119201346` | `meli.la/XXXX` (preferido) o `mercadolivre.com.br/...#D[A:ja20250119201346]` |
| **Amazon Brasil** | `criba20-20` | `amazon.com.br/...?tag=criba20-20` |

### GitHub Repo
- **Repo:** `https://github.com/Gollop33/criba`
- **GitHub Pages:** `https://achadinhosnozap.com.br` (custom domain)

---

## 3. 🔴 REGLA DE ORO — Links de Afiliado

**NUNCA usar `url_corta` (links `/go/` de redirect).** Solo generan click pero NO comisión.

### Prioridad de links para Mercado Livre:
1. ✅ `meli_la` → `https://meli.la/XXXX` (generado por `melila_api.py`)
2. ✅ `url` con tag → `mercadolivre.com.br/...#D[A:ja20250119201346]`
3. ❌ **NUNCA** `url_corta` → `/go/...` (estos NO monetizan)

### Prioridad de links para Amazon:
1. ✅ `url` con tag → `amazon.com.br/...?tag=criba20-20`

### Implementación:
- `gerar_fila_posts.py` → función `elegir_link_afiliado(item)` (línea ~44)
- `index.html` → función JS `linkAfiliado(a)` (línea ~312)

---

## 4. Arquitectura y Flujo de Datos

```
CRON EXTERNO (cron-job.org, cada 8 min) ──► workflow_dispatch modo=publicar
│                                            (solo fila + 1 post, ~1 min)
│
GitHub Actions `schedule` (~cada 2-4 h, ver §9) ──► modo=full
│
├─ 1. cupones_pelando.py      → Scrape cupones de Pelando.com.br
├─ 2. agente_ml.py             → Scrape ofertas Mercado Livre → achados_ml.json
├─ 3. agente_amazon.py         → Scrape ofertas Amazon Brasil → achados_amazon.json
├─ 4. unir_achados.py          → Unifica → achados.json
├─ 5. agente_autonomo.py       → IA curada → achados_especificos.json (usa Gemini + Dealee)
├─ 6. gerador_melila.py --lote → Genera meli.la para todos los ML → cache_melila.json
├─ 7. acortador.py             → Acorta links → links.json + go/
├─ 8. gerar_fila_posts.py      → Genera cola de posts → fila_posts.json   [SIEMPRE]
├─ 9. publicar_proximo.py      → Publica 1 post a WhatsApp                 [SIEMPRE]
├─10. bot_precios.py           → Monitorea precios → precios.db + productos.json
├─11. alertas_telegram.py      → Alerta caídas/subidas → Telegram
└─12. git commit + push        → Actualiza repo → Triggerea GitHub Pages deploy
```

> Los pasos **1-7 y 10-11** solo corren en `modo=full`. Los pasos **8, 9 y 12**
> corren siempre, así que el cron externo publica sin scrapear.

### Archivos JSON Principales
| Archivo | Qué contiene |
|---|---|
| `achados.json` | Ofertas unificadas ML + Amazon (el sitio web lee este) |
| `achados_ml.json` | Ofertas Mercado Livre raw |
| `achados_amazon.json` | Ofertas Amazon raw |
| `achados_especificos.json` | Ofertas curadas por IA |
| `fila_posts.json` | Cola de posts pendientes para WhatsApp |
| `cupones.json` | Cupones vigentes (códigos, descuentos, fechas) |
| `productos.json` | Productos monitoreados con historial de precios |
| `logs/enviados.json` | Registro anti-repetición (qué ya se envió y cuándo) |
| `logs/control_canal.json` | Control de calentamiento del canal (envíos/día) |
| `cache_melila.json` | Cache de links meli.la (válido 7 días) |
| `links.json` | Links acortados mapeados |

---

## 5. Formato de Posts WhatsApp (Estilo "Samuel/Ninja Ofertas")

El formato exacto que se envía al grupo:

```
🔥 [Título del producto]

💵 R$ [precio sin centavos]
🎟️ Cupom: [CÓDIGO] (solo si hay cupón válido)

[link meli.la o amazon con tag]

anúncio
```

- Se envía **foto del producto** (descargada) con el texto como caption
- Si falla la foto, se envía solo texto
- **Sin centavos** en el precio (R$ 299, no R$ 299.90)
- Footer `anúncio` obligatorio (requisito legal Brasil)

### Cadencia
- **7 minutos** entre post Amazon y post ML (implementado como 7.5 min sleep)
- 2 posts por ejecución del workflow (15 min entre ejecuciones)
- Límite diario: Día 1 = 20, Día 2 = 40, Día 3+ = 120 posts/día
- Ventana horaria: 8:00 a 22:00 hora Brasilia (UTC-3)

---

## 6. Filtro de Nicho — WhatsApp vs Website

### WhatsApp (grupo): Solo nicho TECH + PERFUMES + RELOJES
El filtro está en `gerar_fila_posts.py`:
- `es_producto_tecnologia(nombre)` → función que filtra por keywords
- `KEYWORDS_TECH` → lista de ~100+ keywords (monitores, SSD, RAM, RTX, perfume, relógio, etc.)
- `EXCLUIR_NO_TECH` → lista de exclusión (panela, toalha, shampoo, etc.)
- `clasificar_categoria(nombre)` → categoriza en: Monitores, Hardware, Notebooks, Periféricos, Games, Smartphones, Perfumes, Relógios, Gadgets

### Website (achadinhosnozap.com.br): TODAS las categorías
- El sitio web muestra TODO lo que hay en `achados.json` sin filtro de nicho
- Auto-refresh cada 60 segundos (`setInterval(init, 60000)`)
- Cache-busting en fetches (`?_t=Date.now()`)

---

## 7. Módulos Python — Referencia Rápida

### `publicar_proximo.py` (~330 líneas)
- **Publica exactamente 1 post por ejecución.** Sin `sleep` (ver §15.3).
- **`main()`** → valida ventana BRT, límite diario, credenciales y **guardia de
  cadencia** (`MIN_GAP_MIN`, 6 min por defecto), luego publica 1 post.
- **`resolver_link_afiliado(url, loja, cookie)`** → aplica la Regla de Oro.
  Devuelve `None` si el link es `/go/` (aborta el post). No re-acorta si ya es
  `meli.la`. Si ML no tiene link corto, cae a `#D[A:ja20250119201346]`.
- **`ultimo_envio_utc(enviados)`** → base de la guardia anti-duplicado.
- Skipea posts tipo `cupons_loja` (solo envía productos con foto).
- Lee `fila_posts.json`, escribe `logs/enviados.json` y `logs/control_canal.json`.

### `gerar_fila_posts.py` (521 líneas)
- **Función principal:** `armar_fila_rotativa()` → genera `fila_posts.json`
- Alterna 50/50 entre ML y Amazon
- Aplica filtro de nicho tech
- Cruza productos con cupones vigentes
- Anti-repetición 48h

### `melila_api.py` (219 líneas)
- **Función principal:** `generar_melila(url, cookie_str, tag)` → retorna `meli.la/XXXX` o `None`
- Llama `POST /affiliate-program/api/v2/stripe/user/links`
- Cache persistente 7 días en `cache_melila.json`
- Rate limit: 1 segundo mínimo entre llamadas
- Si la cookie ML vence, retorna `None` y hay que renovarla manualmente

### `enviar_whatsapp.py` (269 líneas)
- `enviar_whatsapp(mensaje)` → envía texto por Green API
- `enviar_whatsapp_archivo(ruta, caption)` → envía imagen con caption
- `verificar_green_api()` → verifica estado de la instancia

### `modulo_ofertas.py` (~466 líneas)
- `fmt_brl(precio)` → formatea precio brasileño
- `cargar_enviados()` / `guardar_enviados()` → log anti-repetición
- `marcar_enviado()` / `ya_enviado()` → marca/verifica si ya se envió
- `elegir_mejores_ofertas()` → selecciona ofertas por score

### `agente_ml.py`
- Scraper de ofertas Mercado Livre
- Genera `achados_ml.json`

### `agente_amazon.py`
- Scraper de ofertas Amazon Brasil
- Genera `achados_amazon.json`

### `unir_achados.py`
- Unifica ML + Amazon + Específicos → `achados.json`

### `cargar_cupones.py`
- Parsea mensajes de Telegram del canal de afiliados ML
- Extrae códigos, descuentos, fechas, mínimos
- Actualiza `cupones.json`

### `transformar_campana.py`
- Convierte campañas con bit.ly → meli.la con tu tag
- Flag `--enviar` para publicar directo al grupo

---

## 8. Website (`index.html` — 451 líneas)

- **Framework:** Vanilla HTML/CSS/JS (sin dependencias)
- **Diseño:** Dark theme, Space Grotesk font, cards con precios y descuentos
- **Datos:** Fetch de `achados.json`, `productos.json`, `cupones.json`, `links.json`
- **Función JS `linkAfiliado(a)`:** Aplica la Regla de Oro para links
- **Auto-refresh:** `setInterval(init, 60000)` recarga datos cada 1 minuto
- **Cache-busting:** `?_t=Date.now()` en todos los fetch
- **GA4:** `G-NFQTYQ0HXH`
- **Otras páginas:** `ofertas.html`, `tiendas.html`, `cupones.html`, `privacidad.html`, `analytics.html`

---

## 9. GitHub Actions Workflow (`bot.yml`)

### 🔴 HALLAZGO CRÍTICO: el `schedule` de GitHub NO sirve para la cadencia

Medido sobre las últimas 60 ejecuciones reales (vía API de GitHub):

| Métrica | Valor |
|---|---|
| Gap **mediano** entre ejecuciones | **174 min (~3 h)** |
| Gap mínimo observado | 56 min |
| Gaps > 60 min | **58 de 59** |
| Cron declarado | `*/15` (15 min) |

**GitHub estrangula los `schedule` de alta frecuencia.** El cron nunca dispara a
15 min: entrega una ejecución cada 2-4 horas. Ésta es la causa raíz de que el bot
publicara cada ~4 h en vez de cada 7-8 min. No era culpa de `time.sleep`, ni de
`control_canal.json`, ni del push.

**Solución implementada:** la cadencia la aporta un **cron externo**
(cron-job.org) que llama a la API `workflow_dispatch` cada 8 min.
Configuración paso a paso en **`CRON_EXTERNO_SETUP.md`**.

### Dos modos de ejecución

| Disparador | `modo` | Qué ejecuta |
|---|---|---|
| Cron externo (cron-job.org) cada 8 min | `publicar` | fila + **1 post** + commit (~1 min) |
| `schedule` de GitHub (~cada 3 h) | `full` | pipeline completo: scrape ML + Amazon + IA + fila + 1 post + precios + alertas |

Publicar y scrapear están **separados a propósito**: scrapear ML/Amazon cada
8 minutos haría que bloqueen la IP del runner.

```yaml
cron: '*/15 0,11-23 * * *'   # respaldo: ~8:00-21:45 Brasília
```

### Salvaguardas del publicador

| Regla | Valor | Dónde |
|---|---|---|
| Separación mínima entre posts | 6 min | `MIN_GAP_MIN` (`bot.yml` / env) |
| Ejecuciones solapadas | bloqueadas | `concurrency: criba-bot-${{ github.ref }}` |
| Ventana de publicación | 8:00-22:00 BRT | `horario_permitido_brt()` |
| Límite diario (día 3+) | 120 posts | `limite_diario_calentamiento()` |
| Timeout del job | 40 min | `timeout-minutes` |

El guardia de 6 min es la red de seguridad: si cron-job.org reintenta o GitHub
encola dos ejecuciones seguidas, la segunda **no publica**. Sin él, un reintento
duplicaría el post en el grupo.

### ⚠️ `continue-on-error: true`
Los steps de scraping siguen con `continue-on-error: true`, así que **sus fallos
son SILENCIOSOS**. Usa `python verificar_criba.py` para saber si el pipeline está
sano de verdad.

### Step final — Git Push
```yaml
git add -A -- '*.json' go/ img/ logs/ || true
git pull --rebase --autostash origin main
git commit -m "auto: achados+fila+cupons $(date -u +%H:%M)"
git push || git push --force-with-lease
```
Esto commitea todos los JSON actualizados, images, y logs al repo, lo que triggerea un deploy de GitHub Pages.

---

## 10. 🐛 Bugs Conocidos y Problemas Pendientes

### A. ✅ RESUELTO — Bot enviaba cada ~4 horas en vez de cada 7-8 minutos
**Causa raíz (medida, no supuesta):** el `schedule` de GitHub entrega ejecuciones
cada **~3 h** (mediana 174 min), no cada 15 min. Las 4 hipótesis que había aquí
antes eran incorrectas.

**Arreglo aplicado:**
1. `publicar_proximo.py` publica **1 post por ejecución** (se eliminó el
   `time.sleep(450)`; dormir dentro del job ataba la cadencia al cron otra vez).
2. Cron externo (cron-job.org) dispara `workflow_dispatch` cada 8 min →
   ver `CRON_EXTERNO_SETUP.md`.
3. Guardia `MIN_GAP_MIN=6` para no duplicar si hay reintentos.
4. `concurrency` en `bot.yml` para que no se solapen dos ejecuciones.

**Verificación:** `python verificar_criba.py` muestra la cadencia real medida.

### B. Website estancado — Solo mostraba monitores viejos
**Causa:** el `schedule` estrangulado hacía que `achados.json` se refrescara cada
~3 h (y a veces mucho más). **Mitigado:** el cron externo también ejecuta
`gerar_fila_posts.py` cada 8 min, y el `schedule` mantiene el `full` para
refrescar `achados.json`. El `?_t=Date.now()` sigue evitando la caché del CDN.

### C. Cookie ML_PORTAL_COOKIE vencida
- La cookie de sesión de Mercado Livre se vence periódicamente.
- **Estado actual: VENCIDA** (comprobado: HTTP 403 en
  `/affiliate-program/api/v2/stripe/user/links`).
- **Ya no es fatal:** la fila lleva los `meli.la` desde la caché
  (`melila_cache.json`, válida 7 días). Si la caché no tiene el link,
  `resolver_link_afiliado()` cae a la prioridad 2 de la Regla de Oro:
  `mercadolivre.com.br/...#D[A:ja20250119201346]`, que **sí monetiza**.
- **Para renovar:** loguear en `mercadolivre.com.br/affiliate-program`, DevTools →
  Application → Cookies, copiar TODA la cookie string, actualizar en `.env` local
  **Y** en GitHub Secrets (`ML_PORTAL_COOKIE`).

### D. ✅ RESUELTO — `melila_api` se llamaba sobre URLs que ya eran `meli.la`
Generaba un `400 Bad Request` en cada post y gastaba una llamada a la API por
gusto. `resolver_link_afiliado()` ahora detecta `meli.la` y no re-acorta.

### E. ✅ RESUELTO — `publicar_proximo.py` tenía dos `main()`
La definición de la línea ~101 era código muerto (Python usaba la segunda).
Eliminada. De paso, el archivo quedó con una sola ruta de ejecución.

### F. Regla de Oro — red de seguridad nueva
`resolver_link_afiliado()` **aborta el post** si el link contiene `/go/`
(no monetiza). Antes se podía publicar un link sin comisión sin que nada avisara.

### G. ✅ RESUELTO — `fila_posts.json` fuera de git
Se encontró el repo a mitad de un merge con `fila_posts.json` en conflicto
(`UU`). Y en la nube, el `git pull --rebase --autostash` lo dejó con **39 bloques
de marcadores**.

**Causa de raíz:** `fila_posts.json` se **regenera entero** en cada run
(`gerar_fila_posts.py`), así que el autostash choca en casi todas las líneas.

**Arreglo:** está en `.gitignore` y se sacó del índice
(`git rm --cached fila_posts.json`). Lo lee `publicar_proximo.py` en el **mismo
run** que lo genera, así que no necesita persistir. Si alguna vez lo ves
corrupto, `python gerar_fila_posts.py` lo regenera.

### H. `img/envios/` — NO está en git (dato corregido)
`img/envios/` está en `.gitignore` (línea 29), así que las fotos enviadas **no**
se commitean y el repo no crece por ahí. No hay nada que arreglar.

### I. ✅ RESUELTO — Carrera entre publicar y sincronizar → posts DUPLICADOS
**Observado el 2026-09-25:** dos ejecuciones disparadas con 9 s de diferencia
publicaron **el mismo producto** (Monitor LG UltraGear) a las 12:11:35 y
12:12:00.

**Causa:** `actions/checkout` ocurre al **principio** del run, pero el estado
(`logs/enviados.json`) solo se pushea al **final**. Si el run B arranca antes de
que el run A haga push, B lee un historial viejo, la guardia `MIN_GAP_MIN` no ve
el envío reciente y republica.

**Arreglo:** step nuevo **"sincronizar estado remoto (antes de publicar)"**
(`git pull --ff-only origin main`) justo antes de `gerar_fila_posts.py` y
`publicar_proximo.py`. En ese punto el árbol está limpio. `concurrency` sigue
serializando las ejecuciones.

### J. ✅ RESUELTO — `git pull --rebase --autostash` corrompía los JSON
El commit `a94cb56` de la nube llegó con `logs/enviados.json` y
`fila_posts.json` llenos de:

```
<<<<<<< Updated upstream
=======
>>>>>>> Stashed changes
```

**Por qué era grave:** `cargar_enviados()` no puede parsear eso, devuelve `{}` y
el bot cree que **nunca envió nada** → republica el catálogo entero.

**Arreglos (tres capas):**
1. **`fila_posts.json` fuera de git** (ver G) — elimina la causa de raíz.
2. **`reparar_estado.py`** — corre tras el pull y antes del commit. Une
   `logs/enviados.json` (log append-only: conserva el ts más reciente por
   producto y fusiona canales) y restaura el resto desde `origin/main`. El step
   de commit **falla a propósito** si queda algún JSON con marcadores.
3. **Fail-safe en `publicar_proximo.py`** — `cargar_enviados_estricto()`: si el
   log existe pero no parsea, **aborta con exit 2** en vez de tratarlo como
   vacío. Probado: con el log corrupto sale código 2 y no publica nada.

---

## 11. Estructura de Archivos del Proyecto

```
criba/
├── .env                         # Credenciales locales (NO en git)
├── .env.example                 # Template de credenciales
├── .github/workflows/bot.yml    # GitHub Actions workflow (cron)
├── .gitignore
├── CNAME                        # Custom domain GitHub Pages
├── CONTEXT.md                   # ← ESTE ARCHIVO
├── CRON_EXTERNO_SETUP.md        # Guía del cron externo (cron-job.org)
├── verificar_criba.py           # Chequeo de salud del pipeline
├── monitor_workflow.py          # Monitor de ejecuciones de GitHub Actions
├── reparar_estado.py            # Repara JSON con marcadores de conflicto
│
├── # === SCRAPERS / AGENTES ===
├── agente_ml.py                 # Scraper Mercado Livre
├── agente_amazon.py             # Scraper Amazon Brasil
├── agente_shopee.py             # Scraper Shopee (legacy, poco usado)
├── agente_autonomo.py           # Curación IA con Gemini/Dealee
├── cupones_pelando.py           # Scraper cupones Pelando.com.br
├── cupons_ml.py                 # Scraper cupones ML
├── descobrir_ofertas.py         # Descubridor de ofertas (legacy)
│
├── # === PROCESAMIENTO ===
├── unir_achados.py              # Unifica achados ML+Amazon
├── gerador_melila.py            # Generador batch de meli.la
├── melila_api.py                # API meli.la (sin Playwright)
├── acortador.py                 # Acortador de links → go/
├── gerar_fila_posts.py          # Genera cola de posts WhatsApp
├── bot_precios.py               # Monitor de precios
├── descargar_imagenes.py        # Descargador de imágenes
├── editar_imagen.py             # Editor de imágenes con badges
│
├── # === PUBLICACIÓN ===
├── publicar_proximo.py          # Publica a WhatsApp (1 post/ejecución)
├── enviar_whatsapp.py           # API de Green API (texto + archivos)
├── alertas_telegram.py          # Alertas a Telegram
├── transformar_campana.py       # Transforma campañas bit.ly → meli.la
├── cargar_cupones.py            # Carga cupones del canal Telegram
│
├── # === UTILIDADES ===
├── modulo_ofertas.py            # Utilidades: formateo, anti-repetición
├── api_agente.py                # API Flask (no usado activamente)
├── test_whatsapp.py             # Test de envío WhatsApp
│
├── # === CONFIGURACIÓN ===
├── config_afiliados.json        # Config de afiliados
├── cupones.json                 # Cupones vigentes
├── cupones_hoy.txt              # Template para pegar cupones del día
├── requirements.txt             # Dependencias Python
│
├── # === DATOS GENERADOS ===
├── achados.json                 # Ofertas unificadas (website lee esto)
├── achados_ml.json              # Ofertas ML raw
├── achados_amazon.json          # Ofertas Amazon raw
├── achados_especificos.json     # Ofertas curadas IA
├── fila_posts.json              # Cola de posts WhatsApp (NO versionado: .gitignore)
├── productos.json               # Productos monitoreados
├── links.json                   # Links acortados
├── cache_melila.json / melila_cache.json  # Cache meli.la
├── precios.db                   # SQLite historial precios
├── manual.json                  # Productos manuales
├── estado_alertas.json          # Estado alertas Telegram
├── faltantes_imagenes.json      # Imágenes faltantes
│
├── # === LOGS ===
├── logs/
│   ├── control_canal.json       # Control calentamiento (envíos/día)
│   ├── enviados.json            # Anti-repetición (qué ya se envió)
│   ├── ejecucion.log            # Log de ejecución
│   ├── imagenes.log             # Log de descarga de imágenes
│   └── cupons_ml_dump.html      # Dump cupones ML
│
├── # === WEBSITE ===
├── index.html                   # Página principal
├── ofertas.html                 # Página de ofertas
├── tiendas.html                 # Página de tiendas
├── cupones.html                 # Página de cupones
├── privacidad.html              # Política de privacidad
├── analytics.html               # Dashboard analytics
├── css/style.css                # Estilos
│
├── # === ASSETS ===
├── img/                         # Imágenes de productos
│   ├── envios/                  # Imágenes enviadas al WhatsApp
│   ├── *.jpg / *.png            # Assets del sitio
│   └── *.svg                    # Iconos de categorías
│
└── go/                          # Redirects cortos (NO usar para monetización)
    └── */index.html             # Redirect HTML por producto
```

---

## 12. Fuentes de Cupones

### Canal oficial ML Afiliados (Telegram)
- Link: `https://t.me/+iUwhewgG9bg3N2Yx`
- Nombre: "Afiliados e Criadores Mercado Livre Brasil 🇧🇷"
- Los cupones vienen con bit.ly que hay que resolver → extraer `go=` parameter → pasar a `melila_api.py`

### Workflow de cupones:
1. Copiar mensajes del Telegram a `cupones_hoy.txt`
2. Ejecutar `python cargar_cupones.py`
3. Esto actualiza `cupones.json` y regenera `fila_posts.json`

---

## 13. Dependencias (`requirements.txt`)

```
requests>=2.31.0
beautifulsoup4>=4.12.0
Pillow>=10.0.0
flask>=3.0.0
google-generativeai>=0.7.0
```

---

## 14. Cómo Probar Localmente

```bash
# 1. Configurar credenciales
cp .env.example .env
# Editar .env con tus credenciales

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Probar scraping
python agente_ml.py
python agente_amazon.py

# 4. Generar cola de posts
python gerar_fila_posts.py

# 5. Probar publicación SIN enviar (preview del post exacto)
python publicar_proximo.py --test

# 6. Publicar de verdad (1 post, es el modo normal)
python publicar_proximo.py

# 7. Comprobar la salud de TODO el pipeline (empieza por aquí si algo falla)
python verificar_criba.py

# 8. Probar meli.la
python melila_api.py --test "https://www.mercadolivre.com.br/..."
```

> `--single` ya no hace falta: el publicador siempre envía **1 post por
> ejecución**. La cadencia de 7-8 min la da el cron externo, no un `sleep`.

> **Si `verificar_criba.py` dice "cookie ML vencida"**: no es fatal, el bot
> sigue publicando con la prioridad 2 de la Regla de Oro. Renueva la cookie
> cuando puedas.

---

## 15. Decisiones de Diseño Importantes

1. **50/50 ML/Amazon en WhatsApp** — Alternancia estricta entre tiendas
2. **No posts genéricos de cupones** — Solo productos con foto (el usuario eliminó los posts tipo `cupons_loja` porque eran spam)
3. **1 post por ejecución, sin `sleep`** — La cadencia de 7-8 min la da el cron
   externo (cron-job.org → `workflow_dispatch`). Dormir dentro del job ataba la
   cadencia al `schedule` de GitHub, que se estrangula a ~3 h. **Éste fue el bug
   de fondo.**
4. **Filtro de nicho SOLO en WhatsApp** — El website muestra TODO
5. **Anti-repetición 48h** — `gerar_fila_posts.py` excluye de la fila lo enviado
   en 48 h. Además `modulo_ofertas.ya_enviado()` aplica un segundo filtro de 24 h
   (`HORAS_ANTI_SPAM`) en el momento de publicar.
6. **Calentamiento progresivo** — Día 1: 20 posts, Día 2: 40, Día 3+: 120 (para no bloquear el grupo)
7. **Cache meli.la 7 días** — Para no llamar la API por cada link repetido
8. **`continue-on-error: true` en los steps de scraping** — Decisión del usuario
   para que el workflow no se detenga por un step fallido. Ojo: hace que los
   fallos sean silenciosos.
9. **Publicar y scrapear separados** — El cron externo solo publica; el
   `schedule` scrapea. Scrapear ML/Amazon cada 8 min haría que bloqueen la IP.
10. **Regla de Oro ejecutable** — `resolver_link_afiliado()` aborta el post si el
    link contiene `/go/`. La regla ya no depende de que alguien se acuerde.

---

## 16. Contacto y Cuentas

- **Dueño:** Jose Gregorio Alcala
- **Nick ML:** `JA20250119201346`
- **Grupo WhatsApp:** "🔥Achadinhos no Zap" (`120363413395651443@g.us`)
- **Sitio web:** `achadinhosnozap.com.br`
- **GitHub:** `Gollop33/criba`
