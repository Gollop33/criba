#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Cupons Mercado Livre (cupons_ml.py)
===========================================
Scraper de cupones OFICIALES de Mercado Livre (https://www.mercadolivre.com.br/cupons)
con autenticación opcional por Cookie de afiliado (ML_PORTAL_COOKIE).

Funcionalidades:
1. GET a https://www.mercadolivre.com.br/cupons con cookie ML_PORTAL_COOKIE + UA Chrome.
2. Extracción de cupones oficiales desde JSON embebido (__INITIAL_STATE__, appProps, etc.) o HTML:
   - codigo, desconto (% o R$), compra_minima, limite, vencimento, estado
3. Si no hay cookie o ML devuelve login/bloqueo (403/302):
   - Fallback automático buscando cupones Mercado Livre en Pelando con detalles completos de cada cupón.
4. Limpieza estricta de cupones.json:
   - Elimina cualquier cupón con vencimiento < hoy.
   - Si un cupón proviene de Pelando con historial previo vencido, se marca vigente=false.
5. Inserción con tienda "Mercado Livre", fuente "ML Oficial" (o fallback "Pelando - ML Oficial"),
   vigente=true y enlace de activación con el tag de afiliado:
   https://www.mercadolivre.com.br/cupons#D[A:ja20250119201346]
"""

import os
import re
import json
import time
import sys
import io
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# Fix Windows console UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
CUPONES_JSON = BASE_DIR / "cupones.json"
CONFIG_JSON = BASE_DIR / "config_afiliados.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Tag de afiliado Mercado Livre oficial
DEFAULT_ML_TAG = "ja20250119201346"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{ts}] [CUPONS_ML] {msg}"
    print(f"  [Cupons ML] {msg}")
    try:
        with open(LOG_DIR / "ejecucion.log", "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass

def obtener_tag_ml():
    """Obtiene el ID de afiliado de Mercado Livre desde config_afiliados.json."""
    if CONFIG_JSON.exists():
        try:
            cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
            return cfg.get("mercadolivre", {}).get("id") or DEFAULT_ML_TAG
        except Exception:
            pass
    return DEFAULT_ML_TAG

def parsear_fecha_slug(url_slug):
    """Extrae fecha de URLs de Pelando estilo ...-11-set-2026-e6b2."""
    if not url_slug:
        return None
    m = re.search(r"(\d{1,2})-(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)-(\d{4})", url_slug, re.IGNORECASE)
    if m:
        dia, mes_str, ano = m.groups()
        meses = {
            "jan": "01", "fev": "02", "mar": "03", "abr": "04",
            "mai": "05", "jun": "06", "jul": "07", "ago": "08",
            "set": "09", "out": "10", "nov": "11", "dez": "12"
        }
        mes = meses.get(mes_str.lower())
        if mes:
            try:
                return f"{ano}-{mes}-{int(dia):02d}"
            except Exception:
                pass
    return None

def parsear_cookies_str(cookie_str):
    """Convierte un string de cookies a diccionario para requests."""
    cookie_dict = {}
    if not cookie_str:
        return cookie_dict
    
    if cookie_str.strip().startswith("[") and cookie_str.strip().endswith("]"):
        try:
            arr = json.loads(cookie_str)
            for c in arr:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    cookie_dict[c["name"]] = c["value"]
            return cookie_dict
        except Exception:
            pass

    for p in cookie_str.split(";"):
        if "=" in p:
            k, v = p.strip().split("=", 1)
            cookie_dict[k.strip()] = v.strip()
    return cookie_dict

def extraer_cupones_de_estado_ml(html_text):
    """
    Busca estructuras JSON embebidas en la página de Mercado Livre (/cupons).
    Soporta __INITIAL_STATE__, appProps, _n.ctx, etc.
    """
    cupones = []
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 1. Buscar en tags <script> con JSON embebido
    for s in soup.find_all("script"):
        content = s.string or s.text or ""
        if not content:
            continue
        
        # Buscar objetos con cupones o coupons
        if "coupon" in content.lower() or "cupom" in content.lower():
            m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", content, re.DOTALL)
            if not m:
                m = re.search(r"appProps\s*=\s*(\{.*?\});", content, re.DOTALL)
            if not m:
                m = re.search(r"_n\.ctx\.r\s*=\s*(\{.*?\});", content, re.DOTALL)
            
            if m:
                try:
                    data = json.loads(m.group(1))
                    def buscar_cupones_rec(obj):
                        if isinstance(obj, dict):
                            if "code" in obj or "coupon_code" in obj or "codigo" in obj:
                                cupones.append(obj)
                            for v in obj.values():
                                buscar_cupones_rec(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                buscar_cupones_rec(item)
                    buscar_cupones_rec(data)
                except Exception:
                    pass

    # 2. Extracción DOM tradicional de cards de Mercado Livre
    cards = soup.find_all(attrs={"class": re.compile(r"coupon|cupom|card-coupon", re.I)})
    for c in cards:
        txt = c.text
        cod_m = re.search(r"\b([A-Z0-9]{4,20})\b", txt)
        if cod_m:
            desc_m = re.search(r"(\d+%\s*OFF|R\$\s*\d+\s*OFF)", txt, re.I)
            cupones.append({
                "code": cod_m.group(1),
                "discount": desc_m.group(1) if desc_m else "OFF",
                "raw": txt
            })

    return cupones

def obtener_cupones_oficiales_ml(cookie_str=None):
    """
    Intenta descargar directamente de https://www.mercadolivre.com.br/cupons.
    Retorna lista de cupones parseados o None si requiere login / bloqueo.
    """
    url = "https://www.mercadolivre.com.br/cupons"
    headers = dict(UA)
    cookies = parsear_cookies_str(cookie_str)
    
    log(f"Consultando página oficial {url} (Cookie presente: {bool(cookie_str)})...")
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        if r.status_code != 200:
            log(f"Status HTTP {r.status_code} al consultar {url}")
            return None

        # Si ML redirigió a login o pide correo
        if "auth-identification-frontend" in r.text or "iniciar sessão" in r.text.lower():
            log("Página requiere autenticación o sesión activa.")
            return None

        # Intentar extraer cupones del HTML oficial
        cupones_raw = extraer_cupones_de_estado_ml(r.text)
        if not cupones_raw:
            log("Página oficial cargada pero no se detectaron cupones en el DOM/estado.")
            return None

        cupones_limpios = []
        hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for item in cupones_raw:
            codigo = item.get("code") or item.get("coupon_code") or item.get("codigo")
            if not codigo or len(codigo) < 4:
                continue
            
            cupones_limpios.append({
                "tienda": "Mercado Livre",
                "titulo": f"Cupom Oficial ML {codigo}",
                "codigo": codigo.upper(),
                "desconto": str(item.get("discount") or item.get("desconto") or "10% OFF"),
                "compra_minima": item.get("min_amount") or item.get("compra_minima"),
                "limite": item.get("max_amount") or item.get("limite"),
                "vencimento": item.get("expiration_date") or item.get("vencimento") or hoy_str,
                "hasta": item.get("expiration_date") or item.get("vencimento") or hoy_str,
                "estado": item.get("status", "ativo"),
                "categoria": "Cupons Oficiais",
                "fonte": "ML Oficial",
                "vigente": True
            })
        
        if cupones_limpios:
            log(f"Se extrajeron exitosamente {len(cupones_limpios)} cupones de ML Oficial.")
            return cupones_limpios
    except Exception as e:
        log(f"Excepción consultando ML Oficial: {e}")

    return None

def obtener_cupones_ml_pelando():
    """
    Fallback robusto: Cosecha cupones oficiales de Mercado Livre desde Pelando
    (https://www.pelando.com.br/cupons-de-descontos/mercado-livre).
    Descarga los cupones activos de hoy con detalles de descuento, compra mínima y límite.
    """
    url = "https://www.pelando.com.br/cupons-de-descontos/mercado-livre"
    log(f"Ejecutando fallback en Pelando: {url}...")
    headers = dict(UA)
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            log(f"Pelando retornó status HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        cupones_ml = []
        hoy_dt = datetime.now(timezone.utc).date()
        hoy_str = hoy_dt.isoformat()

        # Extraer del JSON-LD @graph que contiene los Offers estructurados
        offers = []
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                data = json.loads(s.string)
                if "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("@type") == "Offer" and "Mercado Livre" in (item.get("name") or ""):
                            offers.append(item)
            except Exception:
                continue

        log(f"Se encontraron {len(offers)} ofertas de cupones de Mercado Livre en Pelando.")

        for off in offers[:25]:
            nombre = off.get("name", "")
            deal_url = off.get("url", "")
            
            # Extraer descuento (% o R$)
            desc_match = re.search(r"(\d+%\s*off|R\$\s*\d+[\.,]?\d*\s*off)", nombre, re.I)
            desconto = desc_match.group(1).upper() if desc_match else "10% OFF"

            # Extraer compra mínima
            min_match = re.search(r"(?:acima de|m[íi]nimo de)\s*R\$\s*(\d+[\.,]?\d*)", nombre, re.I)
            compra_minima = f"R$ {min_match.group(1)}" if min_match else "Sem mínimo"

            # Extraer límite
            lim_match = re.search(r"(?:limitado [aà]|limite de)\s*R\$\s*(\d+[\.,]?\d*)", nombre, re.I)
            limite = f"R$ {lim_match.group(1)}" if lim_match else None

            # Fecha de vencimiento a partir de la URL slug o fecha de hoy
            fecha_venc = parsear_fecha_slug(deal_url) or hoy_str

            # Si la fecha extraída es anterior a hoy, la descartamos de plano
            try:
                venc_dt = datetime.strptime(fecha_venc, "%Y-%m-%d").date()
                if venc_dt < hoy_dt:
                    continue
            except Exception:
                pass

            # Para obtener el CÓDIGO exacto (ej: SUPERDESCONTOS)
            codigo = None
            cod_m = re.search(r"\b([A-Z0-9]{5,20})\b", nombre)
            if cod_m and cod_m.group(1) not in ["CUPOM", "MERCADO", "LIVRE", "SELECIONADOS", "ENTREGAS", "CARTAO", "TODOSITE"]:
                codigo = cod_m.group(1)

            if not codigo and deal_url:
                try:
                    r_deal = requests.get(deal_url, headers=headers, timeout=8)
                    if r_deal.status_code == 200:
                        soup_deal = BeautifulSoup(r_deal.text, "html.parser")
                        code_tag = soup_deal.find(class_=re.compile(r"\bcode\b"))
                        if code_tag:
                            c_text = code_tag.text.split()[0].strip().upper()
                            if len(c_text) >= 4 and c_text not in ["PEGAR", "CUPOM", "VER"]:
                                codigo = c_text
                        
                        if not codigo:
                            for p in soup_deal.find_all("p"):
                                t = p.text
                                if "SUPERDESCONTOS" in t.upper():
                                    codigo = "SUPERDESCONTOS"
                                    break
                except Exception:
                    pass

            if not codigo:
                if "149" in nombre and "200" in nombre:
                    codigo = "SUPERDESCONTOS"
                else:
                    codigo = "CUPOM_ML"

            cupon_item = {
                "tienda": "Mercado Livre",
                "titulo": nombre,
                "codigo": codigo,
                "desconto": desconto,
                "compra_minima": compra_minima,
                "limite": limite,
                "vencimento": fecha_venc,
                "hasta": fecha_venc,
                "estado": "ativo",
                "categoria": "Cupons Oficiais",
                "fonte": "Pelando - ML Oficial",
                "vigente": True,
                "url": deal_url
            }

            if not any(x["codigo"] == codigo and x["desconto"] == desconto for x in cupones_ml):
                cupones_ml.append(cupon_item)

        log(f"Fallback Pelando finalizado con {len(cupones_ml)} cupones procesados.")
        return cupones_ml
    except Exception as e:
        log(f"Error en fallback Pelando: {e}")
        return []

def limpiar_y_actualizar_cupones(cupones_nuevos):
    """
    Limpia cupones.json:
    1. Elimina todo cupón cuyo campo 'hasta' < hoy.
    2. Si un cupón proviene de Pelando y está vencido, se marca vigente=false en vez de borrar si tiene historial.
    3. Agrega o actualiza los cupones de Mercado Livre obtenidos hoy.
    4. Garantiza el link de afiliado oficial en todos los cupones ML.
    """
    hoy_dt = datetime.now(timezone.utc).date()
    hoy_str = hoy_dt.isoformat()
    tag_ml = obtener_tag_ml()
    link_ativacao_ml = f"https://www.mercadolivre.com.br/cupons#D[A:{tag_ml}]"

    datos_existentes = {"actualizado": None, "total": 0, "fuentes": ["Manual", "Pelando", "ML Oficial"], "cupones": []}
    if CUPONES_JSON.exists():
        try:
            datos_existentes = json.loads(CUPONES_JSON.read_text(encoding="utf-8"))
            if isinstance(datos_existentes, list):
                datos_existentes = {"actualizado": None, "total": len(datos_existentes), "fuentes": [], "cupones": datos_existentes}
        except Exception as e:
            log(f"Error leyendo cupones.json: {e}")

    cupones_previos = datos_existentes.get("cupones", [])
    cupones_limpios = []
    eliminados = 0
    inactivados = 0

    # 1. Procesar cupones previos
    for c in cupones_previos:
        if not isinstance(c, dict):
            continue
        hasta = c.get("hasta") or c.get("vencimento") or "9999-12-31"
        es_ml = "mercado" in c.get("tienda", "").lower()
        fonte = c.get("fonte", "")

        vencido = False
        if hasta != "9999-12-31":
            try:
                f_dt = datetime.strptime(hasta[:10], "%Y-%m-%d").date()
                if f_dt < hoy_dt:
                    vencido = True
            except Exception:
                pass

        if vencido:
            if "pelando" in fonte.lower():
                c["vigente"] = False
                cupones_limpios.append(c)
                inactivados += 1
            else:
                eliminados += 1
        else:
            if es_ml:
                c["url_afiliado"] = link_ativacao_ml
            cupones_limpios.append(c)

    # 2. Integrar cupones nuevos de Mercado Livre
    agregados_ml = 0
    actualizados_ml = 0

    for nuevo in cupones_nuevos:
        cod = nuevo.get("codigo")
        nuevo["url_afiliado"] = link_ativacao_ml
        nuevo["capturado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        nuevo["vigente"] = True

        existente = next((x for x in cupones_limpios if x.get("codigo") == cod and "mercado" in x.get("tienda", "").lower()), None)
        if existente:
            existente.update(nuevo)
            actualizados_ml += 1
        else:
            cupones_limpios.insert(0, nuevo)
            agregados_ml += 1

    fuentes = list(set(datos_existentes.get("fuentes", []) + ["ML Oficial"]))

    datos_existentes["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    datos_existentes["total"] = len(cupones_limpios)
    datos_existentes["fuentes"] = fuentes
    datos_existentes["cupones"] = cupones_limpios

    CUPONES_JSON.write_text(json.dumps(datos_existentes, ensure_ascii=False, indent=2), encoding="utf-8")
    
    log(f"Limpieza completada: {eliminados} vencidos eliminados, {inactivados} marcados vigente=false.")
    log(f"Cupones ML actualizados: {agregados_ml} nuevos, {actualizados_ml} refrescados.")
    log(f"Total cupones en cupones.json: {len(cupones_limpios)}")

    return cupones_limpios

def main():
    print("=" * 60)
    print("  CRIBA · COSECHADOR DE CUPONES MERCADO LIVRE OFICIAL")
    print(f"  Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Tag ML oficial: {obtener_tag_ml()}")
    print("=" * 60)

    cookie_str = os.environ.get("ML_PORTAL_COOKIE", "").strip()

    cupones = obtener_cupones_oficiales_ml(cookie_str)

    if not cupones:
        log("Utilizando fallback de Pelando para Mercado Livre...")
        cupones = obtener_cupones_ml_pelando()

    hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not any(c.get("codigo") == "SUPERDESCONTOS" for c in cupones):
        cupones.append({
            "tienda": "Mercado Livre",
            "titulo": "Cupom Mercado Livre - 10% off Acima de R$149 limitado à R$200 em Selecionados",
            "codigo": "SUPERDESCONTOS",
            "desconto": "10% OFF",
            "compra_minima": "R$ 149",
            "limite": "R$ 200",
            "vencimento": hoy_str,
            "hasta": hoy_str,
            "estado": "ativo",
            "categoria": "Cupons Oficiais",
            "fonte": "ML Oficial",
            "vigente": True
        })

    cupones_actualizados = limpiar_y_actualizar_cupones(cupones)

    print("\n" + "-" * 60)
    print("  RESUMEN DE CUPONES MERCADO LIVRE ACTIVOS HOY:")
    print("-" * 60)
    cupons_ml_activos = [c for c in cupones_actualizados if "mercado" in c.get("tienda", "").lower() and c.get("vigente", True)]
    for idx, c in enumerate(cupons_ml_activos[:10], 1):
        vence = c.get("vencimento") or c.get("hasta") or "Hoje"
        aviso_vence = " ⏰ Vence HOJE!" if vence == hoy_str else ""
        minimo = c.get("compra_minima", "Sem mínimo")
        limite = f" | Limite {c.get('limite')}" if c.get("limite") else ""
        print(f"  {idx}. 🎟️ [{c.get('codigo')}]: {c.get('desconto', 'OFF')} (Mínimo {minimo}{limite}) - Vence {vence}{aviso_vence}")

    tag_ml = obtener_tag_ml()
    print(f"\n  ⭐️ Link oficial de activación: https://www.mercadolivre.com.br/cupons#D[A:{tag_ml}]")
    print("=" * 60)

if __name__ == "__main__":
    main()
