#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Bucle de publicación (bucle_publicacion.py)
====================================================
Publica de forma continua dentro de una misma ejecución de GitHub Actions,
porque el `schedule` de GitHub entrega una ejecución cada ~3 h.

INTERVALOS ALEATORIOS
---------------------
Entre post y post espera un tiempo ALEATORIO entre INTERVALO_MIN_SEG y
INTERVALO_MAX_SEG (por defecto 1 a 10 minutos). No es un capricho: un patrón
perfectamente regular (cada 7.5 min exactos) es justo lo que buscan los
sistemas anti-spam. Intervalos irregulares parecen una persona.

    media con 1-10 min ≈ 5.5 min  ->  ~11 posts/hora  (antes: 8/hora con 7.5 fijo)

Se para cuando:
  - se agota la ventana Brasília (8:00-22:00), o
  - se alcanza el tope diario (MAX_ENVIOS_DIA, por defecto 120), o
  - la fila se queda sin ofertas nuevas, o
  - se cumple DURACION_MAX_SEG (4.5 h, muy por debajo del límite de 6 h/job).

Persiste estado (commit+push) después de CADA post, así que si el job muere no
se pierde el registro anti-duplicados.

Variables de entorno:
  INTERVALO_MIN_SEG    espera mínima entre posts   (defecto 60  = 1 min)
  INTERVALO_MAX_SEG    espera máxima entre posts   (defecto 600 = 10 min)
  INTERVALO_SEG        si se define, usa intervalo FIJO (compatibilidad)
  DURACION_MAX_SEG     duración máxima del bucle    (defecto 16200 = 4.5 h)
  MAX_POSTS            tope duro de posts por bucle (defecto 80)
  MAX_ENVIOS_DIA       tope diario (lo aplica publicar_proximo.py)

Uso:
    python bucle_publicacion.py
    python bucle_publicacion.py --dry
