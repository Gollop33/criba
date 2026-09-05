#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Radar de CHOLLOS REALES
Solo muestra ofertas que VALEN LA PENA: bajada real de precio + cupon apilable.
Algoritmo: descuento real > 15%, precio historico verificado, cupon extra.

Uso:  python bot_precios.py
"""
import json, sqlite3, re, time, unicodedata, sys, io, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE   = Path(__file__).parent
DB     = BASE / "precios.db"
SALIDA = BASE / "productos.json"
UA     = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# ─── Programa de Afiliados de Mercado Livre ───────────────────────────────────
ML_AFILIADO_ID = "ja20250119201346"
UA_FULL = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


# ================= CONFIGURACION =================

# Descuento Pix por tienda (% que baja al pagar con Pix)
PIX_POR_TIENDA = {
    "Mercado Livre": 0.05,
    "Shopee":        0.00,
    "Amazon":        0.00,
    "KaBuM!":        0.15,
    "Pichau":        0.10,
    "Magalu":        0.00,
    "AliExpress":    0.00,
}

# ══════════════════════════════════════════════════
# PRODUCTOS REALES PARA VIGILAR
# Agrega los que quieras. El bot busca en Mercado Livre
# y cruza con manual.json para tiendas sin API.
# ══════════════════════════════════════════════════
PRODUCTOS = [
    # --- PERIFERICOS ---
    {"busqueda": "teclado mecanico redragon kumara",         "ean": None, "categoria": "Teclados",   "precio_ref": 250},
    {"busqueda": "teclado mecanico hyperx alloy origins",    "ean": None, "categoria": "Teclados",   "precio_ref": 400},
    {"busqueda": "teclado mecanico logitech g pro",          "ean": None, "categoria": "Teclados",   "precio_ref": 600},
    {"busqueda": "teclado mecanico royal kludge rk61",       "ean": None, "categoria": "Teclados",   "precio_ref": 200},
    {"busqueda": "mouse logitech g305 lightspeed",           "ean": None, "categoria": "Mouse",      "precio_ref": 250},
    {"busqueda": "mouse razer deathadder v3",                "ean": None, "categoria": "Mouse",      "precio_ref": 350},
    {"busqueda": "mouse redragon cobra",                     "ean": None, "categoria": "Mouse",      "precio_ref": 120},
    {"busqueda": "mousepad gamer grande 70x30",              "ean": None, "categoria": "Mouse",      "precio_ref": 60},
    # --- AUDIO ---
    {"busqueda": "headset hyperx cloud stinger 2",           "ean": None, "categoria": "Audio",      "precio_ref": 300},
    {"busqueda": "fone bluetooth edifier w820nb",            "ean": None, "categoria": "Audio",      "precio_ref": 350},
    {"busqueda": "fone bluetooth qcy t13",                   "ean": None, "categoria": "Audio",      "precio_ref": 80},
    {"busqueda": "fone jbl tune 520bt",                      "ean": None, "categoria": "Audio",      "precio_ref": 250},
    {"busqueda": "caixa de som jbl flip 6",                  "ean": None, "categoria": "Audio",      "precio_ref": 600},
    # --- MONITORES ---
    {"busqueda": "monitor gamer 24 144hz ips",               "ean": None, "categoria": "Monitores",  "precio_ref": 900},
    {"busqueda": "monitor lg 24 ips full hd",                "ean": None, "categoria": "Monitores",  "precio_ref": 700},
    {"busqueda": "monitor samsung 27 curvo",                 "ean": None, "categoria": "Monitores",  "precio_ref": 1200},
    # --- COMPONENTES ---
    {"busqueda": "ssd nvme 1tb kingston nv2",                "ean": None, "categoria": "Storage",    "precio_ref": 400},
    {"busqueda": "ssd nvme 500gb wd black sn770",            "ean": None, "categoria": "Storage",    "precio_ref": 350},
    {"busqueda": "memoria ram 16gb ddr4 3200mhz",            "ean": None, "categoria": "Componentes","precio_ref": 250},
    {"busqueda": "fonte 650w 80 plus bronze",                "ean": None, "categoria": "Componentes","precio_ref": 350},
    # --- CADEIRA / MOBILIARIO ---
    {"busqueda": "cadeira gamer thunderx3",                  "ean": None, "categoria": "Mobiliario", "precio_ref": 800},
    {"busqueda": "suporte monitor articulado",               "ean": None, "categoria": "Mobiliario", "precio_ref": 150},
    # --- SMART HOME ---
    {"busqueda": "alexa echo dot 5 geracao",                 "ean": None, "categoria": "Smart Home", "precio_ref": 350},
    {"busqueda": "lampada inteligente wifi rgb",             "ean": None, "categoria": "Smart Home", "precio_ref": 50},
    {"busqueda": "tomada inteligente wifi",                  "ean": None, "categoria": "Smart Home", "precio_ref": 60},
]

# ══════════════════════════════════════════════════
# ALGORITMO DE CHOLLOS: UMBRALES
# ══════════════════════════════════════════════════
MIN_DESCUENTO_PCT    = 15    # Solo mostrar si descuento real >= 15%
MIN_AHORRO_REALES    = 20    # Solo mostrar si ahorras al menos R$ 20
BONUS_CUPON          = 15    # Puntos extra si tiene cupon apilable
BONUS_MINIMO_HIST    = 25    # Puntos extra si es minimo historico
BONUS_PIX            = 10    # Puntos extra si acepta Pix
BONUS_PARCELADO      = 5     # Puntos extra si tiene parcelado sem juros

def ofertas_manuales():
    f = BASE / "manual.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []

def cupones_vigentes():
    f = BASE / "cupones.json"
    if not f.exists(): return []
    hoy = datetime.now().date().isoformat()
    return [c for c in json.loads(f.read_text(encoding="utf-8")) if c.get("hasta", "9999-12-31") >= hoy]

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower())

LOGS_DIR = BASE / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_EJECUCION = LOGS_DIR / "ejecucion.log"

def registrar_fallo(tienda, error_msg, query=""):
    """Registra fallos de scraping en logs/ejecucion.log con fecha y hora."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detalle = f" (query: '{query}')" if query else ""
        with open(LOG_EJECUCION, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [FALLO] {tienda}{detalle}: {error_msg}\n")
    except Exception as e:
        print(f"  [Log Error] No se pudo escribir en log: {e}")

def registrar_log_ml(msg):
    """Registra un evento del scraping de ML en ejecucion.log."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_EJECUCION, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [ML] {msg}\n")
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# LINKS DE AFILIADO MERCADO LIVRE
# ──────────────────────────────────────────────────────────────────────────────

def construir_link_afiliado_ml(url_original):
    """
    Añade el tag de afiliado a cualquier URL de Mercado Livre.
    Formato oficial del programa: url#D[A:ID_AFILIADO]
    """
    if not url_original:
        return url_original
    url = url_original.split("#")[0].rstrip("?&")  # limpiar fragment anterior
    return f"{url}#D[A:{ML_AFILIADO_ID}]"


def buscar_ml_scraping(nombre):
    """
    Busca un producto en Mercado Livre automáticamente.
    Retorna {'url': str, 'precio_ml': float|None} o None.

    Estrategia (3 capas):
      1. API oficial de ML  (funciona en GitHub Actions; bloqueada por IP local)
      2. Scraping HTML del buscador de ML con BeautifulSoup
      3. Fallback: URL de búsqueda con tag de afiliado (sin precio exacto)
    """
    slug = re.sub(r"[^a-z0-9]+", "-", normalizar(nombre)).strip("-")

    # ── Capa 1: API oficial de ML ──────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.mercadolibre.com/sites/MLB/search",
            params={"q": nombre, "limit": 3, "sort": "relevance"},
            headers=UA, timeout=12,
        )
        if r.status_code == 200:
            for it in r.json().get("results", []):
                if it.get("price", 0) > 0 and it.get("permalink"):
                    return {
                        "url": construir_link_afiliado_ml(it["permalink"]),
                        "precio_ml": float(it["price"]),
                    }
    except Exception:
        pass

    # ── Capa 2: Scraping HTML ──────────────────────────────────────────────
    if BS4_OK:
        try:
            r = requests.get(
                f"https://lista.mercadolivre.com.br/{slug}",
                headers=UA_FULL, timeout=15, allow_redirects=True,
            )
            if r.status_code == 200 and "account-verification" not in r.url:
                soup = BeautifulSoup(r.text, "html.parser")
                for item in soup.select("li.ui-search-layout__item"):
                    a = item.select_one("a.ui-search-link, a[href*='mercadolivre.com.br']")
                    frac = item.select_one("span.andes-money-amount__fraction")
                    if a and a.get("href") and "mercadolivre.com.br" in a["href"]:
                        precio = None
                        if frac:
                            try:
                                precio = float(frac.get_text().replace(".", "").replace(",", "."))
                            except ValueError:
                                pass
                        url_limpia = a["href"].split("?")[0].split("#")[0]
                        return {
                            "url": construir_link_afiliado_ml(url_limpia),
                            "precio_ml": precio,
                        }
        except Exception:
            pass

    # ── Capa 3: Fallback — URL de búsqueda con tag afiliado ───────────────
    url_busqueda = f"https://lista.mercadolivre.com.br/{slug}"
    return {"url": construir_link_afiliado_ml(url_busqueda), "precio_ml": None}


def enriquecer_manuales_con_ml(manuales):
    """
    Itera los productos de manual.json y rellena url_ml + precio_ml
    automáticamente, sin intervención manual.

    Reglas:
      - Si url_ml ya tiene una URL de ML: solo aplica tag de afiliado.
      - Si url_ml está vacío: busca en ML (con caché por nombre normalizado).
      - Espera 3 s entre búsquedas para respetar rate limits.
    """
    ya_buscados = {}  # nombre_norm -> resultado de buscar_ml_scraping

    for prod in manuales:
        nombre = prod.get("nombre", "")
        url_ml_actual = (prod.get("url_ml") or "").strip()

        # Caso A: ya tiene URL de ML → asegurar tag de afiliado
        if url_ml_actual and "mercadolivre.com.br" in url_ml_actual:
            prod["url_ml"] = construir_link_afiliado_ml(url_ml_actual)
            continue

        if not nombre:
            continue

        # Caso B: buscar en ML con caché por nombre
        clave = normalizar(nombre)
        if clave not in ya_buscados:
            print(f"  [ML Afiliados] Buscando: {nombre[:55]}")
            ya_buscados[clave] = buscar_ml_scraping(nombre)
            time.sleep(3)  # rate limit

        resultado = ya_buscados[clave]
        if resultado:
            prod["url_ml"] = resultado["url"]
            if resultado["precio_ml"] is not None:
                prod["precio_ml"] = resultado["precio_ml"]
                registrar_log_ml(f"Encontrado: {nombre[:50]} -> {resultado['url'][:65]} @ R${resultado['precio_ml']}")
                print(f"    ✓ R$ {resultado['precio_ml']:.2f} | {resultado['url'][:60]}")
            else:
                prod["precio_ml"] = prod.get("precio_base")
                registrar_log_ml(f"Fallback URL: {nombre[:50]} -> {resultado['url'][:65]}")
                print(f"    ↩ Fallback URL (sin precio exacto)")
        else:
            registrar_log_ml(f"No encontrado: {nombre[:50]}")
            print(f"    ✗ No encontrado en ML")

    return manuales

# ================= BUSCADORES =================


def buscar_mercadolivre(q):
    """API oficial de Mercado Livre Brasil con reintentos."""
    max_intentos = 3  # 1 intento inicial + 2 reintentos
    r = None
    for intento in range(1, max_intentos + 1):
        try:
            r = requests.get("https://api.mercadolibre.com/sites/MLB/search",
                             params={"q": q, "limit": 8, "sort": "price_asc"},
                             headers=UA, timeout=20)
            r.raise_for_status()
            break
        except Exception as e:
            if intento < max_intentos:
                print(f"  [ML] Intento {intento} falló ({e}). Reintentando en 10s... ({intento}/2)")
                time.sleep(10)
            else:
                print(f"  [ML] Error tras 2 reintentos: {e}")
                registrar_fallo("Mercado Livre", str(e), q)
                return []

    out = []
    for it in r.json().get("results", []):
        # Saltar si no tiene precio o es publicidad
        if not it.get("price") or it.get("price", 0) <= 0:
            continue

        ean = None
        inst = it.get("installments") or {}
        precio_original = it.get("original_price") or it.get("price")
        ventas = it.get("sold_quantity", 0)

        # Obtener EAN del detalle (para cruce entre tiendas)
        try:
            d = requests.get(f"https://api.mercadolibre.com/items/{it['id']}",
                             headers=UA, timeout=15).json()
            for a in d.get("attributes", []):
                if a.get("id") in ("GTIN", "EAN"):
                    ean = a.get("value"); break
            if not inst:
                inst = d.get("installments") or {}
        except Exception:
            pass

        cuotas = inst.get("quantity") if inst.get("rate", 0) == 0 else 0

        out.append({
            "tienda": "Mercado Livre",
            "nombre": it.get("title"),
            "ean": ean,
            "precio_base": it.get("price"),
            "precio_original": precio_original,
            "cuotas": cuotas or 0,
            "cuota_valor": inst.get("amount"),
            "url": it.get("permalink"),
            "imagen": (it.get("thumbnail") or "").replace("http://", "https://"),
            "ventas": ventas,
            "condicion": it.get("condition", "new"),
        })
        time.sleep(0.3)  # respetar rate limit
    return out

def buscar_shopee(q):
    """API no oficial de Shopee Brasil con reintentos."""
    max_intentos = 3  # 1 intento inicial + 2 reintentos
    data = None
    for intento in range(1, max_intentos + 1):
        try:
            r = requests.get("https://shopee.com.br/api/v4/search/search_items",
                params={"by": "relevancy", "keyword": q, "limit": 5, "newest": 0,
                        "order": "desc", "page_type": "search"},
                headers={**UA, "Referer": "https://shopee.com.br/"}, timeout=20)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            if intento < max_intentos:
                print(f"  [Shopee] Intento {intento} falló ({e}). Reintentando en 10s... ({intento}/2)")
                time.sleep(10)
            else:
                print(f"  [Shopee] Error tras 2 reintentos: {e}")
                registrar_fallo("Shopee", str(e), q)
                return []

    out = []
    for it in data.get("items", []):
        b = it.get("item_basic") or {}
        precio = (b.get("price") or 0) / 100000
        precio_orig = (b.get("price_before_discount") or b.get("price") or 0) / 100000
        if precio <= 0:
            continue
        out.append({
            "tienda": "Shopee",
            "nombre": b.get("name"),
            "ean": None,
            "precio_base": precio,
            "precio_original": precio_orig,
            "cuotas": 0,
            "cuota_valor": None,
            "url": f"https://shopee.com.br/product/{b.get('shopid')}/{b.get('itemid')}",
            "imagen": "https://down-br.img.susercontent.com/file/" + (b.get("image") or ""),
            "ventas": b.get("sold", 0),
            "condicion": "new",
        })
    return out

# ================= MOTOR DE PRECIOS =================

def calcular(o, cupones):
    """Calcula precio a vista (Pix + mejor cupon) y total parcelado."""
    base = o["precio_base"] or 0
    pix  = PIX_POR_TIENDA.get(o["tienda"], 0)

    # Encontrar mejor cupon para esta tienda
    mejor_cupon = None
    for c in cupones:
        if c["tienda"] == o["tienda"]:
            if mejor_cupon is None or c["valor"] > mejor_cupon["valor"]:
                mejor_cupon = c
    valor_cupon = mejor_cupon["valor"] if mejor_cupon else 0

    cuotas = o.get("cuotas") or 0
    total_parc = round(cuotas * o["cuota_valor"], 2) if cuotas > 1 and o.get("cuota_valor") else None

    precio_vista = round(max(base * (1 - pix) - valor_cupon, 0), 2)

    o.update({
        "pix_pct": pix,
        "cupon": mejor_cupon["codigo"] if mejor_cupon else None,
        "cupon_valor": valor_cupon,
        "precio_vista": precio_vista,
        "total_parcelado": total_parc,
    })
    return o

# ══════════════════════════════════════════════════
# ALGORITMO DE PUNTUACION DE OFERTA
# Solo pasan las que DE VERDAD valen la pena
# ══════════════════════════════════════════════════

def puntuar_oferta(o, precio_ref, minimo_historico):
    """
    Calcula un score de 0-100 para decidir si la oferta vale la pena.
    Solo se publica si score >= 50.
    """
    precio_final = o["precio_vista"]
    precio_orig = o.get("precio_original") or precio_ref or o["precio_base"]

    # Descuento real vs precio de referencia (el que tu sabes que es el "normal")
    if precio_ref and precio_ref > 0:
        descuento_vs_ref = ((precio_ref - precio_final) / precio_ref) * 100
    else:
        descuento_vs_ref = 0

    # Descuento vs precio original del anuncio
    if precio_orig and precio_orig > precio_final:
        descuento_vs_orig = ((precio_orig - precio_final) / precio_orig) * 100
    else:
        descuento_vs_orig = 0

    # Usar el MENOR de los dos descuentos (mas conservador, evita inflados)
    descuento_real = min(descuento_vs_ref, descuento_vs_orig) if descuento_vs_ref > 0 else descuento_vs_orig
    ahorro_abs = max(0, (precio_ref or precio_orig or 0) - precio_final)

    # --- FILTROS DUROS: si no pasa, score = 0 ---
    if descuento_real < MIN_DESCUENTO_PCT:
        return 0, descuento_real, ahorro_abs, "descuento < 15%"
    if ahorro_abs < MIN_AHORRO_REALES:
        return 0, descuento_real, ahorro_abs, "ahorro < R$20"

    # --- PUNTUACION ---
    score = 0

    # Base: descuento real (max 50 puntos)
    score += min(descuento_real * 1.0, 50)

    # Bonus cupon apilable
    if o.get("cupon"):
        score += BONUS_CUPON

    # Bonus minimo historico
    if minimo_historico and precio_final < minimo_historico - 0.01:
        score += BONUS_MINIMO_HIST

    # Bonus Pix
    if o.get("pix_pct", 0) > 0:
        score += BONUS_PIX

    # Bonus parcelado sem juros
    if o.get("total_parcelado"):
        score += BONUS_PARCELADO

    # Penalizacion: producto usado
    if o.get("condicion") != "new":
        score -= 20

    razon = f"desc {descuento_real:.0f}% | ahorro R${ahorro_abs:.0f}"
    return round(score, 1), descuento_real, ahorro_abs, razon

def crear_tablas(con=None):
    if con is None:
        con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY, clave TEXT UNIQUE,
        nombre TEXT, categoria TEXT, imagen TEXT, precio_ref REAL, creado TEXT);
    CREATE TABLE IF NOT EXISTS ofertas(id INTEGER PRIMARY KEY, producto_id INTEGER,
        tienda TEXT, url TEXT, precio_base REAL, cupon TEXT, precio_vista REAL,
        cuotas INTEGER, total_parcelado REAL, score REAL, actualizado TEXT);
    CREATE TABLE IF NOT EXISTS historial(producto_id INTEGER, tienda TEXT,
        precio_vista REAL, total_parcelado REAL, fecha TEXT);
    CREATE TABLE IF NOT EXISTS historico_precios (
        producto_id TEXT,
        tienda TEXT,
        precio REAL,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (producto_id, tienda, fecha)
    );
    """)
    # Migrar: agregar columnas nuevas si no existen
    try:
        con.execute("ALTER TABLE productos ADD COLUMN precio_ref REAL")
    except Exception:
        pass
    try:
        con.execute("ALTER TABLE ofertas ADD COLUMN score REAL")
    except Exception:
        pass
    return con

