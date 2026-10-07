#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Pruebas offline del agente Amazon (probar_amazon.py)
============================================================
No toca la red. Lo que se vigila aquí es LA REGLA Nº1 del proyecto: no publicar
datos inventados.

Contexto (bug real, encontrado el 2026-10-02):
  `cosechar_pelando_amazon()` metía precio fijo 89,90 y descuento inventado en
  artículos que además eran páginas de CAMPAÑA, no productos. De 37 artículos,
  30 son campañas y solo 1 es una ficha; aun así salían 34 "ofertas".
  Estas pruebas impiden que eso vuelva.

Uso: python probar_amazon.py
"""
import base64
import io
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import agente_amazon as az

FALLOS = []
PRUEBAS = 0


def check(nombre, condicion, detalle=""):
    global PRUEBAS
    PRUEBAS += 1
    if condicion:
        print(f"  [OK]   {nombre}")
    else:
        print(f"  [FALLO] {nombre} {detalle}")
        FALLOS.append(nombre)


def enlace_pelando(destino):
    """Genera el redirect de Pelando (base64) como el de la web real."""
    payload = base64.urlsafe_b64encode(json.dumps({"url": destino}).encode()).decode().rstrip("=")
    return f"https://dpl.pelando.com.br/r/xxx.{payload}"


def html_pelando(articulos):
    trozos = []
    for titulo, destino in articulos:
        trozos.append(
            f'<article><h3>{titulo}</h3>'
            f'<a href="{enlace_pelando(destino)}">ir</a>'
            f'<img src="https://img/pelando.jpg"></article>'
        )
    return "<html><body>" + "".join(trozos) + "</body></html>"


FICHA_OK = """
<html><body>
<span id="productTitle">Fogão Electrolux Efficient 4 bocas</span>
<span class="a-price"><span class="a-offscreen">R$1.420,30</span></span>
<span class="a-price"><span class="a-offscreen">R$1.499,00</span></span>
<span class="a-text-price"><span class="a-offscreen">R$1.499,00</span></span>
<img id="landingImage" src="https://m.media-amazon.com/images/I/fogao.jpg">
</body></html>
"""

FICHA_SIN_PRECIO = """
<html><body><span id="productTitle">Producto sin precio visible</span></body></html>
"""


class Resp:
    def __init__(self, texto, status=200):
        self.text, self.status_code, self.content = texto, status, texto.encode()
        self.url = ""


def main():
    print("=" * 68)
    print("  CRIBA · PRUEBAS OFFLINE · AGENTE AMAZON")
    print("=" * 68)

    # ── 1. parse_precio ──────────────────────────────────────────────────────
    check("parse_precio('R$ 1.420,30')", az.parse_precio("R$ 1.420,30") == 1420.30)
    check("parse_precio('R$1.499,00')", az.parse_precio("R$1.499,00") == 1499.00)
    check("parse_precio('sin precio') es None", az.parse_precio("sin precio") is None)
    check("parse_precio('') es None", az.parse_precio("") is None)

    # ── 2. Ficha de producto: precio real ────────────────────────────────────
    import requests
    real_get = requests.get
    try:
        requests.get = lambda *a, **k: Resp(FICHA_OK)
        ficha = az.datos_ficha_amazon("https://www.amazon.com.br/dp/B0FVP2TLX5")
        check("lee el título de la ficha", ficha and ficha["titulo"].startswith("Fogão Electrolux"))
        check("lee el precio más bajo como actual", ficha and ficha["precio"] == 1420.30)
        check("lee el precio de lista como anterior", ficha and ficha["precio_anterior"] == 1499.00)
        check("lee la imagen", ficha and ficha["imagen"].endswith("fogao.jpg"))

        requests.get = lambda *a, **k: Resp(FICHA_SIN_PRECIO)
        check("ficha sin precio -> None (no se estima)", az.datos_ficha_amazon("x") is None)

        requests.get = lambda *a, **k: Resp("", status=500)
        check("HTTP 500 -> None", az.datos_ficha_amazon("x") is None)
    finally:
        requests.get = real_get

    # ── 3. Pelando: solo productos reales, con precio real ───────────────────
    articulos = [
        ("Fogão Electrolux com 5% OFF", "https://www.amazon.com.br/dp/B0FVP2TLX5?ref=psp"),
        ("Cupom de 15% OFF em Itens Walita", "https://www.amazon.com.br/promotion/psp/AE3R0SX0Q51E7"),
        ("Ganhe cupom de até R$1000 off", "https://www.amazon.com.br/b?node=220818659011"),
        ("Producto sin precio", "https://www.amazon.com.br/dp/B0AAAAAAA1"),
        ("Otro producto repetido", "https://www.amazon.com.br/dp/B0FVP2TLX5"),
    ]
    html_p = html_pelando(articulos)

    llamadas = {"fichas": 0}

    def fake_get(url, **k):
        if "pelando" in url:
            return Resp(html_p)
        llamadas["fichas"] += 1
        if "B0AAAAAAA1" in url:
            return Resp(FICHA_SIN_PRECIO)
        return Resp(FICHA_OK)

    import time as _time
    real_sleep = _time.sleep
    _time.sleep = lambda *a, **k: None          # sin esperas en las pruebas
    try:
        requests.get = fake_get
        items = az.cosechar_pelando_amazon(max_fichas=10)
    finally:
        requests.get = real_get
        _time.sleep = real_sleep

    check("solo entra el producto de verdad (1 de 5 artículos)", len(items) == 1,
          f"-> {len(items)}: {[i['nombre'][:30] for i in items]}")
    check("ya NO se inventa el precio 89,90 (bug corregido)",
          all(i["precio"] != 89.90 for i in items))
    check("el precio es el REAL de la ficha", items and items[0]["precio"] == 1420.30)
    check("el descuento sale de precios reales, no del título",
          items and items[0]["desc_pct"] == round((1499.00 - 1420.30) / 1499.00 * 100, 1))
    check("todas las URLs son fichas /dp/ con el tag",
          all("/dp/" in i["url"] and f"tag={az.AMAZON_TAG}" in i["url"] for i in items))
    check("ninguna URL apunta a una campaña",
          all("/promotion/" not in i["url"] and "/b?node=" not in i["url"] for i in items))
    check("trae imagen real", all(i["imagen"] for i in items))
    check("no se repite el mismo producto dos veces", llamadas["fichas"] == 2,
          f"-> fichas leídas: {llamadas['fichas']}")

    # ── 4. Si Amazon no responde, no hay ofertas (y no revienta) ─────────────
    try:
        requests.get = lambda *a, **k: Resp(html_p)   # solo Pelando responde
        items2 = az.cosechar_pelando_amazon(max_fichas=3)
    finally:
        requests.get = real_get
    check("si las fichas fallan, no se publica nada", items2 == [])

    # ── 5. Bestsellers con error HTTP: 0 ofertas y sin excepción ─────────────
    real_targets = az.AMAZON_TARGETS
    az.AMAZON_TARGETS = [("Prueba", "https://www.amazon.com.br/gp/bestsellers/x")]
    try:
        requests.get = lambda *a, **k: Resp("", status=503)
        items3 = az.cosechar_bestsellers()
    finally:
        requests.get = real_get
        az.AMAZON_TARGETS = real_targets
    check("bestsellers con HTTP 503 -> 0 ofertas, sin reventar", items3 == [])

    print("-" * 68)
    print(f"  {PRUEBAS - len(FALLOS)}/{PRUEBAS} pruebas OK")
    if FALLOS:
        print(f"  FALLARON: {', '.join(FALLOS)}")
        return 1
    print("  [OK] Todo correcto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
