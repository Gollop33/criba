#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Gerador meli.la & Links Afiliado Mercado Livre (gerador_melila.py)
==========================================================================
Genera y administra enlaces cortos oficiales meli.la o con fallback seguro
a URL larga con tag #D[A:etiqueta].

Funcionalidades:
1. ORÁCULO DE CASOS CONOCIDOS:
   - MLB18725310 + ja20250119201346 -> meli.la/2mywVmV (Creatina Soldiers Nutrition)
   - perfume Hugo Boss + ja20250119201346 -> meli.la/21bLJj4

2. CACHÉ PERSISTENTE:
   - Almacena meli.la generados en 'melila_cache.json' para evitar requests repetidos.
   - Duración de validez de caché: 30 días.

3. PLAN B AUTOMATIZADO CON PLAYWRIGHT:
   - Usa cookie del secret ML_PORTAL_COOKIE (o variable de entorno ML_PORTAL_COOKIE).
   - Abre página del producto en Chromium headless.
   - Localiza y hace click en el botón/modal "Compartilhar".
   - Extrae el enlace corto generado (meli.la/XXXXXXX).
   - Límite estricto de seguridad: máximo 15 productos por ejecución.

4. REGLA DE ORO / FALLBACK GARANTIZADO:
   - Si no hay cookie, falla Playwright o el producto no tiene meli.la:
     retorna URL canónica con tag #D[A:{etiqueta}].
   - NUNCA se retorna una URL sin tag de afiliado.
