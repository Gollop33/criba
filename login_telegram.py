#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Login de Telegram SIN escribir en la consola (login_telegram.py)
=========================================================================
Pensado para Windows, donde la consola puede congelarse al hacer clic dentro
(Modo de edición rápida / QuickEdit) y entonces parece que no deja pegar el
código ni escribir la contraseña. En realidad el programa está PAUSADO: se
desbloquea pulsando Esc.

Aquí todo se hace desde el archivo .env con el Bloc de notas. Son DOS pasos y
en ninguno hay que teclear en la ventana negra.

── PASO 1 ───────────────────────────────────────────────────────────────────
Abre .env con el Bloc de notas y añade tu teléfono:

    TELEGRAM_TELEFONO=+5511999999999

Ejecuta (doble clic en LOGIN_TELEGRAM.bat):

    python login_telegram.py

Te llega un código a TU Telegram (no por SMS normalmente) y el script termina
diciéndote que pongas ese código en .env.

── PASO 2 ───────────────────────────────────────────────────────────────────
Añade el código al .env:

    TELEGRAM_CODE=12345

Si tienes verificación en dos pasos, añade también:

    TELEGRAM_PASSWORD=tu_contrasena

Vuelve a ejecutar el script. Ahora inicia sesión y escribe la SESSION STRING en:
  - el archivo  telegram_session.txt   (ábrelo con el Bloc de notas y copia)
  - y en tu .env como TELEGRAM_SESSION

telegram_session.txt es lo que pegas en GitHub → Settings → Secrets and
variables → Actions con el nombre TELEGRAM_SESSION.

Modo clásico interactivo (si tu consola va bien):
    python login_telegram.py --interactivo
"""

import asyncio
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent
ENV = BASE / ".env"
ESTADO = BASE / ".telegram_login.json"
SALIDA = BASE / "telegram_session.txt"


def cargar_env():
    env = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
                os.environ.setdefault(k.strip(), env[k.strip()])
    return env


def set_env(clave, valor):
    """Añade o reemplaza una clave en .env conservando el resto."""
    lineas = ENV.read_text(encoding="utf-8-sig").splitlines() if ENV.exists() else []
    salida, hecho = [], False
    for ln in lineas:
        if ln.strip().startswith(f"{clave}="):
            salida.append(f"{clave}={valor}")
            hecho = True
        else:
            salida.append(ln)
    if not hecho:
        salida.append(f"{clave}={valor}")
    ENV.write_text("\n".join(salida) + "\n", encoding="utf-8")


def marco(*lineas):
    print("=" * 70)
    for l in lineas:
        print(l)
    print("=" * 70)


async def interactivo(api_id, api_hash):
    """Flujo clásico: tecleando en la consola."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    print("Modo interactivo. Si la ventana se congela al hacer clic, pulsa Esc.")
    async with TelegramClient(StringSession(), api_id, api_hash) as c:
        yo = await c.get_me()
        session = c.session.save()
        marco(f"  Sesión iniciada como {yo.first_name or ''} (@{yo.username})")
        SALIDA.write_text(session, encoding="utf-8")
        set_env("TELEGRAM_SESSION", session)
        print(f"  Guardada en {SALIDA.name} y en .env (TELEGRAM_SESSION)")
        print(session)
    return 0


