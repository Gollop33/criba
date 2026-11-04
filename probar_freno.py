#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Prueba del freno anti-repetición (probar_freno.py)
===========================================================
Valida el freno nuevo (120h / 10% contra precio_min_publicado) contra el
historial REAL de publicaciones (logs/enviados.json).

Escenarios:
  A. Los productos publicados 4-7 veces deben quedar BLOQUEADOS mientras estén
     dentro de la ventana de 120h y sin una caída real de precio.
  B. Una caída real nueva (precio >= 10% por debajo del mínimo publicado) debe
     seguir publicándose, incluso dentro de la ventana de 120h.

Uso: python probar_freno.py
"""
import io
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
ENVIADOS = BASE / "logs" / "enviados.json"

from gerar_fila_posts import (repeticion_permitida, HORAS_MIN_REPETIR,
                              MEJORA_MIN_PCT, _horas_desde)


def _minimo(e):
    m = e.get("precio_min_publicado")
    try:
        m = float(m) if m is not None else float(e.get("precio"))
    except (TypeError, ValueError):
        m = 0.0
    return m


def main():
    enviados = json.loads(ENVIADOS.read_text(encoding="utf-8-sig"))

    # Productos publicados 4-7 veces (el universo de "repetidos" del plan)
    repetidos = {
        pid: e for pid, e in enviados.items()
        if isinstance(e, dict) and 4 <= len(e.get("precios_publicados") or []) <= 7
    }

    print("=" * 72)
    print("  PRUEBA DEL FRENO ANTI-REPETICIÓN")
    print(f"  HORAS_MIN_REPETIR = {HORAS_MIN_REPETIR:.0f}h | "
          f"MEJORA_MIN_PCT = {MEJORA_MIN_PCT*100:.0f}% | base = precio_min_publicado")
    print(f"  Productos publicados 4-7 veces en el historial real: {len(repetidos)}")
    print("=" * 72)

    # ── A. Freno sobre el historial real, sin caída (precio actual = mínimo) ──
    bloqueados = 0
    readmitidos_fuera_ventana = 0
    readmitidos_indebidos = 0
    for pid, e in repetidos.items():
        minimo = _minimo(e)
        if minimo <= 0:
            continue
        permitido, motivo = repeticion_permitida(pid, minimo, enviados)
        horas = _horas_desde(e.get("ts"))
        if permitido:
            if horas is not None and horas >= HORAS_MIN_REPETIR:
                readmitidos_fuera_ventana += 1   # correcto: ya pasó la ventana
            else:
                readmitidos_indebidos += 1       # fallo: dentro de ventana sin caída
                print(f"    ⚠️ READMITIDO indebido: {pid[:48]} -> {motivo}")
        else:
            bloqueados += 1

    print(f"\n[A] Sin caída de precio (precio actual = mínimo publicado):")
    print(f"    bloqueados (dentro de 120h):      {bloqueados}")
    print(f"    readmitidos (fuera de 120h, OK):  {readmitidos_fuera_ventana}")
    print(f"    readmitidos INDEBIDOS:            {readmitidos_indebidos}")

    # ── B. Determinista: caída real nueva debe publicar (dentro de la ventana) ──
    ahora = datetime.now(timezone.utc)
    sintetico = {
        "ml-test-freno": {
            "ts": (ahora - timedelta(hours=1)).isoformat(timespec="seconds"),
            "precio": 100.0,
            "precio_min_publicado": 100.0,
            "precios_publicados": [110.0, 105.0, 100.0, 100.0],
        }
    }

    # B1: sin caída (precio = mínimo) -> debe bloquear
    ok_sin_caida, m_sin = repeticion_permitida("ml-test-freno", 100.0, sintetico)
    # B2: caída real de -15% -> debe publicar
    ok_con_caida, m_con = repeticion_permitida("ml-test-freno", 85.0, sintetico)
    # B3: caída marginal de -5% (< 10%) -> debe bloquear
    ok_caida_corta, m_corta = repeticion_permitida("ml-test-freno", 95.0, sintetico)

    print(f"\n[B] Caso determinista (enviado hace 1h, mínimo publicado R$ 100):")
    print(f"    sin caída (R$ 100): {'READMITIDO' if ok_sin_caida else 'BLOQUEADO'} -> {m_sin}")
    print(f"    caída -15% (R$ 85): {'READMITIDO' if ok_con_caida else 'BLOQUEADO'} -> {m_con}")
    print(f"    caída -5%  (R$ 95): {'READMITIDO' if ok_caida_corta else 'BLOQUEADO'} -> {m_corta}")

    # ── Verificación final ──
    ok = (readmitidos_indebidos == 0) and (not ok_sin_caida) and ok_con_caida and (not ok_caida_corta)
    print("\n" + "=" * 72)
    if ok:
        print("  RESULTADO: OK — 0 republicaciones indebidas dentro de 120h/10%,")
        print("             y la caída real nueva (-15%) sí publica.")
    else:
        print("  RESULTADO: FALLO — revisar los casos marcados arriba.")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
