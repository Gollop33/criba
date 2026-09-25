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
GitHub Actions (cada 15 min, 11:00-23:59 UTC)
│
├─ 1. cupones_pelando.py      → Scrape cupones de Pelando.com.br
├─ 2. agente_ml.py             → Scrape ofertas Mercado Livre → achados_ml.json
├─ 3. agente_amazon.py         → Scrape ofertas Amazon Brasil → achados_amazon.json
├─ 4. unir_achados.py          → Unifica → achados.json
├─ 5. agente_autonomo.py       → IA curada → achados_especificos.json (usa Gemini + Dealee)
├─ 6. gerador_melila.py --lote → Genera meli.la para todos los ML → cache_melila.json
├─ 7. acortador.py             → Acorta links → links.json + go/
├─ 8. gerar_fila_posts.py      → Genera cola de posts → fila_posts.json
├─ 9. publicar_proximo.py      → Publica 2 posts a WhatsApp (7.5 min entre ellos)
├─10. bot_precios.py           → Monitorea precios → precios.db + productos.json
├─11. alertas_telegram.py      → Alerta caídas/subidas → Telegram
└─12. git commit + push        → Actualiza repo → Triggerea GitHub Pages deploy
```

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

### `publicar_proximo.py` (299 líneas)
- **Función principal:** `main()` → publica 2 posts con 7.5min de pausa entre ellos
- **`publicar_un_post()`** → selecciona 1 post no enviado, genera meli.la, descarga foto, envía por WhatsApp
- Skipea posts tipo `cupons_loja` (solo envía productos con foto)
- Lee `fila_posts.json`, escribe `logs/enviados.json` y `logs/control_canal.json`

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

```yaml
cron: '*/15 11-23 * * *'  # Cada 15 min, 11:00 a 23:59 UTC (~8:00 a 20:59 BRT)
```

### ⚠️ ADVERTENCIA: `continue-on-error: true`
Todos los steps tienen `continue-on-error: true`, lo que significa que **los fallos son SILENCIOSOS**. Si un step falla, el workflow sigue como si nada. Esto dificulta el debugging.

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

### A. Bot envía cada ~4 horas en vez de cada 7-8 minutos
**Síntoma:** El grupo recibe posts muy espaciados (~4h) en vez de cada 7-8 min.
**Causas posibles:**
1. `publicar_proximo.py` tiene `time.sleep(450)` (7.5 min) que junto con el workflow de 15 min = solo 2 posts por ejecución. Eso es correcto, pero quizás los workflows fallan silenciosamente (por `continue-on-error: true`)
2. `logs/control_canal.json` puede no estar persistiendo correctamente el `envios_hoy` entre ejecuciones
3. La cookie `ML_PORTAL_COOKIE` vence y `melila_api.py` retorna `None`, causando que se saltee el post
4. El git push puede fallar por conflictos de merge, haciendo que `fila_posts.json` y `logs/` no se actualicen

**Para investigar:** Revisar los logs de GitHub Actions en `https://github.com/Gollop33/criba/actions/workflows/bot.yml`

### B. Website estancado — Solo muestra monitores viejos
**Síntoma:** `achadinhosnozap.com.br` muestra los mismos monitores desde hace días.
**Causas posibles:**
1. `achados.json` no se actualiza en el repo (el git push falla)
2. GitHub Pages CDN cachea el JSON viejo (mitigado con `?_t=Date.now()`)
3. Los scrapers `agente_ml.py` / `agente_amazon.py` fallan silenciosamente

### C. Cookie ML_PORTAL_COOKIE se vence
- La cookie de sesión de Mercado Livre se vence periódicamente
- Cuando vence: `melila_api.py` retorna `None`, los posts se envían sin link corto o no se envían
- **Para renovar:** Loguear en `mercadolivre.com.br/affiliate-program`, abrir DevTools → Application → Cookies, copiar TODA la cookie string, actualizar en `.env` local Y en GitHub Secrets

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
├── publicar_proximo.py          # Publica a WhatsApp (2 posts/ejecución)
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
├── fila_posts.json              # Cola de posts WhatsApp
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

# 5. Probar publicación (modo test, no envía realmente)
python publicar_proximo.py --test

# 6. Probar publicación real (1 solo post)
python publicar_proximo.py --single

# 7. Probar meli.la
python melila_api.py --test "https://www.mercadolivre.com.br/..."
```

---

## 15. Decisiones de Diseño Importantes

1. **50/50 ML/Amazon en WhatsApp** — Alternancia estricta entre tiendas
2. **No posts genéricos de cupones** — Solo productos con foto (el usuario eliminó los posts tipo `cupons_loja` porque eran spam)
3. **Sleep de 7.5 min en publicar_proximo.py** — Para lograr cadencia de 7-8 min entre posts
4. **Filtro de nicho SOLO en WhatsApp** — El website muestra TODO
5. **Anti-repetición 48h** — Un producto no se publica dos veces en 48 horas
6. **Calentamiento progresivo** — Día 1: 20 posts, Día 2: 40, Día 3+: 120 (para no bloquear el grupo)
7. **Cache meli.la 7 días** — Para no llamar la API por cada link repetido
8. **`continue-on-error: true` en todos los steps** — Decisión del usuario para que el workflow no se detenga por un step fallido

---

## 16. Contacto y Cuentas

- **Dueño:** Jose Gregorio Alcala
- **Nick ML:** `JA20250119201346`
- **Grupo WhatsApp:** "🔥Achadinhos no Zap" (`120363413395651443@g.us`)
- **Sitio web:** `achadinhosnozap.com.br`
- **GitHub:** `Gollop33/criba`
