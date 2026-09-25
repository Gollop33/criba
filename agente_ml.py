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
import json, os, re, time, unicodedata, sys, io
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

# ─── Parámetros de cosecha (configurables sin tocar código) ───────────────────
# ML_LIMIT      cuántos resultados pedir por término (la API de ML admite 50)
# ML_DESC_MIN   descuento mínimo para aceptar una oferta
# Con ~96 términos x 50 resultados = ~4800 candidatos, de los que tras el filtro
# de descuento y la deduplicación salen varios cientos de ofertas.
ML_LIMIT = int(os.environ.get("ML_LIMIT", "50"))
ML_DESC_MIN = float(os.environ.get("ML_DESC_MIN", "10"))
# Tope de ofertas guardadas. Antes era 40 FIJO: el scraper cosechaba 565
# ofertas y el sistema entero acababa publicando con 40. Es el cuello de
# botella que impedía llegar a 150 posts/día.
ML_MAX_ACHADOS = int(os.environ.get("ML_MAX_ACHADOS", "400"))

# ─── Categorías de Mercado Livre (LA fuente real de volumen) ──────────────────
# Cada URL de categoría devuelve ~90 ofertas reales. Antes solo había 3 y de ahí
# salían las 40 ofertas de ML de todo el sistema. Los IDs son los estándar de
# ML Brasil; los que no devuelvan nada simplemente se ignoran solos.
ML_CATEGORIAS = [
    ("Informática", "https://www.mercadolivre.com.br/ofertas?category=MLB1648"),
    ("Eletrônicos", "https://www.mercadolivre.com.br/ofertas?category=MLB1000"),
    ("Eletrodomésticos", "https://www.mercadolivre.com.br/ofertas?category=MLB1574"),
    ("Celulares e Telefones", "https://www.mercadolivre.com.br/ofertas?category=MLB1051"),
    ("Esportes e Fitness", "https://www.mercadolivre.com.br/ofertas?category=MLB1276"),
    ("Ferramentas", "https://www.mercadolivre.com.br/ofertas?category=MLB1403"),
    ("Beleza e Cuidado Pessoal", "https://www.mercadolivre.com.br/ofertas?category=MLB1747"),
    ("Acessórios para Veículos", "https://www.mercadolivre.com.br/ofertas?category=MLB1132"),
    ("Animais", "https://www.mercadolivre.com.br/ofertas?category=MLB1071"),
    ("Saúde", "https://www.mercadolivre.com.br/ofertas?category=MLB1955"),
    ("Brinquedos e Hobbies", "https://www.mercadolivre.com.br/ofertas?category=MLB1384"),
    ("Construção", "https://www.mercadolivre.com.br/ofertas?category=MLB1499"),
    # Ofertas generales: la que más rinde porque mezcla categorías.
    ("Ofertas Gerais", "https://www.mercadolivre.com.br/ofertas"),
]
# Medido el 2026-09-25: 15 de 16 categorías devuelven ~30-48 ofertas cada una,
# 656 ofertas en bruto (antes el sistema entero producía 40 de ML).
# Se quitaron: "Bebês" (MLB1459, devolvía 0) y dos IDs que estaban repetidos
# (Casa=Mismas que Eletrodomésticos, Indústria=Igual que Construção).

