#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente de calidad de ofertas (agente_calidad.py)
=========================================================
Portero que se ejecuta ANTES de publicar. Responde a la pregunta que hoy nadie
hace: *¿esta oferta es de verdad, y el link funciona?*

Dos comprobaciones:

1. LINK VIVO
   Abre el link de afiliado y confirma que resuelve. Evita publicar al grupo
   links rotos o productos retirados (pierdes el clic Y la confianza).

2. PRECIO REAL  (el problema gordo)
   Mercado Livre y Amazon inflan el "precio tachado". Hoy el publicador se cree
   el `precio_anterior` que le da la tienda y anuncia "52% OFF" sin verificar.
   Este agente compara contra el historial REAL observado en `precios.db`
   (`historico_precios`) y marca como sospechoso el descuento cuyo precio
   tachado nunca existió.

Uso:
    python agente_calidad.py --informe          # audita la fila actual
    python agente_calidad.py --probar <url>     # comprueba un link suelto
    from agente_calidad import evaluar_post     # uso desde el publicador
"""

import io
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
PRECIOS_DB = BASE / "precios.db"
FILA_JSON = BASE / "fila_posts.json"

# Cuánto puede superar el precio "tachado" al máximo histórico observado antes
# de considerarlo un ancla falsa. 10% da margen a variaciones legítimas.
TOLERANCIA_ANCLA = 1.10
MIN_PUNTOS_HISTORIAL = 3


def _norm(s):
    """Normaliza texto para comparar títulos."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def cargar_historial():
    """
    Devuelve {clave_normalizada: {'max','min','ult','n'}}.

    OJO con el esquema real de precios.db:
      - `historico_precios.producto_id` es un SLUG de texto
        (p.ej. 'teclado-mecanico-redragon-kumara-k552-rgb-swi'), no el id entero.
      - `historial.producto_id` SÍ es el id entero -> se une con `productos.id`
        para obtener el nombre humano.
    Se indexa por ambos: slug y nombre normalizado.
    """
    hist = {}
    if not PRECIOS_DB.exists():
        return hist

    def acumular(clave, precio):
        if not clave or not precio or precio <= 0:
            return
        hist.setdefault(clave, []).append(float(precio))

    try:
        con = sqlite3.connect(str(PRECIOS_DB))
        # 1) por slug (historico_precios.producto_id)
        for slug, precio in con.execute(
            "SELECT producto_id, precio FROM historico_precios WHERE precio > 0"
        ):
            acumular(_norm(slug), precio)
        # 2) por nombre humano (historial JOIN productos)
        for nombre, precio in con.execute(
            """SELECT p.nombre, h.precio_vista
               FROM historial h JOIN productos p ON p.id = h.producto_id
               WHERE h.precio_vista > 0"""
        ):
            acumular(_norm(nombre), precio)
        # 3) por clave de productos -> nombre (por si el post trae la clave)
        for clave, nombre in con.execute("SELECT clave, nombre FROM productos"):
            acumular(_norm(clave), 0)  # solo registra la clave; el precio lo pone el historial
        con.close()
    except Exception as e:
        print(f"  [agente] no se pudo leer precios.db: {e}")
        return hist

    salida = {}
    for k, ps in hist.items():
        if not ps:
            continue
        salida[k] = {"n": len(ps), "max": max(ps), "min": min(ps), "ult": ps[-1]}
    return salida


def _buscar_en_historial(post, hist):
    """Busca el producto del post en el historial. Devuelve dict o None."""
    if not hist:
        return None
    titulo = _norm(post.get("titulo"))
    idpost = _norm(post.get("id_post"))
    if not titulo:
        return None

    # Coincidencia exacta por título o id
    for k in (titulo, idpost):
        if k and k in hist:
            return hist[k]

    # Coincidencia parcial: bastantes palabras en comun
    palabras = set(w for w in titulo.split() if len(w) >= 4)
    if not palabras:
        return None
    mejor, mejor_score = None, 0.0
    for clave, d in hist.items():
        cp = set(w for w in clave.split() if len(w) >= 4)
        if not cp:
            continue
        score = len(palabras & cp) / max(1, len(palabras))
        if score > mejor_score:
            mejor, mejor_score = d, score
    return mejor if mejor_score >= 0.7 else None


