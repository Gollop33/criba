#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Shopee Brasil (agente_shopee.py)
================================================
Cosecha ofertas y cupones de Shopee Brasil:
https://affiliate.shopee.com.br/

ESTADO ACTUAL:
- Pendiente de aprobación de cuenta de afiliado.
- REGLA DE ORO: No publica ningún producto ni link de Shopee hasta que
  el usuario configure su tag/ID de afiliado en config_afiliados.json
  y agregue "shopee" a "tiendas_que_pagan".

Cuando esté aprobado:
1. Poner tu App ID / Secret o Link corto en config_afiliados.json -> shopee
2. Agregar "shopee" a "tiendas_que_pagan"
"""
import json, sys, io
from pathlib import Path

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config_afiliados.json"
OUTPUT_FILE = BASE / "achados_shopee.json"

def esta_habilitado():
    if not CONFIG_FILE.exists():
        return False
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        pagam = cfg.get("tiendas_que_pagan", [])
        shopee_cfg = cfg.get("shopee", {})
        shopee_id = shopee_cfg.get("id", "")
        if "shopee" in pagam and shopee_id and not shopee_id.startswith("PON_"):
            return True
    except Exception:
        pass
    return False

def main():
    print("=" * 60)
    print("  CRIBA · AGENTE SHOPEE BRASIL")
    print("=" * 60)
    if not esta_habilitado():
        print("  [Shopee] Estado: PENDIENTE DE APROBACIÓN.")
        print("  [Regla de Oro] Shopee no está en 'tiendas_que_pagan' con ID activo.")
        print("  Para activar: Regístrate en https://affiliate.shopee.com.br/,")
        print("  agrega tu ID en config_afiliados.json y agrega 'shopee' a 'tiendas_que_pagan'.")
        # Generar archivo vacio para consistencia
        OUTPUT_FILE.write_text(json.dumps({"actualizado": "", "achados": []}), encoding="utf-8")
        return

    print("  [Shopee] Módulo de afiliados activo. Cosechando...")
    # Aquí se ejecutará la extracción de ofertas Shopee una vez aprobada la cuenta

if __name__ == "__main__":
    main()
