#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Radar de Cupons - Pelando.com.br
Scraping automático de cupons activos por tienda.
Guarda resultado en cupones.json (formato compatible con bot_precios.py).

Uso: python cupones_pelando.py
"""
import json, re, time, sys, io
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE    = Path(__file__).parent
SALIDA  = BASE / "cupones.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Tiendas a rastrear en Pelando + sus links de afiliado del proyecto
TIENDAS_PELANDO = [
    {"slug": "amazon",       "nome": "Amazon",        "afiliado": "https://www.amazon.com.br/?tag=criba20-20"},
    {"slug": "kabum",        "nome": "KaBuM!",        "afiliado": "https://www.kabum.com.br/"},
    {"slug": "mercado-livre","nome": "Mercado Livre",  "afiliado": "https://www.mercadolivre.com.br/"},
    {"slug": "shopee",       "nome": "Shopee",         "afiliado": "https://shopee.com.br/"},
    {"slug": "magalu",       "nome": "Magazine Luiza", "afiliado": "https://www.magazineluiza.com.br/"},
    {"slug": "aliexpress",   "nome": "AliExpress",     "afiliado": "https://www.aliexpress.com/"},
    {"slug": "pichau",       "nome": "Pichau",         "afiliado": "https://www.pichau.com.br/"},
    {"slug": "terabyte",     "nome": "Terabyte Shop",  "afiliado": "https://www.terabyteshop.com.br/"},
]

# Patron para extraer codigos de cupom del texto HTML
PATTERN_CODIGO = re.compile(
    r"\b([A-Z]{2,}[0-9]{1,}[A-Z0-9]{0,20}|"
    r"[A-Z0-9]{4,6}[A-Z]{2,}[0-9A-Z]{0,10}|"
    r"PRIME[A-Z0-9]{0,10}|"
    r"[A-Z]{3,}OFF[0-9]{0,3})\b"
)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_DIR / "ejecucion.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [PELANDO] {msg}\n")
    except Exception:
        pass
    print(f"  [Pelando] {msg}")


def fetch(url, reintentos=2):
    """GET con reintentos."""
    for intento in range(1, reintentos + 2):
        try:
            r = requests.get(url, headers=UA, timeout=18)
            if r.status_code == 200:
                return r
            if intento <= reintentos:
                time.sleep(2)
        except Exception as e:
            if intento <= reintentos:
                time.sleep(2)
            else:
                log(f"Error al acceder {url}: {e}")
    return None


def extraer_expiracion(descripcion):
    """Extrae fecha de expiración de la descripción si aparece la frase 'Expira em'."""
    if not descripcion:
        return None
    m = re.search(r"[Ee]xpira\s+em[:\s]+([^\n\.]{5,40})", descripcion)
    if m:
        return m.group(1).strip()
    # Buscar patron de fecha dd/mm/yyyy
    m2 = re.search(r"\d{1,2}/\d{2}/\d{4}", descripcion)
    if m2:
        return m2.group(0)
    return None


def extraer_desconto(titulo, descripcion):
    """Extrae el porcentaje o valor de descuento del título."""
    texto = titulo + " " + (descripcion or "")
    m = re.search(r"(\d+)%\s*(?:OFF|off|desconto|de\s+desc)", texto)
    if m:
        return f"{m.group(1)}% OFF"
    m2 = re.search(r"R\$\s*(\d+[\.,]?\d*)\s*(?:OFF|desconto|de\s+desc|off)", texto)
    if m2:
        return f"R$ {m2.group(1)} OFF"
    m3 = re.search(r"(?:Economize|economize|desconto\s+de)\s+R\$\s*(\d+[\.,]?\d*)", texto)
    if m3:
        return f"R$ {m3.group(1)} OFF"
    return None


def extraer_codigos_pagina(html_text):
    """Encuentra códigos de cupón en el texto completo de la página."""
    encontrados = set(PATTERN_CODIGO.findall(html_text))
    # Filtrar falsos positivos comuns
    falsos = {"OFF", "KG", "ML", "GB", "TB", "CPU", "RAM", "SSD", "HDD", "USB",
               "HDMI", "RGB", "FPS", "GHz", "AMD", "GTX", "RTX", "DDR", "PCIe",
               "OEM", "LED", "LCD", "IPS", "UHD", "FHD", "HDR", "BR", "SA"}
    return {c for c in encontrados if c not in falsos and len(c) >= 5}


def scrape_tienda(slug, nome):
    """Scraping de uma tienda en Pelando. Retorna lista de cupons."""
    url = f"https://www.pelando.com.br/cupons-de-descontos/{slug}"
    log(f"Scraping {nome} ({url})")

    r = fetch(url)
    if r is None:
        log(f"  Falha ao acessar {nome}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Extraer codigos de cupom visibles en el HTML
    codigos_pagina = extraer_codigos_pagina(r.text)

    # Extraer Offers del JSON-LD (fuente mas confiable)
    jsonld_tag = soup.find("script", type="application/ld+json")
    if not jsonld_tag or not jsonld_tag.string:
        log(f"  Sin JSON-LD para {nome}")
        return []

    try:
        jsonld = json.loads(jsonld_tag.string)
    except json.JSONDecodeError:
        log(f"  JSON-LD inválido para {nome}")
        return []

    graph = jsonld.get("@graph", [])
    offers_raw = [g for g in graph if g.get("@type") == "Offer"]

    if not offers_raw:
        log(f"  Sin offers en JSON-LD para {nome}")
        return []

    cupons = []
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for offer in offers_raw:
        titulo = offer.get("name", "").strip()
        desc   = offer.get("description", "").strip()
        url_c  = offer.get("url", "")
        avail  = offer.get("availability", "")

        # Solo ofertas InStock (disponibles)
        if "InStock" not in avail:
            continue

        if not titulo:
            continue

        desconto  = extraer_desconto(titulo, desc)
        expiracao = extraer_expiracion(desc)

        # Intentar asignar código: buscar en la descripción directamente
        codigo = None
        # Primero buscar en la descripcion del offer
        codigos_desc = set(PATTERN_CODIGO.findall(desc)) if desc else set()
        falsos = {"OFF", "KG", "ML", "GB", "TB", "CPU", "RAM", "SSD", "HDD",
                  "USB", "HDMI", "RGB", "FPS", "GHz", "AMD", "GTX", "RTX",
                  "DDR", "PCIe", "OEM", "LED", "LCD", "IPS", "UHD", "FHD",
                  "HDR", "BR", "SA", "PIX", "TED", "DOC", "CEP", "CPF", "CEP"}
        codigos_desc = {c for c in codigos_desc if c not in falsos and len(c) >= 5}
        if codigos_desc:
            codigo = sorted(codigos_desc, key=len, reverse=True)[0]
        elif codigos_pagina:
            # Usar primer codigo de la pagina como candidato
            codigo = sorted(codigos_pagina, key=len, reverse=True)[0]

        cupons.append({
            "tienda":          nome,
            "titulo":          titulo,
            "codigo":          codigo,
            "desconto":        desconto,
            "url":             url_c,
            "data_expiracao":  expiracao,
            "categoria":       "Geral",
            "fonte":           "Pelando",
            "vigente":         True,
            "hasta":           "9999-12-31",  # campo compatible con bot_precios.py
            "valor":           0,             # campo compatible con bot_precios.py
            "capturado_em":    ahora,
        })

    log(f"  {len(cupons)} cupons encontrados en {nome}")
    return cupons


def scrape_todas_tiendas():
    """Hace scraping de todas las tiendas configuradas."""
    todos = []
    vistos = set()  # Deduplicar por (tienda + titulo)

    for tienda in TIENDAS_PELANDO:
        cupons = scrape_tienda(tienda["slug"], tienda["nome"])
        for c in cupons:
            clave = f"{c['tienda']}|{c['titulo'][:60]}"
            if clave not in vistos:
                vistos.add(clave)
                c["url_afiliado"] = tienda["afiliado"]
                todos.append(c)
        time.sleep(2)  # rate limiting entre tiendas

    return todos


def cargar_cupones_existentes():
    """Carga cupones manuales ya existentes en cupones.json."""
    if not SALIDA.exists():
        return []
    try:
        data = json.loads(SALIDA.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return data.get("cupones", [])
    except Exception:
        return []


def ejecutar():
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print("=" * 55)
    print("  CRIBA · RADAR DE CUPONS — Pelando.com.br")
    print(f"  {ahora}")
    print(f"  {len(TIENDAS_PELANDO)} tiendas a rastrear")
    print("=" * 55)

    # Scraping Pelando
    nuevos = scrape_todas_tiendas()

    # Cargar cupones manuales preexistentes (los que tienen 'fonte' != 'Pelando')
    existentes = [c for c in cargar_cupones_existentes() if c.get("fonte") != "Pelando"]

    # Unificar: manuales + nuevos de Pelando
    todos = existentes + nuevos

    # Guardar
    salida = {
        "actualizado": ahora,
        "total": len(todos),
        "fuentes": ["Manual", "Pelando"],
        "cupones": todos,
    }
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 55)
    print(f"  {len(nuevos)} cupons de Pelando")
    print(f"  {len(existentes)} cupons manuales")
    print(f"  Total: {len(todos)} cupons en {SALIDA.name}")
    print("=" * 55)
    log(f"Completado: {len(nuevos)} Pelando + {len(existentes)} manuales = {len(todos)} total")


if __name__ == "__main__":
    ejecutar()
