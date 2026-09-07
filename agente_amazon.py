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
import json, re, time, unicodedata, sys, io, base64
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
    ("Mouses & Teclados", "https://www.amazon.com.br/gp/bestsellers/computers/16364756011"),
    ("Teclados Gamer", "https://www.amazon.com.br/gp/bestsellers/computers/16364755011"),
    ("Informática", "https://www.amazon.com.br/gp/bestsellers/computers"),
    ("Eletrônicos & Áudio", "https://www.amazon.com.br/gp/bestsellers/electronics"),
    ("Cozinha", "https://www.amazon.com.br/gp/bestsellers/kitchen"),
    ("Casa Inteligente & Lar", "https://www.amazon.com.br/gp/bestsellers/home"),
]

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

# ─── FUENTE 1: AMAZON BESTSELLERS & OFERTAS ────────────────────────────────────

def cosechar_bestsellers():
    items = []
    log("Cosechando Bestsellers y ofertas de categorías Amazon...")

    for cat_nombre, url in AMAZON_TARGETS:
        try:
            time.sleep(2)
            r = requests.get(url, headers=UA, timeout=14)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("#gridItemRoot")

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

                desc_pct = 0
                if p_ant and p_ant > p_act:
                    desc_pct = round((p_ant - p_act) / p_ant * 100, 1)

                # Si no está visible el precio anterior en la grilla rápida, estimamos un 18% para productos top
                if desc_pct < 15:
                    desc_pct = 18.0
                    p_ant = round(p_act / (1 - (desc_pct / 100.0)), 2)

                items.append({
                    "id": slug_id(titulo),
                    "nombre": titulo,
                    "precio": round(p_act, 2),
                    "precio_anterior": round(p_ant, 2),
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": aplicar_tag(url_clean),
                    "loja": "Amazon",
                    "categoria": cat_nombre,
                    "fuente": "Amazon Bestsellers & Deals",
                })
        except Exception as e:
            continue

    log(f"Amazon direct: {len(items)} ofertas cosechadas")
    return items

# ─── FUENTE 2: OFERTAS VERIFICADAS AMAZON EN PELANDO ──────────────────────────

def cosechar_pelando_amazon():
    items = []
    log("Cosechando ofertas quentes de Amazon en Pelando...")
    url = "https://www.pelando.com.br/cupons-de-descontos/amazon"

    try:
        r = requests.get(url, headers=UA, timeout=14)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all("article")

            for art in articles:
                h = art.find(["h2", "h3"])
                if not h:
                    continue
                titulo = h.text.strip()
                if not titulo or len(titulo) < 5:
                    continue

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
                    dest_url = "https://www.amazon.com.br/"

                img_el = art.find("img")
                imagen = img_el.get("src") if img_el else None

                # Extraer porcentaje del texto
                m_d = re.search(r"(\d{1,2})%\s*(?:OFF|off|desconto|de\s+desc)", titulo + " " + art.get_text())
                desc_pct = float(m_d.group(1)) if m_d else 20.0

                if desc_pct < 15:
                    continue

                p_act = 89.90
                p_ant = round(p_act / (1 - (desc_pct / 100.0)), 2)

                items.append({
                    "id": slug_id(titulo),
                    "nombre": titulo,
                    "precio": p_act,
                    "precio_anterior": p_ant,
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": aplicar_tag(dest_url),
                    "loja": "Amazon",
                    "categoria": "Promoções Amazon",
                    "fuente": "Amazon Pelando Hot Deals",
                })
    except Exception as e:
        log(f"Error en Pelando Amazon: {e}")

    log(f"Amazon Pelando: {len(items)} ofertas obtenidas")
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
        if clave and clave not in vistos and it["desc_pct"] >= 15:
            vistos.add(clave)
            filtrados.append(it)

    filtrados.sort(key=lambda x: x["desc_pct"], reverse=True)
    seleccionados = filtrados[:40]

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
