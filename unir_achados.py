#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Unificador de Achados (unir_achados.py)
==============================================
Fusiona achados_ml.json, achados_amazon.json y achados_shopee.json en achados.json:
  - Deduplicación estricta por nombre
  - Ordenación por mayor descuento porcentual (desc_pct)
  - Validación 100% de la Regla de Oro (solo tiendas con tag/enlace de afiliado
    propio: Amazon, Mercado Livre y Shopee)
  - Limpieza de ofertas expiradas (> 36h)
  - Generación de achados frescos y activos (MAX_ACHADOS, def. 600)

Regla de oro por tienda:
  - Amazon       -> url con amazon.com.br y tag=criba20-20
  - Mercado Livre-> url meli.la o mercadolivre.com.br con el tag de afiliado
  - Shopee       -> SOLO enlace corto de afiliado (s.shopee.com.br / shp.ee) y
                    con `afiliado_verificado` en True. Ese enlace lo genera la
                    API oficial con la cuenta del afiliado (ver agente_shopee.py).
                    Un enlace normal de producto Shopee se descarta.

Uso: python unir_achados.py
"""
import json, os, re, unicodedata, sys, io, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from shopee_api import HOSTS_AFILIADO

# UTF-8 fix for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
FILE_ML = BASE / "achados_ml.json"
FILE_AMZ = BASE / "achados_amazon.json"
FILE_SHP = BASE / "achados_shopee.json"
FILE_OUT = BASE / "achados.json"

AMAZON_TAG = "criba20-20"
ML_TAG = "ja20250119201346"

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def cargar_items(path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("achados", [])
        elif isinstance(data, list):
            return data
    except Exception as e:
        print(f"Error cargando {path.name}: {e}")
    return []

def registrar_historial(items):
    """
    Guarda el precio de cada oferta en precios.db -> historico_precios, pero
    SOLO cuando el precio CAMBIA respecto al último registro de ese producto.

    Por qué aquí: este es el único punto por el que pasan TODAS las ofertas
    frescas de todas las tiendas cada vez que corre el bot. Antes el histórico
    solo cubría los ~60 productos vigilados (643 filas en total), así que no se
    podía saber si un precio era bueno de verdad.

    Con esto ya se puede:
      · marcar "MENOR PREÇO EM 30 DIAS" solo cuando es cierto
      · detectar la bajada real y readmitir el producto (gerar_fila_posts)
      · alimentar la web con un precio de referencia honesto

    Escribir solo en los CAMBIOS mantiene la base pequeña: no crece por correr
    el bot cada hora, solo cuando el precio se mueve de verdad.
    """
    db = Path(__file__).parent / "precios.db"
    if not db.exists():
        return 0, 0
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS historico_precios (
            producto_id TEXT, tienda TEXT, precio REAL, fecha TEXT)""")
        ultimos = {}
        for pid, tienda, precio in cur.execute(
                "SELECT producto_id, tienda, precio FROM historico_precios"):
            ultimos[(pid, tienda)] = precio
        ahora_bd = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        nuevos = 0
        for it in items:
            pid = str(it.get("id") or "")
            tienda = str(it.get("loja") or "")
            try:
                precio = float(it.get("precio") or 0)
            except (TypeError, ValueError):
                continue
            if not pid or not tienda or precio <= 0:
                continue
            if ultimos.get((pid, tienda)) == precio:
                continue
            cur.execute("INSERT INTO historico_precios (producto_id, tienda, precio, fecha) "
                        "VALUES (?,?,?,?)", (pid, tienda, precio, ahora_bd))
            nuevos += 1
        con.commit()
        con.close()
        return nuevos, len(ultimos)
    except Exception as e:
        print(f"  • Histórico de precios no disponible: {e}")
        return 0, 0


