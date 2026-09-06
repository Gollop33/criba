#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Alertas de Telegram
============================
Selecciona las mejores ofertas del día y las envía formateadas al canal/chat.

Anti-spam:
  - Máximo 5 mensajes por ejecución
  - No repetir mismo producto en 24h
  - Solo envía si hay descuento >= 20% o precio bajo vs historial

Configuración: variables de entorno TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID

Uso: python alertas_telegram.py
"""
import json, sys, io, os, time
import requests
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).parent

# ─── Configuración ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8761354869:AAGAa4nQDb_FgqU32OEWBYjF5hlMNCVybE0")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "1277930676")

PRODUCTOS_JSON  = BASE / "productos.json"
ESTADO_ANTERIOR = BASE / "estado_alertas.json"   # compatibilidad legacy


# ─── Envío Telegram ───────────────────────────────────────────────────────────

def enviar_telegram(mensaje, parse_mode="HTML"):
    """Envía mensaje al chat de Telegram. Retorna True si OK."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     mensaje,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": True,
        }, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False


# ─── Guardar estado legacy ───────────────────────────────────────────────────

def _guardar_estado_previo(productos):
    """Mantiene compatibilidad con el estado anterior de precios."""
    estado = {p["nombre"]: p.get("vista", {}).get("precio", 0) for p in productos}
    ESTADO_ANTERIOR.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    from modulo_ofertas import (
        elegir_mejores_ofertas,
        formatear_mensaje,
        cargar_enviados,
        guardar_enviados,
        marcar_enviado,
    )

    print("=" * 55)
    print("  CRIBA · Alertas Telegram")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # Validar token
    if not TELEGRAM_BOT_TOKEN or "PEGA_TU" in TELEGRAM_BOT_TOKEN:
        print("  [Telegram] Token no configurado — saltando")
        return

    # Leer productos
    if not PRODUCTOS_JSON.exists():
        print("  productos.json no encontrado — ejecuta bot_precios.py primero")
        return

    try:
        data      = json.loads(PRODUCTOS_JSON.read_text(encoding="utf-8"))
        productos = data.get("productos", [])
    except Exception as e:
        print(f"  Error leyendo productos.json: {e}")
        return

    # Seleccionar mejores ofertas (con anti-spam automático)
    ofertas = elegir_mejores_ofertas(productos, canal="telegram")

    if not ofertas:
        print("  Sin ofertas que cumplan los criterios — no se envía nada")
        _guardar_estado_previo(productos)
        return

    print(f"  Ofertas seleccionadas: {len(ofertas)}")

    enviados    = cargar_enviados()
    enviados_ok = 0

    for oferta in ofertas:
        p   = oferta["producto"]
        pid = p.get("id") or p.get("nombre", "")[:40]
        msg = formatear_mensaje(oferta, modo="html")  # Telegram: HTML

        print(f"\n  Enviando: {p.get('nombre','?')[:50]}")
        print(f"  Score: {oferta['score']} | {oferta['motivo']}")

        ok = enviar_telegram(msg)
        if ok:
            marcar_enviado(pid, enviados, canal="telegram")
            enviados_ok += 1
            print("  Enviado a Telegram")
        else:
            print("  Fallo en envio Telegram")

        time.sleep(2)  # Anti-flood

    guardar_enviados(enviados)
    _guardar_estado_previo(productos)

    print()
    print("=" * 55)
    print(f"  Enviados: {enviados_ok}/{len(ofertas)}")
    print("=" * 55)


if __name__ == "__main__":
    main()
