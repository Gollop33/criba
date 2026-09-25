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


def buscar_cupon_para_producto(item, cupones):
    """Cruza un producto con cupones vigentes por tienda y compra mínima."""
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
    """Carga cupones reales y vigentes de cupones.json."""
    if not CUPONES_JSON.exists():
        return []
    try:
        data = json.loads(CUPONES_JSON.read_text(encoding="utf-8"))
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
            hasta = c.get("hasta", "9999-12-31")
            if hasta >= hoy:
                validos.append(c)
        return validos
    except Exception:
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

    link_ativacao_ml = f"https://www.mercadolivre.com.br/cupons#D[A:{ML_ID}]"
    for chunk_idx in range(0, min(16, len(cupons_ml)), 4):
        grupo = cupons_ml[chunk_idx:chunk_idx+4]
        if not grupo:
            continue
        lineas = [f"🔥 Cupons Mercado Livre Selecionados #{chunk_idx//4 + 1}\n"]
        for c in grupo:
            cod = c.get("codigo") or "NO CARRINHO"
            desc = c.get("desconto") or f"R$ {c.get('valor', 15)} OFF"
            titulo = c.get("titulo", "Desconto ativo")[:45]
            vence = c.get("hasta") or c.get("vencimento")
            urgencia = " ⏰ Vence HOJE!" if vence == hoy_str else ""
            lineas.append(f"🎟️ {desc}: {cod} ({titulo}){urgencia}")
        lineas.append(f"\n⭐️ Ative por aqui para aplicar no carrinho:\n👉 {link_ativacao_ml}")
        
        posts_cupones.append({
            "id_post": f"cupom-ml-lote{chunk_idx//4 + 1}-{datetime.now().strftime('%Y%m%d%H')}",
            "tipo": "cupons_loja",
            "loja": "Mercado Livre",
            "categoria": "Cupons",
            "titulo": f"🔥 Cupons Mercado Livre #{chunk_idx//4 + 1}",
            "mensagem": "\n".join(lineas),
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
            desc = c.get("desconto") or f"{c.get('valor', 10)}% OFF"
            titulo = c.get("titulo", "Promoção especial")[:45]
            lineas.append(f"🎟️ {desc}: {cod} ({titulo})")
        lineas.append(f"\n⭐️ Resgate e ative seus cupons Amazon:\n👉 {link_ativacao_amz}")
        
        posts_cupones.append({
            "id_post": f"cupom-amz-lote{chunk_idx//4 + 1}-{datetime.now().strftime('%Y%m%d%H')}",
            "tipo": "cupons_loja",
            "loja": "Amazon",
            "categoria": "Cupons",
            "titulo": f"🔥 Cupons & Promoções Amazon #{chunk_idx//4 + 1}",
            "mensagem": "\n".join(lineas),
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

    # Unificar y filtrar por 48h (ofertas específicas tienen prioridad absoluta)
    todos_candidatos = []
    vistos_slug = set()
    reingresos = []   # productos readmitidos porque BAJARON de precio

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
        else:
            continue

        # FILTRO DE NICHO: según NICHO_MODO ('tech' cerrado o 'geral' achadinhos)
        nombre_prod = item.get("nombre", "")
        if not es_producto_del_canal(nombre_prod):
            continue

        cat = clasificar_categoria(nombre_prod)
        item["categoria_canal"] = cat
        todos_candidatos.append(item)

    # Dividir candidatos por tienda
    cola_ml = [x for x in todos_candidatos if "Mercado Livre" in x.get("loja", "")]
    cola_amz = [x for x in todos_candidatos if "Amazon" in x.get("loja", "")]

    # Shuffle suave para evitar que el mismo top de descuento esté siempre adelante
    random.seed(int(datetime.now().strftime("%Y%m%d%H")))
    random.shuffle(cola_ml)
    random.shuffle(cola_amz)

    # Crear posts de cupones
    posts_cupones = generar_posts_cupones(cupones)

    fila_final = []
    
    # 0. PRIORIDAD ABSOLUTA: Ofertas curadas con IA / específicas ingresadas por el usuario
    for esp in items_esp:
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
                "pix": "mais 5% OFF" if "Mercado" in esp.get("loja", "") else "à vista",
                "imagen": esp.get("imagen"),
                "url": elegir_link_afiliado(esp),
                "criado_em": ahora_iso,
                "prioridade": 10,
                "destaque": esp.get("analise_ia", {}).get("destaque", "🔥 Oportunidade Selecionada")
            })

    idx_ml = 0
    idx_amz = 0
    idx_cupom = 0
    ultima_cat = None
    repeticiones_cat = 0

    # Armar hasta 100 posts alternando: ML, Amazon, Cupon, ML, Amazon, etc.
    total_deseado = min(120, max(80, len(todos_candidatos) + len(posts_cupones)))

    for step in range(total_deseado):
        item_elegido = None

        # Rotación 50/50: alternar entre Mercado Livre y Amazon (100% productos con foto)
        if (step % 2 == 0 and idx_ml < len(cola_ml)) or (idx_amz >= len(cola_amz) and idx_ml < len(cola_ml)):
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
                "pix": "mais 5% OFF",
                "imagen": candidato.get("imagen"),
                "url": elegir_link_afiliado(candidato),
                "criado_em": ahora_iso,
                "prioridade": 5,
                "bajada": bool(candidato.get("_bajada")),
                "precio_antes_publicado": candidato.get("_precio_antes")
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
                    "pix": "mais 5% OFF",
                    "imagen": candidato.get("imagen"),
                    "url": elegir_link_afiliado(candidato),
                    "criado_em": ahora_iso,
                    "prioridade": 5,
                    "bajada": bool(candidato.get("_bajada")),
                    "precio_antes_publicado": candidato.get("_precio_antes")
                }

        if item_elegido:
            fila_final.append(item_elegido)

    # Si aún no llegamos a 80, rellenar con lo que quede
    while len(fila_final) < 80 and (idx_ml < len(cola_ml) or idx_amz < len(cola_amz)):
        if idx_ml < len(cola_ml):
            c = cola_ml[idx_ml]
            idx_ml += 1
            loja = "Mercado Livre"
        else:
            c = cola_amz[idx_amz]
            idx_amz += 1
            loja = "Amazon"

        fila_final.append({
            "id_post": c.get("id") or f"post-{len(fila_final)}",
            "tipo": "producto",
            "loja": loja,
            "categoria": c.get("categoria_canal", "Tech"),
            "titulo": c.get("nombre"),
            "precio": c.get("precio"),
            "precio_anterior": c.get("precio_anterior"),
            "desc_pct": c.get("desc_pct"),
            "cupom": c.get("cupon") or c.get("cupom") or buscar_cupon_para_producto(c, cupones),
            "pix": "mais 5% OFF",
            "imagen": c.get("imagen"),
            "url": elegir_link_afiliado(c),
            "criado_em": ahora_iso,
            "prioridade": 3
        })

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
    print(f"  • Posts tipo cupón/especial: {sum(1 for x in fila_final if x.get('tipo') == 'cupons_loja')}")
    ml_n = sum(1 for x in fila_final if "Mercado" in (x.get("loja") or ""))
    amz_n = sum(1 for x in fila_final if "Amazon" in (x.get("loja") or ""))
    print(f"  • Reparto: {ml_n} Mercado Livre | {amz_n} Amazon")
    print(f"  • Con cupón: {sum(1 for x in fila_final if x.get('cupom'))}")
    if reingresos:
        print(f"  • READMITIDOS por bajada de precio: {len(reingresos)}")
        for tit, motivo in reingresos[:8]:
            print(f"       {tit}  ->  {motivo}")
    print("=" * 60)
    return len(fila_final)

if __name__ == "__main__":
    armar_fila_rotativa()
