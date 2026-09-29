#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Validador de oferta (validador_oferta.py)
==================================================
LA PUERTA FINAL. Nada se publica sin pasar por aquí.

Responde a una sola pregunta, para cada elemento de la oferta:

    PRODUCTO → ENLACE → CUPÓN → PIX
    ¿todos pertenecen a LA MISMA oferta?

── POR QUÉ EXISTE ESTE ARCHIVO ──────────────────────────────────────────────
Errores reales reportados por el usuario, todos ciertos:
  1. Producto de Amazon con cupón de Mercado Livre.
  2. Cupón de una categoría (Tecnología) en un producto de otra (Casa & Móveis).
  3. Cupón de 30% que en la compra real no aplicaba.
  4. Descuento Pix INVENTADO en el 100% de los posts.
  5. Cupones VENCIDOS publicados (la fila se validó al generarse, pero el bucle
     siguió publicando 5,5 h después, cuando el cupón ya había caducado).
  6. Datos atrasados: precios y cupones de días anteriores reutilizados.

La raíz común: la validación se hacía UNA VEZ al generar la fila, y la
publicación ocurría HORAS después. El precio cambiaba, el cupón vencía y el
enlace se quedaba viejo, pero el post ya estaba escrito y salía igual.

Este validador se ejecuta JUSTO ANTES DE ENVIAR, así que valida el estado real
del momento, no el de hace 5 horas.

── PRINCIPIO RECTOR ─────────────────────────────────────────────────────────
Ante la duda, NO publicar el dato problemático:
    cupón dudoso  -> se publica la oferta SIN cupón
    enlace roto   -> se DESCARTA la oferta entera
    PIX sin dato  -> no se menciona el PIX
