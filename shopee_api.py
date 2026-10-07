#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Cliente de la API oficial de Afiliados de Shopee Brasil (shopee_api.py)
===============================================================================
Habla con el endpoint GraphQL de afiliados:

    https://open-api.affiliate.shopee.com.br/graphql

Autenticación (la que exige Shopee):
    Authorization: SHA256 Credential=<APP_ID>, Timestamp=<unix>, Signature=<sha256>
    Signature = sha256(APP_ID + Timestamp + payload_json + SECRET_KEY)

De dónde salen las credenciales (NO se inventan nunca):
    https://affiliate.shopee.com.br/open_api   -> botón "Aplicar" -> App ID + Secret
    Si el botón no está naranja, primero hay que pedir la API con el formulario:
    https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091

Se leen de `.env`:
    SHOPEE_APP_ID=<App ID>
    SHOPEE_SECRET_KEY=<Secret>

Uso por línea de comandos:
    python shopee_api.py --estado                 # ¿hay credenciales? (no gasta cuota)
    python shopee_api.py --test                   # 3 ofertas reales (prueba de firma)
    python shopee_api.py --buscar "air fryer"
    python shopee_api.py --buscar "air fryer" --limite 20 --json
    python shopee_api.py --link https://shopee.com.br/product/123/456
    python shopee_api.py --producto https://shopee.com.br/product/123/456

Regla de oro del proyecto: sin credenciales este módulo NO llama a la red,
devuelve vacío y lo dice. Nunca se publica un enlace de Shopee sin verificar.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import io
from pathlib import Path
from urllib.parse import quote, unquote

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config_afiliados.json"

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"
TIMEOUT = 25

# Hosts de enlace corto de afiliado de Shopee. Es el único formato de enlace
# de Shopee que el proyecto acepta publicar (ver validador_oferta.py).
HOSTS_AFILIADO = ("s.shopee.com.br", "shp.ee")

# Campos de productOfferV2. Esta lista es la que usa la documentación de
# afiliados y las librerías públicas que funcionan contra el endpoint.
# Si se pide un campo que la API no conoce, la consulta ENTERA falla.
CAMPOS_OFERTA = """
    productName
    shopName
    shopId
    itemId
    offerLink
    productLink
    price
    commissionRate
    commission
    sales
    imageUrl
    periodStartTime
    periodEndTime
    priceMin
    priceMax
    productCatIds
    ratingStar
    priceDiscountRate
    shopType
    sellerCommissionRate
    shopeeCommissionRate
"""


def _cargar_env():
    """Carga .env en os.environ sin pisar lo que ya venga del entorno."""
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_cargar_env()


class ShopeeAPIError(RuntimeError):
    """Error devuelto por la API de Shopee (firma, permisos, parámetros...)."""


# ── Credenciales ─────────────────────────────────────────────────────────────
def credenciales():
    """
    (app_id, secret). Cadena vacía si no están configuradas.

    Se leen de .env y, como respaldo, de config_afiliados.json -> shopee.
    Ojo: config_afiliados.json va al repositorio, así que el secreto debería
    vivir SIEMPRE en .env / GitHub Secrets, nunca en el JSON.
    """
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_SECRET_KEY", "").strip()
    if not (app_id and secret) and CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("shopee", {}) or {}
            app_id = app_id or str(cfg.get("app_id") or "").strip()
            secret = secret or str(cfg.get("secret_key") or "").strip()
        except Exception:
            pass
    return app_id, secret


def disponible():
    """True solo si hay App ID y Secret. Sin esto no se toca la red."""
    app_id, secret = credenciales()
    return bool(app_id and secret)


def affiliate_id():
    """
    ID numérico de afiliado (ej. 14382300002).

    NO es secreto: viaja dentro de cada enlace que se comparte, así que no pasa
    nada por tenerlo en el repositorio. Es lo único que hace falta para generar
    enlaces de afiliado SIN la API (ver `link_afiliado`).
    """
    v = os.environ.get("SHOPEE_AFFILIATE_ID", "").strip()
    if not v and CONFIG_FILE.exists():
        try:
            v = str((json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("shopee") or {})
                    .get("id") or "").strip()
        except Exception:
            v = ""
    v = re.sub(r"[^0-9]", "", v)           # por si lo pegan como "an_14382300002"
    return v


def estado():
    """Resumen para imprimir en consola. No hace llamadas de red."""
    app_id, secret = credenciales()
    return {
        "app_id": (app_id[:4] + "…" + app_id[-2:]) if len(app_id) > 6 else ("sí" if app_id else ""),
        "secret": "sí" if secret else "",
        "disponible": bool(app_id and secret),
        "endpoint": API_URL,
    }