def main():
    print("=" * 60)
    print("  CRIBA · UNIFICADOR DE ACHADOS DO DIA")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    items_ml = cargar_items(FILE_ML)
    items_amz = cargar_items(FILE_AMZ)
    items_shp = cargar_items(FILE_SHP)

    print(f"  • Achados ML:     {len(items_ml)}")
    print(f"  • Achados Amazon: {len(items_amz)}")
    print(f"  • Achados Shopee: {len(items_shp)}")

    todos = items_ml + items_amz + items_shp
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Umbrales por tienda: Amazon muestra menos descuentos que ML en su grilla
    # de bestsellers, así que exigirle el mismo 15% dejaba fuera casi todo.
    # Y el tope de 80 era el último cuello de botella: los scrapers ya producían
    # 400 + 33 ofertas y aquí se quedaban en 80.
    desc_min_ml = float(os.environ.get("ML_DESC_MIN", "10"))
    # Amazon: 0 por defecto. Se midió que los 268 productos del bestseller de
    # Amazon tienen desc_pct=0 porque su lista NO muestra precio tachado. Exigir
    # descuento ahí dejaba Amazon en 33 ofertas de 268.
    desc_min_az = float(os.environ.get("AZ_DESC_MIN", "0"))
    # Shopee: 15% por defecto. La API SÍ devuelve priceDiscountRate, así que
    # aquí exigir descuento real no deja fuera casi nada (a diferencia de Amazon).
    desc_min_shp = float(os.environ.get("SHOPEE_DESC_MIN", "15"))
    max_achados = int(os.environ.get("MAX_ACHADOS", "600"))

    vistos = set()
    validos = []
    descartados_desc = 0
    descartados_enlace = 0

    for it in todos:
        u = it.get("url", "")
        loja = it.get("loja", "")
        desc = float(it.get("desc_pct") or 0)
        exp = it.get("expira_em", "")

        # 1. Filtro de expiración
        if exp and exp <= ahora_iso:
            continue

        # 2. Filtro de descuento mínimo (por tienda)
        if "Amazon" in loja:
            desc_min = desc_min_az
        elif "Shopee" in loja:
            desc_min = desc_min_shp
        else:
            desc_min = desc_min_ml
        if desc < desc_min:
            descartados_desc += 1
            continue

        # 3. Regla de Oro estricta
        if "Amazon" in loja:
            if "amazon.com.br" not in u or f"tag={AMAZON_TAG}" not in u:
                descartados_enlace += 1
                continue
        elif "Mercado Livre" in loja:
            if "meli.la" not in u and ("mercadolivre.com.br" not in u or ML_TAG not in u):
                descartados_enlace += 1
                continue
        elif "Shopee" in loja:
            # Doble condición: enlace corto de afiliado + marca del cosechador.
            # Cualquier enlace de producto normal (shopee.com.br/product/...) cae aquí.
            if not it.get("afiliado_verificado") or not any(h in u for h in HOSTS_AFILIADO):
                descartados_enlace += 1
                continue
        else:
            # Descartar cualquier otra tienda no aprobada
            descartados_enlace += 1
            continue

        # 4. Deduplicar por nombre normalizado
        clave = normalizar(it.get("nombre", ""))[:32]
        if clave and clave not in vistos:
            vistos.add(clave)
            it["revalidado_em"] = ahora_iso
            validos.append(it)

    # ── ORDEN: ALTERNAR TIENDAS ───────────────────────────────────────────────
    # Antes se ordenaba solo por fecha de cosecha. Como agente_amazon.py corre
    # DESPUÉS de agente_ml.py, TODAS las de Amazon tenían fecha más reciente y
    # quedaban las primeras: el catálogo empezaba con 78 de Amazon y las 400 de
    # Mercado Livre venían detrás. El usuario abría la web y solo veía Amazon.
    #
    # Ahora se alternan tienda a tienda (y dentro de cada una, por descuento),
    # así el catálogo muestra las dos desde la primera fila.
    def _clave_orden(x):
        return (float(x.get("desc_pct") or 0),
                x.get("encontrado_em", "") or x.get("revalidado_em", ""))

    ml = sorted([x for x in validos if "Mercado" in (x.get("loja") or "")],
                key=_clave_orden, reverse=True)
    az = sorted([x for x in validos if "Amazon" in (x.get("loja") or "")],
                key=_clave_orden, reverse=True)
    shp = sorted([x for x in validos if "Shopee" in (x.get("loja") or "")],
                 key=_clave_orden, reverse=True)
    otros = [x for x in validos if "Mercado" not in (x.get("loja") or "")
             and "Amazon" not in (x.get("loja") or "")
             and "Shopee" not in (x.get("loja") or "")]

    # Ronda entre las tiendas monetizadas: la primera fila del catálogo muestra
    # las tres, en vez de 400 de ML y las demás detrás.
    seleccionados = []
    fuentes = [ml, az, shp]
    indices = [0] * len(fuentes)
    while len(seleccionados) < max_achados and any(indices[k] < len(fuentes[k]) for k in range(len(fuentes))):
        for k, lista in enumerate(fuentes):
            if indices[k] < len(lista) and len(seleccionados) < max_achados:
                seleccionados.append(lista[indices[k]])
                indices[k] += 1

    if len(seleccionados) < max_achados:
        seleccionados += otros[:max_achados - len(seleccionados)]

    print(f"  • Descartadas por descuento insuficiente: {descartados_desc}")
    print(f"  • Descartadas por enlace no verificado : {descartados_enlace}")
    nuevos_hist, total_hist = registrar_historial(seleccionados)
    print(f"  • Histórico de precios: {nuevos_hist} precio(s) nuevo(s) de {total_hist} conocidos")
    print(f"  • Orden alternado: ML {len(ml)} | Amazon {len(az)} | Shopee {len(shp)} | otras {len(otros)}")

    resultado = {
        "actualizado": ahora_iso,
        "revalidado_em": ahora_iso,
        "total_achados": len(seleccionados),
        "achados": seleccionados
    }

    FILE_OUT.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] achados.json generado exitosamente con {len(seleccionados)} ofertas.")
    print("=" * 60)

if __name__ == "__main__":
    main()