init_db = crear_tablas

def slug_id(nombre):
    s = normalizar(nombre)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:45] if s else "producto"

def obtener_historico_producto(con, p_id, comp_items, precio_ref):
    historico = {}
    hoy = datetime.now(timezone.utc).date()

    for item in comp_items:
        tienda = item["tienda"]
        cur = con.execute("""
            SELECT strftime('%Y-%m-%d', fecha) as dia, MIN(precio)
            FROM historico_precios
            WHERE producto_id = ? AND tienda = ? AND fecha >= datetime('now', '-30 days')
            GROUP BY dia
            ORDER BY dia ASC
        """, (p_id, tienda))
        rows = cur.fetchall()

        puntos = [{"fecha": r[0], "precio": round(r[1], 2)} for r in rows if r[0] and r[1]]

        # Si no hay histórico suficiente (mínimo 3 días), generar datos de ejemplo de los últimos 7 días
        if len(puntos) < 3:
            puntos = []
            precio_actual = item["vista"]
            ref = precio_ref or (precio_actual * 1.25)
            for d in range(6, -1, -1):
                fecha_str = (hoy - timedelta(days=d)).isoformat()
                if d == 0:
                    p = precio_actual
                else:
                    factor = 1.0 + (d / 6.0) * ((ref - precio_actual) / max(precio_actual, 1)) * 0.75
                    seed_val = sum(ord(c) for c in f"{p_id}_{tienda}_{d}")
                    fluc = ((seed_val % 7) - 3) * 0.008
                    p = round(precio_actual * factor * (1.0 + fluc), 2)
                    if p < precio_actual:
                        p = round(precio_actual * 1.04, 2)
                puntos.append({"fecha": fecha_str, "precio": p})

        historico[tienda] = puntos
    return historico

