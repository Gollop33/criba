#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Asistente para obtener el token de Mercado Livre
=========================================================
Te guía paso a paso para conseguir el ML_ACCESS_TOKEN y el ML_REFRESH_TOKEN.

── POR QUÉ HACE FALTA ───────────────────────────────────────────────────────
Sin token, Mercado Livre bloquea TODO (medido):
  - GET api.mercadolibre.com/items/MLB...  -> 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES
  - La ficha del producto es JavaScript: 41 KB sin datos, "pix" aparece 0 veces
  - La API de afiliados solo expone /user/tags; /user/coupons -> 404
Por eso el bot nunca pudo verificar el Pix ni el cupón real.

── LA TRAMPA DEL PROCESO ────────────────────────────────────────────────────
Mercado Livre usa OAuth2: la app no da el token directamente, hay que AUTORIZAR
en el navegador y ML devuelve un `code` en la URL de retorno, que caduca en
10 minutos. Este script hace esa parte fácil: te da la URL, tú la abres, pegas
el code de vuelta y aquí se cambia por los tokens.

── USO ──────────────────────────────────────────────────────────────────────
    python obtener_token_ml.py --paso1        # crea la app y te da la URL
    python obtener_token_ml.py --code XXXX    # cambia el code por los tokens
    python obtener_token_ml.py --renovar      # renueva (el token dura 6 h)
    python obtener_token_ml.py --estado       # ¿el token sigue vivo?

Una vez guardado, `subir_secrets.py` los sube a GitHub y el bot los usa.
"""

import io
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
ENV = BASE / ".env"
TOKEN_CACHE = BASE / ".ml_token.json"

AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

# Scopes que necesita el bot: leer items y productos del catálogo.
# `offline_access` es OBLIGATORIO para recibir refresh_token (si no, el token
# dura 6 h y no se puede renovar solo: habría que repetir todo a mano cada 6 h).
SCOPES = "offline_access read"


def leer_env():
    d = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip("'\"")
    return d


def guardar_env(clave, valor):
    """Escribe/actualiza una clave del .env sin tocar las demás."""
    lineas = []
    encontrada = False
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith(f"{clave}="):
                lineas.append(f"{clave}={valor}")
                encontrada = True
            else:
                lineas.append(line)
    if not encontrada:
        lineas.append(f"{clave}={valor}")
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def guardar_cache(tokens):
    """Guarda los tokens con su caducidad para saber cuándo renovar."""
    datos = dict(tokens)
    datos["obtenido_en"] = int(time.time())
    if "expires_in" in tokens:
        datos["expira_en"] = int(time.time()) + int(tokens["expires_in"])
    TOKEN_CACHE.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def probar_token(token):
    """Comprueba el token contra la API: la prueba de fuego."""
    try:
        import requests
    except ImportError:
        return None, "falta requests"
    try:
        r = requests.get("https://api.mercadolibre.com/users/me",
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 200:
            d = r.json()
            return d, (f"usuario {d.get('nickname')} (id {d.get('id')}) "
                       f"site {d.get('site_id')}")
        return None, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:100]}"


def paso1():
    env = leer_env()
    app_id = env.get("ML_APP_ID", "").strip()
    redirect = env.get("ML_REDIRECT_URI", "").strip()

    print("=" * 78)
    print("  PASO 1 · CREAR LA APLICACIÓN")
    print("=" * 78)
    print("""
  1. Abre:  https://developers.mercadolivre.com.br/devcenter/
  2. Pulsa "Crear aplicación" (es GRATIS, no pide tarjeta).
  3. Rellena:
        Nombre        : CRIBA (o lo que quieras)
        Escenarios    : Escritorio / Desktop
        Redirect URI  : la que uses abajo (tiene que coincidir EXACTA)
        Tópicos       : deja lo que venga por defecto
  4. Al crearla te dará un  App ID  y un  Secret Key.
  5. Ejecuta (con tus datos):

        python obtener_token_ml.py --config <APP_ID> <SECRET_KEY> <REDIRECT_URI>

     Ejemplo de Redirect URI válida (no necesita servidor):
        https://localhost
