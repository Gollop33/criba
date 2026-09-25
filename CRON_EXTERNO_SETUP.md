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

## Paso 3 — Crear el cronjob

`Create cronjob` y rellena **exactamente** esto:

### Título
```
CRIBA publicar WhatsApp
```

### URL
```
https://api.github.com/repos/Gollop33/criba/actions/workflows/bot.yml/dispatches
```

### Schedule
- **Every 8 minutes** (o expresión cron: `*/8 * * * *`)
- **Execution:** cada 8 min, todos los días.
- ⚠️ En cron-job.org, desmarca cualquier opción de "días" que limite el horario:
  el propio bot ya filtra la ventana 8:00-22:00 Brasília. Si prefieres ahorrar
  ejecuciones, puedes limitarlo a las horas 11-01 UTC.

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

> El campo `modo` es importante: `publicar` ejecuta solo la parte ligera
> (generar fila + publicar 1 post + commit). **No** scrapea Mercado Livre ni
> Amazon, para que no nos bloqueen la IP por hacer 180 peticiones/hora.
> El pipeline completo lo sigue disparando el `schedule` de GitHub.

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
`History` del cronjob: deben aparecer `204` cada 8 minutos.

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
