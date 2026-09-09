#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Mercado Livre (agente_ml.py)
===========================================
Cosecha ofertas tech y de alta demanda en Mercado Libre:
  - Fuente 1: API oficial ML (/sites/MLB/search con o sin ml_api_token)
  - Fuente 2 (respaldo): Scraping directo de ofertas y categorías
  - Categorías: monitores, ssd, ram, placa de video, teclado, mouse, headset,
               notebook, echo dot, freidora, aspirador

REGLA DE ORO:
  - Todo link sale SIEMPRE con tag: #D[A:ja20250119201346]
  - Solo productos con descuento >= 15%
  - Guarda en achados_ml.json (máx 40, expira_em +36h)
"""
import json, re, time, unicodedata, sys, io
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# UTF-8 fix for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "achados_ml.json"
CONFIG_FILE = BASE / "config_afiliados.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "ejecucion.log"

ML_TAG = "#D[A:ja20250119201346]"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

CATEGORIAS_BUSQUEDA = [
    # Smartphones & Gadgets
    ("Smartphones Samsung", "smartphone samsung"),
    ("iPhone", "iphone"),
    ("Smart TV", "smart tv"),
    ("Notebooks", "notebook"),
    ("Caixa de Som Bluetooth", "caixa de som bluetooth"),
    ("Ar Condicionado", "ar condicionado inverter"),
    
    # Casa & Eletro
    ("Air Fryer", "air fryer fritadeira"),
    ("Aspiradores Verticais", "aspirador vertical robo"),
    ("Echo Dot Alexa", "echo dot alexa"),
    
    # Saúde & Beleza
    ("Perfumes Masculinos", "perfume masculino"),
    ("Creatina", "creatina"),
    ("Whey Protein", "whey protein"),
    
    # Setup Gamer & Informática
    ("Cadeiras Gamer", "cadeira gamer"),
    ("Monitores Gamer", "monitor gamer"),
    ("SSDs NVMe", "ssd nvme"),
    ("Placas de Video", "placa de video"),
    ("Memoria RAM", "memoria ram"),
    ("Teclados Gamer", "teclado gamer"),
    ("Mouses Gamer", "mouse gamer"),
    ("Headsets Gamer", "headset gamer"),
]

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [AGENTE-ML] {msg}\n")
    except Exception:
        pass
    print(f"  [Agente ML] {msg}")

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def slug_id(nombre):
    s = normalizar(nombre)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return f"ml-{s[:45]}" if s else f"ml-{int(time.time())}"

def aplicar_tag(url):
    if not url:
        return ""
    u = url.split("#")[0]
    return f"{u}{ML_TAG}"

def cargar_token_ml():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            tok = cfg.get("ml_api_token") or cfg.get("mercadolivre", {}).get("api_token")
            if tok and isinstance(tok, str) and not tok.startswith("PON_"):
                return tok.strip()
        except Exception:
            pass
    return None

# ─── FUENTE 1: API OFICIAL MERCADO LIBRE ───────────────────────────────────────

def cosechar_api(token=None):
    items = []
    log("Consultando API oficial de Mercado Libre...")
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for cat_nombre, query in CATEGORIAS_BUSQUEDA:
        url = f"https://api.mercadolibre.com/sites/MLB/search?q={requests.utils.quote(query)}&limit=15"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            results = data.get("results", [])
            for res in results:
                p_act = res.get("price")
                p_ant = res.get("original_price")
                if not p_act:
                    continue

                desc_pct = 0
                if p_ant and p_ant > p_act:
                    desc_pct = round((p_ant - p_act) / p_ant * 100, 1)

                if desc_pct < 15:
                    continue

                titulo = res.get("title", "")
                permalink = res.get("permalink", "")
                thumb = res.get("thumbnail", "")
                if thumb and thumb.startswith("http://"):
                    thumb = "https://" + thumb[7:]

                items.append({
                    "id": slug_id(titulo),
                    "nombre": titulo,
                    "precio": float(p_act),
                    "precio_anterior": float(p_ant),
                    "desc_pct": desc_pct,
                    "imagen": thumb,
                    "url": aplicar_tag(permalink),
                    "loja": "Mercado Livre",
                    "categoria": cat_nombre,
                    "fuente": "ML API Oficial",
                })
        except Exception as e:
            continue

    log(f"API ML: {len(items)} ofertas obtenidas")
    return items

# ─── FUENTE 2: SCRAPING DE RESPALDO (OFERTAS & CATEGORÍAS) ────────────────────

def cosechar_scraping():
    items = []
    log("Consultando scraping de ofertas en Mercado Livre...")

    scrape_targets = [
        ("Informática", "https://www.mercadolivre.com.br/ofertas?category=MLB1648"),
        ("Eletrônicos", "https://www.mercadolivre.com.br/ofertas?category=MLB1000"),
        ("Eletrodomésticos", "https://www.mercadolivre.com.br/ofertas?category=MLB1574"),
    ]
    for cat_nombre, query in CATEGORIAS_BUSQUEDA:
        scrape_targets.append((cat_nombre, f"https://www.mercadolivre.com.br/ofertas?q={requests.utils.quote(query)}"))

    for cat_nombre, url in scrape_targets:
        try:
            time.sleep(1.5)
            r = requests.get(url, headers=UA, timeout=12)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            polys = soup.select(".poly-card")

            for card in polys:
                t_el = card.select_one(".poly-component__title")
                if not t_el:
                    continue
                titulo = t_el.get_text(strip=True)

                link_el = card.select_one("a")
                if not link_el or not link_el.get("href"):
                    continue
                url_raw = link_el["href"].split("?")[0].split("#")[0]

                img_el = card.select_one("img")
                imagen = img_el.get("src") or img_el.get("data-src") if img_el else None

                curr_el = card.select_one(".poly-price__current .andes-money-amount__fraction")
                curr_cents = card.select_one(".poly-price__current .andes-money-amount__cents")
                prev_el = card.select_one(".poly-price__label s .andes-money-amount__fraction")
                prev_cents = card.select_one(".poly-price__label s .andes-money-amount__cents")

                if not curr_el or not prev_el:
                    continue

                def parse_val(frac, cent):
                    try:
                        f = frac.get_text(strip=True).replace(".", "")
                        c = cent.get_text(strip=True) if cent else "00"
                        return float(f"{f}.{c}")
                    except Exception:
                        return None

                p_act = parse_val(curr_el, curr_cents)
                p_ant = parse_val(prev_el, prev_cents)

                if not p_act or not p_ant or p_ant <= p_act:
                    continue

                desc_pct = round((p_ant - p_act) / p_ant * 100, 1)
                if desc_pct < 15:
                    continue

                items.append({
                    "id": slug_id(titulo),
                    "nombre": titulo,
                    "precio": p_act,
                    "precio_anterior": p_ant,
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": aplicar_tag(url_raw),
                    "loja": "Mercado Livre",
                    "categoria": cat_nombre,
                    "fuente": "ML Ofertas Web",
                })
        except Exception as e:
            continue

    log(f"Scraping ML: {len(items)} ofertas obtenidas")
    return items

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  CRIBA · AGENTE MERCADO LIVRE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Tag obligatorio: {ML_TAG}")
    print("=" * 60)

    token = cargar_token_ml()
    items_api = []
    if token:
        items_api = cosechar_api(token)

    items_scrape = cosechar_scraping()
    todos = items_api + items_scrape

    ahora_dt = datetime.now(timezone.utc)
    ahora_iso = ahora_dt.isoformat(timespec="seconds")
    expira_iso = (ahora_dt + timedelta(hours=36)).isoformat(timespec="seconds")

    # Deduplicar y ordenar
    vistos = set()
    filtrados = []
    for it in todos:
        it["encontrado_em"] = agora_iso = ahora_iso
        it["expira_em"] = expira_iso
        # Garantía estricta de tag
        if ML_TAG not in it["url"]:
            it["url"] = aplicar_tag(it["url"])

        clave = normalizar(it["nombre"])[:32]
        if clave and clave not in vistos and it["desc_pct"] >= 15:
            vistos.add(clave)
            filtrados.append(it)

    filtrados.sort(key=lambda x: x["desc_pct"], reverse=True)
    seleccionados = filtrados[:40]

    resultado = {
        "actualizado": ahora_iso,
        "total": len(seleccionados),
        "tienda": "Mercado Livre",
        "tag": ML_TAG,
        "achados": seleccionados
    }

    OUTPUT_FILE.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Guardados {len(seleccionados)} achados en {OUTPUT_FILE.name}")
    print(f"\n[OK] Agente ML finalizado: {len(seleccionados)} ofertas guardadas en {OUTPUT_FILE.name}")

if __name__ == "__main__":
    main()
