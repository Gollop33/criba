#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Envío automático a WhatsApp via Green API
==================================================
Usa secrets de entorno: GREEN_API_ID, GREEN_API_TOKEN, WHATSAPP_CHAT_ID

Si los secrets no están configurados → salta sin error.

Uso: python enviar_whatsapp.py
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

# ─── Secrets (vía entorno o valores directos) ──────────────────────────────────
GREEN_API_ID    = os.environ.get("GREEN_API_ID", "")
GREEN_API_TOKEN = os.environ.get("GREEN_API_TOKEN", "")
WHATSAPP_CHAT_ID = os.environ.get("WHATSAPP_CHAT_ID", "")
# Formato chatId Green API:
#   Grupo:    "120363XXXXXXXXXX@g.us"
#   Contacto: "5491199999999@c.us"


# ─── Green API ────────────────────────────────────────────────────────────────

def enviar_whatsapp(mensaje, chat_id=None):
    """
    Envía un mensaje de texto a WhatsApp via Green API.
    Retorna True si OK.
    """
    iid   = GREEN_API_ID.strip()
    token = GREEN_API_TOKEN.strip()
    cid   = (chat_id or WHATSAPP_CHAT_ID).strip()

    if not iid or not token or not cid:
        print("  [WhatsApp] Secrets no configurados — saltando")
        return False

    url = f"https://api.green-api.com/waInstance{iid}/sendMessage/{token}"
    payload = {"chatId": cid, "message": mensaje}

    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200 and r.json().get("idMessage"):
            return True
        else:
            print(f"  [WhatsApp] Error {r.status_code}: {r.text[:150]}")
            return False
    except Exception as e:
        print(f"  [WhatsApp] Excepcion: {e}")
        return False


def verificar_green_api():
    """Verifica que la instancia de Green API esté activa."""
    iid   = GREEN_API_ID.strip()
    token = GREEN_API_TOKEN.strip()
    if not iid or not token:
        return False
    try:
        url = f"https://api.green-api.com/waInstance{iid}/getStateInstance/{token}"
        r = requests.get(url, timeout=10)
        state = r.json().get("stateInstance", "")
        print(f"  [WhatsApp] Estado instancia: {state}")
        return state == "authorized"
    except Exception as e:
        print(f"  [WhatsApp] Error verificando instancia: {e}")
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    from modulo_ofertas import (
        elegir_mejores_ofertas,
        formatear_mensaje,
        cargar_enviados,
        guardar_enviados,
        marcar_enviado,
    )

    print("=" * 55)
    print("  CRIBA · WhatsApp via Green API")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # Verificar configuración
    if not GREEN_API_ID or not GREEN_API_TOKEN or not WHATSAPP_CHAT_ID:
        print("  [WhatsApp] Variables GREEN_API_ID / GREEN_API_TOKEN / WHATSAPP_CHAT_ID no configuradas")
        print("  Agrega los secrets en GitHub: Settings → Secrets → Actions")
        return

    # Verificar instancia activa
    if not verificar_green_api():
        print("  [WhatsApp] Instancia no autorizada — saltando envíos")
        return

    # Leer productos
    prod_f = BASE / "productos.json"
    if not prod_f.exists():
        print("  productos.json no encontrado")
        return

    data      = json.loads(prod_f.read_text(encoding="utf-8"))
    productos = data.get("productos", [])

    # Elegir mejores ofertas
    ofertas = elegir_mejores_ofertas(productos, canal="whatsapp")
    if not ofertas:
        print("  Sin ofertas que cumplan los criterios — no se envía nada")
        return

    print(f"  Ofertas seleccionadas: {len(ofertas)}")

    enviados = cargar_enviados()
    enviados_ok = 0

    for oferta in ofertas:
        p   = oferta["producto"]
        pid = p.get("id") or p.get("nombre", "")[:40]
        msg = formatear_mensaje(oferta, modo="texto")  # WhatsApp: texto plano

        print(f"\n  Enviando: {p.get('nombre','?')[:50]}")
        print(f"  Score: {oferta['score']} | {oferta['motivo']}")

        ok = enviar_whatsapp(msg)
        if ok:
            marcar_enviado(pid, enviados, canal="whatsapp")
            enviados_ok += 1
            print(f"  ✅ Enviado a WhatsApp")
        else:
            print(f"  ❌ Fallo en envío")

        time.sleep(3)  # Anti-flood entre mensajes

    guardar_enviados(enviados)

    print()
    print("=" * 55)
    print(f"  Enviados: {enviados_ok}/{len(ofertas)}")
    print("=" * 55)


if __name__ == "__main__":
    main()
