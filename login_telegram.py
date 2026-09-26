#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Login de Telegram (login_telegram.py)
==============================================
Se ejecuta UNA SOLA VEZ en tu ordenador. Abre sesión como tú en Telegram y
guarda una "session string" que después usa el bot en GitHub Actions.

¿Por qué hace falta?
--------------------
Para LEER el canal de afiliados de Mercado Livre hay que entrar como usuario:
un bot no puede, porque no eres administrador de ese canal. La API de cliente
(Telethon) sí.

La session string es como una contraseña de tu cuenta: trátala igual. Va a
GitHub Secrets, nunca a un archivo del repo.

Instalación:
    pip install telethon

Uso:
    python login_telegram.py

Te pedirá el teléfono (con código de país, ej. +55...) y el código que te llega
por Telegram. Al terminar, imprime la session string: cópiala y pégala en
GitHub → Settings → Secrets and variables → Actions → New secret:
    Nombre:  TELEGRAM_SESSION
    Valor:   (lo que imprimió)
"""

import asyncio
import os
import sys
from pathlib import Path

# Cargar .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

API_ID = os.environ.get("TELEGRAM_API_ID", "").strip()
API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()


async def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("Falta Telethon. Instálalo con:  pip install telethon")
        return 1

    if not API_ID or not API_HASH:
        print("Faltan TELEGRAM_API_ID y TELEGRAM_API_HASH en .env")
        return 1

    print("=" * 68)
    print("  CRIBA · LOGIN DE TELEGRAM (una sola vez)")
    print("=" * 68)
    print("  Te va a pedir el teléfono y un código. El código llega por Telegram.")
    print()

    async with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
        yo = await client.get_me()
        print()
        print(f"  Sesión iniciada como: {yo.first_name or ''} "
              f"(@{yo.username}) id={yo.id}")
        session = client.session.save()

        print()
        print("=" * 68)
        print("  TU SESSION STRING (cópiala tal cual, es larga):")
        print("=" * 68)
        print(session)
        print("=" * 68)
        print()
        print("  Pégala en GitHub → Settings → Secrets and variables → Actions")
        print("  Nombre del secret:  TELEGRAM_SESSION")
        print()

        # Guardarla también en .env local para probar sin volver a loguearse
        p = Path(__file__).parent / ".env"
        try:
            t = p.read_text(encoding="utf-8-sig")
            if "TELEGRAM_SESSION=" not in t:
                if not t.endswith("\n"):
                    t += "\n"
                t += f"TELEGRAM_SESSION={session}\n"
                p.write_text(t, encoding="utf-8")
                print("  (también la guardé en tu .env local para que puedas probar)")
        except Exception as e:
            print(f"  aviso: no se pudo guardar en .env: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
