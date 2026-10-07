#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Generador de Fila Rotativa de Posts (gerar_fila_posts.py)
==================================================================
Modo Canal Profesional (CRIBA Ofertas):
- Lee achados.json, achados_ml.json, achados_amazon.json y cupones.json.
- Crea una fila balanceada en 'fila_posts.json' con mezcla rotativa:
    * 40% productos Mercado Livre
    * 25% productos Amazon
    * 20% cupones Mercado Livre / Amazon
    * 15% posts especiales tipo "cupons do dia" / ofertas flash
- Evita repetir el mismo producto durante 48h (cruzando logs/enviados.json).
- Evita publicar más de 2 productos seguidos de la misma categoría.
- Genera posts de cupones reales con links monetizados para activación.
- REGLA DE ORO ESTRICTA: 0 enlaces sin comisión.

Uso: python gerar_fila_posts.py
"""

import json
import os
import re
import random
import sqlite3
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent
ACHADOS_JSON = BASE / "achados.json"
FILE_ML = BASE / "achados_ml.json"
FILE_AMZ = BASE / "achados_amazon.json"
CUPONES_JSON = BASE / "cupones.json"
FILA_JSON = BASE / "fila_posts.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
ENVIADOS_JSON = LOG_DIR / "enviados.json"
CONFIG_FILE = BASE / "config_afiliados.json"

ML_ID = "ja20250119201346"
ML_TAG = "ja20250119201346"
AMAZON_TAG = "criba20-20"
# Hosts de enlace corto de afiliado de Shopee (ver shopee_api.py).
# Shopee no lleva tag en la URL: el enlace corto ES la credencial.
HOSTS_SHOPEE = ("s.shopee.com.br", "shp.ee")


def elegir_link_afiliado(item):
    """Elige el mejor link de afiliado DIRECTO para el producto.
    
    Prioridad para ML: meli_la > url (con tag) > NUNCA url_corta (/go/)
    Prioridad para Amazon: url (con tag=criba20-20)
    """
    loja = item.get("loja", "")
    meli_la = item.get("meli_la", "")
    url = item.get("url", "")
    
    if "Mercado Livre" in loja or "mercadolivre" in loja.lower():
        # 1. meli.la es la prioridad máxima
        if meli_la and "meli.la" in meli_la:
            return meli_la
        # 2. URL directa con tag de afiliado
        if url and ML_TAG in url:
            return url
        # 3. URL directa sin tag → agregar tag
        if url and "mercadolivre.com.br" in url:
            sep = "#" if "#" not in url else "&"
            return f"{url}{sep}D[A:{ML_TAG}]"
        return url
    elif "Amazon" in loja:
        # URL directa con tag
        if url and f"tag={AMAZON_TAG}" in url:
            return url
        if url and "amazon.com.br" in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}tag={AMAZON_TAG}"
        return url
    return url


def _parsear_descuento_cupon(cupon):
    """
    Extrae (porcentaje, tope_maximo, valor_absoluto) de un cupón.

    Los cupones de ML vienen como texto libre del canal de afiliados:
        🎟️ OFFMLHOJE 👉 10% OFF
        Tecnologia | Compra mínima: R$149 | Desconto máx.: R$200
    O a veces en valor absoluto:
        🛋️ R$100 OFF em Móveis / Compra mínima: R$499

    Sin el porcentaje Y el tope no se puede calcular el precio final: un
    "30% OFF" con tope de R$50 sobre un producto de R$500 descuenta 50, no 150.
    """
    pct = tope = valor = None
    for campo in ("desconto", "valor", "titulo"):
        txt = str(cupon.get(campo) or "")
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", txt)
        if m and pct is None:
            try:
                pct = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    for campo in ("limite", "desconto_max", "tope", "valor", "titulo"):
        txt = str(cupon.get(campo) or "")
        m = re.search(r"R\$\s*([\d.,]+)", txt)
        if m and tope is None:
            try:
                tope = float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
    # Descuento en valor absoluto (sin porcentaje): "R$100 OFF"
    if pct is None and tope:
        valor = tope
        tope = None
    return pct, tope, valor


# ─── CUPONES: ¿ESTE CUPÓN APLICA A ESTE PRODUCTO? ─────────────────────────────
# BUG GRAVE REPORTADO POR EL USUARIO: se publicaba un cupón de 30% en una silla
# de bebé y el cupón no aplicaba. Y un cupón de Tecnología en un producto de
# Casa. Publicar un cupón que no sirve destruye la confianza del grupo, que es
# el único activo real de un canal de ofertas.
#
# Había TRES fallos:
#   1. Si un cupón no declaraba tienda, el filtro lo dejaba pasar para CUALQUIER
#      tienda (las dos condiciones del if se saltaban).
#   2. No se comparaba la CATEGORÍA del cupón con la del producto.
#   3. "Geral" se interpretaba como "aplica a todo", cuando ML lo restringe a
#      "produtos elegíveis" que solo ML conoce.
#
# Ahora:
#   - La tienda tiene que coincidir y estar declarada en AMBOS lados.
#   - Si el cupón declara categoría, el producto tiene que ser de esa categoría.
#   - Los cupones "Geral" (sin categoría) se marcan como confianza BAJA: se
#     pueden mencionar, pero NO se calcula ni se promete el precio final.
CATEGORIAS_DE_CUPON = {
    "tecnologia": ["Monitores & Displays", "Hardware & Componentes", "Notebooks & PCs",
                   "Periféricos & Setup Gamer", "Smartphones & Celulares",
                   "Games & Gift Cards", "Gadgets & Smart Tech"],
    "informatica": ["Monitores & Displays", "Hardware & Componentes", "Notebooks & PCs",
                    "Periféricos & Setup Gamer", "Smartphones & Celulares",
                    "Games & Gift Cards", "Gadgets & Smart Tech"],
    "eletronicos": ["Monitores & Displays", "Gadgets & Smart Tech",
                    "Smartphones & Celulares", "Games & Gift Cards"],
    "beleza": ["Beleza & Higiene", "Perfumes & Fragrâncias"],
    "perfume": ["Perfumes & Fragrâncias"],
    "relogio": ["Relógios & Smartwatches"],
    "casa": ["Casa & Limpeza", "Casa & Móveis", "Cozinha & Eletro"],
    "moveis": ["Casa & Móveis"],
    "cozinha": ["Cozinha & Eletro"],
    "pet": ["Pet Shop"],
    "esporte": ["Esporte & Fitness"],
    "ferramentas": ["Ferramentas"],
    "bebe": ["Bebê"],
    "automotivo": ["Automotivo"],
}

# Categorías de cupón que NO permiten prometer nada (dependen de ML)
CATEGORIAS_VAGAS = {"", "geral", "gerais", "todos", "todas", "desconto especial"}


def _categoria_cupon(cupon):
    """Categoría normalizada del cupón, mirando categoria y titulo."""
    for campo in ("categoria", "titulo"):
        valor = normalizar(str(cupon.get(campo) or ""))
        if not valor:
            continue
        if valor in CATEGORIAS_VAGAS:
            continue
        for clave in CATEGORIAS_DE_CUPON:
            if clave in valor:
                return clave
    return ""


def _tienda_de(texto):
    """'Mercado Livre' / 'Amazon' / '' a partir de un texto."""
    t = normalizar(str(texto or ""))
    if "mercado" in t or "melivre" in t:
        return "mercadolivre"
    if "amazon" in t:
        return "amazon"
    if "shopee" in t:
        return "shopee"
    if "kabum" in t:
        return "kabum"
    if "magalu" in t:
        return "magalu"
    return ""


def _minimo_de(cupon):
    """Compra mínima del cupón en número (0 si no se sabe)."""
    txt = str(cupon.get("compra_minima") or "")
    m = re.search(r"([\d.]+(?:,\d{2})?)", txt.replace("R$", "").strip())
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def elegir_cupon(item, cupones):
    """
    Devuelve el cupón que APLICA a este producto, o None.

    Devuelve un dict con: codigo, pct, tope, valor, confianza ('alta'|'baja'),
    motivo. La confianza es 'baja' cuando el cupón es de categoría vaga (Geral),
    porque ML decide qué productos son elegibles y nosotros no podemos saberlo.
    """
    loja_item = _tienda_de(item.get("loja"))
    if not loja_item:
        return None
    try:
        precio = float(item.get("precio") or 0)
    except (TypeError, ValueError):
        precio = 0
    cat_item = item.get("categoria_canal") or clasificar_categoria(item.get("nombre", ""))
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    candidatos = []
    for c in cupones:
        codigo = (c.get("codigo") or "").strip()
        if not codigo:
            continue

        # ── 1. TIENDA: tiene que estar declarada y coincidir ────────────────
        tienda_c = _tienda_de(c.get("tienda"))
        if not tienda_c:
            continue                      # sin tienda declarada -> no se usa
        if tienda_c != loja_item:
            continue

        # ── 2. VIGENCIA ─────────────────────────────────────────────────────
        hasta = c.get("hasta") or c.get("vencimento") or ""
        if hasta and hasta < hoy:
            continue

        # ── 3. COMPRA MÍNIMA ────────────────────────────────────────────────
        minimo = _minimo_de(c)
        if minimo and precio and precio < minimo:
            continue

        # ── 4. CATEGORÍA ────────────────────────────────────────────────────
        cat_cupon = _categoria_cupon(c)
        if cat_cupon:
            permitidas = CATEGORIAS_DE_CUPON.get(cat_cupon, [])
            if permitidas and cat_item not in permitidas:
                continue                  # el cupón es de otra categoría
            confianza = "alta"
            motivo = f"categoría {cat_cupon} coincide con {cat_item}"
        else:
            # Cupón "Geral" o sin categoría: ML decide qué es elegible.
            confianza = "baja"
            motivo = "cupón general (ML decide qué produtos são elegíveis)"

        pct, tope, valor = _parsear_descuento_cupon(c)
        candidatos.append({
            "codigo": codigo,
            "pct": pct,
            "tope": tope,
            "valor": valor,
            "confianza": confianza,
            "motivo": motivo,
        })

    if not candidatos:
        return None
    # Preferir los de confianza alta y, entre esos, el mayor descuento
    candidatos.sort(key=lambda x: (x["confianza"] == "alta", x.get("pct") or 0),
                    reverse=True)
    return candidatos[0]


def buscar_cupon_para_producto(item, cupones):
    """Compatibilidad: devuelve solo el código del cupón aplicable."""
    elegido = elegir_cupon(item, cupones)
    return elegido["codigo"] if elegido else None


def _buscar_cupon_viejo(item, cupones):
    """(sin uso) Código original con los tres fallos documentados arriba."""
    loja = item.get("loja", "").lower()
    precio = float(item.get("precio") or 0)
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for c in cupones:
        tienda_c = (c.get("tienda") or "").lower()
        # Matchear tienda
        if "mercado" in loja and "mercado" not in tienda_c:
            continue
        if "amazon" in loja and "amazon" not in tienda_c:
            continue
        # Verificar vigencia
        hasta = c.get("hasta") or c.get("vencimento") or "9999-12-31"
        if hasta < hoy:
            continue
        # Verificar compra mínima
        minimo_str = c.get("compra_minima") or ""
        if minimo_str:
            try:
                minimo = float(re.sub(r"[^\d.,]", "", minimo_str.replace(",", ".")))
                if precio > 0 and precio < minimo:
                    continue
            except (ValueError, TypeError):
                pass
        codigo = c.get("codigo")
        if codigo:
            return codigo
    return None

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def cargar_enviados_recientes(horas=48):
    """
    Retorna el conjunto de IDs enviados en las últimas N horas.

    OJO: los `ts` de logs/enviados.json son UTC *naive* (los escribe
    datetime.utcnow().isoformat()). Compararlos contra un `limite` con timezone
    lanzaba TypeError, y el `except` metía el producto en `bloqueados` SIEMPRE,
    sin importar su antigüedad. Resultado: la ventana de enfriamiento no se
    aplicaba nunca y el catálogo se agotaba (la fila cayó de 29 a 11 posts).
    """
    if not ENVIADOS_JSON.exists():
        return set()
    try:
        data = json.loads(ENVIADOS_JSON.read_text(encoding="utf-8-sig"))
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=horas)
        bloqueados = set()
        con_error = 0
        for pid, val in data.items():
            ts_str = val.get("ts", "") if isinstance(val, dict) else str(val)
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:            # <-- el arreglo
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts > limite:
                    bloqueados.add(pid)
            except Exception:
                # Si no se puede leer la fecha, bloquear es lo prudente
                # (mejor no repetir que repetir), pero que no sea silencioso.
                con_error += 1
                bloqueados.add(pid)
        if con_error:
            print(f"  [aviso] {con_error} entradas de enviados.json con fecha ilegible")
        return bloqueados
    except Exception:
        return set()


# ─── Repetición inteligente por PRECIO ────────────────────────────────────────
# El producto repetido NO es spam si el precio cambió: hoy puede estar a un
# precio y mañana más barato, o estar más barato que en otras tiendas. Un canal
# de ofertas vive de eso ("¡bajó de precio!").
#
# Regla de tres niveles:
#   1. Enviado hace menos de HORAS_MIN_REPETIR (3h)  -> vetado (suelo anti-spam)
#   2. Dentro de HORAS_ENFRIAMIENTO pero el precio BAJÓ >= MEJORA_MIN_PCT -> PERMITIDO
#   3. Dentro de HORAS_ENFRIAMIENTO y sin mejora de precio -> vetado (no aporta nada)
#   > HORAS_ENFRIAMIENTO                            -> permitido
HORAS_MIN_REPETIR = float(os.environ.get("HORAS_MIN_REPETIR", "3"))
MEJORA_MIN_PCT = float(os.environ.get("MEJORA_MIN_PCT", "3")) / 100.0

# ─── FRESCURA (regla del usuario, 2026-10-07) ─────────────────────────────────
# "cada cosa que consigas actualizada de menos de 12 h, publicas".
# Una oferta de hace 3 días ya no es una oferta: el precio cambió, el stock se
# agotó o el enlace murió. Si la cosecha de una tienda se rompe (p.ej. Amazon
# bloqueando las IPs de GitHub), sus ofertas dejan de renovarse y este filtro
# las retira SOLO en vez de seguir publicándolas como si fueran de hoy.
# Se puede subir/bajar con MAX_EDAD_HORAS.
MAX_EDAD_HORAS = float(os.environ.get("MAX_EDAD_HORAS", "12"))


def cargar_enviados_raw():
    if not ENVIADOS_JSON.exists():
        return {}
    try:
        d = json.loads(ENVIADOS_JSON.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _horas_desde(ts_str):
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return None


def edad_horas(item):
    """
    Horas desde la última confirmación REAL de la oferta. Se toma la fecha más
    reciente de las tres que escriben los cosechadores:
      encontrado_em  -> cuándo se encontró/rencontró el producto
      revalidado_em  -> cuándo el unificador lo dio por bueno
      criado_em      -> cuándo entró a la fila
    Devuelve None si el item no trae ninguna fecha (no se puede demostrar que
    esté fresco, así que no se publica).
    """
    mejor = None
    for campo in ("encontrado_em", "revalidado_em", "criado_em"):
        h = _horas_desde(item.get(campo))
        if h is not None and (mejor is None or h < mejor):
            mejor = h
    return mejor


def _minimos_30d():
    """
    {id_producto: precio_mínimo} de los últimos 30 días, leído del histórico
    REAL (precios.db -> historico_precios, que llena unir_achados.py).

    Solo se devuelven productos con AL MENOS 2 registros: con uno solo no se
    puede afirmar que sea "el mínimo de 30 días", y este bot no afirma lo que no
    puede demostrar.
    """
    db = BASE / "precios.db"
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(db)
        desde = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        por_producto = {}
        for pid, precio, fecha in con.execute(
                "SELECT producto_id, precio, fecha FROM historico_precios WHERE fecha >= ?", (desde,)):
            try:
                p = float(precio)
            except (TypeError, ValueError):
                continue
            if p > 0:
                por_producto.setdefault(str(pid), []).append(p)
        con.close()
        return {pid: min(v) for pid, v in por_producto.items() if len(v) >= 2}
    except Exception:
        return {}


def puntaje_oferta(item):
    """
    Cuánto vale la pena publicar esta oferta. Es lo que ordena la fila.
      · descuento real (desc_pct)      -> el motor principal
      · frescura (< MAX_EDAD_HORAS h)  -> hasta +25
      · cupón CONFIRMADO por la tienda -> +20
      · precio bajo                    -> hasta +10 (R$ 0 suma 10, R$ 150+ suma 0)
      · readmitida porque BAJÓ          -> +15
    Nada de esto inventa datos: solo ordena lo que ya viene verificado.
    """
    desc = float(item.get("desc_pct") or 0)
    edad = edad_horas(item)
    frescura = 0.0
    if edad is not None and MAX_EDAD_HORAS > 0:
        frescura = max(0.0, (MAX_EDAD_HORAS - edad) / MAX_EDAD_HORAS) * 25.0
    cupon = 20.0 if item.get("ml_tiene_cupon") else 0.0
    try:
        precio = float(item.get("precio") or 0)
    except (TypeError, ValueError):
        precio = 0.0
    barato = 10.0 * max(0.0, (150.0 - precio) / 150.0) if precio > 0 else 0.0
    bajada = 15.0 if item.get("_bajada") else 0.0
    return desc + frescura + cupon + barato + bajada


def repeticion_permitida(pid, precio_actual, enviados_raw):
    """
    (permitido, motivo). Decide si vale la pena volver a publicar un producto
    que ya se envió, basándose en si el precio mejoró.
    """
    e = enviados_raw.get(pid)
    if not isinstance(e, dict):
        return True, "sin registro previo"

    horas = _horas_desde(e.get("ts"))
    if horas is None:
        return False, "fecha ilegible"

    if horas < HORAS_MIN_REPETIR:
        return False, f"enviado hace {horas:.1f}h (< {HORAS_MIN_REPETIR:.0f}h)"

    previo = e.get("precio")
    try:
        previo = float(previo)
        actual = float(precio_actual)
    except (TypeError, ValueError):
        return False, "sin precios comparables"

    if previo <= 0 or actual <= 0:
        return False, "precio no válido"

    if actual <= previo * (1 - MEJORA_MIN_PCT):
        ahorro = (previo - actual) / previo * 100
        return True, f"BAJÓ R$ {previo:.0f} -> R$ {actual:.0f} (-{ahorro:.0f}%)"

    return False, f"sin mejora (R$ {previo:.0f} -> R$ {actual:.0f})"

def cargar_cupones_reales():
    """
    Carga cupones reales y vigentes de cupones.json.

    OJO con `hasta = c.get("hasta", "9999-12-31")`: si la clave EXISTE con valor
    None (que es lo que escribe ahora la fuente oficial cuando ML no publica la
    fecha), el valor por defecto NO se aplica y la comparación `None >= hoy`
    lanzaba TypeError. Esa excepción la tragaba el `except` de abajo y devolvía
    una lista vacía EN SILENCIO: cero cupones, cero posts de cupón, y nadie se
    enteraba. Ahora se normaliza el valor y, si algo falla, se dice.
    """
    if not CUPONES_JSON.exists():
        return []
    try:
        data = json.loads(CUPONES_JSON.read_text(encoding="utf-8-sig"))
        lista = data.get("cupones", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        hoy = datetime.now(timezone.utc).date().isoformat()
        validos = []
        for c in lista:
            if not isinstance(c, dict):
                continue
            tienda = c.get("tienda", "").lower()
            # Regla de oro: solo tiendas monetizadas (ML y Amazon hoy)
            if "mercado" not in tienda and "amazon" not in tienda and "shopee" not in tienda:
                continue
            hasta = str(c.get("hasta") or c.get("vencimento") or "9999-12-31")
            if hasta >= hoy:
                validos.append(c)
        return validos
    except Exception as e:
        print(f"  ⚠️  No se pudieron cargar los cupones: {e}")
        return []

KEYWORDS_TECH = [
    # Monitores y Displays
    "monitor", "ultrawide", "ips", "144hz", "165hz", "180hz", "240hz", "75hz", "curvo", "fhd", "qhd", "4k", "oled", "gamer",
    # Hardware & Componentes
    "pc", "computador", "notebook", "laptop", "macbook", "ryzen", "intel", "core i3", "core i5", "core i7", "core i9",
    "ssd", "nvme", "m.2", "sata", "memoria", "memória", "ram", "ddr4", "ddr5",
    "placa de video", "placa de vídeo", "rtx", "gtx", "geforce", "radeon", "rx ", "gpu",
    "placa mae", "placa-mãe", "placa mãe", "gabinete", "cooler", "water cooler", "fonte atx",
    # Periféricos & Setup Gamer
    "teclado", "mouse", "headset", "fone de ouvido", "headphone", "microfone", "webcam",
    "mousepad", "cadeira gamer", "mesa gamer", "hub usb", "suporte monitor",
    # Audio y conectividad: se añaden porque títulos legítimos como
    # "Fone Bluetooth Soundcore P20i" se quedaban FUERA (no decían "de ouvido").
    # Falso negativo = pierdes una venta; falso positivo = pierdes credibilidad.
    "fone", "bluetooth", "earbud", "soundbar", "caixa de som", "power bank",
    "carregador", "carregador turbo", "adaptador usb", "hub usb-c",
    # Games, Consolas & Gift Cards
    "playstation", "ps5", "ps4", "xbox", "nintendo", "switch", "dualsense", "joy-con", "controle sem fio",
    "gift card", "cartao presente", "cartão presente", "steam", "roblox", "play store", "game pass",
    # Smartphones & Smart Tech
    "smartphone", "celular", "iphone", "galaxy", "xiaomi", "redmi", "poco", "motorola",
    "tablet", "ipad", "kindle", "alexa", "echo pop", "echo dot", "fire tv stick", "chromecast", "roku",
    # Perfumes & Fragrâncias Importadas e Nacionais
    "perfume", "fragrancia", "fragrância", "colonia", "colônia", "eau de parfum", "eau de toilette",
    "lattafa", "asaf", "natura", "boticario", "boticário", "malbec", "zaad", "sauvage", "one million", "versace", "ferrari black", "silver scent", "invictus",
    # Relógios & Smartwatches
    "relogio", "relógio", "smartwatch", "smart watch", "casio", "g-shock", "invicta", "technos", "curren", "poedagar", "naviforce", "skmei", "mormaii"
]

EXCLUIR_SOLO_TECH = [
    "panela", "toalha", "motosserra", "whey", "creatina", "suplemento",
    "aspirador", "fritadeira", "air fryer", "ar condicionado", "ventilador", "armario", "armário",
    "mochila", "casinha", "cachorro", "pet", "colchao", "travesseiro", "tenis", "tênis", "camisa",
    "vestido", "bermuda", "bijuteria", "shampoo", "condicionador", "hidratante",
    # ── Limpieza y hogar ─────────────────────────────────────────────────────
    # Un suavizante de ropa pasó el filtro porque su título de Amazon decía
    # "Fabric Softener com Perfume Intenso" y "perfume" está en KEYWORDS_TECH
    # (los perfumes SÍ son nicho). La palabra clave debe describir el PRODUCTO,
    # no una característica, así que excluimos explícitamente el hogar/limpieza.
    "amaciante", "fabric softener", "sabao", "sabão", "detergente", "desinfetante",
    "alvejante", "multiuso", "limpa", "limpador", "lustra", "cera liquida", "cera líquida",
    "lava roupas", "lava-roupas", "amaciantes", "papel higienico", "papel higiênico",
    "fralda", "absorvente", "saco de lixo", "esponja", "vassoura", "rodo", "balde",
    "desodorizador", "aromatizante", "home spray", "difusor", "odorizador",
    "racao", "ração", "areia sanitaria", "areia sanitária",
    # ── Higiene personal (que NO es el nicho "perfumes") ─────────────────────
    # Segundo caso real: 'Boni Natural Creme Dental com Óleos Naturais' pasó el
    # filtro porque "Naturais" contiene "natura", y "natura" es una marca de
    # perfumes de KEYWORDS_TECH. Mismo fallo que el Downy: coincidencia por
    # subcadena con una palabra que describe ingrediente/característica, no el
    # producto. La exclusión gana sobre las keywords.
    "creme dental", "pasta de dente", "pasta dental", "escova de dente",
    "fio dental", "enxaguante", "antisseptico", "antisséptico", "bochecho",
    "sabonete", "gel de banho", "espuma de barbear", "aparelho de barbear",
    "lamina de barbear", "lâmina de barbear", "lenco umedecido", "lenço umedecido",
    "cotonete", "algodao", "algodão", "esmalte", "acetona",
    "removedor de esmalte", "protetor solar", "repelente", "inseticida",
    "raticida", "formicida", "desentupidor"
]

# ─── MODO DE NICHO ────────────────────────────────────────────────────────────
# 'tech'  = solo tecnologia, perfumes y relojes (nicho original, mas cerrado)
# 'geral' = achadinhos generales (casa, limpeza, higiene, suplementos, pet...)
#
# Por qué existe 'geral': medido sobre 69 ofertas scrapeadas, el 100% tenia link
# monetizado pero SOLO 14 pasaban el filtro tech, y las 29 de Amazon caian TODAS
# (su scraper trae categorias de hogar/belleza/suplementos). Resultado: cero
# publicaciones de Amazon en el grupo y el 80% del material monetizable tirado.
#
# Para un canal de achadinhos, los consumibles de casa son ademas los que MAS
# repiten compra (fralda, limpeza, suplemento), asi que suelen convertir mejor
# que la tecnologia, que se compra una vez cada anos.
NICHO_MODO = os.environ.get("NICHO_MODO", "geral").strip().lower()

# Vetos absolutos: no entran en NINGUN modo (no son afiliables o no encajan).
EXCLUIR_SIEMPRE = [
    "medicamento", "remedio", "remédio", "farmacia", "farmácia", "antibiotico",
    "antibiótico", "generico", "genérico", "arma ", "arma de", "municao", "munição",
    "cigarro", "vape", "pod descartavel", "narguile", "aposta", "apostas",
    "cerveja", "vinho", "whisky", "vodka", "gin ", "energetico alcoolico",
]

# Palabras que en modo 'geral' son BIENVENIDAS (en modo 'tech' estaban vetadas).
KEYWORDS_GERAL = [
    # Limpieza y hogar
    "amaciante", "sabao", "sabão", "detergente", "desinfetante", "alvejante",
    "multiuso", "limpador", "lava roupas", "lava-roupas", "papel higienico",
    "papel higiênico", "papel toalha", "guardanapo", "saco de lixo", "esponja",
    "vassoura", "rodo", "balde", "desodorizador", "aromatizante", "odorizador",
    "toalha", "lençol", "lencol", "jogo de cama", "cobertor", "travesseiro",
    "colchao", "colchão", "organizador", "caixa organizadora", "cabide",
    # Cozinha
    "panela", "frigideira", "jogo de panelas", "air fryer", "fritadeira",
    "aspirador", "liquidificador", "batedeira", "cafeteira", "chaleira",
    "sanduicheira", "micro-ondas", "microondas", "faqueiro", "jogo de pratos",
    "copo", "garrafa", "marmita", "utensilio", "utensílio", "tábua", "tabua",
    "cozinha", "casa inteligente", "ventilador", "climatizador", "umidificador",
    "purificador", "ar condicionado", "ferro de passar", "maquina de costura",
    # Higiene y beleza
    "creme dental", "pasta de dente", "escova de dente", "fio dental",
    "enxaguante", "sabonete", "gel de banho", "shampoo", "condicionador",
    "hidratante", "protetor solar", "desodorante", "perfume", "fragrancia",
    "fragrância", "colonia", "colônia", "cotonete", "algodao", "algodão",
    "fralda", "absorvente", "lenco umedecido", "lenço umedecido", "esmalte",
    "maquiagem", "batom", "base facial", "secador de cabelo", "prancha",
    "chapinha", "barbeador", "aparador de pelos", "depilador",
    # Suplementos e saude
    "whey", "creatina", "suplemento", "vitamina", "colageno", "colágeno",
    "omega", "ômega", "pre-workout", "termogenico", "termogênico", "albumina",
    "proteina", "proteína", "bcaa", "glutamina", "multivitaminico",
    # Pet
    "racao", "ração", "areia sanitaria", "areia sanitária", "comedouro",
    "bebedouro", "coleira", "petisco", "brinquedo para cachorro", "casinha",
    "tapete higienico", "tapete higiênico", "caminha",
    # Bebé
    "mamadeira", "chupeta", "berco", "berço", "carrinho de bebe", "cadeirinha",
    "papinha", "leite em po", "leite em pó", "fralda",
    # Ferramentas, automotivo, esporte, papelaria
    "parafusadeira", "furadeira", "serra", "chave de fenda", "jogo de chaves",
    "trena", "multimetro", "multímetro", "caixa de ferramentas", "compressor",
    "aspirador de po", "aspirador de pó", "lavadora de alta pressao",
    "capota", "capa de volante", "suporte de celular para carro", "oleo",
    "óleo", "pneu", "bateria automotiva", "som automotivo", "camera de re",
    "bicicleta", "patins", "skate", "halter", "anilha", "colchonete",
    "corda de pular", "luva de treino", "faixa elastica", "faixa elástica",
    "mochila", "caderno", "caneta", "marcador", "papelaria", "mochila escolar",
    "mesa", "cadeira", "escrivaninha", "guarda-roupa", "sapateira", "estante",
    "tenis", "tênis", "camisa", "vestido", "bermuda", "bijuteria", "relogio",
]

EXCLUIR_NO_TECH = EXCLUIR_SOLO_TECH  # compatibilidad con codigo antiguo


def es_producto_tecnologia(nombre):
    """Nicho ORIGINAL cerrado: Tech, Hardware, Setup, Perfumes y Relojes."""
    n = (nombre or "").lower()
    if any(e in n for e in EXCLUIR_SIEMPRE):
        return False
    if any(e in n for e in EXCLUIR_SOLO_TECH):
        return False
    return any(k in n for k in KEYWORDS_TECH)


def es_producto_del_canal(nombre):
    """
    Filtro REAL que usa la generacion de la fila, segun NICHO_MODO.
    En modo 'geral' no se aplica la lista de exclusion del modo tech y se
    acepta tambien KEYWORDS_GERAL, que es lo que desbloquea Amazon y el hogar.
    """
    if NICHO_MODO != "geral":
        return es_producto_tecnologia(nombre)
    n = (nombre or "").lower()
    if any(e in n for e in EXCLUIR_SIEMPRE):
        return False
    return any(k in n for k in KEYWORDS_TECH + KEYWORDS_GERAL)

def clasificar_categoria(nombre):
    """Categoriza el producto para el sitio y para el balance del canal."""
    n = (nombre or "").lower()
    # ── Categorías de "achadinhos" (modo geral) ──────────────────────────────
    # Van PRIMERO porque son más específicas: si no, un suplemento acababa
    # etiquetado como "Gadgets & Smart Tech", que era el cajón de sastre.
    if any(k in n for k in ["creatina", "whey", "suplemento", "vitamina", "colageno",
                            "colágeno", "omega", "ômega", "proteina", "proteína",
                            "bcaa", "glutamina", "termogenico", "termogênico",
                            "albumina", "pre-workout", "multivitaminico"]):
        return "Suplementos & Saúde"
    if any(k in n for k in ["creme dental", "pasta de dente", "escova de dente",
                            "fio dental", "enxaguante", "sabonete", "gel de banho",
                            "shampoo", "condicionador", "hidratante", "desodorante",
                            "protetor solar", "fralda", "absorvente", "cotonete",
                            "algodao", "algodão", "esmalte", "maquiagem", "batom",
                            "barbeador", "depilador", "secador de cabelo", "prancha"]):
        return "Beleza & Higiene"
    if any(k in n for k in ["amaciante", "sabao", "sabão", "detergente", "desinfetante",
                            "alvejante", "multiuso", "limpador", "lava roupas",
                            "lava-roupas", "papel higienico", "papel higiênico",
                            "papel toalha", "guardanapo", "saco de lixo", "esponja",
                            "vassoura", "rodo", "balde", "aspirador", "desodorizador",
                            "aromatizante", "odorizador"]):
        return "Casa & Limpeza"
    if any(k in n for k in ["panela", "frigideira", "air fryer", "fritadeira",
                            "liquidificador", "batedeira", "cafeteira", "chaleira",
                            "sanduicheira", "micro-ondas", "microondas", "faqueiro",
                            "copo", "garrafa", "marmita", "utensilio", "utensílio",
                            "cozinha", "ventilador", "climatizador", "umidificador",
                            "purificador", "ferro de passar"]):
        return "Cozinha & Eletro"
    if any(k in n for k in ["racao", "ração", "areia sanitaria", "areia sanitária",
                            "comedouro", "bebedouro", "coleira", "petisco", "caminha",
                            "tapete higienico", "tapete higiênico"]):
        return "Pet Shop"
    if any(k in n for k in ["mamadeira", "chupeta", "berco", "berço", "carrinho de bebe",
                            "cadeirinha", "papinha", "leite em po", "leite em pó"]):
        return "Bebê"
    if any(k in n for k in ["parafusadeira", "furadeira", "serra", "chave de fenda",
                            "trena", "multimetro", "multímetro", "caixa de ferramentas",
                            "compressor", "lavadora de alta pressao"]):
        return "Ferramentas"
    if any(k in n for k in ["capota", "capa de volante", "oleo", "óleo", "pneu",
                            "bateria automotiva", "som automotivo", "camera de re"]):
        return "Automotivo"
    if any(k in n for k in ["bicicleta", "patins", "skate", "halter", "anilha",
                            "colchonete", "corda de pular", "faixa elastica",
                            "faixa elástica", "luva de treino"]):
        return "Esporte & Fitness"
    if any(k in n for k in ["toalha", "lençol", "lencol", "jogo de cama", "cobertor",
                            "travesseiro", "colchao", "colchão", "organizador", "cabide",
                            "mesa", "cadeira", "escrivaninha", "guarda-roupa",
                            "sapateira", "estante"]):
        return "Casa & Móveis"
    # ── Categorías tech (nicho original) ─────────────────────────────────────
    if any(k in n for k in ["perfume", "fragrancia", "fragrância", "colonia", "colônia", "parfum", "toilette", "malbec", "zaad"]):
        return "Perfumes & Fragrâncias"
    if any(k in n for k in ["relogio", "relógio", "smartwatch", "casio", "g-shock", "invicta", "technos"]):
        return "Relógios & Smartwatches"
    if any(k in n for k in ["monitor", "ultrawide", "144hz", "165hz", "180hz", "240hz"]):
        return "Monitores & Displays"
    if any(k in n for k in ["ssd", "nvme", "m.2", "ram", "memoria", "memória", "placa de video", "placa de vídeo", "rtx", "gtx", "radeon", "placa mae", "placa-mãe", "cooler", "fonte"]):
        return "Hardware & Componentes"
    if any(k in n for k in ["notebook", "laptop", "macbook", "pc gamer", "computador"]):
        return "Notebooks & PCs"
    if any(k in n for k in ["teclado", "mouse", "headset", "mousepad", "microfone", "webcam", "cadeira gamer"]):
        return "Periféricos & Setup Gamer"
    if any(k in n for k in ["playstation", "ps5", "xbox", "nintendo", "switch", "gift card", "steam", "roblox", "controle"]):
        return "Games & Gift Cards"
    if any(k in n for k in ["smartphone", "celular", "iphone", "galaxy", "xiaomi", "redmi"]):
        return "Smartphones & Celulares"
    return "Ofertas Gerais"

def _link_cupones_con_afiliado():
    """
    (link, es_corto) para la página de cupones de Mercado Livre.

    Intenta el meli.la OFICIAL (el enlace corto de referido que usan todos los
    canales de ofertas); si ML no lo permite para esa URL, devuelve el enlace
    largo CON el tag de afiliado, que también cobra. Nunca /go/: ese dominio no
    monetiza (Regla de Oro del proyecto).
    """
    try:
        from cupones_vigia import link_afiliado_cupones
        return link_afiliado_cupones()
    except Exception as e:
        print(f"  • [cupones] enlace corto no disponible ({e}); se usa el largo con tag")
        return f"https://www.mercadolivre.com.br/cupons#D[A:{ML_ID}]", False


def generar_posts_cupones(cupones_reales):
    """Crea posts de cupones estilo canal profesional con enlaces monetizados de activación."""
    posts_cupones = []
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    
    # Agrupar cupones por tienda
    por_tienda = {}
    for c in cupones_reales:
        t = "mercadolivre" if "mercado" in c.get("tienda", "").lower() else "amazon"
        por_tienda.setdefault(t, []).append(c)

    # 1. Posts de Cupones Mercado Livre en lotes de 3-4 (Priorizando ML Oficial y urgencia)
    cupons_ml = por_tienda.get("mercadolivre", [])
    hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Prioridad: 1) fuente "ML Oficial", 2) vencimiento hoy
    cupons_ml.sort(
        key=lambda c: (
            0 if "oficial" in (c.get("fonte") or "").lower() else 1,
            0 if (c.get("hasta") or c.get("vencimento")) == hoy_str else 1
        )
    )

    link_ativacao_ml, _es_corto = _link_cupones_con_afiliado()
    for chunk_idx in range(0, min(16, len(cupons_ml)), 4):
        grupo = cupons_ml[chunk_idx:chunk_idx+4]
        if not grupo:
            continue
        lineas = [f"🔥 Cupons Mercado Livre Selecionados #{chunk_idx//4 + 1}\n"]
        for c in grupo:
            cod = c.get("codigo") or "NO CARRINHO"
            # NADA INVENTADO: antes esto ponía "R$ 15 OFF" por defecto cuando la
            # fuente no traía descuento. Es un dato inventado en el grupo.
            desc = c.get("desconto") or "desconto não informado"
            # str(...) a propósito: hay cupones con "titulo": null en
            # cupones.json (clave presente, valor nulo) y .get(k, defecto) NO
            # aplica el defecto en ese caso -> None[:45] reventaba el generador
            # entero y la fila se quedaba sin cupones (y sin avisar).
            # Si el título no existe, no se inventa relleno: se omite el paréntesis.
            titulo = str(c.get("titulo") or "").strip()[:45]
            sufijo = f" ({titulo})" if titulo else ""
            vence = c.get("hasta") or c.get("vencimento")
            urgencia = " ⏰ Vence HOJE!" if vence == hoy_str else ""
            lineas.append(f"🎟️ {desc}: {cod}{sufijo}{urgencia}")
        lineas.append(f"\n⭐️ Ative por aqui para aplicar no carrinho:\n👉 {link_ativacao_ml}")
        
        posts_cupones.append({
            "id_post": f"cupom-ml-lote{chunk_idx//4 + 1}-{datetime.now().strftime('%Y%m%d%H')}",
            # OJO: el publicador SALTA el tipo legacy 'cupons_loja' (nunca se
            # publicó ni una tanda de cupones en el canal). El tipo nuevo es
            # 'cupon' y tiene su propia rama de envío.
            "tipo": "cupon",
            "loja": "Mercado Livre",
            "categoria": "Cupons",
            "titulo": f"🔥 Cupons Mercado Livre #{chunk_idx//4 + 1}",
            "mensaje": "\n".join(lineas),
            "codigos": [c.get("codigo") for c in grupo if c.get("codigo")],
            "url": link_ativacao_ml,
            "criado_em": ahora_iso,
            "prioridade": 10
        })

    # 2. Posts de Cupones Amazon en lotes de 3-4
    cupons_amz = por_tienda.get("amazon", [])
    link_ativacao_amz = f"https://www.amazon.com.br/gp/coupons?tag={AMAZON_TAG}"
    for chunk_idx in range(0, min(16, len(cupons_amz)), 4):
        grupo = cupons_amz[chunk_idx:chunk_idx+4]
        if not grupo:
            continue
        lineas = [f"🔥 Cupons & Promoções Amazon Brasil #{chunk_idx//4 + 1}\n"]
        for c in grupo:
            cod = c.get("codigo") or "RESGATE DIRETO"
            # NADA INVENTADO (antes: f"{c.get('valor', 10)}% OFF")
            desc = c.get("desconto") or "oferta não informada"
            titulo = str(c.get("titulo") or "Promoção especial")[:45]
            lineas.append(f"🎟️ {desc}: {cod} ({titulo})")
        lineas.append(f"\n⭐️ Resgate e ative seus cupons Amazon:\n👉 {link_ativacao_amz}")
        
        posts_cupones.append({
            "id_post": f"cupom-amz-lote{chunk_idx//4 + 1}-{datetime.now().strftime('%Y%m%d%H')}",
            "tipo": "cupon",
            "loja": "Amazon",
            "categoria": "Cupons",
            "titulo": f"🔥 Cupons & Promoções Amazon #{chunk_idx//4 + 1}",
            "mensagem": "\n".join(lineas),
            "codigos": [c.get("codigo") for c in grupo if c.get("codigo")],
            "url": link_ativacao_amz,
            "criado_em": ahora_iso,
            "prioridade": 9
        })

    return posts_cupones

def armar_fila_rotativa():
    """Genera la fila completa balanceando tiendas y evitando repetición de categorías."""
    print("=" * 60)
    print("  CRIBA · GENERADOR DE FILA DE POSTS (MODO CANAL VIVO)")
    print("=" * 60)

    # 1. Cargar todas las fuentes
    items_achados = []
    if ACHADOS_JSON.exists():
        try:
            d = json.loads(ACHADOS_JSON.read_text(encoding="utf-8"))
            items_achados = d.get("achados", []) if isinstance(d, dict) else d
        except Exception:
            pass

    items_ml = []
    if FILE_ML.exists():
        try:
            d = json.loads(FILE_ML.read_text(encoding="utf-8"))
            items_ml = d.get("achados", []) if isinstance(d, dict) else d
        except Exception:
            pass

    items_amz = []
    if FILE_AMZ.exists():
        try:
            d = json.loads(FILE_AMZ.read_text(encoding="utf-8"))
            items_amz = d.get("achados", []) if isinstance(d, dict) else d
        except Exception:
            pass

    items_esp = []
    file_esp = BASE / "achados_especificos.json"
    if file_esp.exists():
        try:
            d = json.loads(file_esp.read_text(encoding="utf-8"))
            items_esp = d.get("achados", []) if isinstance(d, dict) else d
        except Exception:
            pass

    # ── BLINDAJE: fuera las ofertas de EJEMPLO ───────────────────────────────
    # Estas ofertas entran por DOS sitios (la lista de "específicas" y el bucle
    # general de candidatos), así que hay que filtrarlas aquí, al cargarlas.
    # El 2026-09-30 se publicó así un "SSD Kingston NV2 1TB" a R$ 389 con precio
    # inventado, y quedaron en la fila otros dos de ejemplo (Monitor LG R$ 849 y
    # Teclado Redragon R$ 179,90) por delante de todo lo demás.
    def _especifica_confiable(x):
        """
        Puerta dura para achados_especificos.json.

        El 2026-09-09 se escribieron ahí 3 ofertas de EJEMPLO (Monitor LG R$ 849,
        SSD Kingston R$ 389,90, Teclado Redragon R$ 179,90) con ids inventados o
        precios fijos de plantilla. El campo `simulado` no las cubría porque son
        anteriores a él, así que siguieron en producción 28 días.
        Ahora no basta con "no estar marcada": hay que DEMOSTRAR que es real.
          · precio > 0
          · id con formato REAL de la tienda (MLB + dígitos / ASIN de 10)
          · url de la tienda
        Lo que no se pueda demostrar, no se publica.
        """
        if x.get("simulado"):
            return False
        if str(x.get("origem") or "") in ("agente_autonomo_api", "curadoria_agente_ia"):
            return False
        try:
            if float(x.get("precio") or 0) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        url = str(x.get("url") or "")
        pid = str(x.get("id") or "")
        loja = str(x.get("loja") or "")
        if not url or not pid or not loja:
            return False
        if "Mercado" in loja and not re.fullmatch(r"MLB\d{6,}", pid):
            return False
        if "Amazon" in loja and not re.fullmatch(r"[A-Z0-9]{10}", pid):
            return False
        if "Shopee" in loja and not x.get("afiliado_verificado"):
            return False
        return True

    sospechosas = [x for x in items_esp if not _especifica_confiable(x)]
    if sospechosas:
        print(f"  [Regla de Oro] {len(sospechosas)} oferta(s) curada(s) SIN datos "
              f"verificables descartadas: {[str(x.get('nombre'))[:28] for x in sospechosas][:3]}")
    items_esp = [x for x in items_esp if _especifica_confiable(x)]

    cupones = cargar_cupones_reales()
    # Ventana de enfriamiento anti-repetición (horas). Configurable porque es
    # el factor que MÁS limita cuántos posts/día se pueden publicar: con 48 h el
    # catálogo se agota enseguida, con 24 h se duplica el material disponible.
    horas_enfriamiento = int(os.environ.get("HORAS_ENFRIAMIENTO", "24"))
    bloqueados_48h = cargar_enviados_recientes(horas_enfriamiento)
    enviados_raw = cargar_enviados_raw()
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"  • Achados totales disponibles: {len(items_achados)}")
    print(f"  • Ofertas ML: {len(items_ml)} | Ofertas Amazon: {len(items_amz)}")
    print(f"  • Ofertas curadas con IA (específicas): {len(items_esp)}")
    print(f"  • Cupones activos cargados: {len(cupones)}")
    print(f"  • Enfriamiento {horas_enfriamiento}h: {len(bloqueados_48h)} productos "
          f"(suelo anti-spam {HORAS_MIN_REPETIR:.0f}h, mejora mínima {MEJORA_MIN_PCT*100:.0f}%)")
    print(f"  • Frescura exigida: {MAX_EDAD_HORAS:.0f}h (MAX_EDAD_HORAS)")

    # Unificar y filtrar por 48h (ofertas específicas tienen prioridad absoluta)
    todos_candidatos = []
    vistos_slug = set()
    reingresos = []   # productos readmitidos porque BAJARON de precio
    descartados_viejos = 0   # ofertas sin confirmar en las últimas MAX_EDAD_HORAS

    for item in (items_esp + items_achados + items_ml + items_amz):
        pid = item.get("id") or item.get("nombre", "")[:40]
        slug = normalizar(item.get("nombre", ""))[:32]
        
        # Anti-repetición INTELIGENTE: repetir está bien si el precio mejoró.
        if pid in bloqueados_48h:
            permitido, motivo = repeticion_permitida(pid, item.get("precio"), enviados_raw)
            if not permitido:
                continue
            reingresos.append((str(item.get("nombre", ""))[:44], motivo))
            # Se marca para que el post lo anuncie: repetir solo funciona si el
            # grupo SABE que el precio bajó. Si no, parece spam.
            item["_bajada"] = True
            try:
                item["_precio_antes"] = float(enviados_raw.get(pid, {}).get("precio"))
            except (TypeError, ValueError):
                item["_precio_antes"] = None
        if slug in vistos_slug:
            continue
        vistos_slug.add(slug)

        loja = item.get("loja", "")
        url = item.get("url", "")
        # Regla de oro estricta
        if "Mercado Livre" in loja:
            if "meli.la" not in url and ("mercadolivre.com.br" not in url or ML_TAG not in url):
                continue
        elif "Amazon" in loja:
            if "amazon.com.br" not in url or f"tag={AMAZON_TAG}" not in url:
                continue
        elif "Shopee" in loja:
            # Shopee no usa tag en la URL: su enlace de afiliado es un link corto
            # (s.shopee.com.br / shp.ee) que emite la API con la cuenta del
            # afiliado. Se exigen las dos cosas: el host y la marca que deja
            # agente_shopee.py. Un enlace shopee.com.br/product/... NO entra.
            if not item.get("afiliado_verificado") or not any(h in url for h in HOSTS_SHOPEE):
                continue
        else:
            continue

        # FILTRO DE NICHO: según NICHO_MODO ('tech' cerrado o 'geral' achadinhos)
        nombre_prod = item.get("nombre", "")
        if not es_producto_del_canal(nombre_prod):
            continue

        # FILTRO DE FRESCURA: "solo lo actualizado en menos de 12 h" (regla del
        # usuario). Protege al grupo de publicar material que ya no es oferta.
        edad = edad_horas(item)
        if edad is None or edad > MAX_EDAD_HORAS:
            descartados_viejos += 1
            continue

        cat = clasificar_categoria(nombre_prod)
        item["categoria_canal"] = cat
        todos_candidatos.append(item)

    print(f"  • Descartadas por ANTIGUAS (> {MAX_EDAD_HORAS:.0f}h sin confirmar): {descartados_viejos}")

    # Dividir candidatos por tienda
    cola_ml = [x for x in todos_candidatos if "Mercado Livre" in x.get("loja", "")]
    cola_amz = [x for x in todos_candidatos if "Amazon" in x.get("loja", "")]
    cola_shp = [x for x in todos_candidatos if "Shopee" in x.get("loja", "")]

    # ── ORDEN POR VALOR REAL (antes: random.shuffle) ──────────────────────────
    # El azar puro produjo el problema que reportó el usuario: 4 veces la misma
    # creatina en el grupo y ni un monitor. Ahora la fila va ordenada por lo que
    # vale de verdad (descuento real + frescura + cupón confirmado + precio
    # bajo). Se conserva variedad barajando SOLO dentro de bandas de 5 puntos,
    # así el primer puesto no es siempre el mismo producto pero nunca cae uno
    # malo delante de uno bueno.
    random.seed(int(datetime.now().strftime("%Y%m%d")))

    def _ordenar_por_valor(cola):
        bandas = {}
        for it in cola:
            bandas.setdefault(int(puntaje_oferta(it) // 5), []).append(it)
        salida = []
        for b in sorted(bandas, reverse=True):
            grupo = bandas[b]
            random.shuffle(grupo)
            salida.extend(grupo)
        return salida

    cola_ml = _ordenar_por_valor(cola_ml)
    cola_amz = _ordenar_por_valor(cola_amz)
    cola_shp = _ordenar_por_valor(cola_shp)

    # Crear posts de cupones
    posts_cupones = generar_posts_cupones(cupones)

    fila_final = []
    
    # 0. PRIORIDAD ABSOLUTA: Ofertas curadas con IA / específicas ingresadas por el usuario
    for esp in items_esp:
        # BLINDAJE: nunca publicar una oferta de EJEMPLO. El 2026-09-30 se
        # publicó así un "SSD Kingston NV2 1TB" a R$ 389 con precio inventado.
        if esp.get("simulado"):
            print(f"  [Regla de Oro] Descartada oferta SIMULADA: {str(esp.get('nombre'))[:50]}")
            continue
        if not es_producto_del_canal(esp.get("nombre", "")):
            continue
        pid = esp.get("id") or esp.get("nombre", "")[:40]
        permitido_esp = True
        if pid in bloqueados_48h:
            permitido_esp, motivo_esp = repeticion_permitida(pid, esp.get("precio"), enviados_raw)
            if permitido_esp:
                reingresos.append((str(esp.get("nombre", ""))[:44], motivo_esp))
        if permitido_esp:
            fila_final.append({
                "id_post": pid,
                "tipo": "producto",
                "loja": esp.get("loja", "Mercado Livre"),
                "categoria": esp.get("categoria_canal") or clasificar_categoria(esp.get("nombre", "")),
                "titulo": esp.get("nombre"),
                "precio": esp.get("precio"),
                "precio_anterior": esp.get("precio_anterior"),
                "desc_pct": esp.get("desc_pct"),
                "cupom": esp.get("cupom") or esp.get("cupon") or buscar_cupon_para_producto(esp, cupones),
                # NO se inventa el Pix. Si el origen no lo trae, queda vacío y el
                # post simplemente no muestra la línea. Ver el comentario largo
                # más abajo: antes se ponía "mais 5% OFF" a TODO, incluso a
                # productos sin descuento Pix.
                "pix": esp.get("pix") or "",
                # Datos de promocion LEIDOS DE MERCADO LIVRE (no adivinados):
                # si ML no dice que este producto tiene cupon, no se le pone
                # ninguno. Antes se asignaba por categoria y en la compra real
                # no aplicaba ("Seu cupom foi salvo em Cupons, pois nao se
                # aplica a esta compra").
                "ml_tiene_cupon": esp.get("ml_tiene_cupon"),
                "ml_precio_cupon": esp.get("ml_precio_cupon"),
                "ml_tiene_pix": esp.get("ml_tiene_pix"),
                "ml_precio_pix": esp.get("ml_precio_pix"),
                "imagen": esp.get("imagen"),
                "url": elegir_link_afiliado(esp),
                "criado_em": ahora_iso,
                "prioridade": 10,
                "destaque": esp.get("analise_ia", {}).get("destaque", "🔥 Oportunidade Selecionada")
            })

    idx_ml = 0
    idx_amz = 0
    idx_shp = 0
    idx_cupom = 0
    ultima_cat = None
    repeticiones_cat = 0

    # Armar hasta 100 posts alternando: ML, Amazon, Cupon, ML, Amazon, etc.
    # Tamaño objetivo de la fila. Debe ser MAYOR que el tope diario de envíos
    # (MAX_ENVIOS_DIA, 150) o el bucle se queda sin material a mitad de día.
    # Antes estaba clavado en min(120, ...) y era el último recorte artificial
    # que quedaba: con 600 ofertas disponibles, la fila seguía siendo de 120.
    fila_max = int(os.environ.get("FILA_MAX", "400"))
    fila_min = int(os.environ.get("FILA_MIN", "80"))
    total_deseado = min(fila_max, max(fila_min, len(todos_candidatos) + len(posts_cupones)))

    for step in range(total_deseado):
        item_elegido = None

        # Shopee entra en 1 de cada 3 huecos, y SOLO si hay ofertas suyas.
        # Mientras la API de afiliados no devuelva nada, cola_shp está vacía y
        # esta rama nunca se activa: el reparto sigue siendo ML/Amazon como antes.
        if step % 3 == 2 and idx_shp < len(cola_shp):
            candidato = cola_shp[idx_shp]
            idx_shp += 1
            item_elegido = {
                "id_post": candidato.get("id") or f"shp-{step}",
                "tipo": "producto",
                "loja": "Shopee",
                "categoria": candidato.get("categoria_canal", "Shopee Ofertas"),
                "titulo": candidato.get("nombre"),
                "precio": candidato.get("precio"),
                "precio_anterior": candidato.get("precio_anterior"),
                "desc_pct": candidato.get("desc_pct"),
                # SIN CUPÓN a propósito: de Shopee todavía NO tenemos una fuente
                # que confirme qué código aplica a qué producto. Poner uno sería
                # repetir el error de ML ("seu cupom nao se aplica a esta compra").
                "cupom": None,
                "cupom_pct": None,
                "pix": "",
                "ml_tiene_cupon": None,
                "ml_precio_cupon": None,
                "ml_tiene_pix": None,
                "ml_precio_pix": None,
                "imagen": candidato.get("imagen"),
                "url": elegir_link_afiliado(candidato),
                "criado_em": ahora_iso,
                "prioridade": 5,
                "cuotas": candidato.get("cuotas"),
                "cuota_valor": candidato.get("cuota_valor"),
                "cuotas_sin_interes": candidato.get("cuotas_sin_interes"),
                "envio_gratis": bool(candidato.get("envio_gratis"))
            }

        # Rotación 50/50: alternar entre Mercado Livre y Amazon (100% productos con foto)
        elif (step % 2 == 0 and idx_ml < len(cola_ml)) or (idx_amz >= len(cola_amz) and idx_ml < len(cola_ml)):
            # Tomar de ML cuidando repetición de categoría consecutiva
            candidato = cola_ml[idx_ml]
            idx_ml += 1
            item_elegido = {
                "id_post": candidato.get("id") or f"ml-{step}",
                "tipo": "producto",
                "loja": "Mercado Livre",
                "categoria": candidato.get("categoria_canal", "Tech"),
                "titulo": candidato.get("nombre"),
                "precio": candidato.get("precio"),
                "precio_anterior": candidato.get("precio_anterior"),
                "desc_pct": candidato.get("desc_pct"),
                "cupom": candidato.get("cupon") or candidato.get("cupom") or buscar_cupon_para_producto(candidato, cupones),
                "pix": candidato.get("pix") or "",
                # Datos de promocion LEIDOS DE MERCADO LIVRE (no adivinados):
                # si ML no dice que este producto tiene cupon, no se le pone
                # ninguno. Antes se asignaba por categoria y en la compra real
                # no aplicaba ("Seu cupom foi salvo em Cupons, pois nao se
                # aplica a esta compra").
                "ml_tiene_cupon": candidato.get("ml_tiene_cupon"),
                "ml_precio_cupon": candidato.get("ml_precio_cupon"),
                "ml_tiene_pix": candidato.get("ml_tiene_pix"),
                "ml_precio_pix": candidato.get("ml_precio_pix"),
                "imagen": candidato.get("imagen"),
                "url": elegir_link_afiliado(candidato),
                "criado_em": ahora_iso,
                "prioridade": 5,
                "bajada": bool(candidato.get("_bajada")),
                "precio_antes_publicado": candidato.get("_precio_antes"),
                "cuotas": candidato.get("cuotas"),
                "cuota_valor": candidato.get("cuota_valor"),
                "cuotas_sin_interes": candidato.get("cuotas_sin_interes"),
                "envio_gratis": bool(candidato.get("envio_gratis"))
            }
        elif idx_amz < len(cola_amz) or idx_ml >= len(cola_ml):
            if idx_amz < len(cola_amz):
                candidato = cola_amz[idx_amz]
                idx_amz += 1
                item_elegido = {
                    "id_post": candidato.get("id") or f"amz-{step}",
                    "tipo": "producto",
                    "loja": "Amazon",
                    "categoria": candidato.get("categoria_canal", "Tech"),
                    "titulo": candidato.get("nombre"),
                    "precio": candidato.get("precio"),
                    "precio_anterior": candidato.get("precio_anterior"),
                    "desc_pct": candidato.get("desc_pct"),
                    "cupom": candidato.get("cupon") or candidato.get("cupom") or buscar_cupon_para_producto(candidato, cupones),
                    "pix": candidato.get("pix") or "",
                    # Datos de promocion LEIDOS DE MERCADO LIVRE (no adivinados):
                    # si ML no dice que este producto tiene cupon, no se le pone
                    # ninguno. Antes se asignaba por categoria y en la compra real
                    # no aplicaba ("Seu cupom foi salvo em Cupons, pois nao se
                    # aplica a esta compra").
                    "ml_tiene_cupon": candidato.get("ml_tiene_cupon"),
                    "ml_precio_cupon": candidato.get("ml_precio_cupon"),
                    "ml_tiene_pix": candidato.get("ml_tiene_pix"),
                    "ml_precio_pix": candidato.get("ml_precio_pix"),
                    "imagen": candidato.get("imagen"),
                    "url": elegir_link_afiliado(candidato),
                    "criado_em": ahora_iso,
                    "prioridade": 5,
                    "bajada": bool(candidato.get("_bajada")),
                    "precio_antes_publicado": candidato.get("_precio_antes"),
                    "cuotas": candidato.get("cuotas"),
                    "cuota_valor": candidato.get("cuota_valor"),
                    "cuotas_sin_interes": candidato.get("cuotas_sin_interes"),
                    "envio_gratis": bool(candidato.get("envio_gratis"))
                }

        if item_elegido:
            fila_final.append(item_elegido)

    # Si aún no llegamos al objetivo, rellenar con lo que quede
    while len(fila_final) < total_deseado and (idx_ml < len(cola_ml) or idx_amz < len(cola_amz) or idx_shp < len(cola_shp)):
        if idx_ml < len(cola_ml):
            c = cola_ml[idx_ml]
            idx_ml += 1
            loja = "Mercado Livre"
        elif idx_amz < len(cola_amz):
            c = cola_amz[idx_amz]
            idx_amz += 1
            loja = "Amazon"
        else:
            c = cola_shp[idx_shp]
            idx_shp += 1
            loja = "Shopee"

        fila_final.append({
            "id_post": c.get("id") or f"post-{len(fila_final)}",
            "tipo": "producto",
            "loja": loja,
            "categoria": c.get("categoria_canal", "Tech"),
            "titulo": c.get("nombre"),
            "precio": c.get("precio"),
            "precio_anterior": c.get("precio_anterior"),
            "desc_pct": c.get("desc_pct"),
            # En Shopee no se asigna cupón: no hay fuente que confirme qué código
            # aplica a qué producto (misma razón que en la rotación principal).
            "cupom": None if loja == "Shopee" else (c.get("cupon") or c.get("cupom") or buscar_cupon_para_producto(c, cupones)),
            "pix": "" if loja == "Shopee" else (c.get("pix") or ""),
            # Datos de promocion LEIDOS DE MERCADO LIVRE (no adivinados)
            "ml_tiene_cupon": c.get("ml_tiene_cupon"),
            "ml_precio_cupon": c.get("ml_precio_cupon"),
            "ml_tiene_pix": c.get("ml_tiene_pix"),
            "ml_precio_pix": c.get("ml_precio_pix"),
            "imagen": c.get("imagen"),
            "url": elegir_link_afiliado(c),
            "criado_em": ahora_iso,
            "prioridade": 3,
            "bajada": bool(c.get("_bajada")),
            "precio_antes_publicado": c.get("_precio_antes"),
            "cuotas": c.get("cuotas"),
            "cuota_valor": c.get("cuota_valor"),
            "cuotas_sin_interes": c.get("cuotas_sin_interes"),
            "envio_gratis": bool(c.get("envio_gratis"))
        })

    # Enriquecer cada post con el % y el tope del cupón que se le asignó. Es lo
    # que permite al publicador calcular el PRECIO FINAL con los descuentos ya
    # aplicados (cupón + Pix), que es lo que de verdad mueve la conversión.
    cupones_por_codigo = {}
    for c in cupones:
        cod = str(c.get("codigo") or "").strip().upper()
        if cod:
            cupones_por_codigo[cod] = c
    enriquecidos = 0
    for post in fila_final:
        cod = str(post.get("cupom") or "").strip().upper()
        c = cupones_por_codigo.get(cod)
        if not c:
            continue
        pct, tope, valor = _parsear_descuento_cupon(c)
        if pct or tope or valor:
            post["cupom_pct"] = pct
            post["cupom_max"] = tope
            post["cupom_valor"] = valor
            enriquecidos += 1

        # ── CONFIANZA DEL CUPÓN ──────────────────────────────────────────────
        # 'alta'  = el cupón declara categoría y el producto es de esa categoría
        #           -> se puede prometer el precio final.
        # 'baja'  = cupón general/sin categoría: ML decide qué "produtos são
        #           elegíveis" y nosotros NO podemos saberlo. Se menciona, pero
        #           no se promete un descuento que puede no aplicar.
        # Es la diferencia entre informar y engañar al grupo.
        cat_cupon = _categoria_cupon(c)
        if cat_cupon:
            permitidas = CATEGORIAS_DE_CUPON.get(cat_cupon, [])
            cat_post = post.get("categoria", "")
            if permitidas and cat_post not in permitidas:
                # No debería pasar (ya se filtró al elegir), pero por si acaso:
                post["cupom"] = None
                post["cupom_pct"] = None
                post["cupom_confianza"] = None
                continue
            post["cupom_confianza"] = "alta"
        else:
            post["cupom_confianza"] = "baja"

    # ══════════════════════════════════════════════════════════════════════════
    #  EL CUPÓN SOLO SI MERCADO LIVRE CONFIRMA QUE ESTE PRODUCTO TIENE CUPÓN
    # ══════════════════════════════════════════════════════════════════════════
    # EL BUG QUE REPORTÓ EL USUARIO: se publicaba BARRATINHOJA en un Kit de
    # Potes y Mercado Livre respondía al aplicarlo:
    #     "Seu cupom foi salvo em 'Cupons', pois não se aplica a esta compra."
    #
    # CAUSA: los cupones de afiliado (los del canal de Telegram) son cupones
    # GENERALES de Mercado Livre, válidos para "produtos elegíveis" que solo ML
    # conoce. Se asignaban por categoría, así que acababan en productos donde no
    # aplican. Medido: solo el 3,8% de los productos tiene cupón de verdad, pero
    # el bot lo ponía en el 100% de los posts.
    #
    # SOLUCIÓN: Mercado Livre publica en su propia página de ofertas qué
    # productos tienen cupón y a qué precio queda con él:
    #     "promotions":[{"type":"coupon","values":[{"price":{"value":4960}}]}]
    # El scraper lo lee (ml_tiene_cupon / ml_precio_cupon). Si ML no lo dice,
    # NO se pone cupón. Se acabó adivinar.
    #
    # Nota: el código del cupón de ML no viene en ese dato (es un cupón de
    # vendedor que se activa en la página, sin código), así que en el post se
    # muestra el PRECIO con cupón y se indica que se active en la página.
    sin_cupon_confirmado = 0
    con_cupon_confirmado = 0
    for post in fila_final:
        if "Mercado" not in str(post.get("loja") or ""):
            continue
        if not post.get("ml_tiene_cupon"):
            if post.get("cupom"):
                sin_cupon_confirmado += 1
            post["cupom"] = None
            post["cupom_pct"] = None
            post["cupom_max"] = None
            post["cupom_valor"] = None
            post["cupom_confianza"] = None
        else:
            con_cupon_confirmado += 1
            post["cupom_precio_ml"] = post.get("ml_precio_cupon")

    print(f"  • Cupones RETIRADOS por no estar confirmados por ML: {sin_cupon_confirmado}")
    print(f"  • Productos con cupón CONFIRMADO por ML: {con_cupon_confirmado}")

    # ── PRIORIDAD A LOS PRODUCTOS CON CUPÓN ─────────────────────────────────
    # Solo ~4% de los productos tiene cupón de verdad, así que en una fila de
    # 350 quedarían enterrados entre los que no tienen. Se suben al principio
    # para que el bucle los publique primero: así el canal SÍ tiene posts con
    # cupón, y con cupones que aplican de verdad (el precio lo da ML).
    #
    # No se inventa ninguno: simplemente se ordena para que salgan antes los
    # que sí lo tienen.
    # ── MENOR PRECIO EN 30 DÍAS (con datos, no con marketing) ────────────────
    # Ahora que unir_achados.py guarda el histórico de toda la cosecha, se puede
    # marcar "MENOR PRECIO EN 30 DIAS" SOLO cuando es verdad. Se exigen 2+
    # registros del mismo producto; si no, no se marca nada.
    minimos_30d = _minimos_30d()
    marcados_menor = 0
    if minimos_30d:
        for post in fila_final:
            pid = str(post.get("id_post") or "")
            pmin = minimos_30d.get(pid)
            if not pmin:
                continue
            try:
                precio_post = float(post.get("precio") or 0)
            except (TypeError, ValueError):
                continue
            if precio_post > 0 and precio_post <= pmin:
                post["menor_precio_30d"] = True
                post["menor_precio_30d_ref"] = pmin
                marcados_menor += 1
    print(f"  • Marcados como MENOR PRECIO EN 30 DIAS: {marcados_menor} "
          f"(histórico con {len(minimos_30d)} productos comparables)")

    con_cupon = [p for p in fila_final if p.get("ml_tiene_cupon")
                 and p.get("ml_precio_cupon")]
    sin_cupon = [p for p in fila_final if p not in con_cupon]

    # ── TANDAS DE CUPÓN AL FRENTE DE LA FILA (2026-10-07) ────────────────────
    # EL BUG: generar_posts_cupones() construía las tandas y NADIE las usaba
    # (solo se contaban para calcular el tamaño de la fila). Encima el
    # publicador saltaba el tipo 'cupons_loja'. Dos puertas cerradas: el canal
    # nunca publicó una tanda de cupones. Ahora entran de verdad y van primero.
    max_lotes = int(os.environ.get("MAX_LOTES_CUPON_FILA", "2"))
    lotes = posts_cupones[:max_lotes] if max_lotes > 0 else []
    fila_final = lotes + con_cupon + sin_cupon
    print(f"  • Tandas de cupón al frente de la fila: {len(lotes)} "
          f"(MAX_LOTES_CUPON_FILA={max_lotes})")
    print(f"  • Con cupón al principio de la fila: {len(con_cupon)}")

    altos = sum(1 for p in fila_final if p.get("cupom_confianza") == "alta")
    bajos = sum(1 for p in fila_final if p.get("cupom_confianza") == "baja")
    print(f"  • Cupones con categoría verificada (confianza alta): {altos}")
    print(f"  • Cupones generales (confianza baja, sin prometer precio): {bajos}")

    # Guardar en fila_posts.json
    resultado = {
        "actualizado": ahora_iso,
        "total_posts": len(fila_final),
        "fila": fila_final
    }

    FILA_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] fila_posts.json generada con {len(fila_final)} posts.")
    categorias_dist = set(x.get("categoria") for x in fila_final)
    print(f"  • Categorías diferentes en la fila: {len(categorias_dist)}")
    print(f"  • Posts tipo cupón/especial: {sum(1 for x in fila_final if x.get('tipo') == 'cupon')}")
    ml_n = sum(1 for x in fila_final if "Mercado" in (x.get("loja") or ""))
    amz_n = sum(1 for x in fila_final if "Amazon" in (x.get("loja") or ""))
    shp_n = sum(1 for x in fila_final if "Shopee" in (x.get("loja") or ""))
    print(f"  • Reparto: {ml_n} Mercado Livre | {amz_n} Amazon | {shp_n} Shopee")
    print(f"  • Con cupón: {sum(1 for x in fila_final if x.get('cupom'))}")
    if reingresos:
        print(f"  • READMITIDOS por bajada de precio: {len(reingresos)}")
        for tit, motivo in reingresos[:8]:
            print(f"       {tit}  ->  {motivo}")
    print("=" * 60)
    return len(fila_final)

if __name__ == "__main__":
    armar_fila_rotativa()
