#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Shopee Brasil (agente_shopee.py)
================================================
Hace con Shopee lo MISMO que agente_amazon.py y agente_ml.py: consigue
productos, les pone EL ENLACE DE AFILIADO del usuario y los deja listos para
que `unir_achados.py` → `gerar_fila_posts.py` → `publicar_proximo.py` los
manden al grupo.

El enlace de afiliado de Shopee se genera de DOS maneras, y las dos se
verifican antes de publicar (Regla de Oro):

  · API oficial (productOfferV2)      -> `offerLink` que emite Shopee con la
    cuenta del afiliado. Es el camino automático y el que trae comisión real.
  · /an_redir + affiliate_id          -> enlace oficial por URL, NO necesita
    la API: solo el ID numérico de afiliado. Sirve para cualquier producto que
    llegue por otra vía (feed del portal, lista del usuario, etc.).

Qué fuentes de productos acepta, por orden de preferencia:
  1. API oficial de afiliados (si hay SHOPEE_APP_ID + SHOPEE_SECRET_KEY).
  2. `shopee_feed.csv|.xlsx|.json` — el feed de productos que se descarga del
     portal de afiliados (Criativo/Creative → Product Feed). Trae nombre,
     precio, imagen y enlace: no hace falta la API.
  3. Nada de lo anterior -> lo dice claro y no llama a la red.

REGLA DE ORO: hacen falta DOS candados para que algo de Shopee se publique.
  1. Enlace de afiliado verificable (API o /an_redir con tu affiliate_id).
  2. Datos de pago aprobados por Shopee (`pagos_aprobados`), porque Shopee no
     paga comisiones hasta validarlos. Sin ellos el script NO llama a la red y
     deja el fichero vacío, con código de salida 0.

Con `--verificar` se sigue la redirección de cada enlace y se comprueba que
Shopee atribuya el clic a tu ID (`utm_source=an_<ID>`).

Uso:
    python agente_shopee.py                    # cosecha y escribe achados_shopee.json
    python agente_shopee.py --test             # 1 búsqueda, 5 ofertas, NO escribe
    python agente_shopee.py --verificar        # comprueba la atribución de un enlace
    python agente_shopee.py --feed ruta.csv    # cosecha desde un feed del portal
    python agente_shopee.py --json
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import shopee_api as shp

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config_afiliados.json"
OUTPUT_FILE = BASE / "achados_shopee.json"

HORAS_VALIDEZ = 36  # igual que agente_amazon.py: un achado caduca a las 36 h

# Búsquedas por defecto (nicho "geral" del proyecto: casa, limpieza, higiene,
# cocina, pet, bebé, ferretería, fitness). Se pueden cambiar sin tocar código
# en config_afiliados.json -> shopee.busquedas, o con SHOPEE_BUSQUEDAS="a,b,c".
BUSQUEDAS_DEFECTO = [
    "air fryer", "panela eletrica", "aspirador de po", "liquidificador",
    "jogo de cama", "organizador de cozinha", "kit panelas", "cafeteira",
    "fone bluetooth", "smartwatch", "caixa de som bluetooth", "power bank",
    "perfume feminino", "kit shampoo e condicionador", "creatina", "whey protein",
    "racao cachorro", "comedouro pet", "fralda", "mamadeira",
    "parafusadeira", "jogo de chaves", "mochila", "tenis masculino",
]

# Vetos absolutos. Espejo de gerar_fila_posts.EXCLUIR_SIEMPRE: lo que está aquí
# nunca entra, ni siquiera si tiene un descuento enorme.
VETADOS = [
    "medicamento", "remedio", "remédio", "farmacia", "farmácia", "antibiotico",
    "antibiótico", "generico", "genérico", "arma ", "arma de", "municao", "munição",
    "cigarro", "vape", "pod descartavel", "narguile", "aposta", "apostas",
    "cerveja", "vinho", "whisky", "vodka", "gin ", "energetico alcoolico",
]