async def paso_a_paso(api_id, api_hash, env):
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession

    telefono = (env.get("TELEGRAM_TELEFONO") or "").strip()
    code = (env.get("TELEGRAM_CODE") or "").strip()
    password = (env.get("TELEGRAM_PASSWORD") or "").strip()

    if not telefono:
        marco("  FALTA EL TELEFONO",
              "",
              "  Abre el archivo .env con el Bloc de notas y añade:",
              "",
              "      TELEGRAM_TELEFONO=+5511999999999",
              "",
              "  (con código de país, sin espacios ni guiones).",
              "  Luego vuelve a ejecutar este script.")
        return 1

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        yo = await client.get_me()
        session = client.session.save()
        SALIDA.write_text(session, encoding="utf-8")
        set_env("TELEGRAM_SESSION", session)
        marco(f"  Ya había sesión como {yo.first_name or ''} (@{yo.username})",
              f"  Guardada en {SALIDA.name} y en .env (TELEGRAM_SESSION)")
        print(session)
        await client.disconnect()
        return 0

    # ── PASO 1: pedir el código ──────────────────────────────────────────────
    if not code:
        try:
            enviado = await client.send_code_request(telefono)
        except Exception as e:
            marco("  NO SE PUDO ENVIAR EL CÓDIGO", f"  {e}")
            await client.disconnect()
            return 1
        ESTADO.write_text(json.dumps(
            {"phone_code_hash": enviado.phone_code_hash, "telefono": telefono},
            ensure_ascii=False), encoding="utf-8")
        await client.disconnect()
        marco("  CODIGO ENVIADO",
              "",
              "  Telegram te acaba de mandar un mensaje con el código.",
              "  Míralo en la APP o en web.telegram.org (normalmente NO por SMS).",
              "",
              "  AHORA, sin tocar la ventana negra:")
        print("    1. Abre el archivo .env con el Bloc de notas")
        print("    2. Añade esta línea con el código que te llegó:")
        print()
        print("           TELEGRAM_CODE=12345")
        print()
        if "TELEGRAM_PASSWORD" not in env:
            print("    3. Si tienes verificación en dos pasos, añade también:")
            print()
            print("           TELEGRAM_PASSWORD=tu_contrasena")
            print()
        print("    4. Guarda el .env y ejecuta OTRA VEZ este script")
        return 0

    # ── PASO 2: firmar con el código ─────────────────────────────────────────
    hash_guardado = ""
    if ESTADO.exists():
        try:
            hash_guardado = json.loads(ESTADO.read_text(encoding="utf-8")).get(
                "phone_code_hash", "")
        except Exception:
            hash_guardado = ""

    try:
        await client.sign_in(telefono, code, phone_code_hash=hash_guardado or None)
    except SessionPasswordNeededError:
        if not password:
            await client.disconnect()
            marco("  FALTA LA CONTRASEÑA DE 2 PASOS",
                  "",
                  "  Tu cuenta tiene verificación en dos pasos activada.",
                  "  Añade al .env:",
                  "",
                  "      TELEGRAM_PASSWORD=tu_contrasena",
                  "",
                  "  y vuelve a ejecutar este script.")
            return 1
        try:
            await client.sign_in(password=password)
        except Exception as e:
            await client.disconnect()
            marco("  CONTRASEÑA INCORRECTA", f"  {e}")
            return 1
    except Exception as e:
        await client.disconnect()
        marco("  NO SE PUDO INICIAR SESIÓN",
              f"  {e}",
              "",
              "  Si el código caducó, borra la línea TELEGRAM_CODE del .env",
              "  y vuelve a ejecutar para pedir uno nuevo.")
        return 1

    yo = await client.get_me()
    session = client.session.save()
    SALIDA.write_text(session, encoding="utf-8")
    set_env("TELEGRAM_SESSION", session)
    try:
        ESTADO.unlink()
    except Exception:
        pass
    await client.disconnect()

    marco(f"  LISTO. Sesión iniciada como {yo.first_name or ''} (@{yo.username})",
          "",
          f"  1) La SESSION STRING está en el archivo:  {SALIDA.name}",
          "     Ábrelo con el Bloc de notas y copia TODO el contenido.",
          "",
          "  2) Pégala en GitHub → Settings → Secrets and variables → Actions",
          "     Nombre del secret:  TELEGRAM_SESSION")
    print()
    print(session)
    return 0


def main():
    env = cargar_env()
    api_id = (env.get("TELEGRAM_API_ID") or "").strip()
    api_hash = (env.get("TELEGRAM_API_HASH") or "").strip()
    if not api_id or not api_hash:
        marco("  Faltan TELEGRAM_API_ID y TELEGRAM_API_HASH en .env")
        return 1

    try:
        import telethon  # noqa: F401
    except ImportError:
        marco("  Falta Telethon", "  Instálalo con:  pip install telethon")
        return 1

    if "--interactivo" in sys.argv:
        return asyncio.run(interactivo(int(api_id), api_hash))
    return asyncio.run(paso_a_paso(int(api_id), api_hash, env))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelado.")
        sys.exit(1)