# ── Firma ────────────────────────────────────────────────────────────────────
def firma(app_id, timestamp, payload, secret):
    """sha256(app_id + timestamp + payload + secret) en hexadecimal."""
    return hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")).hexdigest()


def _cabeceras(app_id, timestamp, payload, secret):
    return {
        "Content-Type": "application/json",
        "Authorization": (
            f"SHA256 Credential={app_id}, Timestamp={timestamp}, "
            f"Signature={firma(app_id, timestamp, payload, secret)}"
        ),
    }


# ── Llamada GraphQL ──────────────────────────────────────────────────────────
def graphql(query, timeout=TIMEOUT):
    """
    Ejecuta una consulta GraphQL contra la API de afiliados.

    Devuelve el JSON completo. Lanza ShopeeAPIError con el motivo exacto
    (credenciales ausentes, firma inválida, HTTP != 200, errores GraphQL).
    """
    app_id, secret = credenciales()
    if not app_id or not secret:
        raise ShopeeAPIError(
            "Faltan credenciales de Shopee (SHOPEE_APP_ID / SHOPEE_SECRET_KEY). "
            "Consíguelas en https://affiliate.shopee.com.br/open_api"
        )

    import requests  # import perezoso: --estado funciona sin la dependencia

    payload = json.dumps({"query": query}, separators=(",", ":"))
    timestamp = int(time.time())
    r = requests.post(API_URL, headers=_cabeceras(app_id, timestamp, payload, secret),
                      data=payload.encode("utf-8"), timeout=timeout)

    if r.status_code != 200:
        raise ShopeeAPIError(f"HTTP {r.status_code} de Shopee: {r.text[:400]}")

    try:
        data = r.json()
    except Exception:
        raise ShopeeAPIError(f"Respuesta no-JSON de Shopee: {r.text[:400]}")

    if data.get("errors"):
        msgs = "; ".join(str(e.get("message", e)) for e in data["errors"])
        raise ShopeeAPIError(f"Shopee devolvió errores: {msgs}")

    return data


# ── Consultas de alto nivel ──────────────────────────────────────────────────
def ofertas(keyword=None, shop_id=None, item_id=None, page=1, limit=50,
            scroll_id=None, sort_type=None, timeout=TIMEOUT):
    """
    productOfferV2 -> lista de ofertas (nodes).

    keyword   : búsqueda libre
    shop_id   : filtrar por tienda (junto con item_id = producto concreto)
    item_id   : producto concreto
    page      : página (se omite si es 1, para no mandar argumentos de más)
    limit     : máximo 50 por página
    scroll_id : paginación por cursor (alternativa a page)
    sort_type : orden de Shopee (déjalo None salvo que sepas el valor)
    """
    if limit > 50:
        limit = 50
    if item_id and not shop_id:
        raise ShopeeAPIError("Para consultar un producto hay que dar shop_id + item_id.")

    args = []
    if keyword:
        args.append('keyword: %s' % json.dumps(keyword, ensure_ascii=False))
    if shop_id:
        args.append(f"shopId: {int(shop_id)}")
    if item_id:
        args.append(f"itemId: {int(item_id)}")
    if scroll_id:
        args.append('scrollId: %s' % json.dumps(scroll_id))
    if sort_type:
        args.append(f"sortType: {int(sort_type)}")
    if page and page > 1:
        args.append(f"page: {int(page)}")
    # limit se aplica a las listas; en consulta de producto concreto Shopee lo ignora
    if not item_id:
        args.append(f"limit: {int(limit)}")

    query = "{ productOfferV2(%s) { nodes { %s } } }" % (", ".join(args), CAMPOS_OFERTA)
    data = graphql(query, timeout=timeout)
    return ((data.get("data") or {}).get("productOfferV2") or {}).get("nodes") or []


def link_corto(url, sub_ids=None, timeout=TIMEOUT):
    """generateShortLink -> enlace de afiliado corto (s.shopee.com.br/...)."""
    if not str(url or "").startswith("http"):
        raise ShopeeAPIError("La URL debe ser completa (http/https).")
    subs = f", subIds: {json.dumps(sub_ids)}" if sub_ids else ""
    query = (
        'mutation { generateShortLink(input: { originUrl: %s%s }) { shortLink } }'
        % (json.dumps(url, ensure_ascii=False), subs)
    )
    data = graphql(query, timeout=timeout)
    try:
        return data["data"]["generateShortLink"]["shortLink"]
    except (KeyError, TypeError):
        raise ShopeeAPIError(f"Shopee no devolvió shortLink: {json.dumps(data)[:400]}")


