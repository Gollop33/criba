#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Generador meli.la por API interna (sin Playwright) — melila_api.py
==========================================================================
REEMPLAZO del metodo Playwright de gerador_melila.py.

DESCUBRIMIENTO (reverse-engineered por la comunidad, verificado en vivo):
El boton "Compartilhar" de Mercado Livre NO hace magia: solo llama 2 URLs
internas con tu sesion (cookie). Podemos llamarlas directo, sin abrir navegador.

  1. GET  https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/tags
     -> devuelve tus etiquetas: {"tags": [{"tag": "...", "in_use": true, ...}]}

  2. POST https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links
     body: {"url": "<url del producto>", "tag": "<tu etiqueta en uso>"}
     -> devuelve {"short_url": "https://meli.la/xxxx", ...}

VENTAJAS vs Playwright:
  - Sin instalar Chromium (las corridas son mas rapidas y baratas)
  - Sin botones que buscar (no se rompe si ML cambia la pagina)
  - Sin limite de 15 por corrida (son simples llamadas HTTP)
  - Misma cookie de siempre: ML_PORTAL_COOKIE

REQUISITO: ML_PORTAL_COOKIE valida (igual que antes). Si la cookie vencio,
  la API responde 401 y hay que renovarla desde tu navegador.

INTEGRACION con gerador_melila.py:
  En obtener_link_afiliado_ml(), reemplaza la llamada a
  extraer_melila_con_playwright(...) por:
      from melila_api import generar_melila
      melila_resuelto = generar_melila(url_producto, cookie_str)

PRUEBA RAPIDA:
  ML_PORTAL_COOKIE="tu_cookie" python melila_api.py --test "https://www.mercadolivre.com.br/.../p/MLB123..."
"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("Falta 'requests'. Instala con: pip install requests")
    sys.exit(1)

BASE = "https://www.mercadolivre.com.br"
TAGS_URL = BASE + "/affiliate-program/api/v2/stripe/user/tags"
LINKS_URL = BASE + "/affiliate-program/api/v2/stripe/user/links"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": BASE + "/",
}


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
    """Pregunta a ML cual es tu etiqueta de afiliado activa."""
    s = _sesion(cookie_str)
    r = s.get(TAGS_URL, timeout=20)
    if r.status_code == 401:
        print("[meli.la/api] Cookie vencida o invalida (401 en /tags).")
        return None
    r.raise_for_status()
    tags = r.json().get("tags", [])
    for t in tags:
        if t.get("in_use"):
            return t.get("tag")
    return tags[0].get("tag") if tags else None


def generar_melila(url_producto, cookie_str=None, tag=None):
    """
    Genera el link corto meli.la para un producto.
    Retorna "https://meli.la/xxxx" o None si fallo.
    """
    cookie_str = cookie_str or os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if not cookie_str:
        print("[meli.la/api] Sin ML_PORTAL_COOKIE, no se puede generar.")
        return None

    s = _sesion(cookie_str)

    if not tag:
        tag = obtener_tag_en_uso(cookie_str)
    if not tag:
        print("[meli.la/api] No se pudo obtener tu etiqueta de afiliado.")
        return None

    try:
        r = s.post(LINKS_URL, json={"url": url_producto, "tag": tag}, timeout=20)
    except Exception as e:
        print(f"[meli.la/api] Error de red: {e}")
        return None

    if r.status_code == 401:
        print("[meli.la/api] Cookie vencida o invalida (401 en /links).")
        return None
    try:
        r.raise_for_status()
    except Exception as e:
        print(f"[meli.la/api] HTTP {r.status_code}: {e}")
        return None

    short_url = r.json().get("short_url")
    if short_url:
        print(f"[meli.la/api] OK -> {short_url}")
    else:
        print(f"[meli.la/api] Sin short_url en respuesta: {r.text[:200]}")
    return short_url


def generar_lote(urls, cookie_str=None):
    """Genera meli.la para una lista de URLs. Retorna dict {url: short_url}."""
    cookie_str = cookie_str or os.environ.get("ML_PORTAL_COOKIE", "").strip()
    tag = obtener_tag_en_uso(cookie_str) if cookie_str else None
    print(f"[meli.la/api] Etiqueta en uso: {tag}")
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
        print("RESULTADO:", resultado if resultado else "FALLO (revisa la cookie)")
    else:
        print("Uso: ML_PORTAL_COOKIE=\"...\" python melila_api.py --test \"<url producto>\"")
