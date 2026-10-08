#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Cosecha de rescate (cosechar_si_viejo.py)
=================================================
Cosecha SOLO si los achados se están quedando viejos.

POR QUÉ EXISTE (2026-10-08)
---------------------------
Al conectar el cron externo de cron-job.org quedó a la vista un problema del
`concurrency` de GitHub: mientras un run entra en el bucle de 5,5 h, los demás
disparos se quedan PENDIENTES, y GitHub va cancelando los pendientes viejos
cuando llega uno nuevo. Medido sobre los últimos 30 runs: **15 cancelados, solo
2 completados**.

Consecuencia: el cronjob de cosecha (cada hora, `modo=full&bucle=no`) casi
nunca llega a ejecutarse, así que `achados.json` solo se refrescaba cuando
arrancaba un run de bucle (cada ~5,5 h). Con la regla de frescura de 12 h, si
la fila se agotaba antes, el bot se quedaba sin material y en silencio.

QUÉ HACE
--------
Se ejecuta al principio de cada run `modo=publicar` (el de cada 7 minutos) y:
  · si `achados.json` tiene menos de HORAS_MAX_SIN_COSECHA horas -> no hace nada;
  · si está más viejo -> corre la cosecha (ML + cupones + unificador) y deja el
    material fresco para que la fila se regenere con ofertas de verdad.

Así el material se mantiene fresco con el reloj que YA está funcionando, sin
depender de que el trabajo horario consiga hueco en la cola.

Uso:
    python cosechar_si_viejo.py
    python cosechar_si_viejo.py --forzar
"""

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
ACHADOS = BASE / "achados.json"
HORAS_MAX = float(os.environ.get("HORAS_MAX_SIN_COSECHA", "3"))
FORZAR = "--forzar" in sys.argv

# Orden importa: primero las fuentes, después el unificador.
PASOS = ("agente_ml.py", "cupons_ml.py", "unir_achados.py")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def edad_horas():
    """Horas desde la última cosecha. None si no se puede saber."""
    try:
        d = json.loads(ACHADOS.read_text(encoding="utf-8-sig"))
        act = d.get("actualizado")
        if not act:
            return None
        ts = datetime.fromisoformat(str(act).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return None


def correr(script):
    log(f"  -> {script}")
    r = subprocess.run([sys.executable, script], cwd=str(BASE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout or "") + (r.stderr or "")
    for linea in salida.splitlines():
        s = linea.strip()
        if any(k in s for k in ("ofertas obtenidas", "Guardados", "achados.json generado",
                                "DIAGNÓSTICO", "cupón(es)", "Cupones ML actualizados",
                                "ERROR", "Traceback")):
            log("     " + s[:150])
    return r.returncode


def main():
    print("=" * 62)
    print("  CRIBA · COSECHA DE RESCATE")
    print("=" * 62)

    edad = edad_horas()
    if edad is None:
        log("No se pudo leer la edad de achados.json: se cosecha por precaución.")
    elif edad < HORAS_MAX and not FORZAR:
        log(f"achados.json tiene {edad:.1f} h (< {HORAS_MAX:.0f} h): no hace falta cosechar.")
        print("=" * 62)
        return 0
    else:
        log(f"achados.json tiene {edad:.1f} h (>= {HORAS_MAX:.0f} h): COSECHANDO.")

    fallos = 0
    for paso in PASOS:
        try:
            if correr(paso) != 0:
                fallos += 1
        except Exception as e:
            log(f"     excepción en {paso}: {e}")
            fallos += 1

    nueva = edad_horas()
    if nueva is not None:
        log(f"Edad después de cosechar: {nueva:.1f} h")
    log(f"Cosecha de rescate terminada ({len(PASOS) - fallos}/{len(PASOS)} pasos OK).")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
