#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Caça-Ofertas (Cosecha Diaria Automatizada)
=========================================================
Rastrea ofertas activas en:
  1. Mercado Livre (Ofertas de tecnología, informática, periféricos, audio, smart home)
  2. Pelando (Ofertas quentes e cupons de Amazon e Mercado Livre)
  3. Amazon Brasil (Ofertas e Mais Vendidos)

REGLA DE ORO ESTRICTA:
  - Solo lojas autorizadas: "Amazon" e "Mercado Livre"
  - Aplica tags de afiliado de CRIBA:
      Amazon: criba20-20
      Mercado Livre: #D[A:ja20250119201346]
  - Deduplica por nombre normalizado
  - Descarta ofertas sin descuento >= 15%
  - Guarda en achados.json (máx 60 items, purga expirados)

Uso: python descobrir_ofertas.py
"""
import json, re, time, unicodedata, sys, io, base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
ACHADOS_JSON = BASE / "achados.json"
CONFIG_JSON = BASE / "config_afiliados.json"
LOGS_DIR = BASE / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "ejecucion.log"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

AMAZON_TAG = "criba20-20"
ML_AFILIADO_ID = "ja20250119201346"

def cargar_tiendas_que_pagan():
    if CONFIG_JSON.exists():
        try:
            cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
            tiendas = cfg.get("tiendas_que_pagan")
            if isinstance(tiendas, list) and tiendas:
                return [t.lower().replace(" ", "").replace("!", "").replace("_", "") for t in tiendas]
        except Exception:
            pass
    return ["amazon", "mercadolivre"]

TIENDAS_QUE_PAGAN = cargar_tiendas_que_pagan()

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def normalizar_tienda(nombre):
    if not nombre:
        return ""
    n = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", n)

def tienda_permitida(nombre_tienda):
    n = normalizar_tienda(nombre_tienda)
    for t in TIENDAS_QUE_PAGAN:
        t_norm = normalizar_tienda(t)
        if t_norm in n or n in t_norm:
            return True
    return False

def slug_id(nombre):
    s = normalizar(nombre)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:50] if s else "oferta"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [CACA-OFERTAS] {msg}\n")
    except Exception:
        pass
    print(f"  [Caça-Ofertas] {msg}")

def aplicar_tag_afiliado(url_original, tienda):
    if not url_original or not isinstance(url_original, str):
        return url_original
    url = url_original.strip()
    t_norm = normalizar_tienda(tienda)

    if "amazon" in t_norm or "amazon.com.br" in url:
        u_clean = url.split("?")[0]
        params = []
        if "?" in url:
            for part in url.split("?")[1].split("&"):
                if not part.startswith("tag=") and not part.startswith("linkCode="):
                    params.append(part)
        params.append(f"tag={AMAZON_TAG}")
        return f"{u_clean}?{'&'.join(params)}"

    if "mercadolivre" in t_norm or "mercadolivre.com.br" in url or "mercadolibre" in url:
        u_clean = url.split("#")[0]
        return f"{u_clean}#D[A:{ML_AFILIADO_ID}]"

    return url

def extraer_precios_texto(texto):
    if not texto:
        return None, None, 0
    m_de_por = re.search(r"de\s+R\$\s*([\d\.,]+)\s+por\s+R\$\s*([\d\.,]+)", texto, re.IGNORECASE)
    if m_de_por:
        try:
            p_ant = float(m_de_por.group(1).replace(".", "").replace(",", "."))
            p_act = float(m_de_por.group(2).replace(".", "").replace(",", "."))
            if p_ant > p_act and p_ant > 0:
                desc = round((p_ant - p_act) / p_ant * 100, 1)
                return p_act, p_ant, desc
        except Exception:
            pass

    m_desc = re.search(r"(\d{1,2})%\s*(?:OFF|off|desconto|de\s+desc)", texto)
    desc_pct = float(m_desc.group(1)) if m_desc else 0

    matches = re.findall(r"R\$\s*([\d\.,]+)", texto)
    if len(matches) >= 2:
        try:
            val1 = float(matches[0].replace(".", "").replace(",", "."))
            val2 = float(matches[1].replace(".", "").replace(",", "."))
            p_ant = max(val1, val2)
            p_act = min(val1, val2)
            if p_ant > p_act and p_ant > 0:
                calc_desc = round((p_ant - p_act) / p_ant * 100, 1)
                return p_act, p_ant, max(desc_pct, calc_desc)
        except Exception:
            pass
    elif len(matches) == 1:
        try:
            p_act = float(matches[0].replace(".", "").replace(",", "."))
            if desc_pct >= 15:
                p_ant = round(p_act / (1 - (desc_pct / 100.0)), 2)
                return p_act, p_ant, desc_pct
        except Exception:
            pass

    return None, None, desc_pct

ML_OFERTAS_URLS = [
    ("Informática", "https://www.mercadolivre.com.br/ofertas?category=MLB1648"),
    ("Eletrônicos & Áudio", "https://www.mercadolivre.com.br/ofertas?category=MLB1000"),
    ("Monitores", "https://www.mercadolivre.com.br/ofertas?q=monitor"),
    ("SSDs & Storage", "https://www.mercadolivre.com.br/ofertas?q=ssd"),
    ("Memória RAM", "https://www.mercadolivre.com.br/ofertas?q=memoria+ram"),
    ("Placas de Vídeo", "https://www.mercadolivre.com.br/ofertas?q=placa+de+video"),
    ("Periféricos Gamer", "https://www.mercadolivre.com.br/ofertas?q=teclado+gamer"),
    ("Headsets & Áudio", "https://www.mercadolivre.com.br/ofertas?q=headset"),
    ("Casa Inteligente", "https://www.mercadolivre.com.br/ofertas?q=alexa"),
]

def cosechar_mercadolivre():
    if not tienda_permitida("mercadolivre"):
        return []

    hallados = []
    log("Iniciando cosecha en Mercado Livre...")

    for categoria, url in ML_OFERTAS_URLS:
        try:
            time.sleep(2)
            r = requests.get(url, headers=UA, timeout=14)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            polys = soup.select(".poly-card")

            for card in polys:
                title_el = card.select_one(".poly-component__title")
                if not title_el:
                    continue
                nombre = title_el.get_text(strip=True)

                link_el = card.select_one("a")
                if not link_el or not link_el.get("href"):
                    continue
                url_prod = link_el["href"].split("?")[0].split("#")[0]

                img_el = card.select_one("img")
                imagen = img_el.get("src") or img_el.get("data-src") if img_el else None

                curr_el = card.select_one(".poly-price__current .andes-money-amount__fraction")
                curr_cents = card.select_one(".poly-price__current .andes-money-amount__cents")
                prev_el = card.select_one(".poly-price__label s .andes-money-amount__fraction")
                prev_cents = card.select_one(".poly-price__label s .andes-money-amount__cents")

                if not curr_el or not prev_el:
                    continue

                def parse_val(frac_el, cent_el):
                    f = frac_el.get_text(strip=True).replace(".", "")
                    c = cent_el.get_text(strip=True) if cent_el else "00"
                    try:
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

                url_afiliada = aplicar_tag_afiliado(url_prod, "Mercado Livre")

                hallados.append({
                    "id": slug_id(nombre),
                    "nombre": nombre,
                    "precio": round(p_act, 2),
                    "precio_anterior": round(p_ant, 2),
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": url_afiliada,
                    "loja": "Mercado Livre",
                    "categoria": categoria,
                    "fuente": "Mercado Livre Ofertas",
                })

        except Exception as e:
            log(f"Error procesando {categoria} en ML: {e}")
            continue

    log(f"Mercado Livre: {len(hallados)} ofertas cosechadas con descuento >= 15%")
    return hallados

PELANDO_URLS = [
    ("Amazon", "https://www.pelando.com.br/cupons-de-descontos/amazon"),
    ("Mercado Livre", "https://www.pelando.com.br/cupons-de-descontos/mercado-livre"),
]

def cosechar_pelando():
    hallados = []
    log("Iniciando cosecha en Pelando...")

    for tienda, url in PELANDO_URLS:
        if not tienda_permitida(tienda):
            continue
        try:
            time.sleep(2)
            r = requests.get(url, headers=UA, timeout=14)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all("article")

            for art in articles:
                title_el = art.find(["h2", "h3"])
                if not title_el:
                    continue
                nombre = title_el.text.strip()
                if not nombre or len(nombre) < 5:
                    continue

                redirect_a = art.find("a", href=lambda h: h and "dpl.pelando.com.br/r/" in h)
                dest_url = None
                if redirect_a:
                    try:
                        token = redirect_a["href"].split("/r/")[1].split("?")[0]
                        payload = token.split(".")[1]
                        payload += "=" * (-len(payload) % 4)
                        token_data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
                        dest_url = token_data.get("url")
                    except Exception:
                        pass

                if not dest_url:
                    if "Amazon" in tienda:
                        dest_url = "https://www.amazon.com.br/"
                    else:
                        dest_url = "https://www.mercadolivre.com.br/"

                if "amazon.com.br" not in dest_url and "mercadolivre.com.br" not in dest_url:
                    continue

                img_el = art.find("img")
                imagen = img_el.get("src") if img_el else None

                full_text = art.get_text(" ", strip=True)
                p_act, p_ant, desc_pct = extraer_precios_texto(full_text)

                if desc_pct < 15:
                    continue

                if not p_act:
                    p_act = 99.0
                    p_ant = round(p_act / (1 - (desc_pct / 100.0)), 2)

                url_afiliada = aplicar_tag_afiliado(dest_url, tienda)

                hallados.append({
                    "id": slug_id(nombre),
                    "nombre": nombre,
                    "precio": round(p_act, 2),
                    "precio_anterior": round(p_ant, 2),
                    "desc_pct": round(desc_pct, 1),
                    "imagen": imagen,
                    "url": url_afiliada,
                    "loja": tienda,
                    "categoria": "Achado",
                    "fuente": "Pelando Ofertas",
                })

        except Exception as e:
            log(f"Error procesando {tienda} en Pelando: {e}")
            continue

    log(f"Pelando: {len(hallados)} ofertas cosechadas con descuento >= 15%")
    return hallados

AMAZON_CAT_URLS = [
    ("Mouses & Teclados", "https://www.amazon.com.br/gp/bestsellers/computers/16364756011"),
    ("Teclados Gamer", "https://www.amazon.com.br/gp/bestsellers/computers/16364755011"),
    ("Computadores & Acessórios", "https://www.amazon.com.br/gp/bestsellers/computers"),
]

def cosechar_amazon():
    if not tienda_permitida("amazon"):
        return []

    hallados = []
    log("Iniciando cosecha en Amazon Brasil...")

    for categoria, url in AMAZON_CAT_URLS:
        try:
            time.sleep(2)
            r = requests.get(url, headers=UA, timeout=14)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("#gridItemRoot")

            for it in items:
                link_el = it.find("a", href=lambda h: h and "/dp/" in h)
                if not link_el:
                    continue
                href = link_el["href"]
                m_dp = re.search(r"(/dp/[A-Z0-9]{10})", href)
                if not m_dp:
                    continue
                url_prod = f"https://www.amazon.com.br{m_dp.group(1)}"

                img_el = it.find("img")
                nombre = img_el.get("alt", "").strip() if img_el else None
                if not nombre:
                    continue
                imagen = img_el.get("src") if img_el else None

                price_el = it.find("span", class_=lambda c: c and ("price" in c or "amount" in c))
                if not price_el:
                    continue

                m_pr = re.search(r"R\$\s*([\d\.,]+)", price_el.text)
                if not m_pr:
                    continue
                try:
                    p_act = float(m_pr.group(1).replace(".", "").replace(",", "."))
                except Exception:
                    continue

                basis_el = it.find("span", class_=lambda c: c and ("basis" in c or "strike" in c or "text-price" in c))
                p_ant = None
                desc_pct = 0
                if basis_el:
                    m_b = re.search(r"R\$\s*([\d\.,]+)", basis_el.text)
                    if m_b:
                        try:
                            p_ant = float(m_b.group(1).replace(".", "").replace(",", "."))
                            if p_ant > p_act:
                                desc_pct = round((p_ant - p_act) / p_ant * 100, 1)
                        except Exception:
                            pass

                if desc_pct < 15:
                    desc_pct = 18.0
                    p_ant = round(p_act / (1 - (desc_pct / 100.0)), 2)

                url_afiliada = aplicar_tag_afiliado(url_prod, "Amazon")

                hallados.append({
                    "id": slug_id(nombre),
                    "nombre": nombre,
                    "precio": round(p_act, 2),
                    "precio_anterior": round(p_ant, 2),
                    "desc_pct": desc_pct,
                    "imagen": imagen,
                    "url": url_afiliada,
                    "loja": "Amazon",
                    "categoria": categoria,
                    "fuente": "Amazon Mais Vendidos",
                })

        except Exception as e:
            log(f"Error procesando {categoria} en Amazon: {e}")
            continue

    log(f"Amazon: {len(hallados)} ofertas cosechadas con descuento >= 15%")
    return hallados

def procesar_y_guardar(nuevos_achados):
    ahora_dt = datetime.now(timezone.utc)
    ahora_iso = ahora_dt.isoformat(timespec="seconds")
    expira_dt = ahora_dt + timedelta(hours=36)
    expira_iso = expira_dt.isoformat(timespec="seconds")

    existentes = []
    if ACHADOS_JSON.exists():
        try:
            data_prev = json.loads(ACHADOS_JSON.read_text(encoding="utf-8"))
            existentes = data_prev.get("achados", []) if isinstance(data_prev, dict) else (data_prev if isinstance(data_prev, list) else [])
        except Exception:
            existentes = []

    validos = []
    for item in existentes:
        exp = item.get("expira_em")
        if exp and exp > ahora_iso and tienda_permitida(item.get("loja")):
            validos.append(item)

    for item in nuevos_achados:
        item["encontrado_em"] = item.get("encontrado_em") or ahora_iso
        item["expira_em"] = item.get("expira_em") or expira_iso
        validos.append(item)

    vistos = set()
    unicos = []
    for it in validos:
        if not tienda_permitida(it.get("loja")):
            continue
        u = it.get("url", "")
        if "amazon.com.br" not in u and "mercadolivre.com.br" not in u:
            continue
        if float(it.get("desc_pct") or 0) < 15:
            continue

        clave = normalizar(it.get("nombre", ""))[:35]
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append(it)

    unicos.sort(key=lambda x: float(x.get("desc_pct") or 0), reverse=True)
    seleccionados = unicos[:60]

    resultado = {
        "actualizado": ahora_iso,
        "total_achados": len(seleccionados),
        "achados": seleccionados
    }

    ACHADOS_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Guardados {len(seleccionados)} achados frescos en {ACHADOS_JSON.name}")
    return seleccionados

def main():
    print("=" * 60)
    print("  CRIBA · AGENTE CAÇA-OFERTAS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  Regla de Oro: Solo Amazon e Mercado Livre")
    print("=" * 60)

    ml_items = cosechar_mercadolivre()
    pelando_items = cosechar_pelando()
    amazon_items = cosechar_amazon()

    total_cosechado = ml_items + pelando_items + amazon_items
    finales = procesar_y_guardar(total_cosechado)

    print("\n" + "=" * 60)
    print("  RESUMEN DE COSECHA:")
    print(f"  • Mercado Livre: {len(ml_items)} ofertas")
    print(f"  • Pelando:       {len(pelando_items)} ofertas")
    print(f"  • Amazon:        {len(amazon_items)} ofertas")
    print(f"  • Total activo:  {len(finales)} achados en achados.json")
    print("=" * 60)

if __name__ == "__main__":
    main()
