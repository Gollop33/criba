#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Pruebas offline del cliente de Shopee (probar_shopee_api.py)
====================================================================
No toca la red. Verifica lo que sí se puede verificar sin credenciales:

  1. La firma SHA256 coincide con un vector calculado fuera de este código
     (si esto cambia, Shopee responde "Invalid Signature" y nada funciona).
  2. El formato de la cabecera Authorization es el que exige Shopee.
  3. La consulta GraphQL se construye bien (y no mete argumentos de más).
  4. `normalizar_oferta` traduce un nodo real al formato de achados.json
     sin inventar datos.
  5. Sin credenciales, `graphql()` corta ANTES de la red.
  6. Los enlaces de afiliado se reconocen por su host.

Uso: python probar_shopee_api.py
"""
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent

import shopee_api as shp

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


def main():
    print("=" * 68)
    print("  CRIBA · PRUEBAS OFFLINE · SHOPEE API")
    print("=" * 68)

    # ── 1. Firma contra vector externo ───────────────────────────────────────
    payload = '{"query":"{__typename}"}'
    esperado = "f0d6a59f0d8de771c81c3f89a7bebe5d4c77210acb73354b7c6af76c44b3db65"
    obtenido = shp.firma("1234567", 1700000000, payload, "s3cr3t")
    check("firma SHA256 = vector de control", obtenido == esperado,
          f"\n         esperado {esperado}\n         obtenido {obtenido}")
    check("la firma es hex de 64 caracteres",
          len(obtenido) == 64 and all(c in "0123456789abcdef" for c in obtenido))
    check("cambiar el secreto cambia la firma",
          shp.firma("1234567", 1700000000, payload, "otro") != obtenido)
    check("cambiar el timestamp cambia la firma",
          shp.firma("1234567", 1700000001, payload, "s3cr3t") != obtenido)
    check("el payload entra tal cual en el hash",
          shp.firma("1", 2, "x", "y") == hashlib.sha256(b"12xy").hexdigest())

    # ── 2. Cabecera Authorization ────────────────────────────────────────────
    cab = shp._cabeceras("1234567", 1700000000, payload, "s3cr3t")
    auth = cab.get("Authorization", "")
    check("Authorization empieza por 'SHA256 Credential='", auth.startswith("SHA256 Credential=1234567"))
    check("Authorization lleva Timestamp", "Timestamp=1700000000" in auth)
    check("Authorization lleva la Signature calculada", f"Signature={esperado}" in auth)
    check("Content-Type application/json", cab.get("Content-Type") == "application/json")

    # ── 3. Construcción de la consulta ───────────────────────────────────────
    capturado = {}

    def falso_graphql(query, timeout=25):
        capturado["query"] = query
        if "generateShortLink" in query:
            return {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/fake"}}}
        return {"data": {"productOfferV2": {"nodes": [{"itemId": 1}]}}}

    real = shp.graphql
    shp.graphql = falso_graphql
    try:
        nodos = shp.ofertas(keyword="air fryer", limit=30)
        q = capturado["query"]
        check("devuelve los nodes", nodos == [{"itemId": 1}])
        check("pide productOfferV2", "productOfferV2(" in q)
        check("incluye el keyword escapado", 'keyword: "air fryer"' in q)
        check("aplica el límite", "limit: 30" in q)
        check("NO manda 'page' cuando es la 1", "page:" not in q)
        check("NO manda 'sortType' por defecto", "sortType" not in q)
        check("pide los campos clave",
              all(c in q for c in ("productName", "offerLink", "priceDiscountRate", "commissionRate")))

        shp.ofertas(keyword="x", limit=999)
        check("el límite se recorta a 50", "limit: 50" in capturado["query"])
        shp.ofertas(keyword="x", page=3)
        check("manda 'page' cuando es > 1", "page: 3" in capturado["query"])

        try:
            shp.ofertas(item_id=99)
            check("item_id sin shop_id debe fallar", False)
        except shp.ShopeeAPIError:
            check("item_id sin shop_id debe fallar", True)

        corto = shp.link_corto("https://shopee.com.br/product/1/2", sub_ids=["zap"])
        ql = capturado["query"]
        check("la mutation de short link está bien formada",
              "generateShortLink(input:" in ql and "subIds:" in ql and "shortLink" in ql)
        check("devuelve el shortLink de la respuesta", corto == "https://s.shopee.com.br/fake")
    finally:
        shp.graphql = real

    # ── 4. Normalización de una oferta real ──────────────────────────────────
    nodo = {
        "productName": "Air Fryer 5L Antiaderente 1500W",
        "shopName": "Cozinha Top",
        "shopId": 555,
        "itemId": 999888,
        "offerLink": "https://s.shopee.com.br/abc123",
        "productLink": "https://shopee.com.br/product/555/999888",
        "price": "299.90",
        "commissionRate": "6.0",
        "commission": "17.99",
        "sales": 1234,
        "imageUrl": "https://cf.shopee.com.br/file/xyz",
        "priceDiscountRate": "25",
        "ratingStar": "4.8",
    }
    o = shp.normalizar_oferta(nodo)
    check("precio parseado", o["precio"] == 299.90)
    check("descuento parseado", o["desc_pct"] == 25.0)
    check("precio anterior derivado del % (299.90/0.75)", abs(o["precio_anterior"] - 399.87) < 0.05)
    check("usa offerLink y lo marca verificado",
          o["url"] == "https://s.shopee.com.br/abc123" and o["afiliado_verificado"] is True)
    check("id estable con el item_id", o["id"] == "shp-999888")
    check("loja = Shopee", o["loja"] == "Shopee")
    check("comisión guardada", o["comision_pct"] == 6.0 and o["comision_rs"] == 17.99)
    check("vendidos y rating", o["vendidos"] == 1234 and o["rating"] == 4.8)

    # nodo sin offerLink -> NO se declara verificado (regla de oro)
    o2 = shp.normalizar_oferta({"itemId": 1, "productName": "X", "price": 10})
    check("sin offerLink no se marca verificado", o2["afiliado_verificado"] is False)
    check("sin offerLink la url queda vacía", o2["url"] == "")

    # sin descuento: no se inventa un precio anterior
    o3 = shp.normalizar_oferta({"itemId": 2, "productName": "Y", "price": 50, "priceDiscountRate": "0"})
    check("sin descuento no se inventa precio anterior", not o3["precio_anterior"])
    check("sin descuento desc_pct = 0", o3["desc_pct"] == 0.0)

    # ── 5. num() tolera los formatos que manda Shopee ────────────────────────
    check("num('61.32')", shp.num("61.32") == 61.32)
    check("num('R$ 1.234,56')", shp.num("R$ 1.234,56") == 1234.56)
    check("num('')", shp.num("") == 0.0)
    check("num(None)", shp.num(None) == 0.0)
    check("num(4.8)", shp.num(4.8) == 4.8)

    # ── 6. Sin credenciales no se toca la red ────────────────────────────────
    guardado = (os.environ.pop("SHOPEE_APP_ID", None), os.environ.pop("SHOPEE_SECRET_KEY", None))
    try:
        check("disponible() es False sin credenciales", shp.disponible() is False)
        try:
            shp.graphql("{__typename}")
            check("graphql() sin credenciales debe cortar", False)
        except shp.ShopeeAPIError as e:
            check("graphql() sin credenciales corta antes de la red", "credentiales" in str(e).lower() or "SHOPEE_APP_ID" in str(e))
    finally:
        for k, v in zip(("SHOPEE_APP_ID", "SHOPEE_SECRET_KEY"), guardado):
            if v is not None:
                os.environ[k] = v

    # ── 7. Reconocimiento de enlaces de afiliado ─────────────────────────────
    check("reconoce s.shopee.com.br", shp.es_link_afiliado("https://s.shopee.com.br/abc"))
    check("reconoce shp.ee", shp.es_link_afiliado("https://shp.ee/xyz"))
    check("NO acepta un enlace normal de producto",
          not shp.es_link_afiliado("https://shopee.com.br/product/1/2"))
    check("parsea /product/<shop>/<item>", shp.parsear_url("https://shopee.com.br/product/55/99") == ("55", "99"))
    check("parsea el formato -i.<shop>.<item>",
          shp.parsear_url("https://shopee.com.br/air-fryer-i.55.99") == ("55", "99"))
    check("URL sin producto devuelve vacío", shp.parsear_url("https://shopee.com.br/") == ("", ""))

    # ── 8. Cosechador de punta a punta (API simulada, sin red) ───────────────
    import agente_shopee as ag

    nodos_falsos = [
        {  # pasa: descuento alto + offerLink de la API (no gasta cuota)
            "productName": "Air Fryer 5L Mondial", "itemId": 101, "shopId": 1,
            "offerLink": "https://s.shopee.com.br/aaa", "productLink": "https://shopee.com.br/product/1/101",
            "price": "299.90", "priceDiscountRate": "25", "commissionRate": "6.0",
            "commission": "17.99", "sales": 900, "imageUrl": "https://img/1.jpg",
        },
        {  # pasa, pero sin offerLink -> hay que generar el corto
            "productName": "Fone Bluetooth TWS", "itemId": 102, "shopId": 1,
            "productLink": "https://shopee.com.br/product/1/102",
            "price": "89.90", "priceDiscountRate": "30", "commissionRate": "8.0",
            "commission": "7.19", "sales": 4000, "imageUrl": "https://img/2.jpg",
        },
        {  # VETADO (medicamento)
            "productName": "Medicamento para dor", "itemId": 103, "shopId": 1,
            "offerLink": "https://s.shopee.com.br/ccc", "price": "10", "priceDiscountRate": "80",
        },
        {  # descuento insuficiente
            "productName": "Panela simples", "itemId": 104, "shopId": 1,
            "offerLink": "https://s.shopee.com.br/ddd", "price": "50", "priceDiscountRate": "5",
        },
        {  # duplicado del primero (mismo nombre normalizado)
            "productName": "Air Fryer 5L Mondial", "itemId": 105, "shopId": 2,
            "offerLink": "https://s.shopee.com.br/eee", "price": "310", "priceDiscountRate": "28",
        },
    ]
    congelado = {"ofertas": shp.ofertas, "link_corto": shp.link_corto}
    shp.ofertas = lambda keyword=None, limit=50, **kw: nodos_falsos
    shp.link_corto = lambda url, sub_ids=None, **kw: "https://s.shopee.com.br/generado"
    try:
        achados, st = ag.cosechar(["air fryer"], min_desc=15.0, verbose=False)
        check("cosecha 2 ofertas de 5 (veto, descuento y duplicado fuera)", len(achados) == 2,
              f"-> {len(achados)}: {[a['nombre'] for a in achados]}")
        check("vetados contados", st["vetados"] == 1)
        check("poco descuento contado", st["poco_descuento"] == 1)
        check("duplicados contados", st["duplicados"] == 1)
        check("generó 1 link cuando faltaba offerLink", st["links_generados"] == 1)
        check("todas tienen enlace de afiliado verificado",
              all(a["afiliado_verificado"] and shp.es_link_afiliado(a["url"]) for a in achados))
        check("todas caducan (expira_em presente)", all(a.get("expira_em") for a in achados))
        check("todas marcadas como encontradas ahora", all(a.get("encontrado_em") for a in achados))
        check("ordenadas por descuento descendente",
              [a["desc_pct"] for a in achados] == sorted([a["desc_pct"] for a in achados], reverse=True))
        check("el achado sin offerLink usa el link generado",
              any(a["url"] == "https://s.shopee.com.br/generado" for a in achados))
    finally:
        shp.ofertas = congelado["ofertas"]
        shp.link_corto = congelado["link_corto"]

    # ── 9. Regla de oro en el unificador (no toca achados.json real) ─────────
    import tempfile
    import unir_achados as ua

    tmpdir = Path(tempfile.mkdtemp(prefix="criba_shopee_test_"))
    falso_shp = tmpdir / "achados_shopee.json"
    falso_out = tmpdir / "achados.json"
    ahora = datetime.now(timezone.utc)
    futuro = (ahora + timedelta(hours=20)).isoformat(timespec="seconds")
    pasado = (ahora - timedelta(hours=20)).isoformat(timespec="seconds")
    # Las ofertas reales SIEMPRE traen `encontrado_em` (lo escriben agente_ml,
    # agente_amazon y agente_shopee). El filtro de frescura de gerar_fila_posts
    # exige que sea de menos de 12 h.
    ahora_iso_fresco = (ahora - timedelta(hours=1)).isoformat(timespec="seconds")

    def item(nombre, url, verificado, expira):
        return {"id": nombre.lower(), "nombre": nombre, "precio": 100.0, "precio_anterior": 200.0,
                "desc_pct": 50.0, "url": url, "loja": "Shopee", "categoria": "Shopee Ofertas",
                "afiliado_verificado": verificado, "expira_em": expira}

    falso_shp.write_text(json.dumps({"achados": [
        item("Suporte de celular veicular", "https://s.shopee.com.br/valido1", True, futuro),
        item("Organizador de armario", "https://shopee.com.br/product/1/2", True, futuro),
        item("Cadeira de escritorio", "https://s.shopee.com.br/valido2", False, futuro),
        item("Tapete de banheiro", "https://s.shopee.com.br/valido3", True, pasado),
        item("Ventilador de coluna", "https://s.shopee.com.br/valido4", True, futuro),
    ]}, ensure_ascii=False), encoding="utf-8")

    originales = (ua.FILE_SHP, ua.FILE_OUT)
    ua.FILE_SHP, ua.FILE_OUT = falso_shp, falso_out
    try:
        entradas_ml = len(ua.cargar_items(ua.FILE_ML))
        entradas_az = len(ua.cargar_items(ua.FILE_AMZ))
        ua.main()
        salida = json.loads(falso_out.read_text(encoding="utf-8"))["achados"]
        shopee = [a for a in salida if a.get("loja") == "Shopee"]
        nombres = {a["nombre"] for a in shopee}
        check("unir_achados acepta el enlace corto verificado",
              "Suporte de celular veicular" in nombres and "Ventilador de coluna" in nombres)
        check("rechaza enlace de producto sin afiliado",
              "Organizador de armario" not in nombres)
        check("rechaza achado sin afiliado_verificado",
              "Cadeira de escritorio" not in nombres)
        check("rechaza achado caducado", "Tapete de banheiro" not in nombres)
        check("solo pasan 2 de 5 de Shopee", len(shopee) == 2, f"-> {sorted(nombres)}")
        # Se exige conservar al menos 100 de ML (o todos, si hay menos): la
        # deduplicación por nombre puede quitar unos pocos, no cientos.
        check("no se pierden las ofertas de ML/Amazon",
              sum(1 for a in salida if "Mercado" in (a.get("loja") or "")) >= min(entradas_ml, 100)
              and sum(1 for a in salida if "Amazon" in (a.get("loja") or "")) >= (entradas_az if entradas_az < 100 else 100),
              f"(entrada ML {entradas_ml} / Amazon {entradas_az})")
        check("el catálogo sale alternado por tienda (no todo ML al principio)",
              len({a.get("loja") for a in salida[:6]}) >= 2)
    finally:
        ua.FILE_SHP, ua.FILE_OUT = originales
        check("achados.json real intacto", (BASE_DIR / "achados.json").exists())

    # ── 10. La fila de posts acepta Shopee y NO le inventa cupón ─────────────
    import gerar_fila_posts as gf

    tmp2 = Path(tempfile.mkdtemp(prefix="criba_fila_test_"))
    achados = []

    def ml_item(i, nombre):
        return {"id": f"ml-{i}", "nombre": nombre, "precio": 100.0 + i, "precio_anterior": 200.0,
                "desc_pct": 50.0, "imagen": f"https://img/ml{i}.jpg", "loja": "Mercado Livre",
                "categoria": "Casa", "url": f"https://www.mercadolivre.com.br/x/p/MLB{i}#D[A:ja20250119201346]",
                "expira_em": futuro, "encontrado_em": ahora_iso_fresco}

    for i in range(20):
        achados.append(ml_item(i, ["Jogo de Panelas Antiaderente", "Aspirador de Po Vertical",
                                   "Organizador de Cozinha", "Toalha de Banho Kit"][i % 4] + f" {i}"))

    for i in range(6):
        achados.append({"id": f"shp-{i}", "nombre": f"Air Fryer Mondial Familia {i}",
                        "precio": 299.9, "precio_anterior": 399.9, "desc_pct": 25.0,
                        "imagen": f"https://img/shp{i}.jpg", "loja": "Shopee",
                        "categoria": "Shopee Ofertas",
                        "url": "https://s.shopee.com.br/valido" + str(i),
                        "afiliado_verificado": True, "expira_em": futuro,
                        "encontrado_em": ahora_iso_fresco})
    for i in range(3):
        achados.append({"id": f"shp-bad-{i}", "nombre": f"Ventilador de Coluna Ruim {i}",
                        "precio": 199.9, "precio_anterior": 250.0, "desc_pct": 20.0,
                        "imagen": "", "loja": "Shopee", "categoria": "Shopee Ofertas",
                        "url": f"https://shopee.com.br/product/1/{i}",  # enlace SIN afiliado
                        "afiliado_verificado": False, "expira_em": futuro,
                        "encontrado_em": ahora_iso_fresco})

    # Oferta REAL pero CON 3 DÍAS: el filtro de frescura (MAX_EDAD_HORAS=12) debe
    # dejarla fuera. Regla del usuario: "solo lo actualizado de menos de 12 h".
    achados.append({"id": "ml-viejo-1", "nombre": "Panela Electrica Antigua 5L",
                    "precio": 150.0, "precio_anterior": 300.0, "desc_pct": 50.0,
                    "imagen": "https://img/viejo.jpg", "loja": "Mercado Livre",
                    "categoria": "Casa",
                    "url": "https://www.mercadolivre.com.br/x/p/MLB999#D[A:ja20250119201346]",
                    "expira_em": futuro,
                    "encontrado_em": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")})

    (tmp2 / "achados.json").write_text(json.dumps({"achados": achados}, ensure_ascii=False), encoding="utf-8")
    (tmp2 / "cupones.json").write_text(json.dumps({"cupones": []}), encoding="utf-8")
    # Oferta de EJEMPLO (simulada): nunca debe llegar a la fila. El 2026-09-30
    # se publicó así un "SSD Kingston NV2 1TB" con precio inventado.
    (tmp2 / "achados_especificos.json").write_text(json.dumps({"achados": [
        {
            "id": "B0B94JY59Z", "nombre": "SSD Kingston NV2 1TB M.2 2280 NVMe PCIe 4.0",
            "precio": 389.90, "precio_anterior": 549.00, "desc_pct": 29.0,
            "imagen": "https://m.media-amazon.com/images/I/fake.jpg", "loja": "Amazon",
            "categoria": "Promoções Amazon", "url": "https://www.amazon.com.br/dp/B0B94JY59Z?tag=criba20-20",
            "simulado": True, "criado_em": "2026-10-01T00:00:00+00:00",
        },
        # El bug REAL de producción (2026-09-09, seguía vivo el 2026-10-07):
        # ofertas escritas por el curador automático SIN API key. No llevan
        # `simulado` (son anteriores a ese campo), así que se cazaban solas.
        {
            "id": "MLB34928101", "nombre": "Monitor Gamer LG UltraGear 27 Full HD IPS 144Hz",
            "precio": 849.0, "precio_anterior": 1299.0, "desc_pct": 34.0,
            "imagen": "https://http2.mlstatic.com/fake.webp", "loja": "Mercado Livre",
            "categoria": "Monitores & Displays",
            "url": "https://www.mercadolivre.com.br/x/p/MLB34928101#D[A:ja20250119201346]",
            "origem": "agente_autonomo_api", "criado_em": "2026-09-09T16:27:37+00:00",
            "encontrado_em": ahora_iso_fresco,
        },
    ]}, ensure_ascii=False), encoding="utf-8")

    guardado_gf = (gf.ACHADOS_JSON, gf.FILE_ML, gf.FILE_AMZ, gf.CUPONES_JSON,
                   gf.FILA_JSON, gf.ENVIADOS_JSON, gf.BASE)
    gf.BASE = tmp2
    gf.ACHADOS_JSON = tmp2 / "achados.json"
    gf.FILE_ML = tmp2 / "achados_ml.json"
    gf.FILE_AMZ = tmp2 / "achados_amazon.json"
    gf.CUPONES_JSON = tmp2 / "cupones.json"
    gf.FILA_JSON = tmp2 / "fila_posts.json"
    gf.ENVIADOS_JSON = tmp2 / "enviados.json"     # no existe -> sin enfriamiento
    os.environ["NICHO_MODO"] = "geral"
    try:
        gf.armar_fila_rotativa()
        fila = json.loads(gf.FILA_JSON.read_text(encoding="utf-8"))["fila"]
        shopee = [p for p in fila if p.get("loja") == "Shopee"]
        check("la fila incluye posts de Shopee", len(shopee) > 0, f"-> {len(shopee)}")
        check("solo entran los enlaces de afiliado verificados",
              all(shp.es_link_afiliado(p["url"]) for p in shopee))
        check("los enlaces de producto sin afiliado quedan fuera",
              not any("shopee.com.br/product/" in p["url"] for p in shopee))
        check("los posts de Shopee salen SIN cupón", all(not p.get("cupom") for p in shopee))
        check("los posts de Shopee salen sin Pix", all(not p.get("pix") for p in shopee))
        check("el reparto no se rompe: hay posts de ML",
              any("Mercado" in (p.get("loja") or "") for p in fila))
        check("Shopee no se come la fila (menos de la mitad)",
              len(shopee) < len(fila) / 2, f"-> {len(shopee)}/{len(fila)}")
        check("ningún post de la fila apunta a una tienda sin afiliado",
              all(("meli.la" in p["url"] or "D[A:" in p["url"] or shp.es_link_afiliado(p["url"]))
                  for p in fila))
        check("una oferta SIMULADA nunca entra en la fila",
              not any(p.get("id_post") == "B0B94JY59Z" for p in fila))
        check("una oferta de 3 días queda fuera (frescura < 12 h)",
              not any(p.get("id_post") == "ml-viejo-1" for p in fila))
        check("las ofertas del curador automático SIN API no entran",
              not any(p.get("id_post") == "MLB34928101" for p in fila))
    finally:
        (gf.ACHADOS_JSON, gf.FILE_ML, gf.FILE_AMZ, gf.CUPONES_JSON,
         gf.FILA_JSON, gf.ENVIADOS_JSON, gf.BASE) = guardado_gf

    # ── 11. El validador final acepta (y comprueba) un enlace de Shopee ──────
    import validador_oferta as val

    post_shp = {
        "loja": "Shopee", "titulo": "Air Fryer Mondial Family 5L Antiaderente",
        "precio": 299.9, "imagen": "https://img/shp.jpg",
        "url": "https://s.shopee.com.br/abc123",
    }
    real_resolver = val.resolver_enlace
    try:
        val.resolver_enlace = lambda u: "https://shopee.com.br/Air-Fryer-Mondial-Family-5L-Antiaderente-i.55.99"
        ok, det = val._validar_enlace(post_shp)
        check("el validador acepta el enlace corto de Shopee que resuelve al mismo producto", ok, f"-> {det}")

        val.resolver_enlace = lambda u: "https://shopee.com.br/Geladeira-Frost-Free-Duplex-i.55.77"
        ok2, det2 = val._validar_enlace(post_shp)
        check("el validador RECHAZA si el enlace lleva a otro producto", not ok2, f"-> {det2}")

        val.resolver_enlace = lambda u: u  # no se pudo resolver
        ok3, det3 = val._validar_enlace(post_shp)
        check("si el enlace corto no se puede resolver, avisa pero no descarta", ok3, f"-> {det3}")
        check("el aviso dice que no es verificable", "no verificable" in det3)

        post_ml = {"loja": "Mercado Livre", "titulo": "Jogo de Panelas", "precio": 100.0,
                   "imagen": "https://img/ml.jpg",
                   "url": "https://www.mercadolivre.com.br/jogo-de-panelas/p/MLB1#D[A:ja20250119201346]"}
        ok4, det4 = val._validar_enlace(post_ml)
        check("el validador sigue aceptando un enlace de ML con tag", ok4, f"-> {det4}")
    finally:
        val.resolver_enlace = real_resolver

    # ── 12. Candado de PAGOS: sin datos bancarios aprobados no se publica ────
    previo_flag = os.environ.pop("SHOPEE_PAGOS_APROBADOS", None)
    previo_pub = os.environ.pop("SHOPEE_APP_ID", None)
    previo_sec = os.environ.pop("SHOPEE_SECRET_KEY", None)
    tmp3 = Path(tempfile.mkdtemp(prefix="criba_pagos_test_"))
    originales_gate = (ag.OUTPUT_FILE, ag.esta_habilitado, ag.cosechar, ag.cargar_config)
    llamado = {"cosechar": False}

    def falso_cosechar(*a, **k):
        llamado["cosechar"] = True
        return [], {"consultas": 0, "consultas_fallidas": 0, "ofertas_vistas": 0,
                    "sin_enlace": 0, "links_generados": 0, "vetados": 0,
                    "poco_descuento": 0, "poca_comision": 0, "duplicados": 0,
                    "comisiones": [], "errores": []}

    ag.OUTPUT_FILE = tmp3 / "achados_shopee.json"
    ag.esta_habilitado = lambda: True          # simulamos que la API ya está
    ag.cosechar = falso_cosechar
    ag.cargar_config = lambda: {}              # y que el JSON no lo activa
    try:
        check("con pagos sin confirmar, pagos_confirmados() es False",
              ag.pagos_confirmados({}) is False)
        check("pagos_confirmados() acepta true en config",
              ag.pagos_confirmados({"pagos_aprobados": True}) is True)
        os.environ["SHOPEE_PAGOS_APROBADOS"] = "1"
        check("pagos_confirmados() acepta SHOPEE_PAGOS_APROBADOS=1",
              ag.pagos_confirmados({}) is True)
        os.environ.pop("SHOPEE_PAGOS_APROBADOS", None)

        ag.main([])   # sin --test: debe quedarse quieto y NO cosechar
        check("sin pagos aprobados NO se cosecha (no se trabaja gratis)",
              llamado["cosechar"] is False)
        check("sin pagos aprobados el fichero queda vacío",
              json.loads(ag.OUTPUT_FILE.read_text(encoding="utf-8"))["achados"] == [])

        os.environ["SHOPEE_PAGOS_APROBADOS"] = "1"
        ag.main([])   # con pagos aprobados: ahora sí cosecha
        check("con pagos aprobados SÍ se cosecha", llamado["cosechar"] is True)

        llamado["cosechar"] = False
        os.environ.pop("SHOPEE_PAGOS_APROBADOS", None)
        ag.main(["--test"])   # --test valida la API sin publicar nada
        check("--test funciona aunque los pagos no estén confirmados",
              llamado["cosechar"] is True)
    finally:
        (ag.OUTPUT_FILE, ag.esta_habilitado, ag.cosechar, ag.cargar_config) = originales_gate
        os.environ.pop("SHOPEE_PAGOS_APROBADOS", None)
        for k, v in (("SHOPEE_APP_ID", previo_pub), ("SHOPEE_SECRET_KEY", previo_sec),
                     ("SHOPEE_PAGOS_APROBADOS", previo_flag)):
            if v is not None:
                os.environ[k] = v

    # ── 13. Enlace de afiliado SIN API (/an_redir) y feed del portal ─────────
    previo_aid = os.environ.pop("SHOPEE_AFFILIATE_ID", None)
    try:
        # Sin ID no hay enlace posible
        try:
            shp.link_afiliado("https://shopee.com.br/product/1/2")
            check("sin ID de afiliado, link_afiliado debe fallar", False)
        except shp.ShopeeAPIError:
            check("sin ID de afiliado, link_afiliado debe fallar", True)

        os.environ["SHOPEE_AFFILIATE_ID"] = "14382300002"
        check("affiliate_id() limpia el formato 'an_...'",
              shp.affiliate_id() == "14382300002")

        enlace = shp.link_afiliado("https://shopee.com.br/Air-Fryer-i.55.99?utm_source=otro",
                                   sub_id="criba")
        check("el enlace va al dominio de afiliado de Shopee",
              enlace.startswith("https://s.shopee.com.br/an_redir?"))
        check("lleva el affiliate_id correcto", "affiliate_id=14382300002" in enlace)
        check("lleva sub_id para poder segmentar", "sub_id=criba" in enlace)
        check("limpia los parámetros de otro afiliado",
              "utm_source" not in enlace and "origin_link=https%3A%2F%2Fshopee.com.br%2FAir-Fryer-i.55.99" in enlace)
        check("origin_link() recupera el producto",
              shp.origin_link(enlace) == "https://shopee.com.br/Air-Fryer-i.55.99")
        check("es_link_afiliado reconoce el enlace", shp.es_link_afiliado(enlace))

        # Feed del portal: CSV con columnas en inglés (como el del portal)
        tmp4 = Path(tempfile.mkdtemp(prefix="criba_feed_test_"))
        feed = tmp4 / "shopee_feed.csv"
        feed.write_text(
            "Item ID;Product Name;Price;Original Price;Discount Rate;Commission Rate;"
            "Image URL;Product Link;Shop Name;Sales\n"
            "1;Air Fryer Mondial 5L;299,90;399,90;25%;6,5%;https://img/1.jpg;"
            "https://shopee.com.br/product/10/1;Mondial;1500\n"
            "2;Fone Bluetooth TWS;89,90;149,90;40%;8,0%;https://img/2.jpg;"
            "https://shopee.com.br/product/10/2;Audio;9000\n"
            "3;Medicamento para dor;19,90;39,90;50%;10%;https://img/3.jpg;"
            "https://shopee.com.br/product/10/3;Farmacia;10\n"
            "4;Panela sem desconto;219,00;219,00;0%;5,0%;https://img/4.jpg;"
            "https://shopee.com.br/product/10/4;Casa;50\n"
            "5;Fone Bluetooth TWS;89,90;149,90;40%;8,0%;https://img/5.jpg;"
            "https://shopee.com.br/product/10/5;Audio;9000\n",
            encoding="utf-8")

        filas, columnas = ag.leer_feed(feed)
        check("el feed se lee con separador ';'", len(filas) == 5)
        check("detecta la columna del nombre", columnas.get("nombre") == "Product Name")
        check("detecta la columna del precio", columnas.get("precio") == "Price")
        check("detecta la columna del enlace", columnas.get("url") == "Product Link")
        check("detecta la comisión", columnas.get("comision_pct") == "Commission Rate")

        # Verificación de atribución simulada (sin red): todas OK
        real_verif = shp.verificar_afiliacion
        shp.verificar_afiliacion = lambda enlace, aid=None, **k: (True, "https://shopee.com.br/x?utm_source=an_14382300002")
        try:
            achados, st = ag.cosechar_desde_feed(feed, min_desc=15.0, verificar_n=2, verbose=False)
            nombres = [a["nombre"] for a in achados]
            check("el feed produce achados", len(achados) == 2, f"-> {nombres}")
            check("descarta el producto vetado", "Medicamento para dor" not in nombres)
            check("descarta el que no tiene descuento", "Panela sem desconto" not in nombres)
            check("descarta el duplicado", nombres.count("Fone Bluetooth TWS") == 1)
            check("todos los enlaces llevan NUESTRO affiliate_id",
                  all("affiliate_id=14382300002" in a["url"] for a in achados))
            check("todos marcados como verificados",
                  all(a["afiliado_verificado"] for a in achados))
            check("precio y precio anterior bien parseados",
                  any(a["precio"] == 299.90 and a["precio_anterior"] == 399.90 for a in achados))

            # Si NINGÚN enlace se puede atribuir, no se publica nada
            shp.verificar_afiliacion = lambda enlace, aid=None, **k: (False, "sin atribución")
            try:
                ag.cosechar_desde_feed(feed, min_desc=15.0, verificar_n=2, verbose=False)
                check("si no hay atribución, el feed se rechaza entero", False)
            except shp.ShopeeAPIError:
                check("si no hay atribución, el feed se rechaza entero", True)
        finally:
            shp.verificar_afiliacion = real_verif

        # ── El validador final acepta el /an_redir y detecta al ajeno ────────
        post_feed = {
            "loja": "Shopee", "titulo": "Air Fryer Mondial Family 5L Antiaderente",
            "precio": 299.9, "imagen": "https://img/1.jpg",
            "url": shp.link_afiliado("https://shopee.com.br/Air-Fryer-Mondial-Family-5L-Antiaderente-i.55.99"),
        }
        ok, det = val._validar_enlace(post_feed)
        check("el validador acepta un /an_redir con nuestro ID", ok, f"-> {det}")
        check("resolver_enlace decodifica el origin_link (sin red)",
              val.resolver_enlace(post_feed["url"]) == "https://shopee.com.br/Air-Fryer-Mondial-Family-5L-Antiaderente-i.55.99")

        post_ajeno = dict(post_feed)
        post_ajeno["url"] = ("https://s.shopee.com.br/an_redir?origin_link=https%3A%2F%2Fshopee.com.br%2Fproduct%2F55%2F99"
                             "&affiliate_id=99999999999&sub_id=otro")
        ok2, det2 = val._validar_enlace(post_ajeno)
        check("el validador RECHAZA el enlace de otro afiliado", not ok2, f"-> {det2}")
        check("el motivo dice que la comisión no es tuya", "comisión" in det2 or "afiliado" in det2)

        # URL numérica de Shopee (/product/<tienda>/<item>): no hay slug que
        # comparar, se acepta por tienda (igual que Amazon con el ASIN).
        post_num = dict(post_feed)
        post_num["url"] = ("https://s.shopee.com.br/an_redir?origin_link=https%3A%2F%2Fshopee.com.br%2Fproduct%2F1050213612%2F23892819386"
                           "&affiliate_id=14382300002&sub_id=tg")
        ok3, det3 = val._validar_enlace(post_num)
        check("el validador acepta la URL numérica de producto de Shopee", ok3, f"-> {det3}")

        # ── 14. Fuente "grupos de Telegram" (método BlueBot) ─────────────────
        check("dos precios -> actual/anterior/descuento calculado",
              ag._precio_y_anterior(["249,90", "549,90"], None) == (249.90, 549.90, 54.6))
        check("si el mensaje declara el %, manda el del mensaje",
              ag._precio_y_anterior(["249,90", "549,90"], 55) == (249.90, 549.90, 55.0))
        check("un solo precio -> sin descuento inventado",
              ag._precio_y_anterior(["399,00"], None) == (399.0, 0.0, 0.0))
        p_act, p_ant, p_desc = ag._precio_y_anterior(["89,90"], 30)
        check("el % del mensaje manda y se deriva el precio anterior",
              p_desc == 30 and abs(p_ant - 128.43) < 0.05)
        check("sin precios -> cero", ag._precio_y_anterior([], None) == (0.0, 0.0, 0.0))

        # datos_producto() lee los og: que Shopee solo sirve a los crawlers
        import requests as _rq

        class _Resp:
            def __init__(self, texto, url):
                self.text, self.url, self.status_code, self.content = texto, url, 200, texto.encode()

        real_get = _rq.get
        try:
            _rq.get = lambda *a, **k: _Resp(
                '<meta property="og:title" content="Air Fryer Mondial 5L | Shopee Brasil">'
                '<meta property="og:image" content="https://down-br.img.susercontent.com/file/abc">',
                "https://shopee.com.br/product/10/20")
            d = shp.datos_producto("https://shopee.com.br/product/10/20")
            check("datos_producto saca el título y quita '| Shopee Brasil'",
                  d["titulo"] == "Air Fryer Mondial 5L", f"-> {d['titulo']!r}")
            check("datos_producto saca la foto", d["imagen"].endswith("/abc"))
            check("datos_producto marca que el producto existe", d["existe"] is True)

            _rq.get = lambda *a, **k: _Resp(
                '<meta property="og:title" content="Shopee Brasil | Ofertas incríveis">',
                "https://shopee.com.br/opaanlp/1/1")
            d2 = shp.datos_producto("https://shopee.com.br/product/1/1")
            check("datos_producto detecta producto inexistente (no se publica muerto)",
                  d2["existe"] is False)
        finally:
            _rq.get = real_get

        # Cosechador de Telegram completo (datos de Shopee simulados)
        tmp5 = Path(tempfile.mkdtemp(prefix="criba_tg_test_"))
        tg = tmp5 / "ofertas_telegram.json"
        tg.write_text(json.dumps({"ofertas": [
            {"titulo": "Air Fryer com 55% OFF", "precio_texto": "249,90",
             "precios": ["249,90", "549,90"], "desconto_pct": 55,
             "enlaces": ["https://s.shopee.com.br/doOutroAfiliado"]},
            {"titulo": "Fone bluetooth TWS barato", "precio_texto": "89,90",
             "precios": ["89,90"], "desconto_pct": 30,
             "enlaces": ["https://shopee.com.br/product/10/21"]},
            {"titulo": "Medicamento vetado com 90% OFF", "precio_texto": "9,90",
             "precios": ["9,90"], "desconto_pct": 90,
             "enlaces": ["https://shopee.com.br/product/10/22"]},
            {"titulo": "Oferta de Amazon", "precio_texto": "50,00",
             "precios": ["50,00"], "desconto_pct": None,
             "enlaces": ["https://www.amazon.com.br/dp/B0CJ3BDN7T?tag=criba20-20"]},
            {"titulo": "Producto sin precio", "precio_texto": "",
             "precios": [], "desconto_pct": None,
             "enlaces": ["https://shopee.com.br/product/10/23"]},
        ]}, ensure_ascii=False), encoding="utf-8")

        guardado_tg = (shp.datos_producto, shp.verificar_afiliacion)
        shp.datos_producto = lambda u, **k: {
            "titulo": "Air Fryer Mondial Family 5L" if "10/20" in str(u) else "Fone Bluetooth TWS Pro",
            "imagen": "https://down-br.img.susercontent.com/file/foto", "url_final": u, "existe": True}
        shp.verificar_afiliacion = lambda e, aid=None, **k: (True, "https://shopee.com.br/x?utm_source=an_14382300002")
        # El primer enlace es el link corto de OTRO afiliado: hay que resolverlo
        # (siguiendo la redirección) y reconstruirlo con NUESTRO ID.
        real_get_tg = _rq.get
        try:
            _rq.get = lambda *a, **k: _Resp(
                "", "https://shopee.com.br/product/10/20?mmp_pid=an_99999999999"
                    "&utm_source=an_99999999999")
            achados_tg, st_tg = ag.cosechar_desde_telegram(tg, min_desc=0.0, verificar_n=2, verbose=False)
            nombres_tg = [a["nombre"] for a in achados_tg]
            check("Telegram: se quedan las 2 ofertas de Shopee",
                  len(achados_tg) == 2, f"-> {nombres_tg}")
            check("Telegram: descarta la de Amazon", "Oferta de Amazon" not in nombres_tg)
            check("Telegram: descarta la vetada", not any("Medicamento" in n for n in nombres_tg))
            check("Telegram: descarta la que no trae precio", "Producto sin precio" not in nombres_tg)
            check("Telegram: usa el nombre REAL de Shopee",
                  "Air Fryer Mondial Family 5L" in nombres_tg)
            check("Telegram: guarda la foto del producto",
                  all(a["imagen"].startswith("https://") for a in achados_tg))
            check("Telegram: los enlaces llevan NUESTRO ID",
                  all("affiliate_id=14382300002" in a["url"] for a in achados_tg))
            check("Telegram: reconvierte el enlace de OTRO afiliado al nuestro",
                  all("an_99999999999" not in a["url"] for a in achados_tg))
            check("Telegram: el precio queda marcado como del mensaje",
                  all(a.get("precio_fuente") == "mensaje_telegram" for a in achados_tg))
            check("Telegram: 55% -> precio anterior correcto",
                  any(abs(a["precio_anterior"] - 549.90) < 0.05 for a in achados_tg))
            check("Telegram: atribución verificada", st_tg["verificados"] >= 1)

            shp.verificar_afiliacion = lambda e, aid=None, **k: (False, "sin atribución")
            try:
                ag.cosechar_desde_telegram(tg, min_desc=0.0, verificar_n=2, verbose=False)
                check("Telegram: sin atribución no se publica nada", False)
            except shp.ShopeeAPIError:
                check("Telegram: sin atribución no se publica nada", True)
        finally:
            _rq.get = real_get_tg
            shp.datos_producto, shp.verificar_afiliacion = guardado_tg[0], guardado_tg[1]
    finally:
        os.environ.pop("SHOPEE_AFFILIATE_ID", None)
        if previo_aid is not None:
            os.environ["SHOPEE_AFFILIATE_ID"] = previo_aid

    print("-" * 68)
    print(f"  {PRUEBAS - len(FALLOS)}/{PRUEBAS} pruebas OK")
    if FALLOS:
        print(f"  FALLARON: {', '.join(FALLOS)}")
        return 1
    print("  [OK] Todo correcto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