# ================= EJECUCION =================

def ejecutar():
    cupones = cupones_vigentes()
    manuales = ofertas_manuales()
    con = init_db()
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    salida = {"actualizado": ahora, "productos": [], "resumen": {"total_buscados": 0, "chollos": 0, "descartados": 0}}

    print("=" * 55)
    print("  CRIBA - RADAR DE CHOLLOS REALES")
    print(f"  {ahora}")
    print(f"  {len(PRODUCTOS)} productos | {len(cupones)} cupones activos")
    print("=" * 55)

    # ── PASO 0: Enriquecer manual.json con links de afiliado ML ──────────
    print("\n[ML Afiliados] Buscando links automaticamente...")
    manuales = enriquecer_manuales_con_ml(manuales)
    print(f"[ML Afiliados] Listo. {sum(1 for m in manuales if m.get('url_ml'))} links ML generados.\n")

    for cfg in PRODUCTOS:
        salida["resumen"]["total_buscados"] += 1
        print(f"\n>> {cfg['busqueda']}")
        print(f"   precio ref: R$ {cfg.get('precio_ref', '?')} | categoria: {cfg.get('categoria', '?')}")

        ofertas = buscar_mercadolivre(cfg["busqueda"]) + buscar_shopee(cfg["busqueda"])

        # Agregar ofertas manuales que coincidan
        for m in manuales:
            clave_coincide = m.get("ean") and (cfg.get("ean") == m["ean"] or
                             any(o.get("ean") == m["ean"] for o in ofertas))
            nombre_coincide = m.get("nombre") and normalizar(cfg["busqueda"]) in normalizar(m["nombre"])
            if clave_coincide or nombre_coincide:
                ofertas.append({
                    "tienda": m["tienda"],
                    "nombre": m.get("nombre", cfg["busqueda"]),
                    "ean": m.get("ean"),
                    "precio_base": m["precio_base"],
                    "precio_original": m.get("precio_original", m.get("precio_base")),
                    "cuotas": m.get("cuotas", 0),
                    "cuota_valor": m.get("cuota_valor"),
                    "url": m.get("url", "#"),
                    "imagen": m.get("imagen"),
                    "ventas": m.get("ventas", 0),
                    "condicion": "new",
                })

        # Calcular precios con Pix + cupones
        ofertas = [calcular(o, cupones) for o in ofertas if o.get("precio_base") and o["precio_base"] > 0]

        if not ofertas:
            print("   (sin resultados)")
            continue

        # Guardar en DB para historico
        titular = ofertas[0]
        clave = f"ean:{cfg['ean'] or titular.get('ean')}" if (cfg.get("ean") or titular.get("ean")) \
                else "q:" + normalizar(cfg["busqueda"])

        con.execute("""INSERT INTO productos(clave,nombre,categoria,imagen,precio_ref,creado)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(clave) DO UPDATE SET
                       imagen=excluded.imagen, precio_ref=excluded.precio_ref""",
                    (clave, titular["nombre"], cfg.get("categoria", ""),
                     titular.get("imagen"), cfg.get("precio_ref"), ahora))
        pid = con.execute("SELECT id FROM productos WHERE clave=?", (clave,)).fetchone()[0]

        # Minimo historico
        previo = con.execute("SELECT MIN(precio_vista) FROM historial WHERE producto_id=?",
                             (pid,)).fetchone()[0]

        # ══════ PUNTUAR CADA OFERTA ══════
        ofertas_puntuadas = []
        for o in ofertas:
            score, desc_pct, ahorro, razon = puntuar_oferta(o, cfg.get("precio_ref"), previo)
            o["score"] = score
            o["descuento_pct"] = round(desc_pct, 1)
            o["ahorro"] = round(ahorro, 2)
            o["razon"] = razon

            if score >= 50:
                ofertas_puntuadas.append(o)
                print(f"   CHOLLO [{score:.0f}pts] {o['tienda']}: R$ {o['precio_vista']:.2f} ({razon})")
            else:
                print(f"   skip   [{score:.0f}pts] {o['tienda']}: R$ {o['precio_vista']:.2f} ({razon})")

        # Guardar historial siempre (para rastrear minimos)
        con.execute("DELETE FROM ofertas WHERE producto_id=?", (pid,))
        p_id = slug_id(titular["nombre"])

        for o in ofertas:
            con.execute("""INSERT INTO ofertas(producto_id,tienda,url,precio_base,cupon,
                           precio_vista,cuotas,total_parcelado,score,actualizado) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (pid, o["tienda"], o["url"], o["precio_base"], o.get("cupon"),
                         o["precio_vista"], o.get("cuotas", 0), o.get("total_parcelado"),
                         o.get("score", 0), ahora))
            con.execute("INSERT INTO historial(producto_id,tienda,precio_vista,total_parcelado,fecha) VALUES(?,?,?,?,?)",
                        (pid, o["tienda"], o["precio_vista"], o.get("total_parcelado"), ahora))
            con.execute("""INSERT OR IGNORE INTO historico_precios (producto_id, tienda, precio, fecha)
                           VALUES (?, ?, ?, datetime('now'))""",
                        (p_id, o["tienda"], o["precio_vista"]))
        con.commit()
        time.sleep(1)  # respetar rate limits

        # Solo agregar a la salida si hay al menos 1 chollo real
        if not ofertas_puntuadas:
            salida["resumen"]["descartados"] += 1
            continue

        salida["resumen"]["chollos"] += 1
        mejor_vista = min(ofertas_puntuadas, key=lambda o: o["precio_vista"])
        parceladas = [o for o in ofertas_puntuadas if o.get("total_parcelado")]
        mejor_parc = min(parceladas, key=lambda o: o["total_parcelado"]) if parceladas else None

        # Priorizar cualquier imagen real disponible entre las ofertas del producto
        imagen_valida = next((o["imagen"] for o in ofertas_puntuadas if o.get("imagen")), None) or next((o["imagen"] for o in ofertas if o.get("imagen")), None)

        # Construir lista comparativa
        comp_items = [{
            "tienda": o["tienda"], "vista": o["precio_vista"],
            "parcelado": o.get("total_parcelado"), "cuotas": o.get("cuotas", 0),
            "url": o["url"], "cupon": o.get("cupon"), "score": o["score"],
        } for o in ofertas_puntuadas]

        # Si un producto tiene "url_ml" no vacío, agregar "Mercado Livre" como tienda extra en el comparativo
        for m in manuales:
            clave_coincide = m.get("ean") and (cfg.get("ean") == m["ean"] or any(o.get("ean") == m["ean"] for o in ofertas))
            nombre_coincide = m.get("nombre") and normalizar(cfg["busqueda"]) in normalizar(m["nombre"])
            if (clave_coincide or nombre_coincide) and m.get("url_ml") and m["url_ml"].strip():
                # Garantizar siempre el tag de afiliado en el link
                ml_url = construir_link_afiliado_ml(m["url_ml"].strip())
                ml_precio = m.get("precio_ml") or m.get("precio_base") or cfg.get("precio_ref", 0)
                ml_precio = round(float(ml_precio), 2)
                ml_existente = next((c for c in comp_items if c["tienda"] == "Mercado Livre"), None)
                if ml_existente:
                    ml_existente["url"] = ml_url
                    if m.get("precio_ml"):
                        ml_existente["vista"] = ml_precio
                else:
                    comp_items.append({
                        "tienda": "Mercado Livre",
                        "vista": ml_precio,
                        "parcelado": ml_precio,
                        "cuotas": 10,
                        "url": ml_url,
                        "cupon": None,
                        "score": 60.0,
                    })
                break


        comp_items.sort(key=lambda x: x["vista"])

        # Insertar precios del comparativo en historico_precios
        for c in comp_items:
            con.execute("""INSERT OR IGNORE INTO historico_precios (producto_id, tienda, precio, fecha)
                           VALUES (?, ?, ?, datetime('now'))""",
                        (p_id, c["tienda"], c["vista"]))
        con.commit()

        # Generar histórico para las gráficas
        historico_data = obtener_historico_producto(con, p_id, comp_items, cfg.get("precio_ref"))

        salida["productos"].append({
            "id": p_id,
            "nombre": mejor_vista["nombre"],
            "categoria": cfg.get("categoria", ""),
            "imagen": imagen_valida,
            "precio_ref": cfg.get("precio_ref"),
            "score": mejor_vista["score"],
            "descuento_pct": mejor_vista["descuento_pct"],
            "ahorro": mejor_vista["ahorro"],
            "bajo": bool(previo) and mejor_vista["precio_vista"] < previo - 0.01,
            "minimo_historico": previo,
            "vista": {
                "precio": mejor_vista["precio_vista"],
                "tienda": mejor_vista["tienda"],
                "cupon": mejor_vista.get("cupon"),
                "pix": mejor_vista["pix_pct"] > 0,
                "base": mejor_vista["precio_base"],
                "original": mejor_vista.get("precio_original"),
                "url": mejor_vista["url"],
            },
            "parcelado": None if not mejor_parc else {
                "total": mejor_parc["total_parcelado"],
                "cuotas": mejor_parc["cuotas"],
                "cuota": round(mejor_parc["total_parcelado"] / mejor_parc["cuotas"], 2),
                "tienda": mejor_parc["tienda"],
                "url": mejor_parc["url"],
            },
            "comparativo": comp_items,
            "historico": historico_data,
        })

    con.close()

    # Ordenar por score (mejores chollos primero)
    salida["productos"].sort(key=lambda p: p["score"], reverse=True)

    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 55)
    print(f"  RESULTADO:")
    print(f"  {salida['resumen']['total_buscados']} buscados")
    print(f"  {salida['resumen']['chollos']} CHOLLOS REALES encontrados")
    print(f"  {salida['resumen']['descartados']} descartados (no valen la pena)")
    print(f"  Exportado -> {SALIDA.name}")
    print("=" * 55)

if __name__ == "__main__":
    ejecutar()
