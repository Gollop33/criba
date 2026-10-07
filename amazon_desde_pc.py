#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Amazon desde tu PC (amazon_desde_pc.py)
================================================
POR QUÉ EXISTE
--------------
Amazon bloquea las IPs de los servidores de GitHub Actions: allí la cosecha
devuelve 0 ofertas (y por eso la fila sale 100% Mercado Livre). Desde una
conexión normal (tu PC) la MISMA cosecha trae ~300 ofertas, medido el
2026-10-02. Así que Amazon se cosecha aquí y se sube al repositorio, que es de
donde el bot lo lee.

QUÉ HACE
--------
  1. Ejecuta la cosecha de Amazon y comprueba que trajo ofertas de verdad.
  2. Si trajo menos del mínimo, NO toca nada (mejor no publicar que publicar mal).
  3. Sube SOLO el fichero achados_amazon.json al repositorio (git add/commit/push).

Uso:
    python amazon_desde_pc.py              # cosecha + sube
    python amazon_desde_pc.py --sin-push   # cosecha y comprueba, sin subir
    python amazon_desde_pc.py --minimo 50  # exigir al menos 50 ofertas

Para que corra solo cada día: doble clic en ACTUALIZAR_AMAZON.bat, o
programarlo con el Programador de tareas de Windows.
"""
import argparse
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
ACHADOS_AMAZON = BASE / "achados_amazon.json"


def ejecutar(comando):
    """Ejecuta un comando en la carpeta del proyecto y devuelve (ok, salida)."""
    try:
        r = subprocess.run(comando, cwd=str(BASE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def cosechar():
    print("=" * 68)
    print("  CRIBA · AMAZON DESDE TU PC")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)
    print("\n  [1/3] Cosechando Amazon (desde tu IP, que sí puede)...")
    ok, salida = ejecutar([sys.executable, "agente_amazon.py"])
    for linea in salida.strip().splitlines():
        if any(x in linea for x in ("Amazon direct", "Amazon Pelando", "Guardados", "[OK]")):
            print(f"    {linea.strip()}")
    if not ok:
        print("    [X] El agente de Amazon falló. No se sube nada.")
        return 0
    if not ACHADOS_AMAZON.exists():
        print("    [X] No se generó achados_amazon.json.")
        return 0
    try:
        datos = json.loads(ACHADOS_AMAZON.read_text(encoding="utf-8"))
        n = int(datos.get("total") or len(datos.get("achados") or []))
    except Exception as e:
        print(f"    [X] achados_amazon.json ilegible: {e}")
        return 0
    print(f"    Ofertas conseguidas: {n}")
    return n


def publicar(minimo=20):
    print("\n  [3/3] Subiendo achados_amazon.json al repositorio...")
    pasos = [
        (["git", "config", "user.name", "criba-pc"], "config user"),
        (["git", "config", "user.email", "criba@localhost"], "config email"),
        (["git", "pull", "--rebase", "--autostash", "origin", "main"], "pull"),
        (["git", "add", "achados_amazon.json"], "add"),
    ]
    for comando, nombre in pasos:
        ok, salida = ejecutar(comando)
        if nombre in ("pull", "add") and not ok:
            print(f"    [!] {nombre}: {salida.strip()[:160]}")
        elif not ok and nombre.startswith("config"):
            print(f"    [!] {nombre}: {salida.strip()[:120]}")

    ok, salida = ejecutar(["git", "diff", "--staged", "--quiet"])
    if ok:
        print("    Sin cambios: el fichero ya estaba igual. Nada que subir.")
        return 0

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    ok, salida = ejecutar(["git", "commit", "-m", f"amz: cosecha desde PC {fecha}"])
    if not ok:
        print(f"    [X] commit falló: {salida.strip()[:200]}")
        return 0
    ok, salida = ejecutar(["git", "push"])
    if not ok:
        print(f"    [!] push rechazado, reintentando con rebase...")
        ejecutar(["git", "pull", "--rebase", "--autostash", "origin", "main"])
        ok, salida = ejecutar(["git", "push"])
    if ok:
        print("    [OK] Subido. El bot ya tiene ofertas de Amazon para hoy.")
        return 1
    print(f"    [X] No se pudo subir: {salida.strip()[:200]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Cosecha Amazon desde el PC y la sube al repo")
    ap.add_argument("--sin-push", action="store_true", help="cosechar sin subir nada")
    ap.add_argument("--minimo", type=int, default=20, help="mínimo de ofertas exigido (def. 20)")
    args = ap.parse_args()

    n = cosechar()

    print(f"\n  [2/3] Comprobando el resultado (mínimo {args.minimo})...")
    if n < args.minimo:
        print(f"    [X] Solo {n} ofertas. NO se sube: mejor no tener Amazon "
              f"que publicar ofertas mal cosechadas.")
        return 1
    print(f"    [OK] {n} ofertas, suficientes.")

    if args.sin_push:
        print("\n  (--sin-push: no se sube nada)")
        return 0

    return 0 if publicar(args.minimo) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
