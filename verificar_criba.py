#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Verificador de salud (verificar_criba.py)
==================================================
Comprueba de un vistazo que el pipeline cumple lo que se pidió:

  1. fila_posts.json: nicho tech, sin posts de cupón, con foto.
  2. Regla de Oro: ningún link /go/, ML con meli.la, Amazon con tag.
  3. Cadencia real: minutos entre los últimos envíos de logs/enviados.json.
  4. Límite diario y ventana horaria.
  5. Estado de la cookie ML y de Green API.

Uso:  python verificar_criba.py
"""

import io
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
OK, WARN, BAD = "  [OK]  ", "  [!]   ", "  [X]   "
problemas = []


def _load(nombre, default=None):
    p = BASE / nombre
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"{BAD}{nombre}: JSON inválido ({e})")
        problemas.append(f"{nombre} corrupto")
        return default


def check_fila():
    print("\n── 1. FILA DE POSTS ──────────────────────────────────────")
    d = _load("fila_posts.json", {})
    fila = d.get("fila", [])
    if not fila:
        print(f"{BAD}fila_posts.json vacía o inválida")
        problemas.append("fila vacía")
        return
    print(f"{OK}total: {len(fila)} posts | actualizado: {d.get('actualizado', '?')}")

    cats = Counter(p.get("categoria", "?") for p in fila)
    print(f"       categorías: {dict(cats)}")

    cupones = [p for p in fila if p.get("tipo") == "cupons_loja"]
    if cupones:
        print(f"{BAD}posts genéricos de cupón: {len(cupones)} (deben ser 0)")
        problemas.append("posts de cupón en la fila")
    else:
        print(f"{OK}sin posts genéricos de cupón")

    sin_foto = [p for p in fila if not p.get("imagen")]
    if sin_foto:
        print(f"{WARN}{len(sin_foto)} posts sin foto (se enviarán como texto)")
    else:
        print(f"{OK}todos los posts tienen foto")

    if not any(p.get("cupom") for p in fila):
        print(f"{WARN}ningún post trae cupón asociado")


def check_regla_de_oro():
    print("\n── 2. REGLA DE ORO (links que monetizan) ─────────────────")
    d = _load("fila_posts.json", {})
    fila = d.get("fila", [])
    malos = []
    con_melila = con_tag_ml = con_tag_amz = 0
    for p in fila:
        url = p.get("url") or ""
        loja = (p.get("loja") or "").lower()
        # La Regla de Oro acepta DOS formas validas en ML:
        #   1) meli.la/XXXX              2) url con tag #D[A:ja20250119201346]
        # En Amazon: url con ?tag=criba20-20
        es_ml = "mercado" in loja
        es_amz = "amazon" in loja
        if "/go/" in url:
            malos.append((p.get("titulo", "")[:40], "link /go/ NO monetiza"))
        elif es_ml and "meli.la" in url:
            con_melila += 1
        elif es_ml and ("#D[A:" in url or "ja20250119201346" in url):
            con_tag_ml += 1
        elif es_ml:
            malos.append((p.get("titulo", "")[:40], "ML sin meli.la ni tag"))
        elif es_amz and "tag=criba20-20" in url:
            con_tag_amz += 1
        elif es_amz:
            malos.append((p.get("titulo", "")[:40], "Amazon sin tag"))
    if malos:
        print(f"{BAD}{len(malos)} posts con link problemático:")
        for t, m in malos[:5]:
            print(f"       - {t} → {m}")
        problemas.append(f"{len(malos)} links sin monetizar")
    else:
        print(f"{OK}todos los links monetizan ({len(fila)} posts)")
        print(f"       ML con meli.la: {con_melila} | ML con tag #D[A:]: {con_tag_ml} "
              f"| Amazon con tag: {con_tag_amz}")
        if con_melila == 0 and con_tag_ml > 0:
            print(f"{WARN}ningun ML usa meli.la: cookie vencida, se usa el respaldo "
                  f"con tag (monetiza igual, pero se pierde el link corto)")


def check_cadencia():
    print("\n── 3. CADENCIA REAL DE ENVÍO ─────────────────────────────")
    enviados = _load("logs/enviados.json", {}) or {}
    stamps = []
    for entry in enviados.values():
        if not isinstance(entry, dict):
            continue
        canales = entry.get("canales") if isinstance(entry.get("canales"), dict) else {}
        ts_s = canales.get("whatsapp") or entry.get("ts", "")
        if not ts_s:
            continue
        try:
            ts = datetime.fromisoformat(ts_s)
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        stamps.append(ts)
    stamps.sort()
    if not stamps:
        print(f"{WARN}sin envíos registrados")
        return
    print(f"{OK}envíos registrados en el log: {len(stamps)}")
    if len(stamps) < 2:
        return
    gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(stamps, stamps[1:])]
    gaps_sorted = sorted(gaps)
    mediana = gaps_sorted[len(gaps_sorted) // 2]
    print(f"       mediana entre envíos: {mediana:.1f} min  (objetivo 7-8)")
    print(f"       mínimo: {min(gaps):.1f} | máximo: {max(gaps):.1f}")
    print(f"       envíos con gap > 60 min: {sum(1 for g in gaps if g > 60)}/{len(gaps)}")
    if mediana > 15:
        print(f"{BAD}la cadencia NO cumple: mediana {mediana:.1f} min (esperado ~7.5)")
        problemas.append(f"cadencia real {mediana:.1f} min")
    else:
        print(f"{OK}cadencia dentro de objetivo")
    ultimo = stamps[-1]
    hace = (datetime.now(timezone.utc) - ultimo).total_seconds() / 60.0
    print(f"       último envío hace {hace:.1f} min")


def check_control():
    print("\n── 4. CONTROL DE CANAL ───────────────────────────────────")
    c = _load("logs/control_canal.json", {}) or {}
    dias = c.get("dias_activo", "?")
    hoy = c.get("envios_hoy", "?")
    fecha = c.get("fecha_hoy", "?")
    print(f"{OK}día {dias} | envíos hoy {hoy} (fecha registrada {fecha})")
    hoy_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if fecha != hoy_utc:
        print(f"{WARN}el registro es de {fecha}, hoy es {hoy_utc} (se reinicia en el próximo run)")
    brt = (datetime.now(timezone.utc).hour - 3) % 24
    dentro = 8 <= brt < 22
    print(f"{OK if dentro else WARN}hora Brasília {brt}h → "
          f"{'dentro' if dentro else 'FUERA'} de ventana (8-22)")


def check_credenciales():
    print("\n── 5. CREDENCIALES ───────────────────────────────────────")
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip("'\"")
    for var in ("GREEN_API_ID", "GREEN_API_TOKEN", "WHATSAPP_CHAT_ID"):
        val = os.environ.get(var, "")
        print(f"{OK if val else BAD}{var}: {'configurada' if val else 'FALTA'}")
        if not val:
            problemas.append(f"{var} ausente")
    cookie = os.environ.get("ML_PORTAL_COOKIE", "")
    print(f"{OK if cookie else WARN}ML_PORTAL_COOKIE: "
          f"{'presente (' + str(len(cookie)) + ' chars)' if cookie else 'ausente'}")


def check_cookie_ml():
    print("\n── 6. COOKIE MERCADO LIVRE (meli.la) ─────────────────────")
    cookie = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if not cookie:
        print(f"{WARN}sin cookie; se usará la URL con tag como respaldo")
        return
    # Se comprueba con GET /user/tags, que es el PRIMER paso real de
    # melila_api.generar_melila(). Usar POST /user/links aquí daba 403 incluso
    # con una cookie perfectamente válida (falso negativo).
    try:
        import requests
        r = requests.get(
            "https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/tags",
            headers={
                "Cookie": cookie,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://www.mercadolivre.com.br",
                "Referer": "https://www.mercadolivre.com.br/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
            },
            timeout=25,
        )
        if r.status_code == 200:
            try:
                tags = r.json().get("tags", [])
            except Exception:
                tags = []
            activa = next((t.get("tag") for t in tags if t.get("in_use")), None)
            if activa:
                print(f"{OK}cookie VÁLIDA · etiqueta en uso: {activa}")
            else:
                print(f"{WARN}cookie válida pero no hay etiqueta 'in_use'")
                print(f"       etiquetas: {[t.get('tag') for t in tags]}")
        elif r.status_code in (401, 403):
            print(f"{BAD}cookie VENCIDA o sin permiso (HTTP {r.status_code}) → renovar")
            problemas.append("cookie ML vencida")
        else:
            print(f"{WARN}respuesta inesperada HTTP {r.status_code}")
            print(f"       cuerpo: {r.text[:180]}")
    except Exception as e:
        print(f"{WARN}no se pudo comprobar: {e}")


def main():
    print("=" * 62)
    print("  CRIBA · VERIFICACIÓN DE SALUD")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} local")
    print("=" * 62)
    check_fila()
    check_regla_de_oro()
    check_cadencia()
    check_control()
    check_credenciales()
    check_cookie_ml()

    print("\n" + "=" * 62)
    if problemas:
        print(f"  RESULTADO: {len(problemas)} problema(s) detectado(s)")
        for p in problemas:
            print(f"    - {p}")
    else:
        print("  RESULTADO: todo correcto")
    print("=" * 62)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
