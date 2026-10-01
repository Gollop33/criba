#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Modo de sesión (sesion.py)
==================================
Enciende y apaga el catálogo de skills según para qué vayas a usar el chat.

── EL PROBLEMA ──────────────────────────────────────────────────────────────
DSH lee las skills de `<proyecto>/.agents/skills/` y las mete ENTERAS en cada
petición. Con las 14 de marketing activas, eso son ~2.514 tokens por mensaje que
se pagan aunque estés hablando de otra cosa.

Y como se leen de la carpeta del proyecto, abrir un chat nuevo en la misma carpeta
NO lo evita: vuelve a cargar las mismas 14.

── LA SOLUCIÓN ──────────────────────────────────────────────────────────────
Mover la carpeta de skills antes de abrir según qué chat:

    python sesion.py --charlar      -> guarda las skills (0 tokens de catálogo)
    python sesion.py --marketing    -> las vuelve a poner
    python sesion.py --estado       -> ver en qué modo está

El modo se aplica al ABRIR el chat: DSH lee el catálogo al arrancar. Si cambias
de modo con un chat ya abierto, ese chat sigue con el catálogo que cargó.

── QUÉ MODO USAR ────────────────────────────────────────────────────────────
    CHARLAR    -> hablar del proyecto, decisiones, estrategia, revisar estado.
                  No necesita skills de marketing.
    MARKETING  -> SEO, redes, vídeos, copy, conversión. Sí las necesita.
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ACTIVAS = BASE / ".agents" / "skills"
GUARDADAS = BASE / ".agents" / "skills-guardadas"
NO_USADAS = BASE / ".agents" / "skills-no-usadas"
MARCA = BASE / ".agents" / ".modo-sesion"


def contar(carpeta):
    if not carpeta.exists():
        return 0
    return sum(1 for d in carpeta.iterdir() if d.is_dir() and (d / "SKILL.md").exists())


def modo_actual():
    if MARCA.exists():
        return MARCA.read_text(encoding="utf-8").strip() or "?"
    return "marketing" if contar(ACTIVAS) else "charlar"


def poner(nuevo):
    actual = modo_actual()
    if actual == nuevo:
        print(f"  ya estás en modo '{nuevo}' ({contar(ACTIVAS)} skills activas)")
        return 0

    if nuevo == "charlar":
        if not ACTIVAS.exists():
            print("  no hay skills activas que guardar")
        else:
            if GUARDADAS.exists():
                shutil.rmtree(GUARDADAS, ignore_errors=True)
            shutil.move(str(ACTIVAS), str(GUARDADAS))
            print(f"  guardadas {contar(GUARDADAS)} skills en .agents/skills-guardadas/")
        ACTIVAS.mkdir(parents=True, exist_ok=True)
        print("  modo CHARLAR: el catálogo de skills queda vacío")
        print("  -> ahorro de ~2.514 tokens por mensaje")

    elif nuevo == "marketing":
        if not GUARDADAS.exists():
            print("  no hay skills guardadas. ¿Las quitaste a mano?")
            print("  Recupéralas del repo: git checkout .agents/skills")
            return 1
        if ACTIVAS.exists():
            shutil.rmtree(ACTIVAS, ignore_errors=True)
        shutil.move(str(GUARDADAS), str(ACTIVAS))
        print(f"  restauradas {contar(ACTIVAS)} skills")
        print("  modo MARKETING: catálogo completo (~2.514 tokens por mensaje)")

    MARCA.write_text(nuevo, encoding="utf-8")
    print()
    print("  IMPORTANTE: cierra este chat y abre uno NUEVO para que se aplique.")
    print("  DSH lee el catálogo al arrancar la sesión.")
    return 0


def estado():
    m = modo_actual()
    act = contar(ACTIVAS)
    gua = contar(GUARDADAS)
    no_u = contar(NO_USADAS)
    print("=" * 66)
    print("  MODO DE SESIÓN")
    print("=" * 66)
    print(f"  modo actual            : {m.upper()}")
    print(f"  skills activas         : {act}   (~{act * 180} tokens por mensaje aprox.)")
    print(f"  skills guardadas       : {gua}   (en .agents/skills-guardadas/)")
    print(f"  skills descartadas     : {no_u}  (en .agents/skills-no-usadas/, no se cargan)")
    print()
    if m == "marketing":
        print("  Estás pagando el catálogo de marketing en cada mensaje.")
        print("  Si este chat es para hablar del proyecto:  python sesion.py --charlar")
    else:
        print("  Catálogo apagado. Para SEO/redes/vídeos:  python sesion.py --marketing")
    print("=" * 66)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Enciende/apaga el catálogo de skills")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--charlar", action="store_true", help="apaga las skills (charla del proyecto)")
    g.add_argument("--marketing", action="store_true", help="enciende las skills (SEO, redes, vídeo)")
    g.add_argument("--estado", action="store_true", help="ver el modo actual")
    a = ap.parse_args()

    if a.estado or not (a.charlar or a.marketing):
        return estado()
    return poner("charlar" if a.charlar else "marketing")


if __name__ == "__main__":
    sys.exit(main())
