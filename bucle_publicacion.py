#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Bucle de publicación (bucle_publicacion.py)
====================================================
Resuelve el problema de fondo: el `schedule` de GitHub entrega una ejecución
cada ~3 h, así que un job que publica 1 post y termina deja el grupo muerto
durante horas.

Esta es la solución sin depender de servicios externos: **cada ejecución se
queda viva publicando**, un post cada INTERVALO_SEG, hasta que:
  - se agota la ventana Brasília (8:00-22:00), o
  - se alcanza el límite diario de calentamiento, o
  - se cumple DURACION_MAX_SEG (por defecto 4.5 h, muy por debajo del límite
    de 6 h por job de GitHub Actions).

Después de CADA post hace commit+push del estado, así que:
  - si el job muere, no se pierde el registro de lo enviado (anti-duplicados), y
  - cualquier otra ejecución en cola ve el estado fresco.

Variables de entorno:
  INTERVALO_SEG     segundos entre posts            (defecto 450 = 7.5 min)
  DURACION_MAX_SEG  duración máxima de la ejecución (defecto 16200 = 4.5 h)
  MAX_POSTS         tope duro de posts por ejecución (defecto 40)

Uso:
    python bucle_publicacion.py
    python bucle_publicacion.py --dry     # no publica ni commitea, solo simula
"""

import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
INTERVALO_SEG = int(os.environ.get("INTERVALO_SEG", "450"))
DURACION_MAX_SEG = int(os.environ.get("DURACION_MAX_SEG", "16200"))
MAX_POSTS = int(os.environ.get("MAX_POSTS", "40"))
DRY = "--dry" in sys.argv


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def correr(cmd, check=False):
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ventana_abierta():
    brt = (datetime.now(timezone.utc).hour - 3) % 24
    return 8 <= brt < 22


def commit_y_push(n):
    """Persiste el estado tras cada post. Silencioso ante fallos de red."""
    subprocess.run(["git", "add", "-A", "--", "*.json", "logs/"],
                   cwd=str(BASE), capture_output=True)
    subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                   cwd=str(BASE), capture_output=True)
    subprocess.run(["python", "reparar_estado.py"], cwd=str(BASE), capture_output=True)
    subprocess.run(["git", "add", "-A", "--", "*.json", "logs/"],
                   cwd=str(BASE), capture_output=True)
    diff = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(BASE))
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m", f"auto: envio #{n} {datetime.now(timezone.utc):%H:%M}"],
                       cwd=str(BASE), capture_output=True)
        p = subprocess.run(["git", "push"], cwd=str(BASE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode == 0:
            log(f"    estado persistido (commit+push #{n})")
        else:
            log(f"    aviso: no se pudo hacer push ({p.stderr.strip()[:80]})")


def main():
    print("=" * 64)
    print("  CRIBA · BUCLE DE PUBLICACIÓN")
    print(f"  intervalo {INTERVALO_SEG}s | max duración {DURACION_MAX_SEG}s | "
          f"max posts {MAX_POSTS}" + ("  [DRY]" if DRY else ""))
    print("=" * 64)

    if not DRY and not ventana_abierta():
        log("Fuera de la ventana Brasília (8-22). No se publica.")
        return 0

    inicio = time.time()
    publicados = 0

    while True:
        transcurrido = time.time() - inicio
        if transcurrido > DURACION_MAX_SEG:
            log(f"Duración máxima alcanzada ({transcurrido/60:.0f} min). Fin.")
            break
        if not DRY and not ventana_abierta():
            log("Se cerró la ventana Brasília. Fin.")
            break
        if publicados >= MAX_POSTS:
            log(f"Tope de posts por ejecución alcanzado ({MAX_POSTS}). Fin.")
            break

        log(f"── Post {publicados + 1} (transcurrido {transcurrido/60:.1f} min) ──")

        out = ""
        if DRY:
            log("    [DRY] aquí se llamaría a publicar_proximo.py")
            publicados += 1
        else:
            rc, out = correr(["python", "publicar_proximo.py"])
            # Mostrar solo las lineas relevantes
            for ln in out.splitlines():
                s = ln.strip()
                if s.startswith(("🎯", "🔥", "💵", "🎟️", "✅", "⚠️", "❌", "[Cadencia]",
                                 "[Horario]", "[Límite", "[Fila]", "http")):
                    log("    " + s)
            if rc == 2:
                log("    ABORTADO: estado corrupto. Se corta el bucle.")
                return 2
            if "✅ Publicado" in out:
                publicados += 1
                commit_y_push(publicados)
            else:
                log("    (sin publicación en esta pasada)")

        # Si no quedan posts por enviar, no tiene sentido seguir girando
        if not DRY and "Todos los posts ya fueron enviados" in out:
            log("No quedan posts disponibles en la fila. Fin.")
            break

        restante = DURACION_MAX_SEG - (time.time() - inicio)
        if restante <= INTERVALO_SEG:
            log("No queda tiempo para otro post en esta ejecución. Fin.")
            break

        log(f"    esperando {INTERVALO_SEG}s...")
        time.sleep(INTERVALO_SEG)

    print("=" * 64)
    log(f"Bucle terminado. Posts publicados en esta ejecución: {publicados}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
