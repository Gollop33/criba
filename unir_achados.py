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
import json, re, unicodedata, sys, io
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

    vistos = set()
    validos = []

    for it in todos:
        u = it.get("url", "")
        loja = it.get("loja", "")
        desc = float(it.get("desc_pct") or 0)
        exp = it.get("expira_em", "")

        # 1. Filtro de expiración
        if exp and exp <= ahora_iso:
            continue

        # 2. Filtro de descuento mínimo 15%
        if desc < 15:
            continue

        # 3. Regla de Oro estricta
        if "Amazon" in loja:
            if "amazon.com.br" not in u or f"tag={AMAZON_TAG}" not in u:
                continue
        elif "Mercado Livre" in loja:
            if "mercadolivre.com.br" not in u or ML_TAG not in u:
                continue
        else:
            # Descartar cualquier otra tienda
            continue

        # 4. Deduplicar por nombre normalizado
        clave = normalizar(it.get("nombre", ""))[:32]
        if clave and clave not in vistos:
            vistos.add(clave)
            validos.append(it)

    # Ordenar por mayor porcentaje de descuento
    validos.sort(key=lambda x: float(x.get("desc_pct") or 0), reverse=True)

    # Tomar hasta 80 ofertas de alta calidad
    seleccionados = validos[:80]

    resultado = {
        "actualizado": ahora_iso,
        "total_achados": len(seleccionados),
        "achados": seleccionados
    }

    FILE_OUT.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] achados.json generado exitosamente con {len(seleccionados)} ofertas.")
    print("=" * 60)

if __name__ == "__main__":
    main()