def producto_por_url(url, timeout=TIMEOUT):
    """
    Dado un enlace de producto (largo o corto), devuelve su oferta.

    Acepta los dos formatos de URL de Shopee:
      https://shopee.com.br/product/<shop_id>/<item_id>
      https://shopee.com.br/<slug>-i.<shop_id>.<item_id>
    """
    shop_id, item_id = parsear_url(url, resolver_corto=True, timeout=timeout)
    if not (shop_id and item_id):
        return None
    nodos = ofertas(shop_id=shop_id, item_id=item_id, timeout=timeout)
    return nodos[0] if nodos else None


# ══════════════════════════════════════════════════════════════════════════════
#  ENLACE DE AFILIADO **SIN API** (solo hace falta el ID de afiliado)
# ══════════════════════════════════════════════════════════════════════════════
# Shopee documenta este formato en su guía oficial (Affiliate Short Link
# Implementation Guide): se pone la URL del producto codificada detrás de
# /an_redir y se añade affiliate_id + sub_id.
#
#   https://s.shopee.com.br/an_redir?origin_link=<url_codificada>
#        &affiliate_id=<ID>&sub_id=<a-b-c-d-e>
#
# Shopee redirige a la página del producto añadiendo:
#   utm_medium=affiliates & utm_source=an_<ID> & mmp_pid=an_<ID>
#
# Verificado el 2026-10-01 contra el dominio de Brasil: la redirección llega al
# producto y la atribución aparece en la URL final.
URL_AN_REDIR = "https://s.shopee.com.br/an_redir"


def link_afiliado(url, aid=None, sub_id="criba", timeout=TIMEOUT):
    """
    Enlace de afiliado de Shopee SIN la API: solo necesita tu ID de afiliado.

    `url` es la URL del producto (o cualquier landing de Shopee). Se limpian los
    parámetros viejos para no arrastrar el tracking de otro afiliado.
    """
    aid = str(aid or affiliate_id() or "").strip()
    if not aid:
        raise ShopeeAPIError(
            "Falta SHOPEE_AFFILIATE_ID: sin el ID numérico no se puede construir "
            "el enlace de afiliado. Está en el portal (affiliate.shopee.com.br)."
        )
    destino = str(url or "").strip().split("?")[0].split("#")[0]
    if not destino.startswith("http"):
        raise ShopeeAPIError(f"URL de producto inválida: {url!r}")
    sub = re.sub(r"[^A-Za-z0-9._-]", "-", str(sub_id or "criba"))[:50] or "criba"
    return (f"{URL_AN_REDIR}?origin_link={quote(destino, safe='')}"
            f"&affiliate_id={aid}&sub_id={sub}")


def origin_link(url):
    """URL de producto que va dentro de un enlace /an_redir ('' si no lo es)."""
    u = str(url or "")
    m = re.search(r"[?&]origin_link=([^&]+)", u)
    if not m:
        return ""
    try:
        return unquote(m.group(1))
    except Exception:
        return ""


