#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Reparador de estado (reparar_estado.py)
================================================
Se ejecuta en el workflow DESPUES del `git pull --rebase --autostash` y ANTES
del commit. Su trabajo es que nunca se suba al repo un JSON con marcadores de
conflicto.

¿Por qué hace falta?
--------------------
Dos ejecuciones solapadas (cron externo + schedule, o dos disparos seguidos)
pueden dejar `logs/enviados.json` con marcadores de stash:

    <<<<<<< Updated upstream
    =======
    >>>>>>> Stashed changes

Si eso se commitea, `cargar_enviados()` no puede parsearlo, devuelve `{}` y el
bot **republica todo el catálogo** porque cree que nunca envió nada. Ya pasó una
vez. Este script lo evita.

Reglas de resolución:
- `logs/enviados.json`  -> UNION de ambos lados (log append-only). Conserva el
  registro más reciente por producto y fusiona los canales. Nunca pierde envíos.
- cualquier otro .json  -> se restaura la versión de origin/main (son archivos
  generados; se regeneran solos).

Uso:
    python reparar_estado.py            # repara en sitio
    python reparar_estado.py --check    # solo informa, no escribe
"""

import io
import json
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
CHECK_ONLY = "--check" in sys.argv
MARKS = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")


def conflicto_en(txt):
    """Devuelve (i_marca, i_sep, i_fin) del primer bloque de conflicto, o None."""
    i_marca = i_sep = i_fin = None
    lineas = txt.splitlines()
    for i, ln in enumerate(lineas):
        if ln.startswith("<<<<<<<"):
            i_marca = i
        elif ln.startswith("=======") and i_marca is not None and i_sep is None:
            i_sep = i
        elif ln.startswith(">>>>>>>") and i_sep is not None:
            i_fin = i
            break
    if None in (i_marca, i_sep, i_fin):
        return None
    return lineas, i_marca, i_sep, i_fin


def unir_enviados(txt):
    """Resuelve el conflicto de enviados.json uniendo las entradas de ambos lados."""
    r = conflicto_en(txt)
    if not r:
        return None
    lineas, i_marca, i_sep, i_fin = r
    prefijo, ours, theirs, sufijo = (
        lineas[:i_marca], lineas[i_marca + 1:i_sep], lineas[i_sep + 1:i_fin], lineas[i_fin + 1:]
    )

    def parsear(bloque):
        try:
            return json.loads("\n".join(prefijo + bloque + sufijo))
        except Exception:
            return None

    a, b = parsear(ours), parsear(theirs)
    if a is None and b is None:
        return None
    if a is None:
        return json.dumps(b, ensure_ascii=False, indent=2)
    if b is None:
        return json.dumps(a, ensure_ascii=False, indent=2)

    union = {}
    for src in (a, b):
        for k, v in src.items():
            if not isinstance(v, dict):
                continue
            prev = union.get(k)
            if prev is None:
                union[k] = dict(v)
                continue
            canales = dict(prev.get("canales") or {})
            canales.update(v.get("canales") or {})
            nuevo = dict(v) if (v.get("ts") or "") > (prev.get("ts") or "") else dict(prev)
            nuevo["canales"] = canales
            union[k] = nuevo
    return json.dumps(union, ensure_ascii=False, indent=2)


def restaurar_de_origin(rel):
    r = subprocess.run(["git", "checkout", "origin/main", "--", rel], capture_output=True)
    return r.returncode == 0


def main():
    print("=" * 60)
    print("  CRIBA · REPARADOR DE ESTADO" + (" [CHECK]" if CHECK_ONLY else ""))
    print("=" * 60)

    # Solo importan los JSON que git versiona: lo que no se commitea no puede
    # corromper el repo (p.ej. fila_posts.json, que está en .gitignore).
    r = subprocess.run(["git", "ls-files", "*.json"], capture_output=True, cwd=str(BASE))
    rels = [x.strip() for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]
    if rels:
        candidatos = [BASE / x for x in rels]
        print(f"  JSON versionados por git: {len(candidatos)}")
    else:
        candidatos = sorted(p for p in BASE.rglob("*.json") if ".git" not in p.parts)
        print(f"  (sin git) JSON encontrados: {len(candidatos)}")
    con_conflicto = []
    for p in candidatos:
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if any(txt.lstrip().startswith(m) or f"\n{m}" in txt for m in MARKS):
            con_conflicto.append(p)

    if not con_conflicto:
        print("  [OK]  ningun JSON con marcadores de conflicto.")
        return 0

    print(f"  [X]   {len(con_conflicto)} JSON con marcadores de conflicto:")
    reparados = 0
    fallos = []
    for p in con_conflicto:
        rel = p.relative_to(BASE).as_posix()
        print(f"        - {rel}")
        if CHECK_ONLY:
            continue
        if rel == "logs/enviados.json":
            nuevo = unir_enviados(p.read_text(encoding="utf-8"))
            if nuevo:
                p.write_text(nuevo, encoding="utf-8")
                n = len(json.loads(nuevo))
                print(f"          -> UNIDO, {n} entradas")
                reparados += 1
                continue
            print("          -> no se pudo unir, se restaura de origin/main")
        if restaurar_de_origin(rel):
            print("          -> restaurado de origin/main")
            reparados += 1
        else:
            print("          -> FALLO al restaurar")
            fallos.append(rel)

    print(f"  reparados: {reparados} | fallos: {len(fallos)}")
    if fallos:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