Es preferible una oferta más pobre que una oferta que engaña.
"""

import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_VALIDACION = LOG_DIR / "validacion.jsonl"
CACHE_MELILA = BASE / "cache_melila.json"

# ── Ajustes ──────────────────────────────────────────────────────────────────
MIN_PALABRAS_ENLACE = 0.40   # % de palabras del título que deben salir en la URL
CUPON_VALIDEZ_DIAS = 0       # días de margen antes de considerar un cupón vencido
HORAS_MAX_DATOS = 30         # antigüedad máxima tolerada de los datos de origen

# ── Tiendas ──────────────────────────────────────────────────────────────────
DOMINIOS = {
    "mercadolivre": ("mercadolivre.com.br", "meli.la", "produto.mercadolivre"),
    "amazon": ("amazon.com.br", "amzn.to", "amazon."),
    "shopee": ("shopee.com.br", "shp.ee"),
    "kabum": ("kabum.com.br",),
    "magalu": ("magazineluiza", "magalu"),
    "aliexpress": ("aliexpress",),
}


def tienda_de(texto):
    """Tienda normalizada a partir de un texto libre."""
    t = _sin_acentos(str(texto or "")).lower()
    if "mercado" in t or "melivre" in t or "meli.la" in t:
        return "mercadolivre"
    if "amazon" in t:
        return "amazon"
    if "shopee" in t:
        return "shopee"
    if "kabum" in t:
        return "kabum"
    if "magalu" in t or "magazine" in t:
        return "magalu"
    if "aliexpress" in t or "ali express" in t:
        return "aliexpress"
    return ""


def tienda_de_url(url):
    u = str(url or "").lower()
    for tienda, dominios in DOMINIOS.items():
        for d in dominios:
            if d in u:
                return tienda
    return ""


def _sin_acentos(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def _norm(s):
    s = _sin_acentos(str(s or "")).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _palabras(txt, minimo=4):
    """Palabras significativas (>= 4 letras), sin ruido de marketing."""
    RUIDO = {"para", "com", "sem", "mais", "original", "novo", "nova", "kit",
             "unidade", "unidades", "cor", "preto", "branco", "colorido"}
    return {w for w in _norm(txt).split() if len(w) >= minimo and w not in RUIDO}


# ══════════════════════════════════════════════════════════════════════════════
#  RESOLUCIÓN DE ENLACES
# ══════════════════════════════════════════════════════════════════════════════
_CACHE_INVERSO = None


def cache_inverso():
    """
    {enlace_corto: url_original} a partir de cache_melila.json (938 entradas).
    Es lo que permite comprobar que un meli.la apunta al producto anunciado.
    """
    global _CACHE_INVERSO
    if _CACHE_INVERSO is not None:
        return _CACHE_INVERSO
    _CACHE_INVERSO = {}
    if CACHE_MELILA.exists():
        try:
            d = json.loads(CACHE_MELILA.read_text(encoding="utf-8-sig"))
            for original, info in d.items():
                corto = (info or {}).get("short_url") if isinstance(info, dict) else None
                if corto:
                    _CACHE_INVERSO[corto.rstrip("/").lower()] = original
        except Exception as e:
            print(f"  [validador] cache_melila ilegible: {e}")
    return _CACHE_INVERSO


def resolver_enlace(url):
    """
    Devuelve la URL "real" de un enlace, para poder compararla con el producto.
    Primero el caché (0 peticiones). Si no está, se devuelve la propia URL.
    """
    u = str(url or "").strip()
    if not u:
        return ""
    if "meli.la/" in u.lower():
        return cache_inverso().get(u.rstrip("/").lower(), u)
    return u


# ══════════════════════════════════════════════════════════════════════════════
#  VALIDACIONES INDIVIDUALES
# ══════════════════════════════════════════════════════════════════════════════
def _validar_producto(post):
    """El producto tiene que existir y tener datos utilizables."""
    titulo = str(post.get("titulo") or post.get("nombre") or "").strip()
    if len(titulo) < 10:
        return False, "producto sin título utilizable"
    try:
        precio = float(post.get("precio") or 0)
    except (TypeError, ValueError):
        precio = 0
    if precio <= 0:
        return False, "producto sin precio válido"
    if not post.get("imagen"):
        return False, "producto sin imagen"
    if not tienda_de(post.get("loja")):
        return False, f"tienda no reconocida: {post.get('loja')!r}"
    return True, ""


def _validar_enlace(post):
    """
    El enlace tiene que:
      1. Existir.
      2. Ser de la MISMA tienda que el producto.
      3. Corresponder AL MISMO producto (slug de la URL vs título).
      4. No ser un /go/ (no monetiza: Regla de Oro del proyecto).
    """
    url = str(post.get("url") or "").strip()
    if not url.startswith("http"):
        return False, "enlace ausente o inválido"

    if "/go/" in url:
        return False, "enlace /go/ no monetiza (Regla de Oro)"

    t_producto = tienda_de(post.get("loja"))
    t_enlace = tienda_de_url(url)
    if not t_enlace:
        return False, f"no se reconoce la tienda del enlace: {url[:60]}"
    if t_enlace != t_producto:
        return False, (f"enlace de {t_enlace} pero el producto es de {t_producto}: "
                       f"{url[:70]}")

    # Correspondencia producto <-> enlace por slug
    real = resolver_enlace(url)
    if real == url and "meli.la/" in url.lower():
        # Enlace corto sin caché: no se puede comprobar -> se avisa pero no se
        # descarta (descartar todo lo no cacheado dejaría el canal sin posts).
        return True, "enlace corto sin cache: correspondencia no verificable"

    # Extraer el slug del producto de la URL.
    # OJO (bug corregido): antes se borraba cualquier segmento que contuviera
    # "mercadolivre" o "amazon" para quitar el dominio a mano, y eso borraba
    # también slugs LEGÍTIMOS de productos con "amazon" en el nombre (un Fire
    # Stick de Amazon vendido en ML: /fire-stick-tv-lite-amazon-wifi-...). El
    # validador rechazaba ofertas correctas. Ahora se parsea la URL de verdad y
    # solo se quitan el host, los identificadores y las palabras de ruta.
    from urllib.parse import urlparse
    partes_url = urlparse(real)
    partes = [s for s in partes_url.path.split("/") if s]
    partes = [s for s in partes
              if not re.fullmatch(r"MLB[U]?\d+", s, re.I)
              and s.lower() not in ("dp", "p", "up", "produto", "lista", "www")]
    slug_txt = " ".join(partes)
    if not slug_txt:
        return True, "URL sin slug comparable"

    # Amazon usa ASIN, no slug de nombre -> solo se comprueba la tienda
    if t_enlace == "amazon" and re.search(r"/(dp|gp/product)/[A-Z0-9]{10}", real):
        return True, ""

    p_titulo = _palabras(post.get("titulo") or post.get("nombre") or "")
    p_slug = _palabras(slug_txt)
    if not p_titulo or not p_slug:
        return True, "sin palabras comparables"
    # Dos formas de comparar, porque ML concatena palabras en el slug
    # ("...modernoc3-tons-de-luz-ajustaveiscontrole-remoto...": ahí "controle"
    # no es una palabra suelta del slug). Contar solo palabras exactas daba
    # falsos negativos en URLs largas, así que también se busca por subcadena.
    slug_plano = _norm(slug_txt).replace(" ", "")
    coinciden_palabra = len(p_titulo & p_slug)
    coinciden_sub = sum(1 for w in p_titulo if w in slug_plano)
    coinciden = max(coinciden_palabra, coinciden_sub)
    ratio = coinciden / max(1, len(p_titulo))
    if ratio < MIN_PALABRAS_ENLACE:
        return False, (f"el enlace no parece del producto (coincidencia "
                       f"{ratio:.0%}, mínimo {MIN_PALABRAS_ENLACE:.0%}): "
                       f"slug={slug_txt[:60]!r}")
    return True, ""


def _validar_cupon(post, cupon, hoy):
    """
    El cupón tiene que:
      1. Existir en el catálogo de cupones.
      2. Ser de la MISMA tienda que el producto y que el enlace.
      3. Estar VIGENTE HOY (se revalida en el momento de publicar, no antes).
      4. Cubrir la categoría del producto.
      5. Alcanzar la compra mínima.
    Devuelve (estado, motivo) con estado en {'ok', 'sin_cupon', 'descartar'}.
    'sin_cupon' = se publica la oferta sin cupón (cupón dudoso o inexistente).
    'descartar' = el cupón es de otra tienda: se quita también (nunca se publica
                  un cupón ajeno).
    """
    if not cupon:
        return "sin_cupon", "la oferta no tiene cupón"

    codigo = str(cupon.get("codigo") or "").strip()
    if not codigo:
        return "sin_cupon", "cupón sin código"

    # ── FUENTE TRAZABLE ─────────────────────────────────────────────────────
    # Última barrera contra los cupones huérfanos. TECH20 salía en TODAS las
    # publicaciones de Amazon porque era el único cupón marcado como "Amazon",
    # y no tenía fuente: era una entrada vieja metida a mano que los scripts
    # resucitaban en cada ejecución. Un cupón sin origen conocido no se puede
    # validar ni saber si sigue vivo.
    ok_fuente, motivo_fuente = cupon_confiable(cupon, hoy)
    if not ok_fuente and ("SIN FUENTE" in motivo_fuente
                          or "fuente no reconocida" in motivo_fuente):
        return "sin_cupon", motivo_fuente

    # ── ¿MERCADO LIVRE CONFIRMA QUE ESTE PRODUCTO TIENE CUPÓN? ──────────────
    # ML publica en su página de ofertas qué productos tienen cupón; el scraper
    # lo lee y lo guarda en `ml_tiene_cupon`. Si ML dice que NO, el cupón se
    # retira: los cupones de afiliado son generales ("produtos elegíveis") y en
    # la compra real no aplican. El usuario lo comprobó:
    #     "Seu cupom foi salvo em 'Cupons', pois não se aplica a esta compra."
    # gerar_fila_posts.py ya lo aplica al construir la fila; esto es la segunda
    # barrera, por si el post llegase por otra vía.
    if post.get("ml_tiene_cupon") is False:
        return "sin_cupon", (f"cupón {codigo} retirado: Mercado Livre no "
                             f"confirma que este producto tenga cupón")

    t_producto = tienda_de(post.get("loja"))
    t_enlace = tienda_de_url(post.get("url"))
    t_cupon = tienda_de(cupon.get("tienda"))

    if not t_cupon:
        return "sin_cupon", f"cupón {codigo} sin tienda declarada (no verificable)"
    if t_cupon != t_producto:
        return "descartar", (f"cupón {codigo} es de {t_cupon} y el producto de "
                             f"{t_producto}")
    if t_enlace and t_cupon != t_enlace:
        return "descartar", (f"cupón {codigo} es de {t_cupon} y el enlace de "
                             f"{t_enlace}")

    # Vigencia REVALIDADA AHORA
    hasta = str(cupon.get("hasta") or cupon.get("vencimento") or "").strip()
    if hasta:
        try:
            f_hasta = datetime.strptime(hasta[:10], "%Y-%m-%d").date()
            f_hoy = datetime.strptime(hoy, "%Y-%m-%d").date()
            dias = (f_hasta - f_hoy).days
            if dias < CUPON_VALIDEZ_DIAS:
                return "sin_cupon", (f"cupón {codigo} VENCIDO (venció el {hasta}, "
                                     f"hace {-dias} días)")
        except ValueError:
            return "sin_cupon", f"cupón {codigo} con fecha ilegible: {hasta!r}"

    # Categoría
    try:
        sys.path.insert(0, str(BASE))
        from gerar_fila_posts import _categoria_cupon, CATEGORIAS_DE_CUPON
        cat_cupon = _categoria_cupon(cupon)
        if cat_cupon:
            permitidas = CATEGORIAS_DE_CUPON.get(cat_cupon, [])
            cat_post = post.get("categoria") or ""
            if permitidas and cat_post not in permitidas:
                return "sin_cupon", (f"cupón {codigo} es de {cat_cupon} y el "
                                     f"producto es de {cat_post}")
    except Exception:
        pass

    # Compra mínima
    txt_min = str(cupon.get("compra_minima") or "")
    m = re.search(r"([\d.]+(?:,\d{2})?)", txt_min.replace("R$", "").strip())
    if m:
        try:
            minimo = float(m.group(1).replace(".", "").replace(",", "."))
            precio = float(post.get("precio") or 0)
            if minimo and precio and precio < minimo:
                return "sin_cupon", (f"cupón {codigo} exige mínimo R$ {minimo:.0f} "
                                     f"y el producto cuesta R$ {precio:.0f}")
        except (ValueError, TypeError):
            pass

    return "ok", ""


def _validar_pix(post):
    """
    El PIX solo se muestra si EXISTE el dato. Nunca se inventa.
    (Antes se ponía "mais 5% OFF" a todo: el 100% de los posts anunciaba un
    descuento Pix inexistente.)
    """
    pix = str(post.get("pix") or "").strip()
    if not pix:
        return None, "sin descuento PIX (no se menciona)"
    if pix.lower() in ("à vista", "a vista", "-"):
        return None, "sin descuento PIX, solo medio de pago"
    # Tiene que traer un porcentaje o un valor real
    if not re.search(r"\d", pix):
        return None, f"valor PIX no utilizable: {pix!r}"
    return pix, ""


def _validar_frescura(post):
    """El post no puede ser de hace días."""
    for campo in ("revalidado_em", "criado_em", "actualizado"):
        v = post.get(campo)
        if not v:
            continue
        try:
            t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            horas = (datetime.now(timezone.utc) - t).total_seconds() / 3600
            if horas > HORAS_MAX_DATOS:
                return False, (f"dato de hace {horas:.0f} h "
                               f"(máximo {HORAS_MAX_DATOS} h)")
        except (ValueError, TypeError):
            continue
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
#  VALIDACIÓN COMPLETA
# ══════════════════════════════════════════════════════════════════════════════
def validar_oferta(post, cupones=None, registrar=True):
    """
    Valida la oferta completa y devuelve (ok, motivo, oferta_limpia).

    oferta_limpia lleva SOLO campos verificados: si el cupón no es fiable, sale
    sin cupón; si el PIX no existe, sale sin PIX. Así el publicador nunca puede
    pintar un dato que no se haya comprobado.
    """
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    limpio = dict(post)

    # 1. PRODUCTO
    ok, motivo = _validar_producto(post)
    if not ok:
        limpio["cupom"] = None
        _registrar(post, "RECHAZADO", motivo, registrar)
        return False, motivo, limpio

    # 2. FRESCURA
    ok, motivo = _validar_frescura(post)
    if not ok:
        limpio["cupom"] = None
        _registrar(post, "RECHAZADO", motivo, registrar)
        return False, motivo, limpio

    # 3. ENLACE
    ok, motivo = _validar_enlace(post)
    if not ok:
        limpio["cupom"] = None
        _registrar(post, "RECHAZADO", motivo, registrar)
        return False, motivo, limpio

    # 4. CUPÓN
    codigo = str(post.get("cupom") or "").strip()
    cupon = None
    if codigo:
        cupon = (cupones or {}).get(codigo.upper()) if isinstance(cupones, dict) else None
        if cupon is None and isinstance(cupones, list):
            for c in cupones:
                if str(c.get("codigo", "")).strip().upper() == codigo.upper():
                    cupon = c
                    break
        if cupon is None:
            # Cupón que viene del scraping del propio producto: no está en el
            # catálogo, así que la tienda está garantizada por origen y las
            # condiciones no se conocen -> se mantiene pero SIN prometer %.
            limpio["cupom_confianza"] = "baja"

    estado, motivo_cupon = _validar_cupon(post, cupon, hoy)
    if estado == "descartar":
        # Cupón de otra tienda: NUNCA se publica, ni siquiera sin prometer.
        limpio["cupom"] = None
        limpio["cupom_pct"] = None
        limpio["cupom_max"] = None
        limpio["cupom_valor"] = None
        limpio["cupom_confianza"] = None
        motivo = motivo_cupon
        _registrar(post, "RECHAZADO_CUPON", motivo, registrar)
        # El resto de la oferta sigue siendo válida: se publica SIN cupón.
        # (El usuario lo pidió así: "es preferible publicar una oferta sin
        #  cupón antes que publicar un cupón incorrecto".)
    elif estado == "sin_cupon":
        limpio["cupom"] = None
        limpio["cupom_pct"] = None
        limpio["cupom_max"] = None
        limpio["cupom_valor"] = None
        limpio["cupom_confianza"] = None
        motivo_cupon = motivo_cupon
    else:
        # El cupón pasó todas las puertas. La CONFIANZA decide si el publicador
        # puede prometer el precio final: solo si el cupón declara una categoría
        # que coincide (entonces sabemos a qué productos aplica). Los cupones
        # "generales" de ML van a "produtos elegíveis" que solo ML conoce -> baja.
        try:
            from gerar_fila_posts import _categoria_cupon as _cat_cup
            cat_c = _cat_cup(cupon or {})
        except Exception:
            cat_c = ""
        limpio["cupom_confianza"] = "alta" if cat_c else "baja"
        motivo_cupon = ("cupón válido (categoría verificada)"
                        if cat_c else "cupón válido pero general: no se promete precio")

    # 5. PIX
    pix, motivo_pix = _validar_pix(post)
    limpio["pix"] = pix
    if pix is None:
        limpio["pix_pct"] = None

    # Si el cupón no es de confianza alta, no se promete precio final
    if limpio.get("cupom_confianza") == "baja":
        limpio["cupom_pct_fiable"] = None

    _registrar(post, "OK" if limpio.get("cupom") or not codigo else "OK_SIN_CUPON",
               f"{motivo_cupon} | {motivo_pix}", registrar)
    return True, motivo_cupon, limpio


def _registrar(post, resultado, motivo, activo=True):
    """Deja rastro en logs/validacion.jsonl para poder depurar."""
    if not activo:
        return
    try:
        linea = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "resultado": resultado,
            "producto": str(post.get("titulo") or post.get("nombre") or "")[:80],
            "tienda": post.get("loja"),
            "precio": post.get("precio"),
            "cupon": post.get("cupom"),
            "enlace": str(post.get("url") or "")[:110],
            "pix": post.get("pix") or "",
            "motivo": motivo,
        }
        with LOG_VALIDACION.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cargar_cupones():
    """Catálogo de cupones por código (mayúsculas)."""
    f = BASE / "cupones.json"
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        lista = d.get("cupones", d if isinstance(d, list) else [])
        return {str(c.get("codigo", "")).strip().upper(): c
                for c in lista if c.get("codigo")}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
#  ¿ESTE CUPÓN ES DE FIAR?
# ══════════════════════════════════════════════════════════════════════════════
# BUG REPORTADO POR EL USUARIO: el cupón TECH20 aparecía en TODAS las
# publicaciones de Amazon. No es un cupón de Amazon: es una entrada vieja
# metida a mano, con la tienda mal puesta y con la fecha mal, y como era el
# ÚNICO cupón marcado como "Amazon" se le asignaba a todo el catálogo de Amazon.
#
# CAUSA RAÍZ: en cupones.json había cupones con `fonte: null` (sin fuente).
# Y los dos scripts que escriben el fichero los RESUCITABAN en cada ejecución:
#     cupones_pelando.py:  existentes = [c for c in ... if c.get("fonte") != "Pelando"]
#     leer_telegram.py:    por_codigo[cod] = cup ... (conserva todo lo anterior)
# Con `fonte = None`, la condición `None != "Pelando"` es True, así que el cupón
# huérfano se conservaba PARA SIEMPRE. Nunca caducaba, nunca se limpiaba.
#
# REGLA: un cupón sin fuente trazable NO se usa y NO se conserva.
# Si no se sabe de dónde salió, no se puede saber si sigue vigente.
FUENTES_VALIDAS = ("telegram", "pelando", "manual.json", "afiliados")


def cupon_confiable(cupon, hoy=None):
    """
    Decide si un cupón merece ser tenido en cuenta.
    Devuelve (bool, motivo).

    Un cupón es de fiar si:
      - tiene código
      - tiene tienda reconocible
      - tiene FUENTE trazable (lo que impedía que TECH20 muriera)
      - no está caducado
    """
    if not isinstance(cupon, dict):
        return False, "no es un cupón"
    codigo = str(cupon.get("codigo") or "").strip()
    if not codigo:
        return False, "sin código"

    if not tienda_de(cupon.get("tienda")):
        return False, f"{codigo}: sin tienda reconocible"

    fonte = str(cupon.get("fonte") or "").strip().lower()
    if not fonte:
        return False, (f"{codigo}: SIN FUENTE (no se puede saber de dónde salió "
                       f"ni si sigue vigente)")
    if not any(f in fonte for f in FUENTES_VALIDAS):
        return False, f"{codigo}: fuente no reconocida ({fonte!r})"

    hoy = hoy or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hasta = str(cupon.get("hasta") or cupon.get("vencimento") or "").strip()
    if hasta and hasta[:10] < hoy:
        return False, f"{codigo}: caducado el {hasta[:10]}"

    return True, ""


def limpiar_cupones(lista, hoy=None):
    """
    Devuelve (conservados, descartados) aplicando cupon_confiable().
    Se usa en los scripts que ESCRIBEN cupones.json para que los huérfanos no
    se resuciten en cada ejecución.
    """
    hoy = hoy or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conservados, descartados = [], []
    for c in lista or []:
        ok, motivo = cupon_confiable(c, hoy)
        if ok:
            conservados.append(c)
        else:
            descartados.append((c, motivo))
    return conservados, descartados



# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════
def auditar_fila(limite=None):
    """Pasa la fila entera por el validador y resume los motivos."""
    f = BASE / "fila_posts.json"
    if not f.exists():
        print("  no hay fila_posts.json")
        return 1
    posts = json.loads(f.read_text(encoding="utf-8-sig")).get("fila", [])
    cupones = cargar_cupones()
    print("=" * 78)
    print("  AUDITORÍA DE LA FILA CON EL VALIDADOR")
    print("=" * 78)
    print(f"  posts: {len(posts)} | cupones en catálogo: {len(cupones)}")

    from collections import Counter
    res = Counter()
    motivos = Counter()
    ejemplos = {}
    for p in posts:
        ok, motivo, limpio = validar_oferta(p, cupones, registrar=False)
        if not ok:
            res["rechazado"] += 1
            motivos[motivo[:70]] += 1
            ejemplos.setdefault(motivo[:70], p)
        elif p.get("cupom") and not limpio.get("cupom"):
            res["aceptado_sin_cupon"] += 1
            motivos[motivo[:70]] += 1
            ejemplos.setdefault(motivo[:70], p)
        else:
            res["aceptado_completo"] += 1

    for k, v in res.most_common():
        print(f"  {v:>5}  {k}")
    print()
    print("  MOTIVOS:")
    for m, n in motivos.most_common(12):
        print(f"  {n:>5}  {m}")
        p = ejemplos.get(m)
        if p:
            print(f"         -> {str(p.get('titulo'))[:60]}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--auditar", "--audit"):
        return auditar_fila()
    if len(sys.argv) > 1 and sys.argv[1] == "--probar":
        import probar_validador
        return probar_validador.main()
    print(__doc__)
    print("  Uso: python validador_oferta.py --auditar   (revisa la fila)")
    print("       python validador_oferta.py --probar    (escenarios de prueba)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
