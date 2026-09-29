#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Reset diario del ciclo (reset_diario.py)
================================================
Cierra el día anterior y abre el nuevo, UNA vez por día.

── CÓMO SE DISPARA ──────────────────────────────────────────────────────────
No depende de que el cron caiga exactamente a las 08:00 (GitHub Actions
estrangula los `schedule`: se midió una mediana de 174 min de retraso). Lo que
hace es comprobar si YA se reinició hoy (hora de Brasilia):

    primer run del día -> RESET
    cualquier run posterior -> no hace nada

Así, si el cron cae a las 08:00, el reset es a las 08:00; si GitHub lo retrasa a
las 09:40, el reset es a las 09:40. El ciclo diario se reinicia igual, solo, sin
que nadie toque nada.

── QUÉ HACE ──────────────────────────────────────────────────────────────────
1. ARCHIVA el día anterior en logs/historial/ (no se borra nada histórico).
2. VACÍA la fila de posts para que se regenere con datos del día nuevo.
3. MARCA los cupones vencidos como tales (no se borran: quedan para el histórico).
4. LIMPIA temporales viejos (cachés de imágenes, enlaces caducados).
5. CONSERVA: logs/enviados.json (anti-repetición), precios.db (historial de
   precios), cache_melila.json (los enlaces siguen siendo válidos).
6. REGISTRA el arranque del ciclo en logs/ciclo_diario.json + validacion.jsonl.