def verificar_link(url, timeout=15):
    """(ok, detalle). ok=None si no se pudo comprobar (red)."""
    if not url:
        return False, "sin url"
    try:
        import requests
    except ImportError:
        return None, "requests no instalado"
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/128.0.0.0 Safari/537.36"),
                "Accept-Language": "pt-BR,pt;q=0.9",
            },
        )
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        if len(r.content) < 500:
            return False, f"respuesta sospechosamente corta ({len(r.content)} bytes)"
        if re.search(r"p[áa]gina n[ãa]o encontrada|not found|produto indispon", r.text[:20000], re.I):
            return False, "la pagina dice que no existe / no disponible"
        return True, f"HTTP {r.status_code} ({len(r.content)} bytes)"
    except Exception as e:
        return None, f"no verificable: {type(e).__name__}"


def evaluar_precio(post, hist):
    """
    (veredicto, detalle) donde veredicto es:
      'ok'        -> el descuento esta respaldado por el historial
      'sospechoso'-> el precio tachado nunca existio (ancla falsa)
      'sin_datos' -> no hay historial suficiente para juzgar
    """
    actual = post.get("precio")
    tachado = post.get("precio_anterior")
    try:
        actual = float(actual)
        tachado = float(tachado) if tachado else 0.0
    except (TypeError, ValueError):
        return "sin_datos", "precios no numericos"

    if actual <= 0:
        return "sin_datos", "sin precio actual"
    if tachado <= 0:
        return "ok", "sin precio tachado (no se anuncia descuento)"

    d = _buscar_en_historial(post, hist)
    if not d or d.get("n", 0) < MIN_PUNTOS_HISTORIAL:
        return "sin_datos", f"historial insuficiente ({d['n'] if d else 0} puntos)"

    max_hist = d["max"]
    if tachado > max_hist * TOLERANCIA_ANCLA:
        real = round((max_hist - actual) / max_hist * 100, 1) if max_hist > actual else 0.0
        return ("sospechoso",
                f"tachado R$ {tachado:.0f} nunca visto (max real R$ {max_hist:.0f}); "
                f"descuento real ~{real}% en vez de {post.get('desc_pct')}%")
    return "ok", f"respaldado: max real R$ {max_hist:.0f} ({d['n']} puntos)"


def evaluar_post(post, hist=None, verificar_links=True):
    """Evalua un post de la fila. Devuelve dict con apto/avisos/motivos."""
    if hist is None:
        hist = cargar_historial()
    res = {"id_post": post.get("id_post"), "apto": True, "avisos": [], "bloqueos": []}

    vp, dp = evaluar_precio(post, hist)
    res["precio"] = vp
    res["detalle_precio"] = dp
    if vp == "sospechoso":
        res["avisos"].append(f"precio: {dp}")

    if verificar_links:
        ok, det = verificar_link(post.get("url"))
        res["link"] = "ok" if ok else ("sin_verificar" if ok is None else "roto")
        res["detalle_link"] = det
        if ok is False:
            res["bloqueos"].append(f"link roto: {det}")

    if res["bloqueos"]:
        res["apto"] = False
    return res


def informe(limite=25):
    if not FILA_JSON.exists():
        print("no hay fila_posts.json")
        return 1
    fila = json.loads(FILA_JSON.read_text(encoding="utf-8")).get("fila", [])
    hist = cargar_historial()
    print("=" * 70)
    print("  AGENTE DE CALIDAD · INFORME DE LA FILA")
    print(f"  productos en el historial real: {len(hist)} | posts: {len(fila)}")
    print("=" * 70)

    conteo = {"ok": 0, "sospechoso": 0, "sin_datos": 0}
    for p in fila[:limite]:
        r = evaluar_post(p, hist, verificar_links=False)
        conteo[r["precio"]] = conteo.get(r["precio"], 0) + 1
        marca = {"ok": "[ok] ", "sospechoso": "[!!] ", "sin_datos": "[--] "}[r["precio"]]
        tit = (p.get("titulo") or "")[:46]
        print(f"{marca}{tit:46s} {r['detalle_precio']}")

    print("-" * 70)
    print(f"  respaldados: {conteo.get('ok', 0)} | SOSPECHOSOS: {conteo.get('sospechoso', 0)} "
          f"| sin datos: {conteo.get('sin_datos', 0)}")
    print("=" * 70)
    return 0


def main():
    if "--probar" in sys.argv:
        i = sys.argv.index("--probar")
        if i + 1 < len(sys.argv):
            ok, det = verificar_link(sys.argv[i + 1])
            print(f"link -> {ok} : {det}")
            return 0
    return informe()


if __name__ == "__main__":
    sys.exit(main())
