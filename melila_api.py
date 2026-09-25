#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Generador meli.la por API interna directa (sin Playwright) — melila_api.py
=================================================================================
REEMPLAZO del metodo Playwright de gerador_melila.py.

Llama directamente a los endpoints de la API de afiliados de Mercado Livre:
  1. GET  https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/tags
     -> devuelve tus etiquetas: {"tags": [{"tag": "...", "in_use": true, ...}]}
  2. POST https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links
     body: {"url": "<url del producto>", "tag": "<tu etiqueta en uso>"}
     -> devuelve {"short_url": "https://meli.la/xxxx", ...}

CARACTERÍSTICAS ROBUSTAS:
  - Rate limiting inteligente (mínimo 1.0s entre peticiones para no saturar)
  - Caché persistente en 'cache_melila.json' (válido por 7 días)
  - Manejo de excepciones con fallback automático y seguro
  - Cero dependencias de navegador o Chromium
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Falta 'requests'. Instala con: pip install requests")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "cache_melila.json"

BASE_URL = "https://www.mercadolivre.com.br"
TAGS_URL = BASE_URL + "/affiliate-program/api/v2/stripe/user/tags"
LINKS_URL = BASE_URL + "/affiliate-program/api/v2/stripe/user/links"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/",
}

_ultima_llamada = 0.0
MIN_INTERVALO_SEG = 1.0  # Mínimo 1 segundo entre llamadas

# Motivo del último fallo de generar_melila(). Permite al publicador distinguir
# "cookie vencida / error temporal" (donde el respaldo con tag SÍ monetiza) de
# "producto no elegible para el programa" (donde el respaldo NO paga comisión y
# por tanto conviene descartar el post en vez de regalar el clic).
ULTIMO_MOTIVO = None


def _aplicar_rate_limit():
    """Garantiza al menos MIN_INTERVALO_SEG segundos entre peticiones consecutivas."""
    global _ultima_llamada
    ahora = time.time()
    espera = MIN_INTERVALO_SEG - (ahora - _ultima_llamada)
    if espera > 0:
        time.sleep(espera)
    _ultima_llamada = time.time()


