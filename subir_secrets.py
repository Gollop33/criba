#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sube ML_PORTAL_COOKIE (y opcionalmente otros) a los GitHub Secrets del repo.
Cifra con la clave pública del repo (libsodium sealed box) como exige la API.

Uso:
    GH_PAT=... python subir_secrets.py                 # sube ML_PORTAL_COOKIE desde .env
    GH_PAT=... python subir_secrets.py --lista          # solo lista los secrets existentes
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from nacl import encoding, public

REPO = "Gollop33/criba"
API = "https://api.github.com"
TOKEN = os.environ.get("GH_PAT", "").strip()

if not TOKEN:
    raise SystemExit("Falta GH_PAT en el entorno")


def api(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "criba",
        },
    )
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = urllib.request.urlopen(req, data=data, timeout=30)
        raw = r.read().decode("utf-8", "replace")
        return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}


def cargar_env():
    env = {}
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env


def listar():
    s, d = api("GET", f"/repos/{REPO}/actions/secrets")
    if s != 200:
        print("No se pudieron listar los secrets:", s, d)
        return
    print(f"Secrets en {REPO}: {d.get('total_count')}")
    for x in d.get("secrets", []):
        print(f"  - {x['name']}  (actualizado {x['updated_at']})")


def subir(nombre, valor):
    s, d = api("GET", f"/repos/{REPO}/actions/secrets/public-key")
    if s != 200:
        print(f"[X] no se pudo obtener la clave publica: {s} {d}")
        return False
    pk = public.PublicKey(d["key"].encode("utf-8"), encoding.Base64Encoder())
    sellado = public.SealedBox(pk).encrypt(valor.encode("utf-8"))
    cifrado = base64.b64encode(sellado).decode("utf-8")

    s2, d2 = api("PUT", f"/repos/{REPO}/actions/secrets/{nombre}",
                 {"encrypted_value": cifrado, "key_id": d["key_id"]})
    if s2 in (201, 204):
        print(f"  [OK] {nombre} actualizado ({len(valor)} chars)")
        return True
    print(f"  [X] {nombre}: HTTP {s2} {d2}")
    return False


def main():
    if "--lista" in sys.argv:
        listar()
        return 0

    print("=== secrets ANTES ===")
    listar()

    env = cargar_env()
    subidas = 0

    # Solo tocamos lo que tenemos en .env.
    plan = [
        ("ML_PORTAL_COOKIE", "ML_PORTAL_COOKIE"),
        ("GREEN_API_TOKEN", "GREEN_API_TOKEN"),
        ("GREEN_API_ID", "GREEN_API_ID"),
        ("WHATSAPP_CHAT_ID", "WHATSAPP_CHAT_ID"),
    ]

    print("\n=== subiendo ===")
    for nombre_secret, clave_env in plan:
        valor = env.get(clave_env, "").strip()
        if not valor:
            print(f"  [skip] {nombre_secret}: no esta en .env")
            continue
        if subir(nombre_secret, valor):
            subidas += 1

    print(f"\nactualizados: {subidas}")
    print("\n=== secrets DESPUES ===")
    listar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
