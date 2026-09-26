#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Unificador de Achados (unir_achados.py)
==============================================
Fusiona achados_ml.json y achados_amazon.json en achados.json:
  - Deduplicación estricta por nombre
  - Ordenación por mayor descuento porcentual (desc_pct)
  - Validación 100% de la Regla de Oro (solo Amazon y ML con tags oficiales)
  - Limpieza de ofertas expiradas (> 36h)
  - Generación de entre 40 y 80 achados frescos y activos

Uso: python unir_achados.py
"""
import json, os, re, unicodedata, sys, io
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 fix for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
FILE_ML = BASE / "achados_ml.json"
FILE_AMZ = BASE / "achados_amazon.json"
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

def main():
    print("=" * 60)
    print("  CRIBA · UNIFICADOR DE ACHADOS DO DIA")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    items_ml = cargar_items(FILE_ML)
    items_amz = cargar_items(FILE_AMZ)

    print(f"  • Achados ML:     {len(items_ml)}")
    print(f"  • Achados Amazon: {len(items_amz)}")

    todos = items_ml + items_amz
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
    max_achados = int(os.environ.get("MAX_ACHADOS", "600"))

    vistos = set()
    validos = []
    descartados_desc = 0

    for it in todos:
        u = it.get("url", "")
        loja = it.get("loja", "")
        desc = float(it.get("desc_pct") or 0)
        exp = it.get("expira_em", "")

        # 1. Filtro de expiración
        if exp and exp <= ahora_iso:
            continue

        # 2. Filtro de descuento mínimo (por tienda)
        desc_min = desc_min_az if "Amazon" in loja else desc_min_ml
        if desc < desc_min:
            descartados_desc += 1
            continue

        # 3. Regla de Oro estricta
        if "Amazon" in loja:
            if "amazon.com.br" not in u or f"tag={AMAZON_TAG}" not in u:
                continue
        elif "Mercado Livre" in loja:
            if "meli.la" not in u and ("mercadolivre.com.br" not in u or ML_TAG not in u):
                continue
        else:
            # Descartar cualquier otra tienda no aprobada
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
    otros = [x for x in validos if "Mercado" not in (x.get("loja") or "")
             and "Amazon" not in (x.get("loja") or "")]

    seleccionados = []
    i = j = 0
    while len(seleccionados) < max_achados and (i < len(ml) or j < len(az)):
        if i < len(ml):
            seleccionados.append(ml[i])
            i += 1
        if j < len(az) and len(seleccionados) < max_achados:
            seleccionados.append(az[j])
            j += 1
    if len(seleccionados) < max_achados:
        seleccionados += otros[:max_achados - len(seleccionados)]

    print(f"  • Descartadas por descuento insuficiente: {descartados_desc}")
    print(f"  • Orden alternado: ML {len(ml)} | Amazon {len(az)} | otras {len(otros)}")

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
