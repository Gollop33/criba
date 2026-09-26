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
    }
    # Descuento Pix: solo si la API lo trae de verdad. NO se inventa.
    for campo in ("discount_pix", "pix_discount", "payment_discount"):
        if d.get(campo):
            datos["pix"] = d[campo]
            break
    return datos


def verificar_post(post):
    """Verifica un post de la fila contra la API real."""
    item_id, tipo = extraer_item_id(post.get("url"))
    if not item_id:
        return {"verificable": False, "motivo": "sin id de ML en la URL"}
    real = consultar(item_id, tipo)
    if not real:
        return {"verificable": False, "motivo": "sin ML_ACCESS_TOKEN"}
    if real.get("error"):
        return {"verificable": False, "motivo": real["error"]}

    salida = {"verificable": True, "id": item_id, "tipo": tipo, "real": real}
    # Comparar con lo que dice el post
    try:
        p_post = float(post.get("precio") or 0)
        p_real = float(real.get("precio") or 0)
        if p_post and p_real:
            dif = abs(p_post - p_real)
            salida["precio_coincide"] = dif <= 1.0
            salida["precio_post"] = p_post
            salida["precio_real"] = p_real
    except (TypeError, ValueError):
        pass
    if real.get("disponible") in (0, None):
        salida["sin_stock"] = True
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
