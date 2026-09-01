#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Alertas de Telegram
Lee productos.json, compara con el estado anterior,
y avisa por Telegram cuando un precio baja.

Configuración:
  1. Busca @BotFather en Telegram → /newbot → copia el TOKEN
  2. Busca @userinfobot en Telegram → /start → copia tu CHAT ID
  3. Pega ambos abajo, o usa variables de entorno (recomendado para GitHub Actions)

Uso: python alertas_telegram.py
"""
import json, sys, io, os
import requests
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ══════════ CONFIGURACIÓN ══════════
# Usa variables de entorno (GitHub Actions) o pega tus valores directamente
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8761354869:AAGAa4nQDb_FgqU32OEWBYjF5hlMNCVybE0")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "1277930676")

BASE             = Path(__file__).parent
PRODUCTOS_JSON   = BASE / "productos.json"
ESTADO_ANTERIOR  = BASE / "estado_alertas.json"
# ═══════════════════════════════════

def enviar_telegram(mensaje):
    """Envía un mensaje formateado en HTML a tu chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        return False

def cargar_estado_previo():
    """Lee el último estado conocido de precios."""
    if ESTADO_ANTERIOR.exists():
        try:
            return json.loads(ESTADO_ANTERIOR.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def guardar_estado(estado):
    ESTADO_ANTERIOR.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def fmt(n):
    """Formatea número como moneda brasileña."""
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def main():
    # Validar token configurado
    if "PEGA_TU" in TELEGRAM_BOT_TOKEN or "PEGA_TU" in TELEGRAM_CHAT_ID:
        print("=" * 50)
        print("CONFIGURA TU BOT DE TELEGRAM:")
        print("1. Abre Telegram y busca @BotFather")
        print("2. Envia /newbot y sigue las instrucciones")
        print("3. Copia el token y pegalo en este archivo")
        print("4. Busca @userinfobot, envia /start")
        print("5. Copia tu chat ID y pegalo en este archivo")
        print("=" * 50)
        return

    # Leer productos.json
    try:
        data = json.loads(PRODUCTOS_JSON.read_text(encoding="utf-8"))
        productos = data["productos"]
        actualizado = data.get("actualizado", "")
    except FileNotFoundError:
        print("No se encontro productos.json — ejecuta primero: python bot_precios.py")
        return
    except Exception as e:
        print(f"Error leyendo productos.json: {e}")
        return

    estado_previo = cargar_estado_previo()
    estado_nuevo = {}
    alertas = []

    for p in productos:
        nombre = p["nombre"]
        precio_actual = p["vista"]["precio"]
        tienda = p["vista"]["tienda"]
        url = p["vista"]["url"]
        cupon = p["vista"].get("cupon")
        tiene_pix = p["vista"].get("pix", False)
        parcelado = p.get("parcelado")

        estado_nuevo[nombre] = precio_actual

        # Comparar con estado anterior
        if nombre in estado_previo:
            precio_previo = estado_previo[nombre]
            if precio_actual < precio_previo - 0.01:  # bajó
                ahorro = precio_previo - precio_actual
                pct = round((ahorro / precio_previo) * 100, 1)

                msg = (
                    f"<b>BAJADA DE PRECIO</b>\n\n"
                    f"<b>{nombre}</b>\n"
                    f"<b>R$ {fmt(precio_actual)}</b> a vista"
                )
                if tiene_pix:
                    msg += " (Pix)"
                if cupon:
                    msg += f"\nCupon: <code>{cupon}</code>"
                msg += f"\n<s>R$ {fmt(precio_previo)}</s> → ahorro R$ {fmt(ahorro)} ({pct}%)"
                if parcelado:
                    msg += f"\nOu {parcelado['cuotas']}x R$ {fmt(parcelado['cuota'])} sem juros"
                msg += f"\n\n{tienda}\n{url}"

                alertas.append(msg)

            elif precio_actual > precio_previo + 0.01:  # subió
                print(f"  [info] {nombre}: subio de R$ {fmt(precio_previo)} a R$ {fmt(precio_actual)}")

        else:
            # Producto nuevo — aviso informativo
            msg = (
                f"<b>NUEVO PRODUCTO EN RADAR</b>\n\n"
                f"<b>{nombre}</b>\n"
                f"<b>R$ {fmt(precio_actual)}</b> a vista"
            )
            if tiene_pix:
                msg += " (Pix)"
            if cupon:
                msg += f"\nCupon: <code>{cupon}</code>"
            if parcelado:
                msg += f"\nOu {parcelado['cuotas']}x R$ {fmt(parcelado['cuota'])} sem juros"
            msg += f"\n\n{tienda}\n{url}"
            alertas.append(msg)

    # Enviar alertas
    if alertas:
        separador = "\n\n" + "─" * 20 + "\n\n"
        mensaje_completo = separador.join(alertas)
        # Telegram limita a 4096 chars por mensaje
        if len(mensaje_completo) > 4000:
            # Enviar una por una si es muy largo
            ok = 0
            for a in alertas:
                if enviar_telegram(a):
                    ok += 1
            print(f"{ok}/{len(alertas)} alertas enviadas por Telegram")
        else:
            ok = enviar_telegram(mensaje_completo)
            print(f"{'OK' if ok else 'ERROR'} — {len(alertas)} alertas enviadas")
    else:
        print("Sin bajadas de precio en esta ejecucion")

    # Guardar estado para la próxima comparación
    guardar_estado(estado_nuevo)
    print(f"Estado guardado: {len(estado_nuevo)} productos rastreados")

if __name__ == "__main__":
    main()