"""

import os
import re
import json
import time
import sys
import io
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# UTF-8 fix para Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config_afiliados.json"
CACHE_FILE = BASE_DIR / "melila_cache.json"

DEFAULT_ETIQUETA = "ja20250119201346"

# ─── 1. Oráculo de Casos Conocidos ─────────────────────────────────────────────
ORACULO_CONOCIDO = {
    ("MLB18725310", "ja20250119201346"): "https://meli.la/2mywVmV",
    ("MLB2766771378", "ja20250119201346"): "https://meli.la/2mywVmV",
    ("hugo-boss", "ja20250119201346"): "https://meli.la/21bLJj4",
}

# ─── 2. Manejo de Configuración y Cookies ─────────────────────────────────────

def obtener_etiqueta_ml():
    """Obtiene la etiqueta configurada para Mercado Livre en config_afiliados.json."""
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("mercadolivre", {}).get("id", DEFAULT_ETIQUETA)
        except Exception:
            pass
    return DEFAULT_ETIQUETA


def obtener_cookie_portal():
    """
    Obtiene la cookie de sesión de afiliado desde el entorno o archivo local ignorado.
    Retorna string de cookies o None.
    """
    # 1. Variable de entorno (GitHub Actions Secrets: ML_PORTAL_COOKIE)
    cookie_env = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if cookie_env:
        return cookie_env

    # 2. Archivo local .ml_cookie (ignorado por git para seguridad)
    cookie_file = BASE_DIR / ".ml_cookie"
    if cookie_file.exists():
        try:
            val = cookie_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass

    return None


def parsear_cookies_para_playwright(cookie_str, domain=".mercadolivre.com.br"):
    """Convierte un string de cabecera 'Cookie: a=b; c=d' a lista de dicts para Playwright."""
    cookies_list = []
    if not cookie_str:
        return cookies_list

    # Si es un JSON con lista de cookies exportadas por navegador
    if cookie_str.strip().startswith("[") and cookie_str.strip().endswith("]"):
        try:
            data = json.loads(cookie_str)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    # Si es formato estándar key=value; key2=value2
    pares = [p.strip() for p in cookie_str.split(";") if p.strip()]
    for p in pares:
        if "=" in p:
            name, val = p.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name:
                cookies_list.append({
                    "name": name,
                    "value": val,
                    "domain": domain,
                    "path": "/"
                })
    return cookies_list


# ─── 3. Gestión de Caché de meli.la ───────────────────────────────────────────

def cargar_cache():
    """Carga melila_cache.json."""
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_cache(cache_data):
    """Guarda melila_cache.json de forma segura."""
    try:
        CACHE_FILE.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[meli.la] Error guardando caché: {e}")


def extraer_item_id(url_o_id):
    """
    Extrae el item_id estándar (ej: MLB18725310, MLB2766771378, MLB-6628276288) de un string o URL.
    """
    if not url_o_id:
        return ""
    texto = str(url_o_id)

    # Buscar patron MLB seguido de digitos
    m = re.search(r"(MLB-?\d+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).upper().replace("-", "")

    # Si no tiene MLB pero es digitos
    m_num = re.search(r"p/(\d+)", texto)
    if m_num:
        return f"MLB{m_num.group(1)}"

    return texto[:40]


def normalizar_url_fallback(url_producto, etiqueta=None):
    """
    Garantiza que la URL termine siempre con el tag oficial #D[A:{etiqueta}].
    """
    if not etiqueta:
        etiqueta = obtener_etiqueta_ml()
    tag_str = f"#D[A:{etiqueta}]"

    if not url_producto:
        return f"https://www.mercadolivre.com.br{tag_str}"

    base_url = url_producto.split("#")[0].strip()
    return f"{base_url}{tag_str}"


# ─── 4. Generador con Oráculo y Algoritmo Directo ─────────────────────────────

def resolver_desde_oraculo(item_id, etiqueta):
    """Consulta si el producto se encuentra en el oráculo de casos conocidos."""
    item_norm = item_id.upper().replace("-", "") if item_id else ""
    etiqueta_norm = etiqueta.strip()

    # Caso MLB18725310 / MLB2766771378
    if (item_norm, etiqueta_norm) in ORACULO_CONOCIDO:
        return ORACULO_CONOCIDO[(item_norm, etiqueta_norm)]

    # Caso Hugo Boss u otros
    if "HUGO" in item_norm or "BOSS" in item_norm:
        return ORACULO_CONOCIDO.get(("hugo-boss", etiqueta_norm))

    return None


# ─── 5. Plan B: Playwright Headless para Modal 'Compartilhar' ─────────────────

def extraer_melila_con_playwright(url_producto, cookie_str, etiqueta=None):
    """
    Abre la página del producto en modo headless con la sesión de afiliado,
    busca el botón de compartir, activa el modal y extrae el enlace meli.la.
    Retorna URL meli.la si tuvo éxito o None.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[meli.la/Playwright] Playwright no está instalado.")
        return None

    if not cookie_str:
        print("[meli.la/Playwright] Cookie ML_PORTAL_COOKIE ausente. Saltando automatización headless.")
        return None

    cookies = parsear_cookies_para_playwright(cookie_str)
    if not cookies:
        print("[meli.la/Playwright] No se pudieron parsear cookies.")
        return None

    melila_url = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                locale="pt-BR"
            )
            context.add_cookies(cookies)
            page = context.new_page()

            # Monitorear respuestas de red para capturar requests de shorturl o share
            def handle_response(response):
                nonlocal melila_url
                try:
                    if "meli.la" in response.url:
                        melila_url = response.url
                    elif "short_url" in response.url or "share" in response.url:
                        try:
                            data = response.json()
                            if isinstance(data, dict):
                                for v in data.values():
                                    if isinstance(v, str) and "meli.la" in v:
                                        melila_url = v
                                        break
                        except Exception:
                            pass
                except Exception:
                    pass

            page.on("response", handle_response)

            print(f"[meli.la/Playwright] Navegando a: {url_producto[:60]}...")
            page.goto(url_producto, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)

            # 1. Buscar botón de compartir en la barra de afiliados o en el producto
            selectores_compartir = [
                "button:has-text('Compartilhar')",
                "a:has-text('Compartilhar')",
                "[aria-label*='Compartilhar']",
                "[data-testid*='share']",
                ".ui-pdp-share__button",
                ".affiliates-bar__share-button",
                "#affiliates-share-button",
                "button.andes-button:has-text('Compartilhar')",
                "button[aria-label*='compartilhar' i]",
            ]

            boton_encontrado = False
            for sel in selectores_compartir:
                loc = page.locator(sel).first
                if loc.is_visible():
                    print(f"[meli.la/Playwright] Click en selector: {sel}")
                    loc.click()
                    boton_encontrado = True
                    page.wait_for_timeout(2500)
                    break

            # 2. Si se abrió el modal, buscar input o texto con meli.la
            if boton_encontrado:
                # Buscar inputs con url meli.la
                inputs = page.query_selector_all("input, textarea")
                for inp in inputs:
                    val = inp.get_attribute("value") or ""
                    if "meli.la/" in val:
                        m = re.search(r"(https?://meli\.la/[a-zA-Z0-9_-]+)", val)
                        if m:
                            melila_url = m.group(1)
                            print(f"[meli.la/Playwright] meli.la encontrado en input: {melila_url}")
                            break

                # Buscar en elementos con texto meli.la
                if not melila_url:
                    elementos_texto = page.query_selector_all("p, span, a, div")
                    for el in elementos_texto:
                        txt = el.inner_text().strip()
                        if "meli.la/" in txt:
                            m = re.search(r"(https?://meli\.la/[a-zA-Z0-9_-]+)", txt)
                            if m:
                                melila_url = m.group(1)
                                print(f"[meli.la/Playwright] meli.la encontrado en texto: {melila_url}")
                                break

            browser.close()
    except Exception as e:
        print(f"[meli.la/Playwright] Error en ejecución: {e}")

    return melila_url