CATEGORIAS_BUSQUEDA = [
    # ── Tecnología ───────────────────────────────────────────────────────────
    ("Smartphones Samsung", "smartphone samsung"),
    ("iPhone", "iphone"),
    ("Xiaomi", "xiaomi redmi"),
    ("Smart TV", "smart tv 4k"),
    ("Notebooks", "notebook"),
    ("Notebook Gamer", "notebook gamer"),
    ("Tablets", "tablet"),
    ("Caixa de Som Bluetooth", "caixa de som bluetooth"),
    ("Fones Bluetooth", "fone de ouvido bluetooth"),
    ("Ar Condicionado", "ar condicionado inverter"),
    ("Echo Dot Alexa", "echo dot alexa"),
    ("Câmeras de Segurança", "camera de seguranca wifi"),
    ("Projetores", "projetor portatil"),
    # Setup Gamer & Informática
    ("Cadeiras Gamer", "cadeira gamer"),
    ("Cadeiras Escritório", "cadeira escritorio ergonomica"),
    ("Mesas Gamer", "mesa gamer"),
    ("Monitores Gamer", "monitor gamer"),
    ("Monitores 144Hz", "monitor 144hz"),
    ("SSDs NVMe", "ssd nvme"),
    ("HDs Externos", "hd externo"),
    ("Placas de Video", "placa de video"),
    ("Processadores", "processador ryzen"),
    ("Memoria RAM", "memoria ram"),
    ("Placas Mãe", "placa mae"),
    ("Fontes ATX", "fonte atx"),
    ("Gabinetes", "gabinete gamer"),
    ("Water Coolers", "water cooler"),
    ("Teclados Gamer", "teclado gamer"),
    ("Teclados Mecânicos", "teclado mecanico"),
    ("Mouses Gamer", "mouse gamer"),
    ("Mouses Sem Fio", "mouse sem fio"),
    ("Headsets Gamer", "headset gamer"),
    ("Microfones", "microfone condensador"),
    ("Webcams", "webcam full hd"),
    ("Mousepads", "mousepad grande"),
    ("Impressoras", "impressora multifuncional"),
    ("Roteadores", "roteador wifi"),
    ("Pendrives e Cartões", "cartao de memoria 128gb"),
    # Consolas
    ("PlayStation", "playstation 5"),
    ("Xbox", "xbox series"),
    ("Nintendo Switch", "nintendo switch"),
    ("Controles", "controle sem fio"),
    # ── Casa, Limpieza y Cozinha ─────────────────────────────────────────────
    ("Air Fryer", "air fryer fritadeira"),
    ("Fritadeiras Elétricas", "fritadeira eletrica"),
    ("Aspiradores Verticais", "aspirador vertical robo"),
    ("Robô Aspirador", "robo aspirador"),
    ("Liquidificadores", "liquidificador"),
    ("Cafeteiras", "cafeteira expresso"),
    ("Panelas", "jogo de panelas"),
    ("Panelas de Pressão", "panela de pressao"),
    ("Jogos de Pratos", "jogo de pratos"),
    ("Utensílios de Cozinha", "utensilios de cozinha"),
    ("Ventiladores", "ventilador"),
    ("Climatizadores", "climatizador"),
    ("Umidificadores", "umidificador"),
    ("Ferros de Passar", "ferro de passar roupa"),
    ("Máquinas de Lavar", "maquina de lavar"),
    ("Amaciantes", "amaciante"),
    ("Sabão em Pó", "sabao em po"),
    ("Detergentes", "detergente"),
    ("Papel Higiênico", "papel higienico"),
    ("Papel Toalha", "papel toalha"),
    ("Jogos de Cama", "jogo de cama"),
    ("Toalhas de Banho", "jogo de toalhas"),
    ("Travesseiros", "travesseiro"),
    ("Colchões", "colchao"),
    ("Organizadores", "organizador de cozinha"),
    # ── Salud, Belleza y Suplementos ─────────────────────────────────────────
    ("Perfumes Masculinos", "perfume masculino"),
    ("Perfumes Femininos", "perfume feminino"),
    ("Creatina", "creatina"),
    ("Whey Protein", "whey protein"),
    ("Pré-Treino", "pre treino"),
    ("Multivitamínicos", "multivitaminico"),
    ("Colágeno", "colageno"),
    ("Escovas de Dente Elétricas", "escova de dente eletrica"),
    ("Barbeadores", "barbeador eletrico"),
    ("Secadores de Cabelo", "secador de cabelo"),
    ("Pranchas de Cabelo", "prancha de cabelo"),
    # ── Bebé, Pet, Herramientas, Auto, Fitness ───────────────────────────────
    ("Fraldas", "fralda"),
    ("Mamadeiras", "mamadeira"),
    ("Cadeirinhas Bebé", "cadeirinha de bebe"),
    ("Ração para Cães", "racao cachorro"),
    ("Ração para Gatos", "racao gato"),
    ("Comedouros Pet", "comedouro bebedouro pet"),
    ("Furadeiras", "furadeira"),
    ("Parafusadeiras", "parafusadeira"),
    ("Caixas de Ferramentas", "caixa de ferramentas"),
    ("Compressores de Ar", "compressor de ar"),
    ("Lavadoras de Alta Pressão", "lavadora de alta pressao"),
    ("Acessórios Automotivos", "acessorio automotivo carro"),
    ("Halteres", "halter anilha"),
    ("Bicicletas", "bicicleta"),
    ("Tênis Esportivos", "tenis corrida"),
    ("Mochilas", "mochila"),
    ("Relógios Casio", "relogio casio"),
    ("Smartwatches", "smartwatch"),
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
    fallos_403 = 0
    log("Consultando API oficial de Mercado Libre...")
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Antes: limit=15 y umbral de descuento 15% -> 20 terminos x 15 = 300
    # candidatos, de los que pasaban ~40. Ahora hay ~96 terminos y pedimos 50
    # por termino (el maximo que permite la API de ML), y el umbral baja a 10%
    # porque un 10% real sigue siendo una oferta digna y el usuario quiere
    # volumen ("caro o barato, solo que ganemos").
    limite = ML_LIMIT
    desc_min = ML_DESC_MIN

    for cat_nombre, query in CATEGORIAS_BUSQUEDA:
        url = (f"https://api.mercadolibre.com/sites/MLB/search?"
               f"q={requests.utils.quote(query)}&limit={limite}")
        try:
            r = requests.get(url, headers=headers, timeout=10)
            # Desde 2025 la API publica de ML responde 403 sin token de
            # desarrollador. Antes se hacían las ~96 peticiones igual, todas
            # fallando en silencio. Ahora se detecta y se corta: el scraping de
            # /ofertas es el que aporta las ofertas de verdad.
            if r.status_code == 403:
                fallos_403 += 1
                if fallos_403 >= 2:
                    log("API ML responde 403 (necesita token de desarrollador). "
                        "Se omite esta fuente y se usa solo el scraping.")
                    break
                continue
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

                if desc_pct < ML_DESC_MIN:
                    continue

                titulo = res.get("title", "")
                permalink = res.get("permalink", "")
                thumb = res.get("thumbnail", "")
                if thumb and thumb.startswith("http://"):
                    thumb = "https://" + thumb[7:]

                # ── Parcelas y envío gratis ───────────────────────────────
                # Van en la MISMA respuesta de la API que ya descargamos, así
                # que no cuesta ni una petición extra. En Brasil son los dos
                # mayores disparadores de conversión después del precio: mucha
                # gente decide por "cuánto me sale al mes" y por el flete.
                inst = res.get("installments") or {}
                cuotas = inst.get("quantity")
                cuota_valor = inst.get("amount")
                sin_interes = (inst.get("rate") == 0) if inst else None
                envio_gratis = bool((res.get("shipping") or {}).get("free_shipping"))

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
                    "cuotas": cuotas,
                    "cuota_valor": cuota_valor,
                    "cuotas_sin_interes": sin_interes,
                    "envio_gratis": envio_gratis,
                })
        except Exception as e:
            continue

    log(f"API ML: {len(items)} ofertas obtenidas")
    return items

