#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Test de Envío a WhatsApp via Green API (test_whatsapp.py)
"""
import os
import sys
import io
import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path

BASE = Path(__file__).parent
_env_file = BASE / ".env"
if _env_file.exists():
    try:
        for line in _env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

GREEN_API_ID = os.environ.get("GREEN_API_ID", "").strip()
GREEN_API_TOKEN = os.environ.get("GREEN_API_TOKEN", "").strip()
WHATSAPP_CHAT_ID = os.environ.get("WHATSAPP_CHAT_ID", "").strip()

def test_envio():
    print("=" * 60)
    print("  TEST GREEN API - ACHADINHOS NO ZAP")
    print(f"  Instance ID: {GREEN_API_ID or '[NO CONFIGURADO]'}")
    print(f"  Chat ID:     {WHATSAPP_CHAT_ID or '[NO CONFIGURADO]'}")
    print("=" * 60)

    if not GREEN_API_ID or not GREEN_API_TOKEN or not WHATSAPP_CHAT_ID:
        print("  ❌ ERROR: Faltan variables de entorno requeridas:")
        if not GREEN_API_ID:
            print("     - GREEN_API_ID no está configurado.")
        if not GREEN_API_TOKEN:
            print("     - GREEN_API_TOKEN no está configurado.")
        if not WHATSAPP_CHAT_ID:
            print("     - WHATSAPP_CHAT_ID no está configurado.")
        print("  Configura estas variables en tu entorno o en GitHub Secrets.")
        return False

    url_estado = f"https://api.green-api.com/waInstance{GREEN_API_ID}/getStateInstance/{GREEN_API_TOKEN}"
    try:
        r = requests.get(url_estado, timeout=15)
        st = r.json().get("stateInstance")
        print(f"  [1] Estado de la instancia: {st} (HTTP {r.status_code})")
        if st != "authorized":
            print("  ❌ La instancia no está autorizada.")
            return False
    except Exception as e:
        print(f"  ❌ Error conectando a Green API: {e}")
        return False

    url_send = f"https://api.green-api.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
    payload = {
        "chatId": WHATSAPP_CHAT_ID,
        "message": "🔥 Test - Bot de Achadinhos no Zap funcionando!"
    }

    try:
        r = requests.post(url_send, json=payload, timeout=20)
        print(f"  [2] Envío de mensaje: HTTP {r.status_code}")
        if r.status_code == 200 and r.json().get("idMessage"):
            print(f"  ✅ Mensaje enviado exitosamente! ID: {r.json().get('idMessage')}")
            return True
        else:
            print(f"  ❌ Error al enviar: {r.text}")
            return False
    except Exception as e:
        print(f"  ❌ Excepción enviando mensaje: {e}")
        return False

if __name__ == "__main__":
    ok = test_envio()
    sys.exit(0 if ok else 1)
