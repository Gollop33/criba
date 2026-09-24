#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Transformador Automático de Campañas de Afiliados (transformar_campana.py)
================================================================================
Toma cualquier texto con enlaces de bit.ly o listas de cupones de Telegram/WhatsApp
y reemplaza TODOS los enlaces por tus enlaces oficiales meli.la con tu tag.

Uso:
  python transformar_campana.py [--enviar]
  (Lee de 'campana_hoy.txt' o del portapapeles)
"""

import os
import re
import sys
import io
import urllib.parse
from pathlib import Path
import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
TXT_CAMPANA = BASE / "campana_hoy.txt"
ENV_FILE = BASE / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

from melila_api import generar_melila

def resolver_url_real(url_corta):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0"}
    try:
        r = requests.get(url_corta, headers=headers, allow_redirects=True, timeout=15)
        dest = r.url
        if "go=" in dest:
            parsed = urllib.parse.urlparse(dest)
            qs = urllib.parse.parse_qs(parsed.query)
            return qs.get("go", [dest])[0]
        return dest
    except Exception:
        return url_corta

def procesar_texto_campana(texto, cookie, tag="ja20250119201346"):
    # Encontrar todas las URLs (bit.ly o mercadolivre)
    urls = re.findall(r"https?://(?:bit\.ly/\S+|[\w.-]*mercadolivre\.com\.br/\S+)", texto)
    nuevo_texto = texto

    for u in set(urls):
        url_limpia = u.rstrip(".,;!)\"'>")
        print(f"  [Procesando link] {url_limpia}...")
        url_real = resolver_url_real(url_limpia)
        short_melila = generar_melila(url_real, cookie_str=cookie, tag=tag)
        if short_melila:
            print(f"    -> meli.la generado: {short_melila}")
            nuevo_texto = nuevo_texto.replace(url_limpia, short_melila)
        else:
            print(f"    [!] Fallo generando meli.la, manteniendo original.")

    if "anúncio" not in nuevo_texto.lower():
        nuevo_texto = nuevo_texto.strip() + "\n\nanúncio"

    return nuevo_texto

def main():
    print("=" * 60)
    print("  CRIBA · TRANSFORMADOR DE CAMPAÑAS A MELI.LA OFICIAL")
    print("=" * 60)

    cookie = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if not cookie:
        print("  ❌ ERROR: No se encontró ML_PORTAL_COOKIE en .env")
        return

    texto = ""
    if TXT_CAMPANA.exists():
        texto = TXT_CAMPANA.read_text(encoding="utf-8").strip()

    if not texto:
        print(f"  Pega el texto de la campaña en '{TXT_CAMPANA.name}' y ejecuta de nuevo.")
        print("  O escribe/pega el texto aquí y presiona Ctrl+Z (Enter):")
        try:
            texto = sys.stdin.read().strip()
        except Exception:
            return

    if not texto:
        return

    resultado = procesar_texto_campana(texto, cookie)

    print("\n" + "=" * 60)
    print("  MENSAJE RESULTANTE CON TUS LINKS MELI.LA:")
    print("=" * 60)
    print(resultado)
    print("=" * 60)

    if "--enviar" in sys.argv:
        from enviar_whatsapp import enviar_whatsapp
        print("\n  Enviando directamente a WhatsApp...")
        ok = enviar_whatsapp(resultado)
        if ok:
            print("  ✅ Enviado con éxito a tu grupo!")
        else:
            print("  ❌ Error enviando a WhatsApp.")

if __name__ == "__main__":
    main()
