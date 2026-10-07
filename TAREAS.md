# TAREAS — qué chat usar para qué

> Este fichero existe para que **cada chat arranque sin tener que explicar nada**.
> Cuando abras uno nuevo, di: *"Lee TAREAS.md y sigue por donde toca."*

---

## 🔀 Cómo dividir los chats (y por qué ahorra)

El coste de un chat viene de **reenviar todo el historial en cada mensaje**. Así que
la regla es: **un chat = un tema**. Cuando el tema cambia, chat nuevo.

| Chat | Para qué | Skills | Comando antes de abrir |
|------|----------|:------:|------------------------|
| **A · Proyecto** | decisiones, estrategia, revisar estado, arreglar el bot | ❌ | `python sesion.py --charlar` |
| **B · Marketing** | SEO, redes, vídeos, copy, conversión | ✅ | `python sesion.py --marketing` |

**Por qué el interruptor:** DSH mete el catálogo de skills **entero** en cada petición.
Con las 14 activas son ~2.514 tokens por mensaje que pagas aunque estés hablando de
otra cosa. Apagarlas cuando no hacen falta es gratis.

⚠️ **El modo se aplica al ABRIR el chat.** Si cambias de modo con un chat abierto,
ese chat sigue con el catálogo que cargó. Cierra y abre.

---

## 🟢 Estado del sistema (a 2026-10-07)

```
Bot            : 24/7 — ventana VENTANA_BRT=0-24, noche 23-7h cada 20-40 min
Fila           : 164 posts | 149 Mercado Livre + 15 Amazon | 104 con cupon CONFIRMADO
Frescura       : solo se publica lo confirmado hace menos de 12 h (MAX_EDAD_HORAS)
Validacion     : 514 decisiones registradas en logs/validacion.jsonl
Token ML       : se renueva solo (duracion 6 h)
Pruebas        : 23/23 validador + 20/20 amazon + 134/134 shopee
Auditoria seg. : LIMPIA (2026-10-02) — skills sin scripts, sin envios externos raros
Sitio          : 478 ofertas, SEO arreglado, sitemap + robots
Videos         : generador funcionando (video/generar_video.py)
Shopee         : 3 fuentes listas | API pendiente | PAGOS pendientes | falta el ID
Amazon         : precio inventado CORREGIDO | cosecha real OK en local, 0 en Actions
Ofertas falsas : achados_especificos.json VACIADO + puerta dura en gerar_fila_posts
Mercado Livre  : cosecha RESTAURADA (0 -> 240 ofertas) con ML_PORTAL_COOKIE
```

---

## 🔴 2026-10-07 — el día que Mercado Livre se cayó y nadie se enteró

### 1. La causa raíz del "0 ofertas de ML" (lo más importante del día)

El bot pasó de **400 achados de Mercado Livre por día a 0** y el log solo decía
`Scraping ML: 0 ofertas obtenidas`. Sin ML no hay grupo: el 90% del material es de ahí.

**Diagnóstico (medido, no supuesto):**

| Petición | Resultado |
|----------|-----------|
| `GET /ofertas` sin cookie | HTTP 200, 41 KB, **0 poly-card**, 0 precios |
| `GET /ofertas` con `ML_PORTAL_COOKIE` | HTTP 200, 509 KB, **214 poly-card**, 121 precios |
| `lista.mercadolivre.com.br/...` | 41 KB, 0 productos (también cáscara) |
| `GET /sites/MLB/search` con token OAuth | **403 forbidden** (la app no tiene ese scope) |
| `GET /users/me` con token | 200 (el token SÍ sirve) |
| `GET /highlights/MLB/category/...` | 200 pero con `content` vacío |

Mercado Livre dejó de servir la página de ofertas a peticiones anónimas: devuelve una
cáscara que ejecuta `window.location.href = '/gz/account-verification/error'`.
El scraper **nunca enviaba la cookie de sesión**, así que se quedó ciego.