def _leer_cache():
    """Lee cache_melila.json si existe."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _escribir_cache(cache_data):
    """Guarda cache_melila.json de forma segura."""
    try:
        CACHE_FILE.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[meli.la/api] Error guardando caché: {e}")


def _cargar_cookies(cookie_str):
    """Convierte 'a=b; c=d' (o JSON de cookies exportadas) en dict."""
    cookies = {}
    if not cookie_str:
        return cookies
    txt = cookie_str.strip()
    if txt.startswith("[") and txt.endswith("]"):
        try:
            for c in json.loads(txt):
                if isinstance(c, dict) and c.get("name"):
                    cookies[c["name"]] = c.get("value", "")
            return cookies
        except Exception:
            pass
    for parte in txt.split(";"):
        if "=" in parte:
            nombre, valor = parte.split("=", 1)
            nombre = nombre.strip()
            if nombre:
                cookies[nombre] = valor.strip()
    return cookies


def _sesion(cookie_str):
    s = requests.Session()
    s.headers.update(HEADERS)
    for nombre, valor in _cargar_cookies(cookie_str).items():
        s.cookies.set(nombre, valor, domain=".mercadolivre.com.br")
    return s


def obtener_tag_en_uso(cookie_str):
    """Pregunta a ML cuál es tu etiqueta de afiliado activa."""
    if not cookie_str:
        return None
    try:
        _aplicar_rate_limit()
        s = _sesion(cookie_str)
        r = s.get(TAGS_URL, timeout=20)
        if r.status_code == 401:
            print("[meli.la/api] Cookie vencida o inválida (401 en /tags).")
            return None
        r.raise_for_status()
        tags = r.json().get("tags", [])
        for t in tags:
            if t.get("in_use"):
                return t.get("tag")
        return tags[0].get("tag") if tags else None
    except Exception as e:
        print(f"[meli.la/api] Error obteniendo etiqueta: {e}")
        return None


def generar_melila(url_producto, cookie_str=None, tag=None):
    """
    Genera el link corto meli.la para un producto con:
      - Verificación previa de caché (7 días)
      - Rate limiting automático
      - Manejo robusto de errores con retorno seguro (None para fallback)
    """
    global ULTIMO_MOTIVO
    ULTIMO_MOTIVO = None
    if not url_producto:
        return None

    # 1. Verificar caché persistente primero
    cache = _leer_cache()
    if url_producto in cache:
        entrada = cache[url_producto]
        # Válido por 7 días (7 * 86400 segundos)
        if time.time() - entrada.get("timestamp", 0) < 7 * 86400:
            # Ya sabemos que este producto no es elegible: no reintentar.
            if entrada.get("no_elegible"):
                ULTIMO_MOTIVO = "no_elegible"
                return None
            short_cached = entrada.get("short_url")
            if short_cached:
                return short_cached

    # 2. Verificar cookie de sesión
    cookie_str = cookie_str or os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if not cookie_str:
        ULTIMO_MOTIVO = "sin_cookie"
        return None

    try:
        if not tag:
            tag = obtener_tag_en_uso(cookie_str)
        if not tag:
            print("[meli.la/api] No se pudo obtener la etiqueta de afiliado.")
            ULTIMO_MOTIVO = "cookie"
            return None

        _aplicar_rate_limit()
        s = _sesion(cookie_str)
        r = s.post(LINKS_URL, json={"url": url_producto, "tag": tag}, timeout=20)

        if r.status_code == 401:
            print("[meli.la/api] Cookie vencida o inválida (401 en /links).")
            ULTIMO_MOTIVO = "cookie"
            return None

        # 400 con error_code 111 = "URL not allowed in affiliates program".
        # NO es un fallo nuestro: ese producto concreto no es elegible para el
        # programa (ML no paga comisión por él). Se comprobó con una sonda sobre
        # los 6 formatos de payload posibles: el formato {"url","tag"} es
        # correcto y el resto de productos sí se aceptan.
        #
        # Importante: se guarda en caché para no reintentar cada ejecución.
        if r.status_code == 400:
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            if err.get("error_code") == 111:
                print("[meli.la/api] NO ELEGIBLE para el programa de afiliados "
                      "(no paga comisión). Se descarta y se recuerda.")
                cache[url_producto] = {
                    "short_url": None,
                    "no_elegible": True,
                    "timestamp": time.time(),
                    "tag": tag,
                }
                _escribir_cache(cache)
                ULTIMO_MOTIVO = "no_elegible"
                return None

        r.raise_for_status()

        short_url = r.json().get("short_url")
        if short_url:
            print(f"[meli.la/api] OK -> {short_url}")
            # Guardar en caché
            cache[url_producto] = {
                "short_url": short_url,
                "timestamp": time.time(),
                "tag": tag
            }
            _escribir_cache(cache)
            return short_url
        else:
            print(f"[meli.la/api] Sin short_url en respuesta: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"[meli.la/api] Error inesperado en generar_melila: {e}")
        return None


def generar_lote(urls, cookie_str=None):
    """Genera meli.la para una lista de URLs. Retorna dict {url: short_url}."""
    cookie_str = cookie_str or os.environ.get("ML_PORTAL_COOKIE", "").strip()
    tag = obtener_tag_en_uso(cookie_str) if cookie_str else None
    if tag:
        print(f"[meli.la/api] Etiqueta activa en uso: {tag}")
    resultados = {}
    for u in urls:
        short = generar_melila(u, cookie_str, tag=tag)
        resultados[u] = short
    return resultados


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--test":
        url = sys.argv[2]
        print(f"Probando con: {url}")
        resultado = generar_melila(url)
        print("RESULTADO:", resultado if resultado else "FALLO (revisa la cookie ML_PORTAL_COOKIE)")
    else:
        print("Uso: ML_PORTAL_COOKIE=\"...\" python melila_api.py --test \"<url producto>\"")
