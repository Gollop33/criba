#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Lector de Telegram (leer_telegram.py)
==============================================
Lee los canales y grupos donde estás y saca de ahí:
  1. CUPONES  -> cupones.json   (canal oficial de afiliados de Mercado Livre)
  2. OFERTAS  -> ofertas_telegram.json (tus grupos de afiliados, que publican
                 ofertas en tiempo real)

Por qué esto vale dinero: hoy los cupones se copian A MANO a cupones_hoy.txt.
Los cupones de ML duran horas, así que para cuando los pegas ya valen menos.
Esto los captura en el momento.

Requiere:
  - TELEGRAM_API_ID / TELEGRAM_API_HASH
  - TELEGRAM_SESSION  (la genera login_telegram.py UNA vez)

Uso:
    python leer_telegram.py --listar      # ver todos tus canales y grupos
    python leer_telegram.py               # leer y extraer (lo que usa el bot)
    python leer_telegram.py --horas 6     # mirar las últimas 6 h
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
_env = BASE / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

API_ID = os.environ.get("TELEGRAM_API_ID", "").strip()
API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
SESSION = os.environ.get("TELEGRAM_SESSION", "").strip()

# Canal oficial de afiliados de Mercado Livre Brasil
CANAL_ML = "Afiliados e Criadores Mercado Livre Brasil"

# Palabras que identifican un canal/grupo de ofertas de afiliados
CLAVES_OFERTAS = ["afiliad", "achadin", "oferta", "promo", "cupom", "desconto",
                  "promoção", "barato"]

CUPONES_JSON = BASE / "cupones.json"
OFERTAS_JSON = BASE / "ofertas_telegram.json"

# ─── Extracción de cupones (mismo formato que cargar_cupones.py) ──────────────

RE_CUPON = re.compile(r"🎟️?\s*([A-Z][A-Z0-9]{3,24})\s*(?:👉|->|:)?\s*"
                      r"(\d+%\s*OFF|R\$\s*[\d.,]+\s*OFF)", re.IGNORECASE)


def extraer_cupones(texto, fecha_msg):
    """Extrae cupones de un mensaje del canal. Devuelve lista de dicts."""
    salida = []
    if "🎟" not in texto and "cupom" not in texto.lower() and "cupon" not in texto.lower():
        return salida

    # Cada cupón llega como un bloque: código + descuento + condiciones + link
    bloques = re.split(r"(?=🎟️?)", texto)
    for b in bloques:
        m = RE_CUPON.search(b)
        if not m:
            continue
        codigo = m.group(1).strip().upper()
        if codigo in ("CUPOM", "CUPONS", "CANAL", "AFILIADOS", "APENAS", "OFF"):
            continue
        descuento = re.sub(r"\s+", " ", m.group(2)).upper()

        m_min = re.search(r"(?:Compra\s*m[ií]nima|m[ií]nimo)[.:\s]*(?:de\s*)?(R\$\s*[\d.,]+)",
                          b, re.IGNORECASE)
        m_max = re.search(r"(?:Desconto\s*m[aá]x|limite|tope)[.:\s]*(?:de\s*)?(R\$\s*[\d.,]+)",
                          b, re.IGNORECASE)
        m_fecha = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", b)

        vencimiento = ""
        if m_fecha:
            try:
                dia, mes = int(m_fecha.group(1)), int(m_fecha.group(2))
                ano = m_fecha.group(3)
                ano = (int(ano) + 2000 if int(ano) < 100 else int(ano)) if ano \
                    else fecha_msg.year
                vencimiento = f"{ano}-{mes:02d}-{dia:02d}"
            except Exception:
                vencimiento = ""

        categoria = "Geral"
        if re.search(r"tecnolog|tech|inform[aá]tica|eletr", b, re.IGNORECASE):
            categoria = "Tecnologia"
        elif re.search(r"beleza|cuidado|perfum", b, re.IGNORECASE):
            categoria = "Beleza"
        elif re.search(r"m[oó]vei|casa|decora", b, re.IGNORECASE):
            categoria = "Casa"

        salida.append({
            "codigo": codigo,
            "desconto": descuento,
            "compra_minima": m_min.group(1) if m_min else "",
            "limite": m_max.group(1) if m_max else "",
            "hasta": vencimiento,
            "categoria": categoria,
            "tienda": "Mercado Livre",
            "fonte": "Telegram ML Afiliados",
            "detectado_em": fecha_msg.isoformat(),
            "vigente": True,
        })
    return salida


def extraer_ofertas(texto, fecha_msg):
    """
    Extrae ofertas de grupos de afiliados. Los mensajes suelen traer título,
    precio y un enlace de afiliado (meli.la, amzn.to, s.shopee.com.br).
    """
    salida = []
    enlaces = re.findall(r"https?://(?:meli\.la|amzn\.to|amazon\.com\.br|"
                         r"s\.shopee\.com\.br|mercadolivre\.com\.br)/\S+", texto)
    if not enlaces:
        return salida
    precios = re.findall(r"R\$\s*([\d.]+(?:,\d{2})?)", texto)
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    titulo = ""
    for l in lineas[:4]:
        if len(l) > 12 and "http" not in l and "R$" not in l:
            titulo = l[:140]
            break
    if not titulo:
        return salida
    salida.append({
        "titulo": titulo,
        "precio_texto": precios[0] if precios else "",
        "enlaces": enlaces[:3],
        "fonte": "Telegram grupo",
        "detectado_em": fecha_msg.isoformat(),
    })
    return salida


