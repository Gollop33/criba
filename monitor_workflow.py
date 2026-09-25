#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Monitor de ejecuciones de GitHub Actions (monitor_workflow.py)
======================================================================
Muestra las últimas ejecuciones del workflow bot.yml y el intervalo entre
ellas. Sirve para comprobar que el cron externo está disparando cada 8 min:

    python monitor_workflow.py          # últimas 25 ejecuciones
    python monitor_workflow.py 60       # últimas 60

No necesita token: el repo es público.
"""

import io
import json
import sys
import urllib.request
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = "Gollop33/criba"
WORKFLOW = "bot.yml"
URL = (f"https://api.github.com/repos/{REPO}/actions/workflows/"
       f"{WORKFLOW}/runs?per_page={{n}}")


def main():
    n = 25
    if len(sys.argv) > 1:
        try:
            n = max(1, min(100, int(sys.argv[1])))
        except ValueError:
            pass

    req = urllib.request.Request(
        URL.format(n=n), headers={"User-Agent": "criba-monitor"}
    )
    try:
        data = json.load(urllib.request.urlopen(req, timeout=40))
    except Exception as e:
        print(f"No se pudo consultar la API de GitHub: {e}")
        return 1

    runs = list(reversed(data.get("workflow_runs", [])))
    if not runs:
        print("No hay ejecuciones.")
        return 0

    print("=" * 78)
    print(f"  CRIBA · EJECUCIONES DE {WORKFLOW}  (repo {REPO})")
    print("=" * 78)
    print(f"{'#':>5} {'fecha UTC':<17} {'dur':>6}  {'evento':<17} {'gap':>9}  resultado")
    print("-" * 78)

    prev = None
    gaps = []
    for r in runs:
        t = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        u = datetime.strptime(r["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
        dur = (u - t).total_seconds()
        if prev is None:
            gap = "-"
        else:
            g = (t - prev).total_seconds() / 60.0
            gaps.append(g)
            gap = f"{g:5.1f}min"
        concl = r.get("conclusion") or r.get("status")
        print(f"{r['run_number']:>5} {t:%m-%d %H:%M:%S} {dur:5.0f}s  "
              f"{r['event']:<17} {gap:>9}  {concl}")
        prev = t

    print("-" * 78)
    if gaps:
        gs = sorted(gaps)
        mediana = gs[len(gs) // 2]
        print(f"  gap mediano: {mediana:.1f} min | minimo: {min(gaps):.1f} | "
              f"maximo: {max(gaps):.1f}")
        print(f"  ejecuciones con gap > 60 min: {sum(1 for g in gaps if g > 60)}/{len(gaps)}")
        if mediana <= 15:
            print("  [OK]  la cadencia del cron externo esta funcionando")
        else:
            print("  [X]   la cadencia NO cumple: revisa cron-job.org")
            print("        -> si son del tipo 'schedule', el cron externo no esta disparando")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
