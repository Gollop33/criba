# CRIBA · Configurar el cron externo (cron-job.org)

## Por qué hace falta

El `schedule` nativo de GitHub **no publica cada 7-8 minutos**. Medición real sobre
las últimas 60 ejecuciones del workflow `bot.yml`:

| Métrica | Valor |
|---|---|
| Gap **mediano** entre ejecuciones | **174 min (~3 h)** |
| Gap mínimo observado | 56 min |
| Gaps > 60 min | **58 de 59** |
| Cron declarado | `*/15` (15 min) |

GitHub estrangula los `schedule` de alta frecuencia. Por eso la cadencia la da un
**cron externo** que llama a la API `workflow_dispatch` cada 8 minutos.

---

## Paso 1 — Crear un token de GitHub

1. Entra en <https://github.com/settings/personal-access-tokens/new>
   (Fine-grained token. **No** uses un token classic.)
2. **Token name:** `criba-cron-externo`
3. **Expiration:** 90 días o "No expiration" (si expira, el bot se detiene en silencio).
4. **Repository access:** `Only select repositories` → `Gollop33/criba`
5. **Permissions** → `Repository permissions` → busca **Actions** →
   ponlo en **Read and write**. Nada más.
6. `Generate token` y **copia el token** (`github_pat_...`). Solo se muestra una vez.

> ⚠️ El PAT que está guardado hoy en `C:\Users\Jose Alcala\.git-credentials`
> está **expirado** (devuelve `401 Unauthorized`). Hay que crear uno nuevo.
> Ese token viejo además no está siendo usado por git porque el helper
> configurado es `wincred`, no `store`.

---

## Paso 2 — Crear la cuenta en cron-job.org

1. Regístrate en <https://cron-job.org/en/signup/> (gratis, sin tarjeta).
2. Confirma el email.

---

## Paso 3 — Crear los DOS cronjobs

Son dos, y cada uno hace una cosa distinta. El plan gratis de cron-job.org los
admite sin problema.

| # | Título | Cada | Body | Para qué |
|---|--------|------|------|----------|
| 1 | `CRIBA publicar` | 7 min | `{"ref":"main","inputs":{"modo":"publicar"}}` | publica 1 post validado en el momento |
| 2 | `CRIBA cosechar` | 60 min | `{"ref":"main","inputs":{"modo":"full","bucle":"no"}}` | cosecha ML/cupones y regenera la fila, **sin** reservar el job 5,5 h |

> ¿Por qué `"bucle":"no"` en el segundo? Sin ese campo, el run entra en el bucle
> de 5,5 h y con el `concurrency` del workflow **bloquearía** todas las llamadas
> de 7 minutos hasta que termine. Con `bucle=no` cosecha en ~3 min y sale, así
> los dos cronjobs conviven.

### URL (la misma para los dos)
```
https://api.github.com/repos/Gollop33/criba/actions/workflows/bot.yml/dispatches
```

### Schedule
- Job 1: **Every 7 minutes** (`*/7 * * * *`)
- Job 2: **Every 60 minutes** (`0 * * * *`)
- **Todos los días, las 24 horas.** ⚠️ NO limites el horario en cron-job.org:
  desde el 2026-10-07 el bot es 24/7 (`VENTANA_BRT=0-24`) y ya baja el ritmo él
  solo por la noche (23h-7h BRT, un post cada 20-40 min). Si limitas las horas
  aquí, vuelves a tener el bot apagado media jornada.

### Request method
```
POST
```

### Headers (añade los 4)

| Header | Valor |
|---|---|
| `Authorization` | `Bearer github_pat_TU_TOKEN_AQUI` |
| `Accept` | `application/vnd.github+json` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

### Request body
```json
{"ref":"main","inputs":{"modo":"publicar"}}
```
(El job 2 usa `{"ref":"main","inputs":{"modo":"full","bucle":"no"}}`.)

> `publicar` ejecuta solo la parte ligera (regenerar fila + publicar 1 post +
> commit). **No** scrapea Mercado Livre ni Amazon: así el disparo de cada 7 min
> no nos hace 180 peticiones/hora ni nos bloquean la IP. La cosecha la hace el
> job 2 cada hora.

### Respuesta esperada
- **204 No Content** → correcto, la ejecución se ha encolado.
- **401** → el token es inválido o está expirado.
- **403** → al token le falta el permiso `Actions: Read and write`.
- **404** → el nombre del workflow (`bot.yml`) o del repo no coincide.

Activa **"Save responses in job history"** en cron-job.org para poder ver qué
devuelve cada llamada. Es tu principal herramienta de diagnóstico.

---

## Paso 4 — Verificar que funciona

### En cron-job.org
`History` del job 1: deben aparecer `204` cada 7 minutos.

### En GitHub
<https://github.com/Gollop33/criba/actions/workflows/bot.yml>
Deben aparecer ejecuciones con evento `workflow_dispatch` cada ~8 min.

### En el repo
Este comando te dice la cadencia real medida:

```bash
python verificar_criba.py
```

La línea clave es:

```
── 3. CADENCIA REAL DE ENVÍO ─────────────────────────────
  [OK]  envíos registrados en el log: 16
       mediana entre envíos: 39.9 min  (objetivo 7-8)
```

Cuando el cron externo esté activo, la mediana debe bajar a ~8 min.

### En el grupo
Debe llegar 1 post cada ~8 minutos entre las 8:00 y las 22:00 (hora Brasília).

---

## Límites y salvaguardas

| Regla | Valor | Dónde |
|---|---|---|
| Ventana de publicación | 8:00-22:00 BRT | `publicar_proximo.py` |
| Límite diario (día 3+) | 120 posts | `publicar_proximo.py` |
| Separación mínima entre posts | 6 min | `MIN_GAP_MIN` en `bot.yml` |
| Anti-repetición de producto | 24 h | `modulo_ofertas.py` |
| Ejecuciones solapadas | bloqueadas | `concurrency` en `bot.yml` |

El guardia de **6 minutos** (`MIN_GAP_MIN`) es la red de seguridad: si
cron-job.org reintenta una llamada o GitHub encola dos ejecuciones seguidas, la
segunda **no publica** — solo registra el salto. Sin ese guardia, un reintento
duplicaría el post en el grupo.

---

## Alternativa sin cron-job.org

Si prefieres no depender de un servicio externo, puedes disparar el mismo
endpoint desde tu PC con el Programador de tareas de Windows:

```powershell
# guardar como disparar_criba.ps1
$token = "github_pat_TU_TOKEN"
Invoke-RestMethod -Method Post `
  -Uri "https://api.github.com/repos/Gollop33/criba/actions/workflows/bot.yml/dispatches" `
  -Headers @{
    Authorization = "Bearer $token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
  } `
  -ContentType "application/json" `
  -Body '{"ref":"main","inputs":{"modo":"publicar"}}'
```

Luego crea una tarea en el Programador de tareas con desencadenador
"cada 8 minutos". **Requiere que el PC esté encendido**, por eso cron-job.org
es la opción recomendada.

---

## Si el bot deja de publicar

Orden de comprobación:

1. `python verificar_criba.py` → te dice qué falla.
2. cron-job.org → `History` → ¿siguen llegando `204`?
3. GitHub → `Actions` → ¿están fallando las ejecuciones?
4. ¿El token del cron externo caducó? (causa más común)
5. ¿El workflow está deshabilitado? GitHub lo desactiva tras 60 días sin
   actividad del repositorio.