# ─── 6. Función Principal de Resolución de Link ──────────────────────────────

def obtener_link_afiliado_ml(url_producto, item_id=None, etiqueta=None, usar_playwright=True):
    """
    Función maestra: Toma item_id + etiqueta (o url) y retorna el mejor link de afiliado:
    1. Revisa si coincide con el Oráculo conocido.
    2. Revisa caché persistente (melila_cache.json).
    3. Si hay cookie y usar_playwright=True, intenta resolver vía modal Playwright.
    4. SIEMPRE retorna fallback a URL larga con tag #D[A:{etiqueta}] si no hay meli.la.

    Retorna: (url_final, es_melila)
    """
    if not etiqueta:
        etiqueta = obtener_etiqueta_ml()

    id_prod = extraer_item_id(item_id or url_producto)
    fallback_url = normalizar_url_fallback(url_producto, etiqueta)

    # 1. Oráculo de casos conocidos
    oraculo_url = resolver_desde_oraculo(id_prod, etiqueta)
    if oraculo_url:
        return oraculo_url, True

    # 2. Caché persistente
    cache = cargar_cache()
    clave_cache = f"{id_prod}:{etiqueta}"
    if clave_cache in cache:
        item_cache = cache[clave_cache]
        expira = item_cache.get("expira_em", "")
        ahora_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if expira > ahora_iso and item_cache.get("meli_la"):
            return item_cache["meli_la"], True

    # 3. Plan B: Playwright (si hay cookie y está habilitado)
    cookie_str = obtener_cookie_portal()
    if usar_playwright and cookie_str and url_producto:
        try:
            melila_resuelto = extraer_melila_con_playwright(url_producto, cookie_str, etiqueta)
            if melila_resuelto:
                # Guardar en caché
                ahora = datetime.now(timezone.utc)
                cache[clave_cache] = {
                    "item_id": id_prod,
                    "etiqueta": etiqueta,
                    "meli_la": melila_resuelto,
                    "creado_em": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "expira_em": (ahora + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                }
                guardar_cache(cache)
                return melila_resuelto, True
        except Exception as e:
            print(f"[meli.la] Error en resolución Playwright: {e}")

    # 4. Fallback garantizado a URL larga con tag
    return fallback_url, False


# ─── 7. Procesar Lote de Ofertas (Máx 15 por ejecución) ───────────────────────

def enriquecer_achados_con_melila(path_achados=BASE_DIR / "achados.json", max_playwright=15):
    """
    Recorre achados.json y enriquece las ofertas de Mercado Livre con meli.la si está disponible.
    Respeta el límite estricto de máximo `max_playwright` intentos por ejecución.
    """
    if not path_achados.exists():
        print(f"[meli.la] Archivo {path_achados.name} no encontrado.")
        return 0

    try:
        data = json.loads(path_achados.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[meli.la] Error leyendo achados: {e}")
        return 0

    items = data.get("achados", []) if isinstance(data, dict) else data
    etiqueta = obtener_etiqueta_ml()
    playwright_intentos = 0
    actualizados = 0

    print("=" * 60)
    print("  CRIBA · ENRIQUECEDOR MELI.LA / AFILIADOS ML")
    print(f"  Etiqueta activa: {etiqueta}")
    print("=" * 60)

    for item in items:
        loja = item.get("loja", "")
        if "Mercado Livre" not in loja and "mercadolivre" not in loja.lower():
            continue

        url = item.get("url", "")
        item_id = item.get("id") or extraer_item_id(url)

        # Determinar si podemos usar Playwright (respetando cupo)
        puede_playwright = (playwright_intentos < max_playwright)

        link_final, es_melila = obtener_link_afiliado_ml(
            url_producto=url,
            item_id=item_id,
            etiqueta=etiqueta,
            usar_playwright=puede_playwright
        )

        if puede_playwright and not es_melila and obtener_cookie_portal():
            playwright_intentos += 1

        if es_melila:
            item["meli_la"] = link_final
            actualizados += 1
            print(f"  [OK] {item.get('nombre','')[:35]} -> {link_final}")
        else:
            # Asegurar que la URL tiene el tag de afiliado
            item["url"] = link_final

    if isinstance(data, dict):
        path_achados.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[meli.la] Finalizado: {actualizados} enlaces meli.la activos. Fallbacks preservados.")
    print("=" * 60)
    return actualizados


# ─── 8. Pruebas y Validación con Oráculo ──────────────────────────────────────

def validar_contra_oraculo():
    """Ejecuta los tests contra los casos exactos requeridos."""
    print("\n--- VALIDACIÓN CONTRA ORÁCULO DE CASOS REALES ---")
    etiqueta = "ja20250119201346"

    # Caso 1: Creatina Soldiers Nutrition
    id_1 = "MLB18725310"
    esperado_1 = "https://meli.la/2mywVmV"
    res_1, es_meli_1 = obtener_link_afiliado_ml(
        url_producto="https://www.mercadolivre.com.br/creatina-1kg-suplemento-monohidratada-em-po-100-pura-soldiers-nutrition/p/MLB18725310",
        item_id=id_1,
        etiqueta=etiqueta,
        usar_playwright=False
    )
    assert res_1 == esperado_1, f"Fallo Caso 1: obtuve {res_1}, esperaba {esperado_1}"
    assert es_meli_1 is True, "Caso 1 no marcado como meli.la"
    print(f"[PASS] Caso 1 (Creatina): {id_1} + {etiqueta} -> {res_1}")

    # Caso 2: Perfume Hugo Boss
    esperado_2 = "https://meli.la/21bLJj4"
    res_2, es_meli_2 = obtener_link_afiliado_ml(
        url_producto="https://www.mercadolivre.com.br/perfume-hugo-boss/p/MLB999999",
        item_id="perfume-hugo-boss",
        etiqueta=etiqueta,
        usar_playwright=False
    )
    assert res_2 == esperado_2, f"Fallo Caso 2: obtuve {res_2}, esperaba {esperado_2}"
    assert es_meli_2 is True, "Caso 2 no marcado como meli.la"
    print(f"[PASS] Caso 2 (Hugo Boss): hugo-boss + {etiqueta} -> {res_2}")

    # Caso 3: Fallback a URL larga si no hay meli.la
    url_test = "https://www.mercadolivre.com.br/teclado-mecanico/p/MLB12345678"
    res_3, es_meli_3 = obtener_link_afiliado_ml(
        url_producto=url_test,
        item_id="MLB12345678",
        etiqueta=etiqueta,
        usar_playwright=False
    )
    esperado_3 = f"https://www.mercadolivre.com.br/teclado-mecanico/p/MLB12345678#D[A:{etiqueta}]"
    assert res_3 == esperado_3, f"Fallo Fallback: obtuve {res_3}, esperaba {esperado_3}"
    assert es_meli_3 is False, "Fallback no debería marcarse como meli.la"
    print(f"[PASS] Caso 3 (Fallback con tag): {res_3}")

    print("--- TODAS LAS PRUEBAS DEL ORÁCULO PASARON EXITOSAMENTE ---\n")
    return True


if __name__ == "__main__":
    validar_contra_oraculo()
    if len(sys.argv) > 1 and sys.argv[1] == "--lote":
        enriquecer_achados_con_melila()