def verificar_afiliacion(enlace, aid=None, timeout=25):
    """
    Abre el enlace y comprueba que Shopee atribuye el clic a NUESTRO ID.

    Devuelve (ok, url_final). ok=True solo si la URL final trae
    `utm_source=an_<ID>` o `mmp_pid=an_<ID>`.

    Es la verificación de la Regla de Oro para Shopee: no se publica un enlace
    de Shopee que no se pueda atribuir a la cuenta del afiliado.
    """
    aid = str(aid or affiliate_id() or "").strip()
    if not aid:
        # El propio enlace /an_redir lleva el ID: sirve para verificar aunque no
        # haya credenciales configuradas.
        m = re.search(r"[?&]affiliate_id=(\d+)", str(enlace or ""))
        aid = m.group(1) if m else ""
    if not aid:
        return False, "sin SHOPEE_AFFILIATE_ID"
    import requests
    try:
        r = requests.get(enlace, allow_redirects=True, timeout=timeout,
                         headers={"User-Agent": _UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    except Exception as e:
        return False, f"no verificable: {type(e).__name__}"
    final = r.url or ""
    ok = (f"utm_source=an_{aid}" in final) or (f"mmp_pid=an_{aid}" in final)
    return ok, final


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# UA de crawler: Shopee solo entrega los metadatos og: (título e imagen) a los
# rastreadores de previews de enlaces. Comprobado el 2026-10-02:
#   · Facebook/WhatsApp -> og:title + og:image (25 KB, sin precio)
#   · UA de Android     -> lo mismo (580 KB)
#   · navegador normal  -> shell JavaScript de 156 KB SIN datos
#   · Googlebot/Twitter -> 403
# Es lo que permite tener foto y nombre reales de un producto con solo su enlace.
UA_CRAWLER = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"


def _meta(html, propiedad):
    """Contenido de <meta property/name="..."> en cualquiera de los dos órdenes."""
    for patron in (
        r'<meta[^>]+(?:property|name)="' + re.escape(propiedad) + r'"[^>]+content="([^"]*)"',
        r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="' + re.escape(propiedad) + r'"',
    ):
        m = re.search(patron, html or "", re.I)
        if m:
            return m.group(1).strip()
    return ""


def datos_producto(url, timeout=25, quitar_sufijo=True):
    """
    Título e imagen REALES de un producto de Shopee a partir de su enlace.

    Devuelve {"titulo", "imagen", "url_final", "existe"}. `existe` es False si
    Shopee no devolvió metadatos: así se descartan enlaces muertos antes de
    publicarlos (Regla de Oro) y se obtiene la foto que exige el validador.
    """
    import requests
    try:
        r = requests.get(url, allow_redirects=True, timeout=timeout,
                         headers={"User-Agent": UA_CRAWLER, "Accept-Language": "pt-BR,pt;q=0.9"})
        html = r.text
    except Exception as e:
        return {"titulo": "", "imagen": "", "url_final": str(url), "existe": False,
                "error": f"{type(e).__name__}: {e}"}

    titulo = _meta(html, "og:title") or _meta(html, "twitter:title")
    imagen = _meta(html, "og:image") or _meta(html, "twitter:image")
    if quitar_sufijo and titulo:
        titulo = re.sub(r"\s*\|\s*Shopee(\s+Brasil)?\s*$", "", titulo, flags=re.I).strip()

    # Un producto que no existe NO da error: Shopee manda a su portada (título
    # genérico) o a una ruta de "no encontrado". Hay que detectarlo o se
    # publicarían enlaces muertos.
    final = r.url or ""
    generico = bool(re.match(r"^Shopee Brasil\s*\|\s*Ofertas", titulo or "", re.I))
    existe = bool((titulo or imagen) and not generico and "/opaanlp/" not in final)

    return {"titulo": titulo if existe else "", "imagen": imagen if existe else "",
            "url_final": final, "existe": existe}



# ── Utilidades ───────────────────────────────────────────────────────────────
def parsear_url(url, resolver_corto=False, timeout=10):
    """
    (shop_id, item_id) a partir de una URL de Shopee. ('', '') si no se puede.

    resolver_corto=True sigue la redirección de los enlaces s.shopee.com.br /
    shp.ee (necesario para saber qué producto hay detrás).
    """
    u = str(url or "")
    if resolver_corto and any(h in u for h in HOSTS_AFILIADO):
        try:
            import requests
            u = requests.get(url, allow_redirects=True, timeout=timeout).url
        except Exception:
            return "", ""
    m = re.search(r"/product/(\d+)/(\d+)", u) or re.search(r"-i\.(\d+)\.(\d+)", u)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def es_link_afiliado(url):
    """True si la URL es un enlace corto de afiliado de Shopee."""
    u = str(url or "").lower()
    return any(h in u for h in HOSTS_AFILIADO)


def num(valor, por_defecto=0.0):
    """Convierte a float lo que Shopee devuelve como texto ('61.32', 'R$ 61,32')."""
    if valor is None or valor == "":
        return por_defecto
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).replace("R$", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else por_defecto


def normalizar_oferta(nodo, categorias=None):
    """
    Traduce un nodo de productOfferV2 al formato de `achados.json`.

    NO inventa nada: si un campo no viene, se deja vacío o en 0.
    El enlace que se usa es `offerLink` (el que genera Shopee con la cuenta
    del afiliado que llamó). Si no viniera, se deja sin enlace para que el
    cosechador llame a generateShortLink.
    """
    nombre = (nodo.get("productName") or "").strip()
    precio = num(nodo.get("price"))
    desc = num(nodo.get("priceDiscountRate"))
    anterior = num(nodo.get("priceMin"))
    if desc > 0 and precio > 0:
        anterior = round(precio / (1 - desc / 100.0), 2)
    elif anterior <= precio:
        anterior = 0.0

    oferta = {
        "id": f"shp-{nodo.get('itemId')}",
        "nombre": nombre,
        "precio": precio,
        "precio_anterior": anterior or None,
        "desc_pct": desc,
        "imagen": nodo.get("imageUrl") or "",
        "url": (nodo.get("offerLink") or "").strip(),
        "url_producto": (nodo.get("productLink") or "").strip(),
        "loja": "Shopee",
        "categoria": (categorias or {}).get("categoria", "Shopee Ofertas"),
        "fuente": "Shopee Open API (productOfferV2)",
        "tienda_id": str(nodo.get("shopId") or ""),
        "item_id": str(nodo.get("itemId") or ""),
        "tienda_nombre": (nodo.get("shopName") or "").strip(),
        "vendidos": int(num(nodo.get("sales"))),
        "rating": num(nodo.get("ratingStar")),
        "comision_pct": num(nodo.get("commissionRate")),
        "comision_rs": num(nodo.get("commission")),
        "afiliado_verificado": bool(nodo.get("offerLink")),
        "afiliado_fuente": "offerLink" if nodo.get("offerLink") else "",
    }
    return oferta


# ── CLI ──────────────────────────────────────────────────────────────────────
def _imprimir_oferta(o, i):
    print(f"  [{i}] {o['nombre'][:78]}")
    print(f"      R$ {o['precio']:.2f}"
          + (f"  (antes R$ {o['precio_anterior']:.2f}, -{o['desc_pct']:.1f}%)"
             if o.get("precio_anterior") else "")
          + f"  | comisión {o.get('comision_pct', 0):.1f}% (R$ {o.get('comision_rs', 0):.2f})"
          + f"  | vendidos {o.get('vendidos', 0)}")
    print(f"      {o['tienda_nombre']}  ->  {o['url'] or '(sin offerLink)'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cliente API de afiliados Shopee Brasil")
    ap.add_argument("--estado", action="store_true", help="¿hay credenciales? (no gasta cuota)")
    ap.add_argument("--test", action="store_true", help="trae 3 ofertas para probar la firma")
    ap.add_argument("--buscar", metavar="TEXTO", help="busca ofertas por palabra clave")
    ap.add_argument("--producto", metavar="URL", help="oferta de un producto concreto (URL Shopee)")
    ap.add_argument("--link", metavar="URL", help="genera el enlace corto de afiliado")
    ap.add_argument("--limite", type=int, default=10, help="máximo de ofertas (tope 50)")
    ap.add_argument("--json", action="store_true", help="salida JSON cruda")
    args = ap.parse_args(argv)

    est = estado()
    print("=" * 68)
    print("  CRIBA · SHOPEE AFILIADOS (API oficial)")
    print("=" * 68)
    if not args.json:
        print(f"  App ID   : {est['app_id'] or '(vacío)'}")
        print(f"  Secret   : {est['secret'] or '(vacío)'}")
        print(f"  Endpoint : {est['endpoint']}")

    if args.estado or not any([args.test, args.buscar, args.producto, args.link]):
        if est["disponible"]:
            print("\n  [OK] Credenciales presentes. Prueba con --test para validar la firma.")
            return 0
        print("\n  [PENDIENTE] Sin credenciales. Para conseguirlas:")
        print("    1) https://affiliate.shopee.com.br/open_api  (solo en ordenador)")
        print("       -> si el botón 'Aplicar' NO está naranja, pide la API aquí:")
        print("       https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091")
        print("    2) Copia App ID y Secret en .env:")
        print("       SHOPEE_APP_ID=...")
        print("       SHOPEE_SECRET_KEY=...")
        return 0 if args.estado else 1

    if not est["disponible"]:
        print("\n  [ABORTADO] No hay credenciales: no se llama a la red.")
        return 1

    try:
        if args.link:
            corto = link_corto(args.link)
            print(f"\n  Enlace de afiliado: {corto}")
            return 0

        if args.producto:
            nodo = producto_por_url(args.producto)
            if not nodo:
                print("\n  [X] Shopee no devolvió ese producto (¿existe? ¿es de tu región?).")
                return 1
            of = normalizar_oferta(nodo)
            if args.json:
                print(json.dumps(of, ensure_ascii=False, indent=2))
            else:
                print()
                _imprimir_oferta(of, 1)
            return 0

        texto = args.buscar or "achadinhos"
        nodos = ofertas(keyword=texto, limit=args.limite)
        if args.json:
            print(json.dumps([normalizar_oferta(n) for n in nodos], ensure_ascii=False, indent=2))
            return 0
        print(f"\n  {len(nodos)} oferta(s) para '{texto}':\n")
        for i, n in enumerate(nodos, 1):
            _imprimir_oferta(normalizar_oferta(n), i)
        return 0

    except ShopeeAPIError as e:
        print(f"\n  [X] {e}")
        return 2
    except Exception as e:
        print(f"\n  [X] Error inesperado: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