# ─── Lectura ──────────────────────────────────────────────────────────────────

def cargar_cupones_existentes():
    if not CUPONES_JSON.exists():
        return {"cupones": []}
    try:
        d = json.loads(CUPONES_JSON.read_text(encoding="utf-8-sig"))
        if isinstance(d, list):
            return {"cupones": d}
        d.setdefault("cupones", [])
        return d
    except Exception:
        return {"cupones": []}


async def listar():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    async with TelegramClient(StringSession(SESSION), int(API_ID), API_HASH) as c:
        print("=" * 76)
        print("  TUS CANALES Y GRUPOS")
        print("=" * 76)
        async for d in c.iter_dialogs():
            if d.is_channel or d.is_group:
                tipo = "canal" if d.is_channel else "grupo"
                print(f"  [{tipo:5s}] {d.name[:58]:60s} id={d.id}")
    return 0


async def leer(horas=12, max_por_chat=40):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    desde = datetime.now(timezone.utc) - timedelta(hours=horas)
    cupones_nuevos, ofertas_nuevas, resumen = [], [], []

    async with TelegramClient(StringSession(SESSION), int(API_ID), API_HASH) as c:
        async for d in c.iter_dialogs():
            if not (d.is_channel or d.is_group):
                continue
            nombre = d.name or ""
            bajo = nombre.lower()
            es_ml = "afiliados e criadores" in bajo or "mercado livre" in bajo
            es_ofertas = any(k in bajo for k in CLAVES_OFERTAS)
            if not (es_ml or es_ofertas):
                continue

            leidos = 0
            try:
                async for msg in c.iter_messages(d, limit=max_por_chat):
                    if not msg.message or not msg.date:
                        continue
                    if msg.date < desde:
                        break
                    leidos += 1
                    if es_ml:
                        cupones_nuevos.extend(extraer_cupones(msg.message, msg.date))
                    if es_ofertas or es_ml:
                        ofertas_nuevas.extend(extraer_ofertas(msg.message, msg.date))
            except Exception as e:
                print(f"  [!] {nombre[:40]}: {e}")
                continue
            if leidos:
                resumen.append((nombre, leidos, es_ml))

    # ── Guardar cupones (sin duplicar) ────────────────────────────────────────
    datos = cargar_cupones_existentes()
    por_codigo = {str(x.get("codigo", "")).upper(): x for x in datos["cupones"]}
    nuevos = 0
    for cup in cupones_nuevos:
        cod = cup["codigo"]
        if cod in por_codigo:
            # Actualizar condiciones si el cupón ya existía
            por_codigo[cod].update({k: v for k, v in cup.items() if v})
        else:
            por_codigo[cod] = cup
            nuevos += 1
    datos["cupones"] = list(por_codigo.values())
    datos["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    CUPONES_JSON.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    # ── Guardar ofertas ───────────────────────────────────────────────────────
    vistas = set()
    unicas = []
    for o in ofertas_nuevas:
        clave = o["titulo"][:60]
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(o)
    OFERTAS_JSON.write_text(json.dumps(
        {"actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "total": len(unicas), "ofertas": unicas}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("=" * 76)
    print(f"  LEÍDOS {len(resumen)} canales/grupos (últimas {horas} h)")
    print("=" * 76)
    for nombre, n, es_ml in resumen:
        print(f"  {'[ML]' if es_ml else '    '} {nombre[:56]:58s} {n} mensajes")
    print()
    print(f"  Cupones detectados: {len(cupones_nuevos)} "
          f"({nuevos} nuevos) -> cupones.json")
    print(f"  Ofertas detectadas: {len(unicas)} -> ofertas_telegram.json")
    if cupones_nuevos:
        print()
        print("  Cupones:")
        for c in cupones_nuevos[:12]:
            print(f"     {c['codigo']:18s} {c['desconto']:9s} "
                  f"min={c['compra_minima'] or '-':9s} max={c['limite'] or '-':9s} "
                  f"hasta={c['hasta'] or '-'}")
    return 0


def main():
    if not SESSION:
        print("Falta TELEGRAM_SESSION.")
        print("Ejecuta primero:  python login_telegram.py")
        return 1
    horas = 12
    if "--horas" in sys.argv:
        i = sys.argv.index("--horas")
        if i + 1 < len(sys.argv):
            try:
                horas = int(sys.argv[i + 1])
            except ValueError:
                pass
    if "--listar" in sys.argv:
        return asyncio.run(listar())
    return asyncio.run(leer(horas=horas))


if __name__ == "__main__":
    sys.exit(main())
