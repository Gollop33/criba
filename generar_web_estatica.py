#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Página web estática (generar_web_estatica.py)
======================================================
Cocina las ofertas DENTRO del HTML para que se vean sin ejecutar JavaScript.

POR QUÉ EXISTE (2026-10-08)
---------------------------
Awin RECHAZÓ la solicitud de Jose Alcala al programa VX Case BR con el motivo
"URL inativo, página não encontrada". El sitio estaba perfecto (todas las
páginas respondían 200 y achados.json servía 259 ofertas)... pero las ofertas
se pintaban con JavaScript:

    LINKS = await (await fetch('links.json')).json()
    const d = await (await fetch('achados.json')).json()

Un revisor AUTOMÁTICO no ejecuta JavaScript. Lo que ve al pedir el HTML es una
página con CERO precios y CERO productos: para él, el sitio está vacío. Y eso
mismo le pasa a buena parte de los buscadores.

QUÉ HACE
--------
Coge achados.json + cupones.json y escribe tarjetas REALES (título, precio,
descuento, imagen y enlace de afiliado) dentro de los marcadores
    <!-- ESTATICO:INICIO --> ... <!-- ESTATICO:FIN -->
de index.html y ofertas.html.

El JavaScript del sitio sigue funcionando igual: al cargar, reemplaza el
contenido del contenedor con la versión dinámica. Si el visitante no tiene
JavaScript (o es un robot que no lo ejecuta), ve las ofertas estáticas.

Uso:
    python generar_web_estatica.py
    python generar_web_estatica.py --max 60
"""

import html
import io
import json
import os
import re
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
CUPONES = BASE / "cupones.json"
CONFIG = BASE / "config_afiliados.json"

MAX_OFERTAS = 48

INICIO = "<!-- ESTATICO:INICIO -->"
FIN = "<!-- ESTATICO:FIN -->"
PAGINAS = ("index.html", "ofertas.html")


def log(msg):
    print(f"  {msg}", flush=True)


def brl(valor):
    try:
        return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def cargar(path, clave="achados"):
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(d, dict):
        return d.get(clave) or []
    return d if isinstance(d, list) else []


def link_de(item):
    """Enlace corto propio si existe; si no, el enlace con tag (nunca /go/ ajeno)."""
    for campo in ("url_corta", "url"):
        u = str(item.get(campo) or "").strip()
        if u.startswith("http"):
            return u
    return ""


def tarjeta(item):
    nombre = html.escape(str(item.get("nombre") or "Oferta")[:110])
    precio = brl(item.get("precio"))
    anterior = brl(item.get("precio_anterior"))
    tienda = html.escape(str(item.get("loja") or ""))
    imagen = str(item.get("imagen") or "").strip()
    link = html.escape(link_de(item))
    try:
        desc = int(round(float(item.get("desc_pct") or 0)))
    except (TypeError, ValueError):
        desc = 0
    cupon = str(item.get("cupon") or "").strip()

    badge = f'<span class="badge">-{desc}%</span>' if desc >= 5 else ""
    was = f'<span class="was">{anterior}</span>' if anterior else ""
    extra = f"🎟️ {html.escape(cupon)}" if cupon else "💠 Pix 5% OFF"
    img = (f'<img src="{html.escape(imagen)}" loading="lazy" alt="{nombre}" '
           f'referrerpolicy="no-referrer">') if imagen else ""

    return (
        '<article class="card">'
        f'<div class="thumb">{img}{badge}<span class="chip">{tienda}</span></div>'
        '<div class="body">'
        f"<h3>{nombre}</h3>"
        f'<div class="prices"><span class="now">{precio}</span>{was}</div>'
        f'<div class="store">Loja: <b>{tienda}</b> · <span>{extra}</span></div>'
        f'<div class="links"><a class="btn" target="_blank" rel="nofollow noopener" '
        f'href="{link}">Ver achado 🔥</a></div>'
        "</div></article>"
    )


def tarjeta_cupon(c):
    codigo = html.escape(str(c.get("codigo") or ""))
    if not codigo:
        return ""
    desc = html.escape(str(c.get("desconto") or "Cupom ativo"))
    tienda = html.escape(str(c.get("tienda") or "Mercado Livre"))
    return (
        '<article class="card">'
        f'<div class="body"><h3>🎟️ {desc} — {codigo}</h3>'
        f'<div class="store">Loja: <b>{tienda}</b> · <span>ative no carrinho</span></div>'
        '<div class="links"><a class="btn" target="_blank" rel="nofollow noopener" '
        'href="cupones.html">Ver todos os cupons 🎟️</a></div>'
        "</div></article>"
    )


def bloque_estatico(ofertas, cupones, maximo):
    partes = []
    for c in cupones[:4]:
        t = tarjeta_cupon(c)
        if t:
            partes.append(t)
    for o in ofertas[:maximo]:
        t = tarjeta(o)
        if t:
            partes.append(t)
    if not partes:
        return ""
    fecha = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    cabecera = (f'<p class="mono" style="opacity:.65;grid-column:1/-1">'
                f"✅ {len(partes)} ofertas verificadas · atualizado em {fecha}</p>")
    return INICIO + cabecera + "".join(partes) + FIN


def inyectar(path, bloque):
    if not path.exists():
        return False, "no existe"
    texto = path.read_text(encoding="utf-8")
    if INICIO in texto and FIN in texto:
        nuevo = re.sub(re.escape(INICIO) + r".*?" + re.escape(FIN), bloque,
                       texto, count=1, flags=re.DOTALL)
    else:
        return False, "sin marcadores"
    if nuevo == texto:
        return False, "sin cambios"
    path.write_text(nuevo, encoding="utf-8")
    return True, "ok"


def main():
    maximo = MAX_OFERTAS
    if "--max" in sys.argv:
        try:
            maximo = int(sys.argv[sys.argv.index("--max") + 1])
        except Exception:
            pass

    print("=" * 64)
    print("  CRIBA · PÁGINA ESTÁTICA (ofertas visibles sin JavaScript)")
    print("=" * 64)

    ofertas = cargar(ACHADOS, "achados")
    cupones = [c for c in cargar(CUPONES, "cupones")
               if isinstance(c, dict) and c.get("codigo")]
    # Solo ofertas con enlace y precio: nada de tarjetas vacías
    ofertas = [o for o in ofertas if isinstance(o, dict)
               and link_de(o) and o.get("precio")]

    log(f"Ofertas con enlace y precio: {len(ofertas)} | Cupones: {len(cupones)}")

    bloque = bloque_estatico(ofertas, cupones, maximo)
    if not bloque:
        log("⚠️  No hay material: no se toca ninguna página.")
        return 1

    tocadas = 0
    for nombre in PAGINAS:
        ok, motivo = inyectar(BASE / nombre, bloque)
        log(f"{nombre:16s} -> {motivo}")
        tocadas += 1 if ok else 0

    # Comprobación honesta: ¿el HTML tiene ya precios de verdad?
    verificado = 0
    for nombre in PAGINAS:
        try:
            t = (BASE / nombre).read_text(encoding="utf-8")
            verificado += 1 if t.count("R$") > 10 and "class=\"card\"" in t else 0
        except Exception:
            pass

    print("-" * 64)
    log(f"Páginas actualizadas: {tocadas} | con ofertas estáticas dentro: {verificado}")
    log(f"Tarjetas escritas: {bloque.count('class=\"card\"')}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
