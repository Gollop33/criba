#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Comparador multi-tienda (comparador_precios.py)
=======================================================
Responde a la pregunta que MÁS vende en un canal de ofertas:

    "¿esto está más barato aquí que en otros lados?"

No es una oferta más: es LA RAZÓN para comprar por tu link. Un "R$ 189" no dice
nada; un "R$ 189 y en KaBuM está a R$ 240" cierra la venta.

De dónde saca los datos
-----------------------
De `precios.db`, que ya consulta 8 tiendas (Amazon, Mercado Livre, KaBuM!,
Pichau, Terabyte, Shopee, Magalu, AliExpress). El problema es que hoy solo sigue
16 productos de una lista fija que nunca coincide con lo que se publica.

Solución: este script hace dos cosas.
  1. COMPARA: cruza la fila de posts con el historial multi-tienda y anota cada
     post con `mejor_precio` y `comparativa`.
  2. ALIMENTA EL MONITOR: escribe `productos_monitor.json` con los productos que
     se están publicando, para que `bot_precios.py` los vigile a partir de
     ahora. Así la cobertura crece sola día a día.

Uso:
    python comparador_precios.py            # anota la fila y actualiza el monitor
    python comparador_precios.py --informe  # solo informa
"""

import io
import json
import os
import re
import sqlite3
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
DB = BASE / "precios.db"
FILA = BASE / "fila_posts.json"
MONITOR = BASE / "productos_monitor.json"

# Cuánto mejor tiene que ser nuestro precio para presumir de "más barato".
# Un 2% da margen a diferencias de redondeo o de envío.
MARGEN_MEJOR = float(os.environ.get("COMPARADOR_MARGEN", "2")) / 100.0
# Cuántos productos se mandan a vigilar (cada uno son 2 búsquedas: ML y Shopee)
MAX_MONITOR = int(os.environ.get("MAX_MONITOR", "60"))


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _clave(nombre):
    """Clave aproximada de producto: palabras significativas."""
    return " ".join(w for w in _norm(nombre).split() if len(w) >= 3)[:70]


def cargar_historial():
    """
    {clave_producto: {tienda: {'min':x, 'ult':y, 'n':n}}}
    Lee `historico_precios` (slug + tienda + precio) y también `historial`
    unido a `productos` para tener el nombre humano.
    """
    idx = {}

    def meter(clave, tienda, precio):
        if not clave or not tienda or not precio or precio <= 0:
            return
        d = idx.setdefault(clave, {}).setdefault(
            tienda, {"min": precio, "max": precio, "n": 0})
        d["min"] = min(d["min"], precio)
        d["max"] = max(d["max"], precio)
        d["ult"] = precio
        d["n"] += 1

    if not DB.exists():
        return idx
    try:
        con = sqlite3.connect(str(DB))
        for slug, tienda, precio in con.execute(
            "SELECT producto_id, tienda, precio FROM historico_precios WHERE precio > 0"
        ):
            meter(_clave(slug), tienda, float(precio))
        for nombre, tienda, precio in con.execute(
            """SELECT p.nombre, h.tienda, h.precio_vista
               FROM historial h JOIN productos p ON p.id = h.producto_id
               WHERE h.precio_vista > 0"""
        ):
            meter(_clave(nombre), tienda, float(precio))
        con.close()
    except Exception as e:
        print(f"  [comparador] no se pudo leer precios.db: {e}")
    return idx


def _buscar(item, idx):
    """
    Busca un post en el índice multi-tienda. Devuelve {tienda: datos} o None.
    Primero por clave exacta; si no, por solapamiento de palabras.
    """
    titulo = item.get("titulo") or item.get("nombre") or ""
    idp = item.get("id_post") or ""
    for k in (_clave(titulo), _clave(idp)):
        if k and k in idx:
            return idx[k]

    palabras = {w for w in _norm(titulo).split() if len(w) >= 4}
    if not palabras:
        return None
    mejor, score = None, 0.0
    for clave, datos in idx.items():
        cp = {w for w in clave.split() if len(w) >= 4}
        if not cp:
            continue
        s = len(palabras & cp) / max(1, len(palabras))
        if s > score:
            mejor, score = datos, s
    return mejor if score >= 0.7 else None


def evaluar(item, idx):
    """
    Compara el precio del post con el de las demás tiendas.
    Devuelve dict con mejor_precio / comparativa / otras_tiendas, o {} si no hay datos.
    """
    datos = _buscar(item, idx)
    if not datos:
        return {}
    try:
        nuestro = float(item.get("precio") or 0)
    except (TypeError, ValueError):
        return {}
    if nuestro <= 0:
        return {}

    tienda_post = _norm(item.get("loja") or "")
    otras = {t: d for t, d in datos.items() if _norm(t) and _norm(t) not in tienda_post}
    if not otras:
        return {}

    mas_barata = min(otras.items(), key=lambda kv: kv[1]["min"])
    rival_nombre, rival = mas_barata
    if rival["min"] <= 0:
        return {}

    ahorro_pct = (rival["min"] - nuestro) / rival["min"] * 100

    resultado = {
        "otras_tiendas": {t: round(d["min"], 2) for t, d in sorted(
            otras.items(), key=lambda kv: kv[1]["min"])[:4]},
        "rival_mas_barato": rival_nombre,
        "rival_precio": round(rival["min"], 2),
    }
    if ahorro_pct >= MARGEN_MEJOR * 100:
        resultado["mejor_precio"] = True
        resultado["comparativa"] = (
            f"R$ {int(round(nuestro))} aqui y R$ {int(round(rival['min']))} "
            f"en {rival_nombre}")
        resultado["ahorro_pct"] = round(ahorro_pct, 1)
    else:
        resultado["mejor_precio"] = False
    return resultado


def productos_para_monitor(limite=MAX_MONITOR):
    """
    Saca de la fila los productos que conviene vigilar, priorizando los que más
    se van a publicar. Esto es lo que hace que el comparador tenga datos: el
    monitor sigue lo que se publica, no una lista fija.
    """
    if not FILA.exists():
        return []
    try:
        fila = json.loads(FILA.read_text(encoding="utf-8-sig")).get("fila", [])
    except Exception:
        return []

    vistos, salida = set(), []
    for p in fila:
        titulo = (p.get("titulo") or "").strip()
        if not titulo:
            continue
        k = _clave(titulo)
        if not k or k in vistos:
            continue
        vistos.add(k)
        # La búsqueda se acorta: 8 palabras bastan para encontrar el producto
        busqueda = " ".join(_norm(titulo).split()[:8])
        salida.append({
            "busqueda": busqueda,
            "nombre": titulo,
            "precio_ref": p.get("precio"),
            "categoria": p.get("categoria") or "Geral",
            "tienda_origen": p.get("loja"),
            "monitorizado_desde": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        if len(salida) >= limite:
            break
    return salida


def main():
    solo_informe = "--informe" in sys.argv
    idx = cargar_historial()
    productos_idx = len(idx)

    print("=" * 74)
    print("  COMPARADOR MULTI-TIENDA")
    print("=" * 74)
    print(f"  productos con historial multi-tienda: {productos_idx}")
    if not productos_idx:
        print("  (precios.db vacío: el comparador empezará a funcionar cuando")
        print("   bot_precios.py acumule historial de los productos publicados)")

    if not FILA.exists():
        print("  no hay fila_posts.json")
        return 1
    fila = json.loads(FILA.read_text(encoding="utf-8-sig")).get("fila", [])
    print(f"  posts en la fila: {len(fila)}")

    con_datos = comparados = mejores = 0
    for p in fila:
        r = evaluar(p, idx)
        if not r:
            continue
        con_datos += 1
        p.update(r)
        if r.get("mejor_precio"):
            mejores += 1
        comparados += 1

    print()
    print(f"  posts con datos de otras tiendas: {con_datos}")
    print(f"  marcados como MÁS BARATOS: {mejores}")
    if con_datos:
        print()
        print("  muestra:")
        mostrados = 0
        for p in fila:
            if p.get("comparativa"):
                print(f"     {str(p.get('titulo'))[:44]:46s} {p['comparativa']}")
                mostrados += 1
                if mostrados >= 8:
                    break

    # Alimentar el monitor
    if not solo_informe:
        productos = productos_para_monitor()
        if productos:
            datos = {
                "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "total": len(productos),
                "nota": ("Productos que se están publicando. bot_precios.py los "
                         "vigila en ML y Shopee para poder comparar precios."),
                "productos": productos,
            }
            MONITOR.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            print()
            print(f"  monitor actualizado: {len(productos)} productos -> "
                  f"{MONITOR.name}")
            print("  (a partir de ahora bot_precios.py los vigila)")

    if not solo_informe and fila:
        d = json.loads(FILA.read_text(encoding="utf-8-sig"))
        d["fila"] = fila
        d["comparado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        FILA.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  fila_posts.json anotada con la comparativa")

    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