"""

import io
import os
import random
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

_fijo = os.environ.get("INTERVALO_SEG", "").strip()
INTERVALO_FIJO = int(_fijo) if _fijo else None
INTERVALO_MIN_SEG = int(os.environ.get("INTERVALO_MIN_SEG", "60"))
INTERVALO_MAX_SEG = int(os.environ.get("INTERVALO_MAX_SEG", "600"))
DURACION_MAX_SEG = int(os.environ.get("DURACION_MAX_SEG", "16200"))
MAX_POSTS = int(os.environ.get("MAX_POSTS", "80"))
MAX_REGENERACIONES = int(os.environ.get("MAX_REGENERACIONES", "3"))
DRY = "--dry" in sys.argv

# La guardia anti-duplicado de publicar_proximo.py debe ser MENOR que el
# intervalo mínimo, o bloquearía los posts cortos (p.ej. el de 1 minuto).
# Con concurrency en el workflow no puede haber dos publicando a la vez, así
# que basta con medio intervalo mínimo como red de seguridad.
MIN_GAP_LOOP = max(0.4, round((INTERVALO_FIJO or INTERVALO_MIN_SEG) / 60.0 * 0.5, 2))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def correr(cmd, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ventana_abierta():
    brt = (datetime.now(timezone.utc).hour - 3) % 24
    return 8 <= brt < 22


def commit_y_push(n):
    """Persiste el estado tras cada post. Silencioso ante fallos de red."""
    subprocess.run(["git", "add", "-A", "--", "*.json", "logs/", "precios.db"],
                   cwd=str(BASE), capture_output=True)
    subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                   cwd=str(BASE), capture_output=True)
    subprocess.run(["python", "reparar_estado.py"], cwd=str(BASE), capture_output=True)
    subprocess.run(["git", "add", "-A", "--", "*.json", "logs/", "precios.db"],
                   cwd=str(BASE), capture_output=True)
    if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(BASE)).returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m",
                        f"auto: envio #{n} {datetime.now(timezone.utc):%H:%M}"],
                       cwd=str(BASE), capture_output=True)
        p = subprocess.run(["git", "push"], cwd=str(BASE), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0:
            log("    estado persistido (commit+push)")
        else:
            log(f"    aviso: push falló ({p.stderr.strip()[:70]})")


def siguiente_espera(anterior=None):
    """Espera aleatoria entre el mínimo y el máximo. Evita repetir el mismo valor."""
    if INTERVALO_FIJO:
        return INTERVALO_FIJO
    lo, hi = sorted((INTERVALO_MIN_SEG, INTERVALO_MAX_SEG))
    for _ in range(10):
        s = random.randint(lo, hi)
        # un humano no repite exactamente el mismo hueco dos veces seguidas
        if anterior is None or abs(s - anterior) >= 30:
            return s
    return s


def resumen(esperas):
    if not esperas:
        return
    media = sum(esperas) / len(esperas)
    print(f"  intervalos usados (min): {[round(e/60, 1) for e in esperas]}")
    print(f"  media: {media/60:.1f} min | min: {min(esperas)/60:.1f} | max: {max(esperas)/60:.1f}")
    print(f"  ritmo real: {60/(media/60):.1f} posts/hora")


def main():
    lo, hi = (INTERVALO_FIJO, INTERVALO_FIJO) if INTERVALO_FIJO else (INTERVALO_MIN_SEG, INTERVALO_MAX_SEG)
    print("=" * 66)
    print("  CRIBA · BUCLE DE PUBLICACIÓN")
    print(f"  intervalo aleatorio: {lo/60:.1f} - {hi/60:.1f} min"
          f"  (media teórica {(lo+hi)/2/60:.1f} min ≈ {60/(((lo+hi)/2)/60):.0f} posts/h)")
    print(f"  max duración {DURACION_MAX_SEG/3600:.1f} h | max posts {MAX_POSTS}"
          f" | MIN_GAP interno {MIN_GAP_LOOP} min")
    print("=" * 66)

    if not DRY and not ventana_abierta():
        log("Fuera de la ventana Brasília (8-22). No se publica.")
        return 0

    inicio = time.time()
    publicados = 0
    regenes = 0
    esperas = []
    espera_anterior = None

    while True:
        transcurrido = time.time() - inicio
        if transcurrido > DURACION_MAX_SEG:
            log(f"Duración máxima alcanzada ({transcurrido/60:.0f} min). Fin.")
            break
        if not DRY and not ventana_abierta():
            log("Se cerró la ventana Brasília. Fin.")
            break
        if publicados >= MAX_POSTS:
            log(f"Tope de posts del bucle alcanzado ({MAX_POSTS}). Fin.")
            break

        log(f"── Post {publicados + 1} (transcurrido {transcurrido/60:.1f} min) ──")

        out = ""
        if DRY:
            log("    [DRY] aquí se llamaría a publicar_proximo.py")
            publicados += 1
        else:
            rc, out = correr(["python", "publicar_proximo.py"],
                             env_extra={"MIN_GAP_MIN": str(MIN_GAP_LOOP)})
            for ln in out.splitlines():
                s = ln.strip()
                if s.startswith(("🎯", "🔥", "💵", "🎟️", "✅", "⚠️", "❌", "[Cadencia]",
                                 "[Horario]", "[Límite", "[Fila]", "[Agente", "http",
                                 "⏭️")):
                    log("    " + s)
            if rc == 2:
                log("    ABORTADO: estado corrupto. Se corta el bucle.")
                return 2
            if "✅ Publicado" in out:
                publicados += 1
                commit_y_push(publicados)
            else:
                log("    (sin publicación en esta pasada)")

        # ¿Se quedó la fila sin ofertas nuevas?
        agotada = ("Todos los posts ya fueron enviados" in out
                   or "No hay posts en la fila" in out
                   or "No se publicó ningún post" in out)
        if not DRY and agotada:
            if regenes < MAX_REGENERACIONES:
                regenes += 1
                log(f"    Fila agotada. Regenerando desde achados.json "
                    f"(intento {regenes}/{MAX_REGENERACIONES})...")
                correr(["python", "gerar_fila_posts.py"])
                time.sleep(5)
                continue
            log("    Fila agotada y no hay más ofertas distintas. Fin.")
            break

        restante = DURACION_MAX_SEG - (time.time() - inicio)
        espera = siguiente_espera(espera_anterior)
        if restante <= espera:
            log("No queda tiempo para otro post en esta ejecución. Fin.")
            break

        espera_anterior = espera
        esperas.append(espera)
        log(f"    esperando {espera/60:.1f} min ({espera}s)...")
        time.sleep(espera)

    print("=" * 66)
    log(f"Bucle terminado. Posts publicados: {publicados}")
    resumen(esperas)
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