""")
    if app_id:
        print(f"  Ya tienes configurado: ML_APP_ID={app_id}")
        print(f"  Redirect URI         : {redirect or '(falta)'}")
    print("=" * 78)
    return 0


def configurar(args):
    if len(args) < 3:
        print("  Uso: --config <APP_ID> <SECRET_KEY> <REDIRECT_URI>")
        return 1
    guardar_env("ML_APP_ID", args[0])
    guardar_env("ML_CLIENT_SECRET", args[1])
    guardar_env("ML_REDIRECT_URI", args[2])
    print("  Guardado en .env:")
    print(f"     ML_APP_ID        = {args[0]}")
    print(f"     ML_CLIENT_SECRET = {'*' * 8}{args[1][-4:]}")
    print(f"     ML_REDIRECT_URI  = {args[2]}")
    print()
    print("  Ahora ejecuta:  python obtener_token_ml.py --paso2")
    return 0


def paso2():
    env = leer_env()
    app_id = env.get("ML_APP_ID", "").strip()
    redirect = env.get("ML_REDIRECT_URI", "").strip()
    if not app_id or not redirect:
        print("  Falta configurar la app. Ejecuta primero --paso1")
        return 1

    url = (f"{AUTH_URL}?response_type=code&client_id={urllib.parse.quote(app_id)}"
           f"&redirect_uri={urllib.parse.quote(redirect, safe='')}"
           f"&scope={urllib.parse.quote(SCOPES)}")
    print("=" * 78)
    print("  PASO 2 · AUTORIZAR Y COGER EL CODE")
    print("=" * 78)
    print("""
  1. Abre esta URL en el navegador (con tu cuenta de Mercado Livre):

""")
    print(f"     {url}")
    print("""
  2. Pulsa "Permitir".
  3. El navegador te llevará a tu Redirect URI y DARÁ UN ERROR DE PÁGINA
     (es normal: no hay servidor ahí). Lo que importa es la BARRA DE DIRECCIONES.
  4. Copia el valor de  code=...  de esa URL. Se ve así:

        https://localhost/?code=TG-65f1a2b3c4d5e6f7-123456789&state=...

     El code es lo que va entre  code=  y  &  (dura 10 MINUTOS, no tardes).

  5. Pega el code aquí:

        python obtener_token_ml.py --code TG-65f1a2b3c4d5e6f7-123456789

  NOTA: el parámetro scope pide 'offline_access', que es lo que permite recibir
  el refresh_token. Sin él el token duraría solo 6 h y habría que repetir esto
  cada 6 horas a mano.
