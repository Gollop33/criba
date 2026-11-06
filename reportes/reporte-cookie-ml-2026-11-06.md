# Reporte — Diagnóstico cookie ML + API de respaldo (CRIBA)

Fecha: 2026-11-06 · Rama: `fix/cookie-ml-api` · Ejecutor: dsh

## 1. Archivos cambiados y qué cambió

### `agente_ml.py`
- **`cargar_token_ml()`**: ahora lee `ML_ACCESS_TOKEN` del entorno primero (antes solo leía `config_afiliados.json`, que no existe en el runner). El archivo local queda como respaldo para desarrollo en el PC.
- **Nueva `_estructura_cookie()`**: devuelve el número de cookies parseadas, sus nombres y la longitud total de `ML_PORTAL_COOKIE`, **sin registrar jamás los valores** (son secretos).
- **`cosechar_scraping()`**: registra `[COOKIE-ESTRUCTURA]` al inicio de cada cosecha, para que la próxima corrida muestre si la cookie está completa o truncada.
- **Mensaje del diagnóstico corregido**: ya no remite a `REAUTORIZAR_ML.bat` (que renueva el token OAuth, **no** la cookie). Ahora dice que la API oficial (`ML_ACCESS_TOKEN`) es el respaldo y que, si tampoco cubre, se renueve `ML_PORTAL_COOKIE` vía `python subir_secrets.py`.

### `.github/workflows/bot.yml`
- Añadido `ML_ACCESS_TOKEN: ${{ secrets.ML_ACCESS_TOKEN }}` al paso **`cosechar mercado livre (agente_ml)`** (modo full).
- Añadido `ML_ACCESS_TOKEN` al paso **`cosechar si los achados estan viejos`** (modo publicar). Necesario porque `cosechar_si_viejo.py` lanza `agente_ml.py` por `subprocess.run` sin `env=` y hereda el entorno del paso.

## 2. Resultado del diagnóstico estructural

- **Local (PC del usuario):** la cookie de `.env` tiene **28 cookies, 2742 chars** y es **válida** (la API de afiliados responde con la etiqueta `ja20250119201346`).
- **En el runner (GitHub):** el resultado se conocerá en la próxima cosecha, cuando `[COOKIE-ESTRUCTURA]` imprima nº de cookies y longitud.
  - Si salen **<28 cookies** o **mucho menos de 2742 chars** → el secreto está **truncado** en la cadena exportación → `.env` → `subir_secrets.py` → secreto.
  - Si salen **28 cookies / ~2742 chars** → la cookie está **completa y ML rechaza esa sesión** (la invalidó).

## 3. ¿La API oficial funciona como respaldo?

- **Conectada**: el token ya se pasa al paso de cosecha y `cargar_token_ml()` lo lee del entorno.
- **PERO el token actual está vencido**: una llamada de prueba devuelve `HTTP 401 {"code":"unauthorized","message":"invalid access token"}`. El token OAuth de ML dura 6h y el de `.env` es del 05/11. Para que el respaldo funcione hay que renovarlo con `python obtener_token_ml.py --renovar` (usa `ML_REFRESH_TOKEN`).

## 4. Qué NO toqué

- **Tags de afiliado**: `#D[A:ja20250119201346]`, cortos `meli.la` vía `gerador_melila.py`, `tag=criba20-20` — intactos.
- **Formato de posts, frecuencia, lógica de cosecha de ofertas**: intactos. Solo se añadió el token de respaldo al env y un log de estructura, sin tocar cómo se cosecha.
- **Freno 120h/10%, piso 50 ventas, frescura 12h**: intactos.
- **Secrets/tokens/.env**: no se tocó ningún valor; no se registró ningún valor de cookie ni token en log (solo nombres y longitudes).

## 5. Diff para revisar

Ver `git diff main...fix/cookie-ml-api` (2 archivos: `agente_ml.py`, `.github/workflows/bot.yml`). No se sube a `main` sin revisión.

## 6. Pruebas

- `python -m py_compile agente_ml.py` → OK.
- `_estructura_cookie()` sin env → `"0 cookies, 0 chars (sin cookie)"` (correcto).
- `cargar_token_ml()` sin env → `None` (correcto).
- API oficial con el token de `.env` → `HTTP 401 invalid access token` (token vencido).

## Nota para emti

El respaldo de la API oficial está cableado, pero **no cubrirá mientras el token OAuth siga vencido**. Para que el respaldo quede operativo hace falta: (a) renovar el token (`obtener_token_ml.py --renovar`), y opcionalmente (b) que la cosecha renueve automáticamente con `ML_REFRESH_TOKEN` cuando la API responda 401 (hoy `cosechar_api` solo maneja 403). Queda fuera del alcance de este plan, pero es el siguiente paso natural si se quiere que la cosecha deje de depender de la cookie.
