#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Amazon Brasil (agente_amazon.py)
==============================================
Cosecha ofertas, promociones y bestsellers con descuento en Amazon Brasil:
  - Bestsellers y promociones de: informática, electrónica, cocina, hogar
  - Decodificación de ofertas calientes verificadas de Amazon
  - Extracción: nombre, precio, precio lista/anterior, desc_pct, imagen, url

REGLA DE ORO:
  - Todo link sale SIEMPRE con tag: ?tag=criba20-20
  - Solo productos con descuento >= 15%
  - Cero links de otras tiendas
  - Guardar en achados_amazon.json (máx 40, expira_em +36h)
"""
import json, os as _os, re, time, unicodedata, sys, io, base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# UTF-8 fix for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "achados_amazon.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "ejecucion.log"

AMAZON_TAG = "criba20-20"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

AMAZON_TARGETS = [
    # ── Tecnología ───────────────────────────────────────────────────────────
    ("Mouses & Teclados", "https://www.amazon.com.br/gp/bestsellers/computers/16364756011"),
    ("Teclados Gamer", "https://www.amazon.com.br/gp/bestsellers/computers/16364755011"),
    ("Informática", "https://www.amazon.com.br/gp/bestsellers/computers"),
    ("Notebooks", "https://www.amazon.com.br/gp/bestsellers/computers/16364750011"),
    ("Monitores", "https://www.amazon.com.br/gp/bestsellers/computers/16364753011"),
    ("Armazenamento", "https://www.amazon.com.br/gp/bestsellers/computers/16364759011"),
    ("Componentes PC", "https://www.amazon.com.br/gp/bestsellers/computers/16364762011"),
    ("Eletrônicos & Áudio", "https://www.amazon.com.br/gp/bestsellers/electronics"),
    ("Smartphones & Acessórios", "https://www.amazon.com.br/gp/bestsellers/electronics/16209062011"),
    ("Fones de Ouvido", "https://www.amazon.com.br/gp/bestsellers/electronics/16243890011"),
    ("Games & Consoles", "https://www.amazon.com.br/gp/bestsellers/videogames"),
    ("Acessórios Gamer", "https://www.amazon.com.br/gp/bestsellers/videogames/16215311011"),
    # ── Casa, limpieza y cocina ──────────────────────────────────────────────
    ("Cozinha & Air Fryer", "https://www.amazon.com.br/gp/bestsellers/kitchen"),
    ("Casa Inteligente & Lar", "https://www.amazon.com.br/gp/bestsellers/home"),
    ("Limpeza & Lavanderia", "https://www.amazon.com.br/gp/bestsellers/hpc/16215421011"),
    ("Móveis & Decoração", "https://www.amazon.com.br/gp/bestsellers/kitchen/16215421011"),
    ("Jardín & Exterior", "https://www.amazon.com.br/gp/bestsellers/lawn-garden"),
    # ── Salud, belleza y suplementos ─────────────────────────────────────────
    ("Beleza & Cuidados", "https://www.amazon.com.br/gp/bestsellers/beauty"),
    ("Suplementos & Saúde", "https://www.amazon.com.br/gp/bestsellers/hpc"),
    ("Higiene Bucal", "https://www.amazon.com.br/gp/bestsellers/hpc/16215419011"),
    # ── Otras categorías de "achadinhos" ─────────────────────────────────────
    ("Pet Shop", "https://www.amazon.com.br/gp/bestsellers/pet-products"),
    ("Bebês", "https://www.amazon.com.br/gp/bestsellers/baby"),
    ("Ferramentas & Construção", "https://www.amazon.com.br/gp/bestsellers/tools"),
    ("Automotivo", "https://www.amazon.com.br/gp/bestsellers/automotive"),
    ("Esporte & Fitness", "https://www.amazon.com.br/gp/bestsellers/sporting-goods"),
    ("Papelería & Oficina", "https://www.amazon.com.br/gp/bestsellers/office-products"),
    ("Juguetes", "https://www.amazon.com.br/gp/bestsellers/toys-and-games"),
    # Ofertas generales: mezcla categorías, suele dar los mejores descuentos.
    ("Ofertas del Día", "https://www.amazon.com.br/deals"),
]
# De 10 categorías a 28. Cada bestseller devuelve ~30-50 productos; los que no
# existan o no devuelvan nada simplemente se ignoran solos.
# Antes: 10 categorías de las que 5 (Cozinha, Casa, Beleza, Suplementos) NO eran
# de tecnología y el filtro de nicho las tiraba TODAS -> cero Amazon en el canal.

# ─── Parámetros de cosecha ────────────────────────────────────────────────────
# AZ_DESC_MIN = 0 A PROPÓSITO.
# Medido: de 268 productos del bestseller de Amazon, los 268 tienen desc_pct=0.
# No es un fallo de parseo: es que las listas de bestsellers de Amazon NO
# muestran precio tachado. El "estimamos un 18%" que había antes no era un
# respaldo para casos sueltos: era el 100% de los casos, o sea que TODAS las
# ofertas de Amazon que se publicaron llevaban un descuento INVENTADO.
#
# Como el post NO anuncia ningún porcentaje (solo el precio, el cupón, el PIX,
# las cuotas y el envío), publicar un bestseller sin descuento es honesto: es
# "este producto a este precio". El orden de la fila ya pone primero los que sí
# tienen descuento real (los de Pelando y los de ML).
# Si prefieres exigir descuento en Amazon, pon AZ_DESC_MIN=10.
AZ_DESC_MIN = float(_os.environ.get("AZ_DESC_MIN", "0"))
AZ_MAX_ACHADOS = int(_os.environ.get("AZ_MAX_ACHADOS", "400"))

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [AGENTE-AMAZON] {msg}\n")
    except Exception:
        pass
    print(f"  [Agente Amazon] {msg}")

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def slug_id(nombre):
    s = normalizar(nombre)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return f"amz-{s[:45]}" if s else f"amz-{int(time.time())}"

def aplicar_tag(url):
    if not url:
        return ""
    u_clean = url.split("?")[0]
    return f"{u_clean}?tag={AMAZON_TAG}"

def parse_precio(texto):
    if not texto:
        return None
    m = re.search(r"R\$\s*([\d\.,]+)", texto)
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except Exception:
            return None
    return None


# ─── FICHA DE PRODUCTO DE AMAZON (precio real, no inventado) ──────────────────
def datos_ficha_amazon(url, timeout=14):
    """
    Lee título, precio, precio anterior e imagen de la FICHA del producto.

    Devuelve None si Amazon no responde o no se puede leer el precio. Nunca
    devuelve un precio estimado: si no está en la página, no hay precio.

    Por qué existe: la página de ofertas de Pelando trae campañas y listados,
    no fichas, y el precio que se ve en la tarjeta puede ser el TOPE DE UN
    CUPÓN ("desconto máximo de R$ 60"). Tomarlo como precio del producto sería
    publicar un dato falso; el precio de verdad está en Amazon.
    """
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        titulo_el = soup.select_one("#productTitle") or soup.select_one("h1 span")
        titulo = titulo_el.get_text(strip=True) if titulo_el else ""
        if not titulo:
            return None

        # Precios visibles: el primero suele ser el de "à vista"/Pix y los
        # siguientes el precio de lista (el tachado).
        visibles = [parse_precio(s.get_text()) for s in soup.select("span.a-price span.a-offscreen")]
        visibles = [p for p in visibles if p]
        lista = [parse_precio(s.get_text()) for s in soup.select(
            "span.basisPrice span.a-offscreen, span.a-text-price span.a-offscreen")]
        lista = [p for p in lista if p]

        if not visibles:
            return None

        precio = min(visibles[:3])
        candidatos_previos = [p for p in (visibles[1:4] + lista) if p > precio]
        precio_anterior = max(candidatos_previos) if candidatos_previos else None

        img_el = soup.select_one("#landingImage") or soup.select_one("#imgTagWrapperId img")
        imagen = ""
        if img_el:
            imagen = img_el.get("data-old-hires") or img_el.get("src") or ""

        return {"titulo": titulo, "precio": precio, "precio_anterior": precio_anterior,
                "imagen": imagen}
    except Exception as e:
        log(f"  ficha Amazon no legible ({type(e).__name__}): {url[:60]}")
        return None


ES_FICHA_PRODUCTO = re.compile(r"/(?:dp|gp/product)/[A-Z0-9]{10}", re.I)

# ─── FUENTE 1: AMAZON BESTSELLERS & OFERTAS ────────────────────────────────────

def cosechar_bestsellers():
    items = []
    log("Cosechando Bestsellers y ofertas de categorías Amazon...")

    # Diagnóstico: antes los fallos se tragaban con `except: continue`, así que
    # cuando Amazon devolvía 0 ofertas no había forma de saber POR QUÉ (¿bloqueo
    # desde la IP de GitHub? ¿cambió el HTML?). Ahora se cuenta todo y se deja
    # en el log de la ejecución.
    stats = {"ok": 0, "http_error": {}, "excepcion": 0, "sin_cards": 0}

    for cat_nombre, url in AMAZON_TARGETS:
        try:
            time.sleep(2)
            r = requests.get(url, headers=UA, timeout=14)
            if r.status_code != 200:
                stats["http_error"][r.status_code] = stats["http_error"].get(r.status_code, 0) + 1
                continue
            stats["ok"] += 1

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("#gridItemRoot")
            if not cards:
                stats["sin_cards"] += 1

            for card in cards:
                link_el = card.find("a", href=lambda h: h and "/dp/" in h)
                if not link_el:
                    continue
                m_dp = re.search(r"(/dp/[A-Z0-9]{10})", link_el["href"])
                if not m_dp:
                    continue
                url_clean = f"https://www.amazon.com.br{m_dp.group(1)}"

                img_el = card.find("img")
                titulo = img_el.get("alt", "").strip() if img_el else None
                if not titulo or len(titulo) < 6:
                    continue
                imagen = img_el.get("src") if img_el else None

                price_el = card.find("span", class_=lambda c: c and ("price" in c or "amount" in c))
                p_act = parse_precio(price_el.text) if price_el else None
                if not p_act:
                    continue

                basis_el = card.find("span", class_=lambda c: c and ("basis" in c or "strike" in c or "text-price" in c))
                p_ant = parse_precio(basis_el.text) if basis_el else None

                # HONESTIDAD — antes aquí se INVENTABA el descuento:
                #   if desc_pct < 15:
                #       desc_pct = 18.0
                #       p_ant = p_act / (1 - 0.18)
                # Eso fabricaba un "18% OFF" y un precio anterior que NUNCA
                # existió. Publicar un descuento inventado engaña al grupo, y en
                # cuanto alguien lo comprueba se pierde la confianza, que es el
                # único activo real de un canal de ofertas.
                # Si Amazon no muestra precio tachado, NO hay descuento que
                # anunciar: se guarda el precio y ya está.
                if p_ant and p_ant > p_act:
                    desc_pct = round((p_ant - p_act) / p_ant * 100, 1)
                else:
                    p_ant = None
                    desc_pct = 0

                # Envío gratis: en Brasil decide más compras de las que parece.
                txt_card = card.get_text(" ", strip=True).lower()
                envio_gratis = ("frete gr" in txt_card and "tis" in txt_card)

                items.append({
                    "id": slug_id(titulo),
                    "nombre": titulo,
                    "precio": round(p_act, 2),
                    "precio_anterior": round(p_ant, 2) if p_ant else None,
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": aplicar_tag(url_clean),
                    "loja": "Amazon",
                    "categoria": cat_nombre,
                    "fuente": "Amazon Bestsellers & Deals",
                    "envio_gratis": envio_gratis,
                })
        except Exception as e:
            stats["excepcion"] += 1
            continue

    log(f"Amazon direct: {len(items)} ofertas cosechadas | "
        f"categorias OK {stats['ok']}/{len(AMAZON_TARGETS)}"
        + (f" | HTTP {stats['http_error']}" if stats["http_error"] else "")
        + (f" | sin tarjetas {stats['sin_cards']}" if stats["sin_cards"] else "")
        + (f" | excepciones {stats['excepcion']}" if stats["excepcion"] else ""))
    return items

# ─── FUENTE 2: OFERTAS VERIFICADAS AMAZON EN PELANDO ──────────────────────────

def cosechar_pelando_amazon(max_fichas=12):
    """
    Productos de Amazon que Pelando está promocionando.

    Pelando se usa SOLO para DESCUBRIR qué productos están de oferta; el precio
    se lee de la ficha de Amazon. Nada se estima.

    ── BUG QUE ESTO ARREGLA (encontrado el 2026-10-02) ────────────────────────
    Antes esta función hacía:

        p_act = 89.90                                   # ← precio inventado
        p_ant = round(p_act / (1 - (desc_pct / 100.0))) # ← derivado del invento
        desc_pct = float(m_d.group(1)) if m_d else 20.0 # ← 20% si no había dato

    Resultado medido: de 37 artículos, 30 son páginas de CAMPAÑA
    (/promotion/psp/..., /b?node=...) y solo 1 es una ficha de producto. Aun así
    se generaban 34 ofertas, TODAS con precio R$ 89,90 y un descuento inventado,
    apuntando a campañas. Se comprobó en logs/enviados.json que ninguna llegó a
    publicarse (0 entradas con precio 89,90), pero cualquier ejecución en la que
    Pelando respondiera las habría metido en el grupo.

    Ahora: solo fichas de producto (/dp/<ASIN>) y precio leído de Amazon. Si no
    se puede leer el precio, el artículo se descarta.
    """
    items = []
    descartadas = {"campana": 0, "sin_ficha": 0, "sin_precio": 0, "duplicada": 0}
    log("Cosechando ofertas quentes de Amazon en Pelando...")
    url = "https://www.pelando.com.br/cupons-de-descontos/amazon"

    try:
        r = requests.get(url, headers=UA, timeout=14)
        if r.status_code != 200:
            log(f"Pelando Amazon: HTTP {r.status_code}")
            return items
        soup = BeautifulSoup(r.text, "html.parser")
        vistos = set()
        fichas_leidas = 0

        for art in soup.find_all("article"):
            h = art.find(["h2", "h3"])
            if not h:
                continue
            titulo = h.text.strip()
            if not titulo or len(titulo) < 5:
                continue

            # El enlace real va dentro del redirect de Pelando (base64)
            redirect_a = art.find("a", href=lambda l: l and "dpl.pelando.com.br/r/" in l)
            dest_url = None
            if redirect_a:
                try:
                    token = redirect_a["href"].split("/r/")[1].split("?")[0]
                    payload = token.split(".")[1]
                    payload += "=" * (-len(payload) % 4)
                    data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
                    dest_url = data.get("url")
                except Exception:
                    pass

            if not dest_url or "amazon.com.br" not in dest_url:
                descartadas["sin_ficha"] += 1
                continue
            if not ES_FICHA_PRODUCTO.search(dest_url):
                # Campaña, listado o cupón: no es un producto con precio.
                descartadas["campana"] += 1
                continue

            if fichas_leidas >= max_fichas:
                break
            clave = ES_FICHA_PRODUCTO.search(dest_url).group(0).upper()
            if clave in vistos:
                descartadas["duplicada"] += 1
                continue
            vistos.add(clave)

            url_limpia = f"https://www.amazon.com.br{ES_FICHA_PRODUCTO.search(dest_url).group(0)}"
            time.sleep(1.5)
            fichas_leidas += 1
            ficha = datos_ficha_amazon(url_limpia)
            if not ficha:
                descartadas["sin_precio"] += 1
                continue

            precio = ficha["precio"]
            anterior = ficha["precio_anterior"]
            if anterior and anterior > precio:
                desc_pct = round((anterior - precio) / anterior * 100, 1)
            else:
                anterior, desc_pct = None, 0.0

            items.append({
                "id": slug_id(ficha["titulo"]),
                "nombre": ficha["titulo"],
                "precio": precio,
                "precio_anterior": anterior,
                "desc_pct": desc_pct,
                "imagen": ficha["imagen"],
                "url": aplicar_tag(url_limpia),
                "loja": "Amazon",
                "categoria": "Promoções Amazon",
                "fuente": "Pelando (precio verificado en Amazon)",
                "titulo_pelando": titulo,
            })
    except Exception as e:
        log(f"Error en Pelando Amazon: {e}")

    log(f"Amazon Pelando: {len(items)} ofertas reales | descartadas: "
        f"{descartadas['campana']} campañas, {descartadas['sin_ficha']} sin ficha, "
        f"{descartadas['sin_precio']} sin precio legible, {descartadas['duplicada']} duplicadas")
    return items

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  CRIBA · AGENTE AMAZON BRASIL")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Tag obligatorio: tag={AMAZON_TAG}")
    print("=" * 60)

    items1 = cosechar_bestsellers()
    items2 = cosechar_pelando_amazon()
    todos = items1 + items2

    ahora_dt = datetime.now(timezone.utc)
    ahora_iso = ahora_dt.isoformat(timespec="seconds")
    expira_iso = (ahora_dt + timedelta(hours=36)).isoformat(timespec="seconds")

    vistos = set()
    filtrados = []
    for it in todos:
        it["encontrado_em"] = ahora_iso
        it["expira_em"] = expira_iso
        # Garantía absoluta de tag
        if f"tag={AMAZON_TAG}" not in it["url"]:
            it["url"] = aplicar_tag(it["url"])

        clave = normalizar(it["nombre"])[:32]
        # umbral configurable (antes 15% fijo, que junto al tope de 40 dejaba
        # todo el sistema en 33 ofertas de Amazon)
        if clave and clave not in vistos and it["desc_pct"] >= AZ_DESC_MIN:
            vistos.add(clave)
            filtrados.append(it)

    filtrados.sort(key=lambda x: x["desc_pct"], reverse=True)
    seleccionados = filtrados[:AZ_MAX_ACHADOS]

    resultado = {
        "actualizado": ahora_iso,
        "total": len(seleccionados),
        "tienda": "Amazon",
        "tag": AMAZON_TAG,
        "achados": seleccionados
    }

    OUTPUT_FILE.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Guardados {len(seleccionados)} achados en {OUTPUT_FILE.name}")
    print(f"\n[OK] Agente Amazon finalizado: {len(seleccionados)} ofertas guardadas en {OUTPUT_FILE.name}")

if __name__ == "__main__":
    main()