""")
    print("=" * 78)
    return 0


def canjear_code(code):
    env = leer_env()
    app_id = env.get("ML_APP_ID", "").strip()
    secret = env.get("ML_CLIENT_SECRET", "").strip()
    redirect = env.get("ML_REDIRECT_URI", "").strip()
    if not (app_id and secret and redirect):
        print("  Falta la configuración de la app (--paso1 / --config)")
        return 1

    code = code.strip()
    if "code=" in code:
        q = urllib.parse.urlparse(code).query
        code = urllib.parse.parse_qs(q).get("code", [code])[0]
    print(f"  Canjeando el code ({code[:12]}...)")

    try:
        import requests
        r = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": secret,
            "code": code,
            "redirect_uri": redirect,
        }, headers={"Accept": "application/json"}, timeout=30)
    except Exception as e:
        print(f"  ERROR de red: {e}")
        return 1

    if r.status_code != 200:
        print(f"  FALLÓ HTTP {r.status_code}: {r.text[:220]}")
        print("  Causas típicas: el code caducó (dura 10 min), ya se usó una vez,")
        print("  o el redirect_uri no coincide EXACTAMENTE con el de la app.")
        return 1

    t = r.json()
    guardar_env("ML_ACCESS_TOKEN", t.get("access_token", ""))
    if t.get("refresh_token"):
        guardar_env("ML_REFRESH_TOKEN", t["refresh_token"])
    guardar_cache(t)

    print("  ¡TOKEN CONSEGUIDO!")
    print(f"     access_token : {t.get('access_token','')[:24]}...")
    print(f"     refresh_token: {'sí' if t.get('refresh_token') else 'NO (falta offline_access)'}")
    print(f"     dura         : {t.get('expires_in', '?')} segundos "
          f"(~{int(t.get('expires_in', 0)) // 3600} h)")
    print()
    ok, det = probar_token(t.get("access_token", ""))
    print(f"  Prueba contra la API: {'OK' if ok else 'FALLO'} — {det}")
    print()
    print("  Siguiente paso:")
    print("     python subir_secrets.py     (lo sube a GitHub)")
    return 0


def renovar():
    """El token dura 6 h. Esto lo renueva con el refresh_token, sin navegador."""
    env = leer_env()
    app_id = env.get("ML_APP_ID", "").strip()
    secret = env.get("ML_CLIENT_SECRET", "").strip()
    refresh = env.get("ML_REFRESH_TOKEN", "").strip()
    if not (app_id and secret and refresh):
        print("  Faltan ML_APP_ID, ML_CLIENT_SECRET o ML_REFRESH_TOKEN.")
        print("  Si el refresh_token no existe, hay que repetir --paso2 (el scope")
        print("  'offline_access' es lo que lo genera).")
        return 1
    try:
        import requests
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": secret,
            "refresh_token": refresh,
        }, headers={"Accept": "application/json"}, timeout=30)
    except Exception as e:
        print(f"  ERROR de red: {e}")
        return 1
    if r.status_code != 200:
        print(f"  FALLÓ HTTP {r.status_code}: {r.text[:200]}")
        return 1
    t = r.json()
    guardar_env("ML_ACCESS_TOKEN", t.get("access_token", ""))
    if t.get("refresh_token"):
        guardar_env("ML_REFRESH_TOKEN", t["refresh_token"])
    guardar_cache(t)
    print(f"  Token renovado. Dura {int(t.get('expires_in', 0)) // 3600} h.")
    return 0


def estado():
    print("=" * 78)
    print("  ESTADO DEL TOKEN DE MERCADO LIVRE")
    print("=" * 78)
    env = leer_env()
    token = env.get("ML_ACCESS_TOKEN", "").strip()
    print(f"  ML_APP_ID        : {env.get('ML_APP_ID') or 'FALTA'}")
    print(f"  ML_CLIENT_SECRET : {'configurado' if env.get('ML_CLIENT_SECRET') else 'FALTA'}")
    print(f"  ML_REDIRECT_URI  : {env.get('ML_REDIRECT_URI') or 'FALTA'}")
    print(f"  ML_REFRESH_TOKEN : {'configurado' if env.get('ML_REFRESH_TOKEN') else 'FALTA'}")
    print(f"  ML_ACCESS_TOKEN  : {'configurado' if token else 'FALTA'}")
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = c.get("expira_en")
            if exp:
                restante = exp - time.time()
                if restante > 0:
                    print(f"  caduca en        : {restante / 60:.0f} min")
                else:
                    print(f"  CADUCADO hace    : {-restante / 60:.0f} min "
                          f"-> ejecuta --renovar")
        except Exception:
            pass
    if token:
        ok, det = probar_token(token)
        print()
        print(f"  Prueba real contra la API: {'OK' if ok else 'FALLO'}")
        print(f"     {det}")
    print()
    if not token:
        print("  Empieza por:  python obtener_token_ml.py --paso1")
    print("=" * 78)
    return 0


def main():
    args = sys.argv[1:]
    if not args or "--ayuda" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--paso1" in args:
        return paso1()
    if "--paso2" in args:
        return paso2()
    if "--config" in args:
        return configurar(args[args.index("--config") + 1:])
    if "--code" in args:
        i = args.index("--code")
        if i + 1 >= len(args):
            print("  Falta el code.")
            return 1
        return canjear_code(args[i + 1])
    if "--renovar" in args:
        return renovar()
    if "--estado" in args:
        return estado()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