**Arreglo:** `agente_ml.py` usa ahora `UA_SESION` (con `ML_PORTAL_COOKIE`) y el
workflow le pasa el secreto. Verificado en el PC del usuario: **299 cosechadas → 240
guardadas**. Y si vuelve a dar 0, el log dice POR QUÉ (cookie ausente / caducada /
selectores cambiados) en vez de callarse.

### 2. Ofertas falsas: cerrado de verdad

`achados_especificos.json` tenía **4 ofertas de ejemplo del 2026-09-09** (Monitor LG
R$ 849, SSD Kingston R$ 389,90, Teclado Redragon R$ 179,90 y una basura "Mercado
Libre" R$ 477). El campo `simulado` no las cubría porque **son anteriores a ese
campo**: se colaron casi un mes, y el SSD sí se publicó en el grupo.
Ahora: archivo vaciado + **puerta dura** en `gerar_fila_posts._especifica_confiable()`
que exige precio > 0, id con formato REAL de la tienda (`MLB\d{6,}` / ASIN de 10),
url y que `origem` no sea del curador automático sin API key.

### 3. Frescura: "solo lo actualizado de menos de 12 h" (regla del usuario)

`MAX_EDAD_HORAS=12`. Una oferta sin fecha, o confirmada hace más de 12 h, no se
publica. Si la cosecha de una tienda se rompe (Amazon en Actions, por ejemplo), sus
ofertas **caducan solas** en vez de seguir publicándose como si fueran de hoy.
Probado con un test: una oferta de 3 días queda fuera.

### 4. Bot 24/7, sin dividir por nichos

- `VENTANA_BRT`: `8-22` (histórico) o `0-24`. En el workflow va `0-24`.
- `MODO_24H=1`: de 23h a 7h BRT el ritmo baja a un post cada 20-40 min
  (`INTERVALO_NOCHE_*`). Publicar cada 5 min a las 4 de la mañana es spam y quema el
  tope diario; así el bot sigue vivo sin parecer un robot.
- `MAX_ENVIOS_DIA` 150 → **220** (ahora también cubre la noche).
- Un solo flujo, sin reparto porcentual por nichos: `NICHO_MODO=geral`.
- El orden de la fila ya no es `random.shuffle`: va por **valor real**
  (descuento + frescura + cupón confirmado + precio bajo + bajada), con variedad
  sorteada solo *dentro* de bandas de 5 puntos.

### 5. Cupones y precios bajos — qué hay y qué falta

**Lo que ya funciona (medido hoy):**

| Pieza | Estado |
|-------|--------|
| Cupones genéricos de ML (canal oficial de afiliados por Telegram) | 64 códigos, se refresca cada hora |
| Cupón **por producto** confirmado por ML (`ml_tiene_cupon`) | **104 productos en la fila** |
| Cupones retirados por no estar confirmados por ML | 45 (antes se ponía cupón al 100% y ML lo rechazaba) |
| Precio con cupón y con Pix, leído de ML (no inventado) | `ml_precio_cupon`, `ml_precio_pix` |
| Histórico de precios (`precios.db → historico_precios`) | **+298 precios** el primer día; solo guarda CAMBIOS |
| Detección de bajada y readmisión con "📉 BAJÓ DE PRECIO" | funcionando (6 readmitidos hoy) |

**Por qué el histórico importa:** antes solo cubría ~60 productos vigilados (643
filas). Ahora `unir_achados.py` guarda el precio de **toda la cosecha fresca** y solo
cuando cambia, así que en pocos días se puede decir *"menor precio en 30 días"* sin
mentir — y eso es lo que de verdad mueve a un grupo de ofertas.

**Lo que falta (en orden de valor):**

1. **Etiquetar "MENOR PREÇO EM 30 DIAS"** en el post cuando el precio actual sea el
   mínimo real de los últimos 30 días (ya hay datos; falta pintarlo en la plantilla).
2. **Cupón por producto en Amazon**: leer la insignia "Cupom de X%" de la ficha
   (ya se lee título/precio/imagen de la ficha con `datos_ficha_amazon()`).
3. **Shopee**: sin `SHOPEE_AFFILIATE_ID` no se genera ni un enlace.
4. **Caducidad de la cookie ML**: cuando vuelva el 0, hay que renovarla
   (`REAUTORIZAR_ML.bat`). Ahora el log lo dice claramente.

---

> **OFERTAS FALSAS PUBLICADAS (2026-10-02). Lo más grave encontrado hasta ahora.**
> `agente_autonomo.simular_ofertas_teste()` devolvía 3 ofertas de EJEMPLO con
> precios inventados (Monitor LG R$ 849, SSD Kingston R$ 389,90, Teclado Redragon
> R$ 179,90) y se inyectaban en `achados_especificos.json`, que
> `gerar_fila_posts` publica con **prioridad 10 (las primeras de la fila)**.
> Y el disparador era: **si falta `DEALEE_API_KEY`** (`forzar_simulacion or not
> DEALEE_API_KEY`) → o sea, el modo "no hay API" era justo el que metía datos
> falsos. Además `config_afiliados.json` tenía `"dealee_api_key":
> "${DEALEE_API_KEY}"`, un texto literal que cuenta como clave válida.
>
> Comprobado en `logs/enviados.json`: **el SSD falso SÍ se publicó** el
> 2026-09-30 a las 16:23 con precio 389. Los otros dos estaban en la cola, por
> delante de todo.
>
> Arreglado: (1) sin clave de API el agente **no genera nada**; (2) `--simular`
> ya no escribe en el fichero; (3) cada oferta de ejemplo lleva `simulado: true`;
> (4) `gerar_fila_posts` las descarta **al cargarlas** (entraban por dos sitios:
> la lista de específicas y el bucle general de candidatos); (5) el placeholder
> del config ahora es cadena vacía. Fichero limpiado: 3 fuera, 1 real dentro.
> Prueba de regresión añadida: "una oferta SIMULADA nunca entra en la fila".

> **Amazon (2026-10-02). BUG GRAVE CORREGIDO: se inventaba el precio.**
> `agente_amazon.cosechar_pelando_amazon()` hacía `p_act = 89.90` (precio fijo),
> derivaba de ahí el precio anterior y ponía 20% de descuento si no encontraba
> ninguno. Medido sobre la página real de Pelando: de 37 artículos, **30 son
> páginas de CAMPAÑA** (`/promotion/psp/...`, `/b?node=...`), solo **1** es una
> ficha de producto, y 6 no tienen enlace. Aun así generaba **34 "ofertas"
> clonadas a R$ 89,90** apuntando a campañas.
> Comprobado en `logs/enviados.json`: **0 entradas con precio 89,90** → ninguna
> llegó a publicarse (en Actions Pelando no responde, por eso el fichero quedaba
> a 0). Era una bomba de relojería, no un daño hecho.
>
> **Arreglo:** Pelando solo DESCUBRE; el precio, el título y la foto se leen de
> la ficha de Amazon (`datos_ficha_amazon`, con `#productTitle`, `span.a-price`
> y `#landingImage`). Si el precio no se puede leer, el artículo se descarta.
> Medido tras el arreglo: **1 oferta real** (Electrolux R$ 1.420,30, antes
> R$ 1.499,00, -5,3%) en lugar de 34 inventadas.
>
> **Lo mismo en `descobrir_ofertas.py`** (script viejo, no está en el workflow):
> inventaba `p_act = 99.0` y un 18% OFF. Corregido, y además ahora **no toca
> `achados.json`** salvo que se pase `--forzar` (antes lo sobrescribía entero).
>
> **Amazon bloqueado desde GitHub (2026-10-02) — RESUELTO.**
> La cosecha real da **298 ofertas en el PC** y **0 en Actions**: Amazon
> bloquea las IPs de los centros de datos (se ve en el log nuevo:
> `categorias OK 19/28 | HTTP {503: 9}` incluso desde casa).
> Solución: Amazon se cosecha en el PC y se sube al repositorio.
>   · `ACTUALIZAR_AMAZON.bat` (doble clic) → `amazon_desde_pc.py`.
>   · Cosecha, comprueba el mínimo y sube SOLO `achados_amazon.json`.
>   · En el workflow, el paso de Amazon se salta con la variable de repositorio
>     `AMAZON_DESDE_PC = 1` (Settings → Variables → Actions).
> Resultado de la primera corrida: **219 ofertas reales con imagen y tag**,
> donde antes había 0. `reset_diario.py` solo COPIA ese fichero, no lo borra.
>
> **Pendiente (usuario):** programar `ACTUALIZAR_AMAZON.bat` 1 vez al día en el
> Programador de tareas de Windows, y crear la variable `AMAZON_DESDE_PC = 1`.


> **Shopee (2026-10-01).** El usuario recibió el email de la 1ª etapa: ya puede
> generar enlaces. Pero hay DOS cosas distintas pendientes, y las dos hay que
> hacerlas antes de mandar tráfico:
>
> **A · Datos de pago (esto es el dinero).** Shopee lo dice en el email: solo
> paga comisiones 60 días después de que los datos bancarios y fiscales estén
> rellenados y aprobados. Además, para Persona Física el cobro va SOLO a la
> cuenta digital Maree, el día 10 de cada mes, con mínimo de R$ 10.
>   1. Activar Maree: app Shopee → `Eu` → `Maree` → Ativar Agora (validación de
>      documentos: hasta 3 días hábiles).
>   2. Portal del Afiliado → clic en tu nombre (arriba a la derecha) →
>      `Configuração de Pagamento`. Pide: nombre completo, teléfono, fecha de
>      nacimiento, nombre completo de la madre, RG + comprobante, CPF +
>      comprobante, retención INSS, dirección + comprobante (y CCM si eres de SP).
>      Los datos deben coincidir EXACTAMENTE con los de Maree.
>   3. Shopee responde en hasta 7 días hábiles con "aprobado parcialmente";
>      la validación FINAL ocurre el día 1 de cada mes.
>   Ayuda oficial: https://help.shopee.com.br/portal/10/article/125654 (PF) y
>   https://help.shopee.com.br/portal/10/article/163058 (proceso de pago).
>
> **B · API de afiliados (esto es la automatización).** Estar aprobado como
> afiliado NO da la API; se pide aparte:
>   1. https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091
>      (pide tu ID de afiliado + teléfono; responden por email)
>   2. https://affiliate.shopee.com.br/open_api (solo en ordenador) → botón
>      "Aplicar" naranja → muestra App ID y Secret
>   3. Pegarlos en `.env` (`SHOPEE_APP_ID`, `SHOPEE_SECRET_KEY`) y subirlos a
>      GitHub con `GH_PAT=... python subir_secrets.py`
>
> **Dos candados, los dos cerrados hoy:** sin API no se cosecha; con API pero sin
> `shopee.pagos_aprobados = true` tampoco se publica (para no mandar clics que no
> se cobran). El código está listo y probado: `shopee_api.py` (cliente firmado),
> `agente_shopee.py` (cosechador), y Shopee aceptado por `unir_achados.py`,
> `gerar_fila_posts.py` y `validador_oferta.py`.
>
> **Verificado contra la API real (2026-10-01):** con credenciales de prueba,
> Shopee responde `error [10020]: Invalid Credential` — es decir, la petición
> llega, el endpoint y la consulta GraphQL se aceptan, y lo único que falta es la
> credencial real. No apareció ningún error de formato/consulta.
>
> **C · Enlace de afiliado SIN API (la vía rápida).** Shopee documenta un enlace
> oficial por URL que solo necesita el ID numérico de afiliado:
>
>     https://s.shopee.com.br/an_redir?origin_link=<url_codificada>
>          &affiliate_id=<ID>&sub_id=<etiqueta>
>
> Shopee redirige al producto añadiendo `utm_medium=affiliates` y
> `utm_source=an_<ID>`: la comisión queda atribuida al ID.
> **Probado contra Shopee Brasil el 2026-10-01** (redirect real + atribución
> presente). El bot verifica esa atribución antes de publicar
> (`python agente_shopee.py --verificar "<enlace>"`), y el validador final
> RECHAZA enlaces que lleven el ID de OTRO afiliado.
> Guía oficial: https://help.shopee.sg/portal/10/article/171184
>
> **Fuentes de producto que funcionan hoy (Shopee bloquea su API interna con 403
> y sus páginas son JavaScript puro: se comprobó, no se puede scrapear):**
>   1. **API oficial** (productOfferV2) → precio, comisión real y `offerLink`.
>   2. **Feed del portal** → portal → Criativo → Product Feed → descargar y
>      dejarlo como `shopee_feed.csv` en la carpeta del proyecto. Trae nombre,
>      precio, imagen y enlace; el bot le pone TU enlace `/an_redir`. Probado con
>      CSV y XLSX (detección automática de columnas).
>   3. **Grupos de ofertas de Telegram** → `python leer_telegram.py --horas 12` y
>      el agente resuelve cada enlace de Shopee y lo **reconvierte a tu cuenta**
>      (`/an_redir` + tu ID). Es el método del proyecto más popular del nicho
>      (SaulloGabryel/BlueBot, 22★): no buscar productos, sino reaprovechar los
>      que otros publican. Se apaga con `shopee.usar_telegram = false`.
>   4. Nada de lo anterior → el agente lo dice y no toca la red.
> **Lo único imprescindible HOY es `SHOPEE_AFFILIATE_ID`** (el número de tu
> cuenta): sin él no se puede construir ningún enlace que cobre.
>
> **D · Título y foto sin API (hallazgo 2026-10-02).** Shopee NO sirve los metas
> `og:` a un navegador normal (devuelve un shell JavaScript de 156 KB sin datos),
> pero SÍ se los sirve a los crawlers de previews de enlaces:
>
> | User-Agent | Resultado |
> |---|---|
> | `facebookexternalhit/1.1` | ✅ og:title + og:image (25 KB) |
> | `WhatsApp/2.x` | ✅ og:title + og:image (18 KB) |
> | UA de Android | ✅ og:title + og:image (580 KB) |
> | Chrome normal | ❌ shell sin datos |
> | Googlebot / Twitterbot | ❌ 403 |
>
> Con eso (`shopee_api.datos_producto`) se obtiene **el nombre real y la foto de
> cualquier producto con solo su enlace**, y de paso se detecta si el producto ya
> no existe (Shopee manda a la portada o a `/opaanlp/`) — así no se publican
> enlaces muertos. El precio no viene en los metas: en la fuente de Telegram se
> toma del mensaje y cada achado queda marcado con `precio_fuente`.
>
> **Qué hacen los proyectos de GitHub (investigado 2026-10-02):**
> · **bcat95/shopee-aff (81★)** documenta la Open API y vende una API de datos de
>   pago; no es código para copiar.
> · **SaulloGabryel/BlueBot (22★)** el más completo: monitoriza Telegram y
>   reenvía con media a Telegram + WhatsApp. Para Shopee usa **la API oficial**.
> · **MauricioRFilho/auto-post (16★)** anuncia scraping de Shopee, pero su
>   `scraper/src/scrapers/shopee.py` es un **stub** (`title="Shopee Product"`,
>   `price_cents=0`, selector marcado como "Example class"): no funciona.
> · **Henriq-Ls/api-shopee (6★)** API + copy con IA.
> · **Conclusión:** nadie scrapea Shopee de verdad; los que funcionan usan la API
>   o un navegador con sesión. Nuestro camino `/an_redir` no lo tiene nadie más.




---

## 📋 Pendientes, por chat

### Chat A · Proyecto

| # | Tarea | Estado |
|---|-------|--------|
| A1 | Verificar que el bot sigue publicando (runs de Actions) | ✅ sano |
| A2 | **Consumo de tokens**: revisar si otros procesos gastan de más | 🟡 abierto |
| A3 | Limpiar `video/toolchain/extraer_oferta.py` (lo dejó un agente que falló, sin usar) | ⏳ |
| A4 | Revisar `logs/validacion.jsonl` y ver si hay rechazos raros | ⏳ |
| A5 | **Shopee · dinero**: activar Maree + rellenar `Configuração de Pagamento` (datos bancarios y fiscales) | 🔥🔥🔥 esperando al usuario |
| A6 | **Shopee · ID de afiliado**: pegar `SHOPEE_AFFILIATE_ID` en `.env` (desbloquea el enlace sin API) | 🔥🔥🔥 esperando al usuario |
| A7 | **Shopee · productos**: `python leer_telegram.py --horas 12` y luego el agente (método BlueBot) | ✅ implementado, funciona con A6 |
| A8 | Shopee: `python agente_shopee.py --telegram --test` para ver la primera cosecha | ⏳ depende de A6 |
| A9 | Shopee: feed del portal (`shopee_feed.csv`) **o** API, para precio y comisión oficiales | 🔥🔥 opcional |
| A10 | Shopee: cuando Shopee apruebe los pagos, poner `shopee.pagos_aprobados = true` y encender | ⏳ depende de A5 |
| A11 | **Amazon**: cosechar desde el PC (`ACTUALIZAR_AMAZON.bat`) porque GitHub está bloqueado | ✅ listo, 219 ofertas ya subidas |

| A12 | Decidir qué hacer con los scripts viejos (`descobrir_ofertas.py`, `modulo_ofertas.py`): ya no los usa el workflow | 🟡 |



### Chat B · Marketing

| # | Tarea | Impacto | Estado |
|---|-------|---------|--------|
| B1 | **Vídeo "GRUPO"** — pantalla con ofertas cayendo (idea del usuario) | 🔥🔥 | diseñado, sin implementar |
| B2 | **Páginas por categoría** (`programmatic-seo`) — 12 páginas para Google | 🔥🔥🔥 | pendiente |
| B3 | **Alta en Google Search Console** — lo tiene que hacer el usuario | 🔥🔥🔥 | pendiente (10 min) |
| B4 | **Música en los vídeos** — ahora van mudos | 🔥 | pendiente |
| B5 | **Lote diario de vídeos** enganchado al workflow | 🔥 | pendiente |
| B6 | **3 datos de Meta** (FB + IG) — el código ya está listo | 🔥🔥 | pendiente (usuario) |
| B7 | Confirmar el diseño de los vídeos (colores, texto, tamaño) | — | esperando al usuario |

---

## 🎯 Lo que más rápido mueve la aguja

Por orden de impacto real:

1. **Google Search Console** (10 min tuyos) → sin esto Google no rastrea bien
2. **Páginas por categoría** (1 h mía) → tráfico gratis de Google
3. **Datos de Meta** (15 min tuyos) → publicar en Facebook e Instagram
4. **Vídeo GRUPO** (1 h mía) → contenido para TikTok/Reels
5. Resto

---

## 📚 Ficheros que importan

| Fichero | Qué es |
|---------|--------|
| `CONTEXT.md` | el documento maestro del proyecto |
| `.agents/product-marketing.md` | el contexto que leen las skills de marketing |
| `TAREAS.md` | este fichero |
| `shopee_api.py` | cliente de la API oficial de afiliados de Shopee (firma SHA256) |
| `agente_shopee.py` | cosechador de ofertas de Shopee (solo con credenciales) |
| `probar_shopee_api.py` | 77 pruebas offline de Shopee (no gastan cuota ni tocan la red) |
| `video/README.md` | cómo funciona el generador de vídeos |
| `logs/validacion.jsonl` | cada decisión de validación, con su motivo |

---

## ⚠️ Reglas que NO se negocian

1. **Nunca inventar un dato.** Si no se puede verificar, no se publica. Ya costó caro:
   el bot publicó cupones que no aplicaban y un Pix que no existía, y el usuario lo
   descubrió **en el checkout real**.
2. **El cupón de afiliado no se pone.** El de ML se activa en la página, sin código.
   Ver `.agents/product-marketing.md`.
3. **Verificar con datos, no con "debería funcionar".** El precio se comprobó contra
   el checkout: el post decía R$ 1076 y ML cobró R$ 1.076,49.
4. **Al instalar skills, filtrar.** El catálogo se paga en cada mensaje, no una vez.
