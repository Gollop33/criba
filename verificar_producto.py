#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Verificador real de producto (verificar_producto.py)
============================================================
Comprueba los datos REALES de un producto de Mercado Livre antes de publicarlo:
precio, precio de lista, stock y —si la API lo da— el descuento Pix.

── POR QUÉ HACE FALTA UN TOKEN ──────────────────────────────────────────────
Se intentaron las tres vías sin token y TODAS están cerradas (medido):
  1. La ficha del producto: ML la renderiza con JavaScript. El HTML que
     devuelve son ~41 KB SIN datos: "pix" aparece 0 veces y "price" 0 veces.
  2. API pública de items (api.mercadolibre.com/items/MLB...): 403
     PA_UNAUTHORIZED_RESULT_FROM_POLICIES.
  3. API de afiliados con la cookie del portal: /user/tags funciona, pero
     /user/coupons, /coupons y /user/links devuelven 404.
Así que verificar el Pix y el cupón de verdad NO es posible de forma anónima.

Con un token de la API oficial sí:
  1. Entra en https://developers.mercadolibre.com/devcenter/
  2. Crea una aplicación (es gratis, no pide tarjeta).
  3. Saca el access_token (se renueva cada 6 h, pero con el refresh_token se
     automatiza).
  4. Ponlo en GitHub Secrets como  ML_ACCESS_TOKEN
     (y opcionalmente ML_REFRESH_TOKEN + ML_APP_ID + ML_CLIENT_SECRET para
      renovarlo solo).

Límite con token: 6.000 peticiones al día. Para ~150 posts al día sobra.

── Uso ──────────────────────────────────────────────────────────────────────
    python verificar_producto.py --estado                 # hay token?
    python verificar_producto.py MLB34928101              # verifica un item
    python verificar_producto.py --fila                   # verifica la fila