# ─── FUENTE 2: SCRAPING DE RESPALDO (OFERTAS & CATEGORÍAS) ────────────────────

def cosechar_scraping():
    items = []
    log("Consultando scraping de ofertas en Mercado Livre...")

    scrape_targets = list(ML_CATEGORIAS)
    # Las búsquedas por texto están DESACTIVADAS por defecto: /ofertas?q=...
    # ignora la consulta y devuelve una lista genérica, así que eran ~96
    # peticiones (con 1.5s de espera cada una = ~2.5 min) que no aportaban
    # ofertas nuevas, solo duplicados que luego se descartaban.
    if os.environ.get("ML_USAR_BUSQUEDA", "").strip().lower() in ("1", "true", "si", "sí"):
        for cat_nombre, query in CATEGORIAS_BUSQUEDA:
            scrape_targets.append(
                (cat_nombre,
                 f"https://www.mercadolivre.com.br/ofertas?q={requests.utils.quote(query)}")
            )

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
                if desc_pct < ML_DESC_MIN:
                    continue

                # Parcelas y envío gratis leídos del propio texto del anuncio:
                # ML los pinta como "em até 12x R$ 24,92 sem juros" y
                # "Frete grátis". No cuesta ninguna petición extra.
                txt_card = card.get_text(" ", strip=True).lower()
                cuotas = None
                m_cuotas = re.search(r"(\d{1,2})\s*x\s*(?:de\s*)?r\$", txt_card)
                if m_cuotas:
                    try:
                        cuotas = int(m_cuotas.group(1))
                    except ValueError:
                        cuotas = None
                sin_interes = True if "sem juros" in txt_card else None
                envio_gratis = ("frete gr" in txt_card and "tis" in txt_card) or \
                               ("frete grátis" in txt_card) or ("frete gratis" in txt_card)

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
                    "cuotas": cuotas,
                    "cuotas_sin_interes": sin_interes,
                    "envio_gratis": envio_gratis,
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
        # El umbral estaba FIJO en 15% aquí aunque la cosecha ya usaba
        # ML_DESC_MIN (10%). Y el tope de 40 era el verdadero cuello de botella:
        # el scraper cosechaba 565 ofertas y guardaba 40.
        if clave and clave not in vistos and it["desc_pct"] >= ML_DESC_MIN:
            vistos.add(clave)
            filtrados.append(it)

    filtrados.sort(key=lambda x: x["desc_pct"], reverse=True)
    seleccionados = filtrados[:ML_MAX_ACHADOS]

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
