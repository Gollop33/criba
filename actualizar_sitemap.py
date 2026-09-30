#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Actualizador del sitemap (actualizar_sitemap.py)
========================================================
Regenera sitemap.xml con la fecha de hoy.

Por qué importa para conseguir gente:
  El sitemap es lo primero que leen los buscadores al llegar. Sin él, Google
  tarda semanas en encontrar las páginas (o no las encuentra). Y el campo
  `lastmod` es la señal de frescura: un sitio de ofertas que se actualiza cada
  hora tiene que DECIRLO, o Google lo trata como contenido muerto.

Se ejecuta en cada corrida del bot, después de escribir los datos.
"""

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
DOMINIO = "https://achadinhosnozap.com.br"

# (ruta, frecuencia de cambio, prioridad)
PAGINAS = [
    ("/", "hourly", "1.0"),
    ("/ofertas.html", "hourly", "0.9"),
    ("/cupones.html", "daily", "0.8"),
    ("/tiendas.html", "weekly", "0.5"),
    ("/privacidad.html", "monthly", "0.2"),
]


def main():
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Generado por actualizar_sitemap.py. NO editar a mano. -->",
        "<!-- El sitemap es lo primero que leen los buscadores: sin el, Google",
        "     tarda semanas en indexar las paginas. El lastmod es la senal de",
        "     frescura: un sitio de ofertas tiene que decir que se actualiza. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for ruta, freq, prio in PAGINAS:
        partes += [
            "  <url>",
            f"    <loc>{DOMINIO}{ruta}</loc>",
            f"    <lastmod>{hoy}</lastmod>",
            f"    <changefreq>{freq}</changefreq>",
            f"    <priority>{prio}</priority>",
            "  </url>",
        ]
    partes.append("</urlset>")
    partes.append("")

    (BASE / "sitemap.xml").write_text("\n".join(partes), encoding="utf-8")
    print(f"  sitemap.xml actualizado ({len(PAGINAS)} paginas, lastmod {hoy})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
