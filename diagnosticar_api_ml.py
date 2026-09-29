#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Diagnóstico de la API de Mercado Livre (diagnosticar_api_ml.py)
=======================================================================
Comprueba QUÉ puede hacer realmente el token. Sirve para saber si faltan
permisos en la aplicación sin tener que adivinar.

    python diagnosticar_api_ml.py
"""

import io
import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent

_env = BASE / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

TOKEN = os.environ.get("ML_ACCESS_TOKEN", "").strip()

# (ruta, descripción, si es imprescindible para el bot)
ENDPOINTS = [
    ("/users/me", "identidad", False),
    ("/sites/MLB", "sitio", False),
    ("/categories/MLB1051", "categoria", False),
    ("/currencies/BRL", "moneda", False),
    ("/items/MLB3896678839", "ITEM concreto", True),
    ("/products/MLB34928101", "producto de catalogo", True),
    ("/sites/MLB/search?q=monitor&limit=3", "busqueda", True),
    ("/trends/MLB", "tendencias", False),
]


def main():
    print("=" * 84)
    print("  DIAGNÓSTICO DE LA API DE MERCADO LIVRE")
    print("=" * 84)
    if not TOKEN:
        print("  No hay ML_ACCESS_TOKEN. Ejecuta: python obtener_token_ml.py --paso1")
        return 1

    try:
        import requests
    except ImportError:
        print("  Falta la librería requests.")
        return 1

    H = {"Authorization": f"Bearer {TOKEN}"}
    criticos_ok = 0
    criticos_total = 0
    fallos = []

    for ruta, desc, critico in ENDPOINTS:
        try:
            r = requests.get("https://api.mercadolibre.com" + ruta, headers=H, timeout=25)
        except Exception as e:
            print(f"  [ERR ]        {ruta:42s} {desc:22s} {type(e).__name__}")
            continue
        if critico:
            criticos_total += 1
        if r.status_code == 200:
            if critico:
                criticos_ok += 1
            extra = "OK"
            try:
                d = r.json()
                extra = f"{len(d)} campos" if isinstance(d, dict) else f"{len(d)} elementos"
            except Exception:
                pass
            print(f"  [ OK ] 200    {ruta:42s} {desc:22s} {extra}")
        else:
            msg = ""
            try:
                msg = r.json().get("message", "")[:46]
            except Exception:
                msg = r.text[:46].replace("\n", " ")
            marca = "[FALLO]" if critico else "[    ]"
            print(f"  {marca} {r.status_code}    {ruta:42s} {desc:22s} {msg}")
            if critico:
                fallos.append(desc)

    # Datos del usuario
    print()
    try:
        r = requests.get("https://api.mercadolibre.com/users/me", headers=H, timeout=25)
        if r.status_code == 200:
            d = r.json()
            print(f"  usuario     : {d.get('nickname')} (id {d.get('id')})")
            print(f"  tipo        : {d.get('user_type')}")
            print(f"  tags        : {json.dumps(d.get('tags'), ensure_ascii=False)}")
            rep = (d.get("seller_reputation") or {})
            print(f"  vendedor    : {'sí (' + str(rep.get('level_id')) + ')' if rep.get('level_id') else 'NO'}")
    except Exception:
        pass

    print()
    print("=" * 84)
    if criticos_total and criticos_ok == criticos_total:
        print(f"  TODO CORRECTO: {criticos_ok}/{criticos_total} comprobaciones clave pasan.")
        print("  El bot puede verificar precio, stock y disponibilidad de verdad.")
    else:
        print(f"  FALTAN PERMISOS: {criticos_ok}/{criticos_total} comprobaciones clave pasan.")
        print()
        # No es lo mismo "nada funciona" que "el catálogo sí y solo falta el
        # precio". Medido en este proyecto:
        #   /products/{id} -> 200 con un id válido (catálogo YA funciona)
        #   /items/{id}    -> 403 (falta el permiso de publicaciones)
        #   buy_box_winner -> null, y AHÍ vive el precio
        if any("producto de catalogo" in f for f in fallos):
            print("  [!] CATÁLOGO: revisa que el tópico 'catalog' esté marcado.")
        else:
            print("  [OK] CATÁLOGO funciona. Ya se puede verificar que el producto")
            print("       EXISTE, que está ACTIVO y que el nombre real coincide con el")
            print("       del post. Eso detecta enlaces equivocados y ofertas muertas.")
        print()
        if any("ITEM concreto" in f for f in fallos):
            print("  [!] PUBLICACIONES (items): esto es lo que FALTA. Sin este permiso")
            print("      NO HAY PRECIO, porque vive en buy_box_winner y viene vacío.")
        print()
        print("  QUÉ HACER (en el devcenter de Mercado Livre):")
        print("     1. Abre tu aplicación y pulsa Editar.")
        print("     2. Comprueba que NO haya ningún error rojo en el formulario:")
        print("        un error de validación impide GUARDAR y parece que no")
        print("        hiciste nada. Suele ser el campo de notificaciones ->")
        print("        déjalo VACÍO o pon https://achadinhosnozap.com.br")
        print("     3. En PERMISSÕES pon:")
        print("          Publicação e sincronização   ->  Leitura")
        print("          Promoções, cupons e descontos->  Leitura")
        print("          Usuários                     ->  Leitura e escrita")
        print("     4. En TÓPICOS marca las casillas PRINCIPALES de:")
        print("          items   prices   catalog   promotions")
        print("        (cada uno despliega sub-opciones; basta el principal, o usa")
        print("         'Selecionar Todos' dentro de cada uno)")
        print("     5. Guarda y comprueba que no sale error rojo.")
        print("     6. VUELVE A AUTORIZAR: el token viejo NO hereda permisos nuevos.")
        print("        Doble clic en REAUTORIZAR_ML.bat, o a mano:")
        print("          python obtener_token_ml.py --paso2 --abrir")
        print("          python obtener_token_ml.py --code <CODIGO>")
        print("     7. Vuelve a ejecutar este diagnóstico.")
    print("=" * 84)
    return 0 if criticos_ok == criticos_total else 2


if __name__ == "__main__":
    sys.exit(main())