"""

import io
import json
import os
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent

_env = BASE / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

TOKEN = os.environ.get("ML_ACCESS_TOKEN", "").strip()
API = "https://api.mercadolibre.com"


def token_disponible():
    return bool(TOKEN)


# ── AUTO-RENOVACIÓN DEL TOKEN ────────────────────────────────────────────────
# El access_token de Mercado Livre dura 6 HORAS. Sin esto, cualquier uso después
# de ese plazo devuelve 401 "invalid access token" y la verificación se cae en
# silencio (pasó de verdad: el token llevaba 230 min caducado y todo daba 401).
# Se renueva solo con el refresh_token, sin navegador ni intervención humana.
_renovado = False


def _renovar_si_hace_falta(forzar=False):
    """Renueva el token si está caducado, o si la API respondió 401."""
    global TOKEN, _renovado
    if _renovado and not forzar:
        return False
    _renovado = True
    try:
        import importlib
        import time
        import obtener_token_ml as otm
        importlib.reload(otm)
        env = otm.leer_env()
        exp = None
        cache = BASE / ".ml_token.json"
        if cache.exists():
            try:
                exp = json.loads(cache.read_text(encoding="utf-8")).get("expira_en")
            except Exception:
                pass
        necesita = forzar or (exp is not None and float(exp) - time.time() < 600)
        if not necesita:
            return False
        refresh = env.get("ML_REFRESH_TOKEN", "").strip()
        if not (env.get("ML_APP_ID") and env.get("ML_CLIENT_SECRET") and refresh):
            return False
        import requests as _rq
        r = _rq.post("https://api.mercadolibre.com/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": env["ML_APP_ID"],
            "client_secret": env["ML_CLIENT_SECRET"],
            "refresh_token": refresh,
        }, headers={"Accept": "application/json"}, timeout=30)
        if r.status_code == 200:
            t = r.json()
            otm.guardar_env("ML_ACCESS_TOKEN", t.get("access_token", ""))
            if t.get("refresh_token"):
                otm.guardar_env("ML_REFRESH_TOKEN", t["refresh_token"])
            otm.guardar_cache(t)
            TOKEN = t.get("access_token", "")
            print("  [ML] token renovado automaticamente")
            return True
        print(f"  [ML] no se pudo renovar: HTTP {r.status_code}")
    except Exception as e:
        print(f"  [ML] no se pudo renovar: {type(e).__name__}")
    return False


def extraer_item_id(url_o_id):
    """
    Saca el ID de item (MLB...) de una URL de Mercado Livre.
    OJO: las URLs /p/MLBxxxxx son de CATÁLOGO, no de item. El endpoint /items/
    necesita el id de publicación (MLB-1234567890). Si solo hay catálogo, se
    puede intentar /products/{catalog_id} para datos del catálogo.
    """
    if not url_o_id:
        return None, None
    txt = str(url_o_id).strip()
    if re.fullmatch(r"MLB\d{6,}", txt):
        return txt, "item"
    m = re.search(r"/p/(MLB\d+)", txt)
    if m:
        return m.group(1), "catalogo"
    m = re.search(r"(MLB-?\d{6,})", txt)
    if m:
        return m.group(1).replace("-", ""), "item"
    return None, None


def consultar(item_id, tipo="item", timeout=20):
    """
    Consulta la API oficial. Devuelve dict con los datos reales del producto,
    o None si no hay token o el producto no está disponible.
    """
    if not token_disponible():
        return None
    try:
        import requests
    except ImportError:
        return None

    # El token dura 6 h: se renueva solo antes de usarlo si está por caducar.
    _renovar_si_hace_falta()
    H = {"Authorization": f"Bearer {TOKEN}"}

    # ── LA VÍA BUENA PARA UN PRODUCTO DE CATÁLOGO ───────────────────────────
    # `/items/{id}` da 403 con esta app (medido: "Access to the requested
    # resource is forbidden"), así que el precio NO se puede sacar de ahí.
    #
    # Pero hay otra vía que SÍ funciona y da TODO lo que hace falta:
    #     GET /products/{catalogo_id}         -> nombre, estado, marca
    #     GET /products/{catalogo_id}/items   -> PRECIO, precio original,
    #                                            envío gratis, condición
    # Verificado en vivo:
    #     /products/MLB76109690/items -> 200 con
    #        {"item_id":"MLB5141219581","price":235.08,
    #         "original_price":419.8,"shipping":{"free_shipping":true},...}
    # Y el precio coincide exacto con el del post (235.08), así que sirve para
    # verificar y para CORREGIR precios equivocados.
    if tipo == "catalogo":
        try:
            r = requests.get(f"{API}/products/{item_id}", headers=H, timeout=timeout)
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}", "raw": r.text[:140]}
            d = r.json()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {str(e)[:100]}"}

        bbw = d.get("buy_box_winner") or {}
        datos = {
            "id": d.get("id"),
            "titulo": d.get("name"),
            "precio": bbw.get("price"),
            "precio_lista": bbw.get("original_price"),
            "disponible": None,
            "estado": d.get("status"),
            "envio_gratis": None,
            "permalink": d.get("permalink") or "",
            "categoria_id": d.get("domain_id"),
            "tipo": "catalogo",
            "marca": next((a.get("value_name") for a in (d.get("attributes") or [])
                           if a.get("id") == "BRAND"), None),
            "con_precio": bbw.get("price") is not None,
        }

        # Segundo paso: los items del producto, que es donde está el precio.
        if not datos["con_precio"]:
            try:
                r2 = requests.get(f"{API}/products/{item_id}/items",
                                  headers=H, timeout=timeout)
                if r2.status_code == 200:
                    items = (r2.json() or {}).get("results") or []
                    # Preferir el más barato disponible y nuevo
                    validos = [x for x in items
                               if x.get("price") and str(x.get("condition")) == "new"]
                    elegido = min(validos or items,
                                  key=lambda x: float(x.get("price") or 1e12),
                                  default=None)
                    if elegido:
                        datos["precio"] = elegido.get("price")
                        datos["precio_lista"] = elegido.get("original_price")
                        datos["envio_gratis"] = bool(
                            (elegido.get("shipping") or {}).get("free_shipping"))
                        datos["condicion"] = elegido.get("condition")
                        datos["item_id"] = elegido.get("item_id")
                        datos["vendedor_oficial"] = elegido.get("official_store_id")
                        datos["con_precio"] = True
                        datos["n_items"] = len(items)
                else:
                    datos["aviso_items"] = f"HTTP {r2.status_code}"
            except Exception as e:
                datos["aviso_items"] = f"{type(e).__name__}: {str(e)[:80]}"

        if not datos["con_precio"]:
            datos["aviso"] = "la API no da precio para este producto"
        return datos

    # ── PUBLICACIÓN DIRECTA (/items/{id}) ───────────────────────────────────
    try:
        r = requests.get(f"{API}/items/{item_id}", headers=H, timeout=timeout)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "raw": r.text[:140]}
        d = r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}

    return {
        "id": d.get("id"),
        "titulo": d.get("title") or d.get("name"),
        "precio": d.get("price"),
        "precio_lista": d.get("original_price") or d.get("base_price"),
        "disponible": d.get("available_quantity"),
        "estado": d.get("status") or d.get("condition"),
        "envio_gratis": bool((d.get("shipping") or {}).get("free_shipping")),
        "permalink": d.get("permalink"),
        "categoria_id": d.get("category_id"),
        "tipo": "item",
        "con_precio": d.get("price") is not None,
        "pix": next((d[c] for c in ("discount_pix", "pix_discount",
                                    "payment_discount") if d.get(c)), None),
    }


def _consultar_viejo(item_id, tipo="item", timeout=20):
    """(sin uso) primera versión: no usaba /products/{id}/items y se quedaba
    sin precio porque buy_box_winner viene null."""
    if not token_disponible():
        return None
    try:
        import requests
    except ImportError:
        return None

    H = {"Authorization": f"Bearer {TOKEN}"}
    if tipo == "catalogo":
        url = f"{API}/products/{item_id}"
    else:
        url = f"{API}/items/{item_id}"

    try:
        r = requests.get(url, headers=H, timeout=timeout)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "raw": r.text[:140]}
        d = r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}

    # ── RESPUESTA DE CATÁLOGO (/products/{id}) ──────────────────────────────
    # Devuelve los METADATOS del producto (nombre, marca, atributos, estado)
    # pero el precio NO está aquí: vive en `buy_box_winner`, y ese campo viene
    # null salvo que la app tenga también el permiso de `items`.
    #
    # Medido con el token actual del proyecto:
    #     GET /products/MLB76109690 -> 200, name y status="active", buy_box_winner=null
    #     GET /items/... -> 403 (falta permiso)
    #
    # Aunque no haya precio, esto SÍ sirve para dos comprobaciones reales:
    #   1. Que el producto EXISTE y está activo (no retirado).
    #   2. Que el NOMBRE coincide con el del post -> pilla enlaces cruzados.
    if d.get("type") == "catalog_product" or "buy_box_winner" in d or "family_name" in d:
        bbw = d.get("buy_box_winner") or {}
        datos = {
            "id": d.get("id"),
            "titulo": d.get("name"),
            "precio": bbw.get("price"),
            "precio_lista": bbw.get("original_price"),
            "disponible": None,
            "estado": d.get("status"),
            "envio_gratis": None,
            "permalink": d.get("permalink") or "",
            "categoria_id": d.get("domain_id"),
            "tipo": "catalogo",
            "marca": next((a.get("value_name") for a in (d.get("attributes") or [])
                           if a.get("id") == "BRAND"), None),
            "con_precio": bbw.get("price") is not None,
        }
        if not datos["con_precio"]:
            datos["aviso"] = ("el catálogo no da precio sin el permiso de items "
                              "(buy_box_winner vacío)")
        return datos

    # ── RESPUESTA DE PUBLICACIÓN (/items/{id}) ──────────────────────────────
    datos = {
        "id": d.get("id"),
        "titulo": d.get("title") or d.get("name"),
        "precio": d.get("price"),
        "precio_lista": d.get("original_price") or d.get("base_price"),
        "disponible": d.get("available_quantity"),
        "estado": d.get("status") or d.get("condition"),
        "envio_gratis": bool((d.get("shipping") or {}).get("free_shipping")),
        "permalink": d.get("permalink"),
        "categoria_id": d.get("category_id"),
        "tipo": "item",
        "con_precio": d.get("price") is not None,
    }
    # Descuento Pix: solo si la API lo trae de verdad. NO se inventa.
    for campo in ("discount_pix", "pix_discount", "payment_discount"):
        if d.get(campo):
            datos["pix"] = d[campo]
            break
    return datos


def verificar_post(post):
    """
    Verifica un post de la fila contra la API real.

    IMPORTANTE: hay que RESOLVER el enlace corto ANTES de buscar el id.
    Medido sobre la fila real: 186 de 191 URLs de Mercado Livre son enlaces
    `meli.la/XXXX`, así que sin resolverlos solo se podían verificar 5 de 191
    (2,6%). Con la resolución por cache_melila se recuperan casi todos.
    """
    url_original = post.get("url")
    url = url_original
    try:
        from validador_oferta import resolver_enlace
        url = resolver_enlace(url_original)
    except Exception:
        pass

    item_id, tipo = extraer_item_id(url)
    if not item_id:
        return {"verificable": False,
                "motivo": f"sin id de ML en la URL ({str(url)[:60]})"}
    real = consultar(item_id, tipo)
    if not real:
        return {"verificable": False, "motivo": "sin ML_ACCESS_TOKEN"}
    if real.get("error"):
        return {"verificable": False, "motivo": real["error"], "id": item_id,
                "url_resuelta": url}

    salida = {"verificable": True, "id": item_id, "tipo": tipo, "real": real,
              "url_resuelta": url}

    # ── COMPROBACIÓN 1: el nombre real coincide con el del post ─────────────
    # Esto pilla los ENLACES CRUZADOS (producto A con enlace del producto B),
    # que es uno de los errores que reportó el usuario. Funciona incluso sin el
    # permiso de items, porque /products/ sí devuelve el nombre.
    try:
        import unicodedata

        def _norm(s):
            s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
            s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
            return {w for w in re.sub(r"\s+", " ", s).split() if len(w) >= 4}

        w_post = _norm(post.get("titulo"))
        w_real = _norm(real.get("titulo"))
        if w_post and w_real:
            ratio = len(w_post & w_real) / max(1, len(w_post))
            salida["nombre_coincide"] = ratio >= 0.5
            salida["coincidencia_nombre"] = round(ratio, 2)
            if ratio < 0.5:
                salida["alerta"] = (f"el nombre del enlace NO coincide con el post "
                                    f"({ratio:.0%}): {str(real.get('titulo'))[:60]!r}")
    except Exception:
        pass

    # ── COMPROBACIÓN 2: el producto sigue activo ────────────────────────────
    if real.get("estado") and str(real["estado"]).lower() not in ("active", "new"):
        salida["inactivo"] = True
        salida["alerta_estado"] = f"producto en estado {real['estado']!r}"

    # ── COMPROBACIÓN 3: precio (solo si la API lo da) ───────────────────────
    try:
        p_post = float(post.get("precio") or 0)
        p_real = float(real.get("precio") or 0)
        if p_post and p_real:
            dif = abs(p_post - p_real)
            salida["precio_coincide"] = dif <= 1.0
            salida["precio_post"] = p_post
            salida["precio_real"] = p_real
            if dif > 1.0:
                salida["alerta_precio"] = (f"precio del post R$ {p_post:.2f} "
                                           f"vs real R$ {p_real:.2f}")
    except (TypeError, ValueError):
        pass
    if real.get("disponible") == 0:
        salida["sin_stock"] = True
    if real.get("con_precio") is False:
        salida["sin_precio_api"] = True
    return salida


def main():
    if "--estado" in sys.argv:
        print("=" * 70)
        print("  VERIFICADOR DE PRODUCTO")
        print("=" * 70)
        print(f"  ML_ACCESS_TOKEN: {'configurado' if TOKEN else 'FALTA'}")
        if not TOKEN:
            print()
            print("  Sin token la verificación NO es posible: Mercado Livre")
            print("  bloquea el acceso anónimo (403) y las fichas se renderizan")
            print("  con JavaScript. Ver la cabecera de este archivo para sacar")
            print("  un token gratis en developers.mercadolibre.com")
        return 0

    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        item_id, tipo = extraer_item_id(sys.argv[1])
        print(f"  id: {item_id} ({tipo})")
        print(json.dumps(consultar(item_id, tipo), ensure_ascii=False, indent=2))
        return 0

    if "--fila" in sys.argv:
        fila = json.loads((BASE / "fila_posts.json").read_text(encoding="utf-8-sig"))
        posts = [p for p in fila.get("fila", []) if "Mercado" in str(p.get("loja"))][:10]
        for p in posts:
            r = verificar_post(p)
            print(f"  {str(p.get('titulo'))[:44]:46s} {json.dumps(r, ensure_ascii=False)[:150]}")
        return 0

    print("  Uso: --estado | --fila | <MLB o url>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