── QUÉ NO HACE ───────────────────────────────────────────────────────────────
No borra histórico de publicaciones ni de precios: eso es lo que permite saber
si un producto bajó de precio y decidir si se puede repetir.
"""

import io
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
LOGS = BASE / "logs"
HISTORIAL = LOGS / "historial"
HISTORIAL.mkdir(parents=True, exist_ok=True)
MARCA = LOGS / "ciclo_diario.json"
FILA = BASE / "fila_posts.json"
CUPONES = BASE / "cupones.json"

# Horas de Brasilia (UTC-3). El reset marca el comienzo del día del canal.
TZ_BRT = timezone(timedelta(hours=-3))
HORA_RESET_BRT = int(os.environ.get("HORA_RESET_BRT", "8"))

# Antigüedad máxima de un temporal antes de limpiarlo
DIAS_TEMPORALES = int(os.environ.get("DIAS_TEMPORALES", "7"))
# Ficheros que se archivan cada día (el estado del día que termina)
ARCHIVAR = ("fila_posts.json", "cupones.json", "achados.json",
            "ofertas_telegram.json", "achados_ml.json", "achados_amazon.json")


def ahora_brt():
    return datetime.now(TZ_BRT)


def leer_marca():
    if not MARCA.exists():
        return {}
    try:
        return json.loads(MARCA.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def ya_reiniciado_hoy(marca=None):
    """¿El ciclo de hoy ya se abrió?"""
    marca = marca if marca is not None else leer_marca()
    return marca.get("ultimo_dia") == ahora_brt().strftime("%Y-%m-%d")


def _guardar_json(ruta, datos):
    """Escritura atómica: si se corta a medias, no deja el JSON corrupto."""
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def archivar_dia(dia_anterior):
    """Copia el estado del día que termina a logs/historial/. No borra nada."""
    destino = HISTORIAL / dia_anterior
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nombre in ARCHIVAR:
        f = BASE / nombre
        if not f.exists():
            continue
        try:
            shutil.copy2(f, destino / nombre)
            copiados.append(nombre)
        except Exception as e:
            print(f"  [!] no se pudo archivar {nombre}: {e}")
    return copiados


def vaciar_fila(dia):
    """
    Deja la fila vacía para forzar su regeneración con datos del día nuevo.
    Se conserva una copia de seguridad por si algo falla.
    """
    if not FILA.exists():
        return "no existía"
    try:
        d = json.loads(FILA.read_text(encoding="utf-8-sig"))
        n = len(d.get("fila", []))
    except Exception:
        n = 0
    try:
        shutil.copy2(FILA, LOGS / f"fila_antes_reset_{dia}.json")
    except Exception:
        pass
    _guardar_json(FILA, {
        "actualizado": ahora_brt().isoformat(timespec="seconds"),
        "reset_diario": dia,
        "total_posts": 0,
        "fila": [],
    })
    return f"vaciada ({n} posts del día anterior)"


def marcar_cupones_vencidos(dia):
    """
    Marca los cupones caducados. NO se borran: se quedan con estado 'vencido'
    para el histórico. Así el validador los descarta por fecha y no se pierde
    la traza de qué cupones existieron.
    """
    if not CUPONES.exists():
        return 0, 0
    try:
        d = json.loads(CUPONES.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"  [!] cupones.json ilegible: {e}")
        return 0, 0
    lista = d.get("cupones", d if isinstance(d, list) else [])
    vencidos = vigentes = 0
    for c in lista:
        hasta = str(c.get("hasta") or c.get("vencimento") or "").strip()
        if not hasta:
            c["vigente"] = True
            vigentes += 1
            continue
        if hasta[:10] < dia:
            c["vigente"] = False
            c["estado"] = "vencido"
            vencidos += 1
        else:
            c["vigente"] = True
            c["estado"] = "ativo"
            vigentes += 1
    if isinstance(d, dict):
        d["cupones"] = lista
        d["revisado_em"] = ahora_brt().isoformat(timespec="seconds")
        _guardar_json(CUPONES, d)
    else:
        _guardar_json(CUPONES, lista)
    return vigentes, vencidos


def limpiar_temporales():
    """Borra temporales viejos. Nunca toca historial, precios.db ni enviados."""
    borrados = 0
    limite = ahora_brt().timestamp() - DIAS_TEMPORALES * 86400
    # Backups de fila antiguos
    for f in LOGS.glob("fila_antes_reset_*.json"):
        try:
            if f.stat().st_mtime < limite:
                f.unlink()
                borrados += 1
        except Exception:
            pass
    # Imágenes de envíos de hace días (se regeneran)
    for carpeta in (BASE / "img" / "envios", LOGS / "tmp"):
        if not carpeta.exists():
            continue
        for f in carpeta.glob("*"):
            try:
                if f.is_file() and f.stat().st_mtime < limite:
                    f.unlink()
                    borrados += 1
            except Exception:
                pass
    return borrados


def limpiar_log_validacion():
    """Rota el log de validación para que no crezca sin freno (30 días)."""
    f = LOGS / "validacion.jsonl"
    if not f.exists():
        return 0
    limite = (ahora_brt() - timedelta(days=30)).isoformat()[:10]
    conservadas = []
    quitadas = 0
    try:
        for linea in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not linea.strip():
                continue
            try:
                ts = json.loads(linea).get("ts", "")[:10]
            except Exception:
                conservadas.append(linea)
                continue
            if ts and ts < limite:
                quitadas += 1
            else:
                conservadas.append(linea)
        f.write_text("\n".join(conservadas) + ("\n" if conservadas else ""),
                     encoding="utf-8")
    except Exception:
        return 0
    return quitadas


def ejecutar(forzar=False, seco=False):
    hoy = ahora_brt().strftime("%Y-%m-%d")
    ayer = (ahora_brt() - timedelta(days=1)).strftime("%Y-%m-%d")
    marca = leer_marca()

    print("=" * 78)
    print("  RESET DIARIO DEL CICLO")
    print("=" * 78)
    print(f"  ahora (Brasilia): {ahora_brt().strftime('%d/%m/%Y %H:%M')}")
    print(f"  último reset    : {marca.get('ultimo_dia', '(nunca)')}")

    if ya_reiniciado_hoy(marca) and not forzar:
        print("  El ciclo de hoy YA está abierto. Nada que hacer.")
        print("=" * 78)
        return 0

    print(f"  -> Abriendo el ciclo del {hoy}")
    if seco:
        print("  [SECO] no se modifica nada")
        return 0

    print()
    print("  [1/6] Archivando el día anterior...")
    copiados = archivar_dia(ayer)
    print(f"        {len(copiados)} ficheros -> logs/historial/{ayer}/")

    print("  [2/6] Vaciando la fila (se regenerará con datos nuevos)...")
    print(f"        fila {vaciar_fila(hoy)}")

    print("  [3/6] Revalidando cupones...")
    vig, venc = marcar_cupones_vencidos(hoy)
    print(f"        vigentes: {vig} | vencidos: {venc}")

    print("  [4/6] Limpiando temporales viejos...")
    print(f"        {limpiar_temporales()} ficheros borrados")

    print("  [5/6] Rotando el log de validación...")
    print(f"        {limpiar_log_validacion()} líneas antiguas quitadas")

    print("  [6/6] Registrando la apertura del ciclo...")
    nueva = {
        "ultimo_dia": hoy,
        "ultimo_reset": ahora_brt().isoformat(timespec="seconds"),
        "dia_archivado": ayer,
        "cupones_vigentes": vig,
        "cupones_vencidos": venc,
        "archivados": copiados,
        "nota": ("La fila se vacía y se regenera con datos del día. NO se borran "
                 "logs/enviados.json ni precios.db: son el histórico que permite "
                 "detectar bajadas de precio."),
    }
    _guardar_json(MARCA, nueva)

    # Rastro en el log de validación, para poder auditar los ciclos
    try:
        with (LOGS / "validacion.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "resultado": "RESET_DIARIO",
                "producto": f"ciclo {hoy}",
                "motivo": (f"día {ayer} archivado; fila vaciada; "
                           f"{vig} cupones vigentes, {venc} vencidos"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    print()
    print("  CICLO ABIERTO. El bot regenerará ofertas, cupones y enlaces.")
    print("=" * 78)
    return 0


def main():
    forzar = "--forzar" in sys.argv
    seco = "--test" in sys.argv or "--seco" in sys.argv
    if "--estado" in sys.argv:
        m = leer_marca()
        print(f"  último reset: {m.get('ultimo_dia', '(nunca)')}")
        print(f"  abierto hoy : {'sí' if ya_reiniciado_hoy() else 'NO'}")
        return 0
    return ejecutar(forzar=forzar, seco=seco)


if __name__ == "__main__":
    sys.exit(main())