def normalizar(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def cargar_config():
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("shopee", {}) or {}
        except Exception:
            cfg = {}
    return cfg


def lista_busquedas(cfg):
    env = os.environ.get("SHOPEE_BUSQUEDAS", "").strip()
    if env:
        return [b.strip() for b in env.split(",") if b.strip()]
    de_cfg = cfg.get("busquedas")
    if isinstance(de_cfg, list) and de_cfg:
        return [str(b).strip() for b in de_cfg if str(b).strip()]
    return list(BUSQUEDAS_DEFECTO)


def esta_habilitado():
    """
    Shopee está operativo cuando hay App ID + Secret.

    Nota: `tiendas_que_pagan` de config_afiliados.json NO se usa aquí a
    propósito. Ese interruptor lo leen los scrapers (bot_precios, descobrir...),
    que devolverían enlaces de Shopee SIN afiliado. Aquí la única fuente es la
    API oficial, y el enlace sale de la cuenta del propio afiliado.
    """
    return shp.disponible()


def pagos_confirmados(cfg=None):
    """
    Segundo interruptor: que Shopee ya haya aprobado los DATOS DE PAGO.

    POR QUÉ EXISTE (leer antes de tocarlo):
    Estar aprobado como afiliado deja generar enlaces, pero Shopee NO paga nada
    hasta que los datos bancarios/fiscales estén rellenados y aprobados:

      "você só receberá as suas comissões 60 dias após ter estes dados
       preenchidos e aprovados pela nossa equipe" (email de Shopee)

    Y para Pessoa Física el pago va SOLO a la cuenta digital Maree, el día 10 de
    cada mes, con un mínimo de R$ 10 en comisiones validadas.

    Traducción: si el bot empieza a mandar clics al grupo antes de que esos
    datos estén aprobados, el trabajo puede no cobrarse. Así que se publica
    cuando el usuario lo confirma, y no antes.

    Se activa con config_afiliados.json -> shopee.pagos_aprobados = true,
    o con la variable de entorno SHOPEE_PAGOS_APROBADOS=1 (útil para probar).
    """
    if cfg is None:
        cfg = cargar_config()
    valor = os.environ.get("SHOPEE_PAGOS_APROBADOS", "").strip()
    if not valor:
        valor = str(cfg.get("pagos_aprobados", "")).strip()
    return valor.lower() in ("1", "true", "si", "sí", "yes", "sim", "ok")


def es_vetado(nombre):
    n = normalizar(nombre)
    return any(v in n for v in VETADOS)


# ══════════════════════════════════════════════════════════════════════════════
#  FUENTE 2 · FEED DE PRODUCTOS DEL PORTAL (sin API)
# ══════════════════════════════════════════════════════════════════════════════
# El portal de afiliados deja descargar un feed de productos (nombre, precio,
# imagen y enlace). Se acepta CSV, XLSX o JSON y NO se asume ningún nombre de
# columna: se detectan por parecido, porque el portal cambia los encabezados.
CAMPOS = {
    "nombre": ("productname", "nome", "nomedoproduto", "produto", "titulo", "title",
               "itemname", "name", "descricao", "descripcion"),
    "precio": ("price", "preco", "precovenda", "saleprice", "precopromocional",
               "precoatual", "precocomdesconto", "precioventa", "valor"),
    "precio_anterior": ("originalprice", "precooriginal", "pricebeforediscount",
                        "precobase", "precocheio", "listprice", "precode", "preciooriginal"),
    "desc_pct": ("discount", "desconto", "discountrate", "percentualdedesconto",
                 "taxadedesconto", "pricediscountrate", "desconto%", "pctdesconto"),
    "comision_pct": ("commissionrate", "comissao", "taxadecomissao", "comissaopct",
                     "comision", "commission", "percentualcomissao"),
    "imagen": ("imageurl", "imagem", "imagen", "image", "imagemdoproduto",
               "productimage", "imageurl1", "linkdaimagem"),
    "url": ("productlink", "link", "linkdoproduto", "producturl", "url", "itemlink",
            "offerlink", "shortlink", "links", "linkproduto"),
    "item_id": ("itemid", "iddoproduto", "productid", "item", "id"),
    "tienda_nombre": ("shopname", "loja", "nomeloj", "nomeloj", "vendedor", "seller"),
    "vendidos": ("sales", "vendidos", "vendas", "sold", "quantidadevendida"),
}


def _clave_columna(texto):
    """'Product Name' / 'product_name' / 'Nome do Produto' -> 'productname'."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _detectar_columnas(encabezados):
    """{campo_interno: nombre_de_columna_real} detectado por parecido."""
    mapa = {}
    normalizados = {_clave_columna(h): h for h in encabezados if h}
    for campo, alias in CAMPOS.items():
        for a in alias:
            if a in normalizados:
                mapa[campo] = normalizados[a]
                break
        if campo in mapa:
            continue
        # segundo intento: coincidencia parcial (ej. 'preco_venda_brl')
        for clave in list(normalizados):
            if any(a in clave for a in alias):
                mapa[campo] = normalizados[clave]
                break
    return mapa


def leer_feed(ruta):
    """
    Lee el feed y devuelve (filas, columnas_detectadas).

    Formatos: .csv / .tsv / .txt (separador y codificación autodetectados),
    .xlsx / .xlsm (openpyxl) y .json (lista de objetos).
    """
    p = Path(ruta)
    if not p.exists():
        raise FileNotFoundError(f"no existe el feed: {p}")
    sufijo = p.suffix.lower()

    if sufijo in (".json",):
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            for clave in ("data", "products", "produtos", "items", "achados", "offers"):
                if isinstance(data.get(clave), list):
                    data = data[clave]
                    break
        filas = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
        columnas = _detectar_columnas(list(filas[0].keys()) if filas else [])
        return filas, columnas

    if sufijo in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook           # dependencia opcional
        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        filas_crudas = list(ws.iter_rows(values_only=True))
        if not filas_crudas:
            return [], {}
        encabezados = [str(c) if c is not None else "" for c in filas_crudas[0]]
        columnas = _detectar_columnas(encabezados)
        filas = [dict(zip(encabezados, fila)) for fila in filas_crudas[1:]]
        return [f for f in filas if any(v not in (None, "") for v in f.values())], columnas

    # CSV / TSV / TXT
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = p.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("no se pudo leer el feed (codificación desconocida)")

    primera = texto.splitlines()[0] if texto.splitlines() else ""
    separador = ";" if primera.count(";") > primera.count(",") else ","
    if "\t" in primera and primera.count("\t") > primera.count(separador):
        separador = "\t"

    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    encabezados = [h for h in (lector.fieldnames or []) if h]
    columnas = _detectar_columnas(encabezados)
    filas = [dict(f) for f in lector]
    return [f for f in filas if any(v not in (None, "") for v in f.values())], columnas


def _valor(fila, columnas, campo, por_defecto=""):
    col = columnas.get(campo)
    return fila.get(col, por_defecto) if col else por_defecto


def cosechar_desde_feed(ruta, min_desc=0.0, min_comision=0.0, max_achados=120,
                        verificar_n=3, verbose=True):
    """
    Convierte el feed del portal en achados con enlace de afiliado /an_redir.

    No se publica nada si la atribución no queda probada: se verifican los
    primeros `verificar_n` enlaces siguiendo la redirección real de Shopee.
    """
    aid = shp.affiliate_id()
    if not aid:
        raise shp.ShopeeAPIError(
            "Falta SHOPEE_AFFILIATE_ID: sin el ID de afiliado no hay enlace que cobre comisión."
        )

    filas, columnas = leer_feed(ruta)
    faltan = [c for c in ("nombre", "precio", "url") if c not in columnas]
    if faltan:
        raise ValueError(
            f"al feed le faltan columnas: {', '.join(faltan)}. "
            f"Detectadas: {sorted(columnas)}. Revisa el encabezado del fichero."
        )
    if verbose:
        print(f"  Feed: {ruta} -> {len(filas)} filas")
        print(f"  Columnas detectadas: " + ", ".join(f"{k}={v!r}" for k, v in sorted(columnas.items())))

    ahora = datetime.now(timezone.utc)
    encontrado_iso = ahora.isoformat(timespec="seconds")
    expira_iso = (ahora + timedelta(hours=HORAS_VALIDEZ)).isoformat(timespec="seconds")

    stats = {"filas": len(filas), "sin_precio": 0, "sin_url": 0, "vetados": 0,
             "poco_descuento": 0, "poca_comision": 0, "duplicados": 0,
             "verificados": 0, "errores": []}
    vistos, achados, links = set(), [], []

    for fila in filas:
        nombre = str(_valor(fila, columnas, "nombre")).strip()
        precio = shp.num(_valor(fila, columnas, "precio"))
        url_prod = str(_valor(fila, columnas, "url")).strip()
        if not nombre:
            continue
        if precio <= 0:
            stats["sin_precio"] += 1
            continue
        if not url_prod.startswith("http"):
            stats["sin_url"] += 1
            continue
        if es_vetado(nombre):
            stats["vetados"] += 1
            continue

        desc = shp.num(_valor(fila, columnas, "desc_pct"))
        anterior = shp.num(_valor(fila, columnas, "precio_anterior"))
        if not desc and anterior > precio:
            desc = round((anterior - precio) / anterior * 100, 1)
        comision = shp.num(_valor(fila, columnas, "comision_pct"))

        if desc < min_desc:
            stats["poco_descuento"] += 1
            continue
        if comision < min_comision:
            stats["poca_comision"] += 1
            continue

        clave = normalizar(nombre)[:32]
        if clave in vistos:
            stats["duplicados"] += 1
            continue

        # Si el feed ya trae un enlace corto de afiliado, se usa tal cual;
        # si no, se construye el /an_redir con NUESTRO ID.
        if shp.es_link_afiliado(url_prod):
            enlace = url_prod
        else:
            enlace = shp.link_afiliado(url_prod, aid=aid, sub_id="feed")
            links.append(enlace)

        vistos.add(clave)
        achados.append({
            "id": f"shp-{_valor(fila, columnas, 'item_id') or abs(hash(clave)) % 10**9}",
            "nombre": nombre,
            "precio": precio,
            "precio_anterior": anterior if anterior > precio else None,
            "desc_pct": desc,
            "imagen": str(_valor(fila, columnas, "imagen")).strip(),
            "url": enlace,
            "url_producto": url_prod if not shp.es_link_afiliado(url_prod) else "",
            "loja": "Shopee",
            "categoria": "Shopee Ofertas",
            "fuente": "Shopee Product Feed (portal)",
            "tienda_nombre": str(_valor(fila, columnas, "tienda_nombre")).strip(),
            "vendidos": int(shp.num(_valor(fila, columnas, "vendidos"))),
            "comision_pct": comision,
            "afiliado_verificado": True,     # se confirma abajo con la verificación real
            "afiliado_fuente": "an_redir",
            "afiliado_id": aid,
            "encontrado_em": encontrado_iso,
            "expira_em": expira_iso,
        })

    # ── VERIFICACIÓN REAL: que Shopee atribuya el clic a nuestro ID ──────────
    if links and verificar_n > 0:
        muestras = links[:max(1, int(verificar_n))]
        fallos = []
        for enlace in muestras:
            ok, detalle = shp.verificar_afiliacion(enlace, aid=aid)
            if ok:
                stats["verificados"] += 1
                if verbose:
                    print(f"    [OK] atribución: {detalle[:110]}")
            else:
                fallos.append((enlace, detalle))
        if stats["verificados"] == 0:
            raise shp.ShopeeAPIError(
                "NINGÚN enlace quedó atribuido a tu ID de afiliado "
                f"({aid}). No se publica nada de Shopee. Detalle: {fallos[:2]}"
            )
        if fallos and verbose:
            print(f"    [aviso] {len(fallos)} de {len(muestras)} enlaces no se pudieron verificar ahora")

    achados.sort(key=lambda x: (x.get("desc_pct", 0), x.get("precio", 0)), reverse=True)
    return achados[:max_achados], stats


# ══════════════════════════════════════════════════════════════════════════════
#  FUENTE 3 · GRUPOS DE OFERTAS DE TELEGRAM (el método de BlueBot)
# ══════════════════════════════════════════════════════════════════════════════
# Copiado del proyecto más popular de este nicho (SaulloGabryel/BlueBot, 22★):
# en vez de BUSCAR productos, se MONITORIZAN grupos de ofertas que ya publican
# gangas y se RECONVIERTE el enlace a la cuenta de afiliado propia. Así se
# aprovecha el trabajo de otros y se cobra la comisión uno mismo.
#
# Aquí ya existe la mitad del trabajo: `leer_telegram.py` (Telethon) lee los
# grupos y deja `ofertas_telegram.json` con título, precios y enlaces. Lo que
# faltaba era reconvertir el enlace de Shopee a NUESTRO ID de afiliado, que es
# justo lo que hace `shp.link_afiliado()` (no necesita API).
#
# ⚠ TRADE-OFF HONESTO: el precio viene del mensaje del grupo, no de Shopee. No
# se puede verificar (la página de producto de Shopee es JavaScript y su API
# interna responde 403). Por eso cada achado queda marcado con
# `precio_fuente: "mensaje_telegram"` y se puede apagar con
# `shopee.usar_telegram = false`. Los cupones y el Pix NO se tocan: nunca se
# inventan.
def _precio_y_anterior(precios, desc_pct_msg):
    """
    (precio_actual, precio_anterior, desc_pct) a partir de los precios del
    mensaje. Regla: si hay dos precios distintos, el mayor es el anterior.
    Si el mensaje declara un %, ese manda (es el dato de la fuente).
    """
    valores = []
    for p in (precios or []):
        v = shp.num(p)
        if v > 0:
            valores.append(v)
    if not valores:
        return 0.0, 0.0, 0.0
    actual = valores[0]
    anterior = 0.0
    if len(valores) > 1:
        mayor, menor = max(valores), min(valores)
        if mayor > menor:
            actual, anterior = menor, mayor
    desc = float(desc_pct_msg) if desc_pct_msg else 0.0
    if not desc and anterior > actual:
        desc = round((anterior - actual) / anterior * 100, 1)
    if desc and not anterior and desc < 100:
        anterior = round(actual / (1 - desc / 100.0), 2)
    return actual, anterior, desc


def cosechar_desde_telegram(ruta=None, min_desc=0.0, max_achados=40,
                            verificar_n=3, verbose=True):
    """
    Convierte las ofertas que `leer_telegram.py` encontró en los grupos en
    achados de Shopee con NUESTRO enlace de afiliado.
    """
    aid = shp.affiliate_id()
    if not aid:
        raise shp.ShopeeAPIError(
            "Falta SHOPEE_AFFILIATE_ID: sin el ID de afiliado no hay enlace que cobre comisión."
        )

    ruta = Path(ruta or (BASE / "ofertas_telegram.json"))
    if not ruta.exists():
        raise FileNotFoundError(
            f"no existe {ruta}. Se genera con: python leer_telegram.py --horas 12"
        )
    data = json.loads(ruta.read_text(encoding="utf-8-sig"))
    ofertas = data.get("ofertas", data) if isinstance(data, dict) else data
    if verbose:
        print(f"  Telegram: {ruta} -> {len(ofertas)} ofertas leídas de los grupos")

    ahora = datetime.now(timezone.utc)
    encontrado_iso = ahora.isoformat(timespec="seconds")
    # Una oferta de grupo caduca antes que una del catálogo: se publica fresca.
    expira_iso = (ahora + timedelta(hours=12)).isoformat(timespec="seconds")

    stats = {"ofertas": len(ofertas), "sin_enlace_shopee": 0, "sin_precio": 0,
             "sin_titulo": 0, "vetados": 0, "poco_descuento": 0, "duplicados": 0,
             "no_resueltos": 0, "sin_imagen": 0, "verificados": 0, "errores": []}
    vistos, achados, links = set(), [], []

    for of in ofertas:
        titulo = str(of.get("titulo") or "").strip()
        if len(titulo) < 12:
            stats["sin_titulo"] += 1
            continue
        if es_vetado(titulo):
            stats["vetados"] += 1
            continue

        enlaces = [e for e in (of.get("enlaces") or [])
                   if "shopee.com.br" in e.lower() or "shp.ee" in e.lower()]
        if not enlaces:
            stats["sin_enlace_shopee"] += 1
            continue
        enlace_origen = enlaces[0]

        precio, anterior, desc = _precio_y_anterior(
            of.get("precios") or [of.get("precio_texto")], of.get("desconto_pct"))
        if precio <= 0:
            stats["sin_precio"] += 1
            continue
        if desc < min_desc:
            stats["poco_descuento"] += 1
            continue

        clave = normalizar(titulo)[:32]
        if clave in vistos:
            stats["duplicados"] += 1
            continue

        # Producto real detrás del enlace del grupo (puede ser el link corto de
        # OTRO afiliado: se resuelve y se reconstruye con el nuestro).
        url_producto = enlace_origen.split("?")[0]
        if not re.search(r"/product/\d+/\d+|-i\.\d+\.\d+", url_producto):
            try:
                import requests
                real = requests.get(enlace_origen, allow_redirects=True, timeout=20,
                                    headers={"User-Agent": shp._UA,
                                             "Accept-Language": "pt-BR,pt;q=0.9"}).url
                if re.search(r"/product/\d+/\d+|-i\.\d+\.\d+", real):
                    url_producto = real.split("?")[0]
            except Exception as e:
                stats["errores"].append(f"resolver {enlace_origen[:60]}: {e}")
        if not re.search(r"/product/\d+/\d+|-i\.\d+\.\d+", url_producto):
            stats["no_resueltos"] += 1
            continue

        # Datos REALES del producto (título y foto) leídos de Shopee con el UA de
        # crawler. Además confirma que el producto existe: si no, se descarta.
        datos = shp.datos_producto(url_producto)
        if not datos.get("existe"):
            stats["no_resueltos"] += 1
            continue
        if not datos.get("imagen"):
            stats["sin_imagen"] += 1
            continue

        enlace = shp.link_afiliado(url_producto, aid=aid, sub_id="tg")
        links.append((enlace, enlace_origen))
        vistos.add(clave)
        achados.append({
            "id": f"shp-tg-{abs(hash(clave)) % 10**9}",
            # Se prefiere el nombre REAL de Shopee al del mensaje del grupo: es
            # el que coincide con la URL y el que pasa el validador final.
            "nombre": datos.get("titulo") or titulo,
            "titulo_origen": titulo,
            "precio": precio,
            "precio_anterior": anterior if anterior > precio else None,
            "desc_pct": desc,
            "imagen": datos["imagen"],
            "url": enlace,
            "url_producto": url_producto,
            "loja": "Shopee",
            "categoria": "Shopee Ofertas",
            "fuente": "Grupo de ofertas (enlace reconvertido)",
            "precio_fuente": "mensaje_telegram",
            "detectado_em": of.get("detectado_em", ""),
            "afiliado_verificado": True,
            "afiliado_fuente": "an_redir",
            "afiliado_id": aid,
            "encontrado_em": encontrado_iso,
            "expira_em": expira_iso,
        })

    # ── Verificación REAL de la atribución (no se publica si no cobra) ───────
    if links and verificar_n > 0:
        ok_total = 0
        for enlace, origen in links[:max(1, int(verificar_n))]:
            ok, detalle = shp.verificar_afiliacion(enlace, aid=aid)
            if ok:
                ok_total += 1
                if verbose:
                    print(f"    [OK] atribución: {detalle[:110]}")
        stats["verificados"] = ok_total
        if ok_total == 0:
            raise shp.ShopeeAPIError(
                f"NINGÚN enlace de Telegram quedó atribuido a tu ID ({aid}). "
                "No se publica nada de Shopee hasta que el ID sea correcto."
            )

    achados.sort(key=lambda x: (x.get("desc_pct", 0), x.get("precio", 0)), reverse=True)
    return achados[:max_achados], stats


def ruta_feed(cfg=None, forzada=None):
    """Fichero del feed del portal, si existe (o el que se pase por parámetro)."""
    if forzada:
        return Path(forzada)
    env = os.environ.get("SHOPEE_FEED_FILE", "").strip()
    if env:
        return Path(env)
    if cfg is None:
        cfg = cargar_config()
    de_cfg = str(cfg.get("feed_file") or "").strip()
    if de_cfg:
        p = BASE / de_cfg
        return p if p.exists() else None
    for nombre in ("shopee_feed.csv", "shopee_feed.xlsx", "shopee_feed.json",
                   "shopee_feed.tsv", "shopee_feed.txt"):
        p = BASE / nombre
        if p.exists():
            return p
    return None


def cosechar(busquedas, limite_por_busqueda=50, min_desc=15.0, min_comision=0.0,
             max_achados=120, generar_links=True, verbose=True):
    """
    Devuelve (achados, estadisticas). Nunca lanza por un fallo de red puntual:
    si una búsqueda falla, se anota y se sigue con la siguiente.
    """
    ahora = datetime.now(timezone.utc)
    encontrado_iso = ahora.isoformat(timespec="seconds")
    expira_iso = (ahora + timedelta(hours=HORAS_VALIDEZ)).isoformat(timespec="seconds")

    stats = {
        "consultas": 0, "consultas_fallidas": 0, "ofertas_vistas": 0,
        "sin_enlace": 0, "links_generados": 0, "vetados": 0,
        "poco_descuento": 0, "poca_comision": 0, "duplicados": 0,
        "comisiones": [], "errores": [],
    }
    vistos = set()
    achados = []

    for kw in busquedas:
        try:
            nodos = shp.ofertas(keyword=kw, limit=limite_por_busqueda)
            stats["consultas"] += 1
        except Exception as e:
            stats["consultas_fallidas"] += 1
            stats["errores"].append(f"{kw}: {e}")
            if verbose:
                print(f"    [X] '{kw}': {e}")
            continue

        if verbose:
            print(f"    · '{kw}': {len(nodos)} ofertas")
        stats["ofertas_vistas"] += len(nodos)

        for nodo in nodos:
            nombre = (nodo.get("productName") or "").strip()
            item_id = str(nodo.get("itemId") or "")
            if not nombre or not item_id:
                continue

            desc = shp.num(nodo.get("priceDiscountRate"))
            comision = shp.num(nodo.get("commissionRate"))

            if es_vetado(nombre):
                stats["vetados"] += 1
                continue
            if desc < min_desc:
                stats["poco_descuento"] += 1
                continue
            if comision < min_comision:
                stats["poca_comision"] += 1
                continue

            clave = normalizar(nombre)[:32] or item_id
            if clave in vistos:
                stats["duplicados"] += 1
                continue

            oferta = shp.normalizar_oferta(nodo, {"categoria": "Shopee Ofertas"})

            # Enlace de afiliado, por orden:
            #   1. `offerLink` de la API (ya es nuestro, no gasta cuota).
            #   2. /an_redir con nuestro affiliate_id (no gasta cuota de API).
            #   3. generateShortLink (último recurso, cada llamada gasta cuota).
            if not oferta["url"] and generar_links and oferta.get("url_producto"):
                aid = shp.affiliate_id()
                if aid:
                    try:
                        oferta["url"] = shp.link_afiliado(oferta["url_producto"], aid=aid,
                                                          sub_id="api")
                        oferta["afiliado_fuente"] = "an_redir"
                        oferta["afiliado_id"] = aid
                        stats["links_generados"] += 1
                    except Exception as e:
                        stats["errores"].append(f"an_redir {item_id}: {e}")
                if not oferta["url"]:
                    try:
                        oferta["url"] = shp.link_corto(oferta["url_producto"], sub_ids=["criba"])
                        oferta["afiliado_fuente"] = "generateShortLink"
                        stats["links_generados"] += 1
                    except Exception as e:
                        stats["errores"].append(f"link {item_id}: {e}")
                oferta["afiliado_verificado"] = shp.es_link_afiliado(oferta["url"])

            if not oferta["url"] or not oferta.get("afiliado_verificado"):
                stats["sin_enlace"] += 1
                continue

            oferta["encontrado_em"] = encontrado_iso
            oferta["expira_em"] = expira_iso
            oferta["busqueda"] = kw
            vistos.add(clave)
            achados.append(oferta)
            stats["comisiones"].append(comision)

    achados.sort(key=lambda x: (x.get("desc_pct", 0), x.get("comision_pct", 0)), reverse=True)
    achados = achados[:max_achados]
    return achados, stats


def escribir_salida(achados, extra=None):
    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_achados": len(achados),
        "achados": achados,
    }
    if extra:
        resultado.update(extra)
    OUTPUT_FILE.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cosechador Shopee (API oficial o feed del portal)")
    ap.add_argument("--test", action="store_true", help="prueba corta, no escribe fichero")
    ap.add_argument("--json", action="store_true", help="imprime los achados por consola")
    ap.add_argument("--limite", type=int, default=50, help="ofertas por búsqueda (tope 50)")
    ap.add_argument("--min-desc", type=float, default=None, help="descuento mínimo %% (def. 15)")
    ap.add_argument("--feed", metavar="RUTA", help="cosechar desde un feed del portal (CSV/XLSX/JSON)")
    ap.add_argument("--telegram", metavar="RUTA", nargs="?", const="ofertas_telegram.json",
                    help="cosechar desde las ofertas de grupos de Telegram (método BlueBot)")
    ap.add_argument("--verificar", metavar="URL", help="comprobar que un enlace atribuye el clic a tu ID")
    args = ap.parse_args(argv)

    cfg = cargar_config()
    print("=" * 68)
    print("  CRIBA · AGENTE SHOPEE BRASIL")
    print("=" * 68)

    # ── Comprobación de un enlace suelto ─────────────────────────────────────
    if args.verificar:
        aid = shp.affiliate_id()
        print(f"  ID de afiliado: {aid or '(vacío)'}")
        ok, detalle = shp.verificar_afiliacion(args.verificar, aid=aid or None)
        print(f"  Enlace: {args.verificar[:120]}")
        if ok:
            print("  [OK] Shopee atribuye el clic a ese ID de afiliado.")
            print(f"       destino: {detalle[:160]}")
            return 0
        print(f"  [X] NO se pudo confirmar la atribución: {detalle[:200]}")
        return 2

    feed = ruta_feed(cfg, args.feed)
    hay_api = esta_habilitado()
    aid = shp.affiliate_id()

    # Tercera fuente (método BlueBot): ofertas que ya publican los grupos de
    # Telegram, reconvertidas a nuestro enlace. Se puede apagar en config.
    usar_tg = bool(args.telegram) or str(cfg.get("usar_telegram", True)).lower() not in ("false", "0", "no")
    ruta_tg = Path(args.telegram) if args.telegram else (BASE / str(cfg.get("telegram_file") or "ofertas_telegram.json"))
    hay_tg = usar_tg and ruta_tg.exists()

    print(f"  API de afiliados : {'lista' if hay_api else 'sin credenciales'}")
    print(f"  ID de afiliado   : {aid or '(vacío) -> sin ID no se puede generar enlace'}")
    print(f"  Feed del portal  : {feed if feed and Path(feed).exists() else 'no encontrado'}")
    print(f"  Grupos Telegram  : {ruta_tg if hay_tg else ('desactivado' if not usar_tg else 'sin fichero (corre leer_telegram.py)')}")
    print("-" * 68)

    if not hay_api and not (feed and Path(feed).exists()) and not hay_tg:
        print("  [Shopee] Sin fuente de productos todavía. Tres caminos:")
        print("  A) API oficial (automático): https://affiliate.shopee.com.br/open_api")
        print("     Si el botón 'Aplicar' no está naranja, pídenla en:")
        print("     https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091")
        print("     Luego: SHOPEE_APP_ID y SHOPEE_SECRET_KEY en .env")
        print("  B) Feed de productos (sin API): en el portal, Criativo → Product Feed,")
        print("     descarga el fichero y déjalo como 'shopee_feed.csv' en esta carpeta.")
        print("  C) Grupos de Telegram (sin API): python leer_telegram.py --horas 12")
        print("     y luego este agente reconvierte esos enlaces a tu cuenta.")
        if not aid:
            print("  ⚠ Falta también SHOPEE_AFFILIATE_ID (el número de tu cuenta),")
            print("    que es lo único necesario para generar el enlace de afiliado.")
        if not args.test:
            escribir_salida([])
            print("  achados_shopee.json dejado vacío (consistencia del pipeline).")
        return 0

    # ── SEGUNDO CANDADO: datos de pago aprobados por Shopee ──────────────────
    # Tener la API no basta. Shopee no paga NADA hasta validar los datos
    # bancarios/fiscales, y para Persona Física el dinero va a la cuenta digital
    # Maree (día 10 de cada mes, mínimo R$ 10 en comisiones validadas).
    # Mandar clics al grupo antes de eso es trabajar gratis, así que el bot se
    # queda quieto hasta que el usuario confirme que ya está aprobado.
    if not args.test and not pagos_confirmados(cfg):
        print("  [Shopee] Fuente lista, pero PAGOS SIN CONFIRMAR -> no se publica nada.")
        print("  Shopee deja generar enlaces ya, pero solo paga cuando los datos de")
        print("  pago están rellenados y aprobados (y para PF el cobro va a Maree).")
        print("  Cuando Shopee te apruebe los datos, activa la publicación con:")
        print("     config_afiliados.json -> shopee.pagos_aprobados = true")
        print("     (o SHOPEE_PAGOS_APROBADOS=1 en .env)")
        print("  Mientras tanto, para probar sin publicar: python agente_shopee.py --test")
        escribir_salida([])
        print("  achados_shopee.json dejado vacío (consistencia del pipeline).")
        return 0

    min_desc = args.min_desc if args.min_desc is not None else float(
        os.environ.get("SHOPEE_MIN_DESC", cfg.get("min_desc", 15)))
    min_comision = float(os.environ.get("SHOPEE_MIN_COMISION", cfg.get("min_comision", 0)))
    max_achados = int(os.environ.get("SHOPEE_MAX", cfg.get("max_achados", 120)))

    # ── FUENTE 2: feed del portal (no necesita API) ──────────────────────────
    if feed and Path(feed).exists() and not (hay_api and not args.feed):
        if not args.test and min_desc > 0:
            print(f"  Filtros   : descuento >= {min_desc}% | comisión >= {min_comision}% | máx {max_achados}")
        try:
            achados, stats = cosechar_desde_feed(
                feed, min_desc=min_desc, min_comision=min_comision,
                max_achados=max_achados, verificar_n=0 if args.test else 3)
        except Exception as e:
            print(f"  [X] No se pudo usar el feed: {e}")
            escribir_salida([])
            return 2

        print("-" * 68)
        print(f"  Filas del feed     : {stats['filas']}")
        print(f"  Sin precio         : {stats['sin_precio']}")
        print(f"  Sin enlace         : {stats['sin_url']}")
        print(f"  Vetadas            : {stats['vetados']}")
        print(f"  Poco descuento     : {stats['poco_descuento']}")
        print(f"  Poca comisión      : {stats['poca_comision']}")
        print(f"  Duplicadas         : {stats['duplicados']}")
        print(f"  Enlaces verificados: {stats['verificados']}")
        print(f"\n  Achados Shopee listos: {len(achados)}")
        if args.test:
            for i, o in enumerate(achados[:5], 1):
                print(f"   {i}. {o['nombre'][:58]} | R$ {o['precio']:.2f} | -{o['desc_pct']:.0f}% | {o['url'][:80]}")
            print("  (modo --test: no se escribe ningún fichero)")
            return 0
        escribir_salida(achados, {"fuente": "feed", "feed": str(feed)})
        print(f"  [OK] achados_shopee.json escrito ({len(achados)} ofertas).")
        if args.json:
            print(json.dumps(achados, ensure_ascii=False, indent=2))
        return 0

    # ── FUENTE 3: grupos de Telegram (método BlueBot, sin API) ───────────────
    # Se usa cuando no hay API ni feed, o cuando se pide con --telegram.
    if hay_tg and (args.telegram or not hay_api):
        print(f"  Fuente    : grupos de ofertas de Telegram -> enlace reconvertido")
        try:
            achados, st = cosechar_desde_telegram(
                ruta_tg, min_desc=min_desc, max_achados=int(cfg.get("max_telegram", 40)),
                verificar_n=0 if args.test else 3)
        except Exception as e:
            print(f"  [X] No se pudieron usar las ofertas de Telegram: {e}")
            if not args.test:
                escribir_salida([])
            return 2

        print("-" * 68)
        print(f"  Ofertas leídas     : {st['ofertas']}")
        print(f"  De otras tiendas   : {st['sin_enlace_shopee']}")
        print(f"  Sin título útil    : {st['sin_titulo']}")
        print(f"  Sin precio         : {st['sin_precio']}")
        print(f"  Vetadas            : {st['vetados']}")
        print(f"  Poco descuento     : {st['poco_descuento']}")
        print(f"  Duplicadas         : {st['duplicados']}")
        print(f"  Enlace no resuelto : {st['no_resueltos']}")
        print(f"  Sin foto           : {st['sin_imagen']}")
        print(f"  Enlaces verificados: {st['verificados']}")
        print(f"\n  Achados Shopee listos: {len(achados)}")
        if st["errores"]:
            for e in st["errores"][:3]:
                print(f"     - {e[:140]}")
        if args.test:
            for i, o in enumerate(achados[:5], 1):
                print(f"   {i}. {o['nombre'][:56]} | R$ {o['precio']:.2f} | -{o['desc_pct']:.0f}% | {o['url'][:70]}")
            print("  (modo --test: no se escribe ningún fichero)")
            return 0
        # ⚠ El precio viene del mensaje del grupo: queda marcado en cada achado
        # con `precio_fuente` para que se pueda auditar y apagar si molesta.
        escribir_salida(achados, {"fuente": "telegram", "telegram": str(ruta_tg),
                                  "aviso": "precio tomado del mensaje del grupo, no verificado en Shopee"})
        print(f"  [OK] achados_shopee.json escrito ({len(achados)} ofertas).")
        if args.json:
            print(json.dumps(achados, ensure_ascii=False, indent=2))
        return 0

    # ── FUENTE 1: API oficial ────────────────────────────────────────────────
    busquedas = lista_busquedas(cfg)
    if args.test:
        busquedas = busquedas[:1]
        args.limite = 5

    print(f"  Fuente    : API oficial (productOfferV2)")
    print(f"  Búsquedas : {len(busquedas)}")
    print(f"  Filtros   : descuento >= {min_desc}% | comisión >= {min_comision}% | máx {max_achados}")
    print("-" * 68)

    achados, stats = cosechar(busquedas, limite_por_busqueda=args.limite,
                              min_desc=min_desc, min_comision=min_comision,
                              max_achados=max_achados)

    print("-" * 68)
    print(f"  Consultas OK       : {stats['consultas']} ({stats['consultas_fallidas']} fallidas)")
    print(f"  Ofertas vistas     : {stats['ofertas_vistas']}")
    print(f"  Vetadas            : {stats['vetados']}")
    print(f"  Poco descuento     : {stats['poco_descuento']}")
    print(f"  Poca comisión      : {stats['poca_comision']}")
    print(f"  Sin enlace afiliado: {stats['sin_enlace']}")
    print(f"  Duplicadas         : {stats['duplicados']}")
    print(f"  Links generados    : {stats['links_generados']}")
    if stats["comisiones"]:
        coms = sorted(stats["comisiones"])
        print(f"  Comisión real      : min {coms[0]:.1f}% | media {sum(coms)/len(coms):.1f}% | max {coms[-1]:.1f}%")
    if stats["errores"]:
        print(f"  Avisos             : {len(stats['errores'])}")
        for e in stats["errores"][:5]:
            print(f"     - {e[:150]}")

    print(f"\n  Achados Shopee listos: {len(achados)}")

    if args.test:
        print("  (modo --test: no se escribe ningún fichero)")
        if achados:
            for i, o in enumerate(achados[:5], 1):
                print(f"   {i}. {o['nombre'][:60]} | R$ {o['precio']:.2f} "
                      f"| -{o['desc_pct']:.0f}% | {o['comision_pct']:.1f}% com. | {o['url']}")
        else:
            print("   Ninguna oferta pasó los filtros. Baja --min-desc para ver más.")
        return 0

    escribir_salida(achados, {"fuente": "api",
                              "filtros": {"min_desc": min_desc, "min_comision": min_comision}})
    print(f"  [OK] achados_shopee.json escrito ({len(achados)} ofertas).")

    if args.json:

        print(json.dumps(achados, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
