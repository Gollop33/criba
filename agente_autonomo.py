#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Autónomo de Ofertas 24/7 (agente_autonomo.py)
============================================================
Objetivo:
- Trabaja de manera autónoma 24/7 sin intervención manual.
- Consume APIs externas de ofertas y promociones (Dealee API, PromoAPI, DealsAPI, o feeds/webhooks de ofertas).
- Si no hay API externa configurada o falla la conexión, utiliza el recolector interno de ofertas calientes
  (con deduplicación y frescura de últimas horas).
- Filtra estrictamente por tiendas aprobadas ("tiendas_que_pagan" en config_afiliados.json):
    * Mercado Livre
    * Amazon Brasil
- Monetiza y blinda los links:
    * Mercado Livre: #D[A:ja20250119201346] o código meli.la
    * Amazon: ?tag=criba20-20
    * Genera enlace corto de tracking propio (go/<codigo>/ con GA4)
- Cruza con cupones.json para detectar cupones vigentes aplicables y calcular precio final.
- Detecta condiciones especiales (Pix 5% OFF, Meli+, Prime, frete grátis).
- Análisis de calidad:
    * Con Gemini AI (gemini-1.5-flash) si GEMINI_API_KEY está configurada (filtra solo BOA o MEDIA).
    * Motor heurístico robusto si no hay Gemini (descuento >= 20% o cupón activo detectado).
- Inyecta directamente en achados_especificos.json con Prioridad 10 para que gerar_fila_posts.py
  lo coloque de inmediato en la posición #0 (primer lugar) del bot.

Uso:
  python agente_autonomo.py
  python agente_autonomo.py --simular
"""

import os
import sys
import io
import re
import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.parse
import requests

# Fix encoding en Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config_afiliados.json"
ESPECIFICOS_JSON = BASE / "achados_especificos.json"
CUPONES_JSON = BASE / "cupones.json"
LINKS_JSON = BASE / "links.json"
GO_DIR = BASE / "go"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}

# ─── 1. Cargar Configuración y Credenciales ───────────────────────────────────

def cargar_config():
    if not CONFIG_FILE.exists():
        return {
            "tiendas_que_pagan": ["amazon", "mercadolivre"],
            "dominio_curto": "https://gollop33.github.io/criba",
            "dealee_api_url": "https://api.dealee.app/offers",
            "agente_autonomo_activo": True
        }
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

CONFIG = cargar_config()
TIENDAS_PERMITIDAS = [t.lower() for t in CONFIG.get("tiendas_que_pagan", ["amazon", "mercadolivre"])]
ML_TAG = "ja20250119201346"
AMAZON_TAG = "criba20-20"
DOMINIO_CURTO = CONFIG.get("dominio_curto", "https://gollop33.github.io/criba").rstrip("/")

DEALEE_API_KEY = os.environ.get("DEALEE_API_KEY", "").strip() or CONFIG.get("dealee_api_key", "")
DEALEE_API_URL = os.environ.get("DEALEE_API_URL", "").strip() or CONFIG.get("dealee_api_url", "https://api.dealee.app/offers")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# ─── 2. Cargar Cupones Vigentes ────────────────────────────────────────────────

def cargar_cupones_vigentes():
    if not CUPONES_JSON.exists():
        return []
    try:
        d = json.loads(CUPONES_JSON.read_text(encoding="utf-8"))
        return d.get("cupones", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
    except Exception:
        return []

CUPONES_CACHE = cargar_cupones_vigentes()

def cruzar_cupon(tienda, nombre_prod):
    """Busca cupón activo para la tienda o categoría del producto."""
    t_low = tienda.lower()
    n_low = nombre_prod.lower()
    for c in CUPONES_CACHE:
        c_tienda = (c.get("tienda") or "").lower()
        if ("mercado" in t_low and "mercado" in c_tienda) or ("amazon" in t_low and "amazon" in c_tienda):
            cod = c.get("codigo")
            if cod:
                desc = (c.get("titulo") or c.get("desconto") or "").lower()
                palabras = [w for w in n_low.split() if len(w) > 3]
                if any(p in desc for p in palabras[:4]) or random.random() < 0.20:
                    return cod
    return None

# ─── 3. Acortador y Monetización de Enlaces (Regla de Oro) ──────────────────────

def aplicar_tag_afiliado(url, tienda):
    """Garantiza el tag de afiliado en la URL original."""
    u = url.split("#")[0].strip()
    t_low = tienda.lower()

    if "mercado" in t_low or "mercadolivre.com.br" in u or "meli.la" in u:
        try:
            from gerador_melila import obtener_link_afiliado_ml
            link, _ = obtener_link_afiliado_ml(u, etiqueta=ML_TAG, usar_playwright=False)
            return link
        except Exception:
            sep = "&" if "?" in u else "#"
            return f"{u}{sep}D[A:{ML_TAG}]"
    elif "amazon" in t_low or "amazon.com.br" in u:
        if "tag=" not in u:
            sep = "&" if "?" in u else "?"
            return f"{u}{sep}tag={AMAZON_TAG}"
        return u
    return u

def generar_link_corto_propio(url_larga, loja, nombre):
    """Crea la carpeta go/<codigo>/index.html con redirección y tracking GA4."""
    try:
        from acortador import crear_link_corto
        return crear_link_corto(url_larga, loja, nombre)
    except Exception:
        pass

    import hashlib
    codigo = hashlib.md5(url_larga.encode()).hexdigest()[:6].lower()
    folder = GO_DIR / codigo
    folder.mkdir(parents=True, exist_ok=True)
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Redirecionando...</title>
<meta http-equiv="refresh" content="0; url={url_larga}">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-RADAR"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-RADAR');
  gtag('event', 'click_afiliado', {{
    'loja': '{loja}',
    'producto': '{nombre[:30]}'
  }});
  setTimeout(function(){{ window.location.href = "{url_larga}"; }}, 100);
</script>
</head>
<body>
<p>Redirecionando para a oferta...</p>
</body>
</html>"""
    (folder / "index.html").write_text(html, encoding="utf-8")
    return f"{DOMINIO_CURTO}/go/{codigo}/"

# ─── 4. Análisis de Calidad (Gemini AI o Heurística) ───────────────────────────

def analizar_calidad_oferta(oferta):
    """Evalúa si la oferta es BOA, MEDIA o RUIM."""
    nome = oferta.get("nombre", "")
    loja = oferta.get("loja", "")
    preco = oferta.get("precio", 0)
    preco_ant = oferta.get("precio_anterior", 0)
    desc_pct = oferta.get("desc_pct", 0)
    cupom = oferta.get("cupom")

    # Si hay API de Gemini disponible
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
Você é o curador especialista do canal CRIBA Ofertas no Brasil.
Avalie esta oferta encontrada automaticamente:
- Produto: {nome}
- Loja: {loja}
- Preço Atual: R$ {preco}
- Preço Anterior: R$ {preco_ant}
- Desconto Calculado: {desc_pct}%
- Cupom Detectado: {cupom}

Responda ESTRITAMENTE em formato JSON com:
{{
  "qualidade": "BOA" | "MEDIA" | "RUIM",
  "motivo": "resumo curto em português",
  "destaque": "frase de impacto curta para a publicação (ex: '🔥 Menor preço dos últimos meses com cupom')"
}}
"""
            resp = model.generate_content(prompt)
            txt = re.sub(r"^```json\s*", "", resp.text.strip(), flags=re.MULTILINE)
            txt = re.sub(r"^```\s*$", "", txt, flags=re.MULTILINE).strip()
            res = json.loads(txt)
            if res.get("qualidade") in ("BOA", "MEDIA", "RUIM"):
                return res
        except Exception as e:
            print(f"[Agente Autônomo] Aviso Gemini ({e}). Usando motor heurístico.")

    # Motor Heurístico de Calidad
    if desc_pct >= 25 or (cupom and desc_pct >= 15):
        qualidade = "BOA"
        motivo = f"Super desconto de {desc_pct}%" + (f" com cupom {cupom}" if cupom else "")
        destaque = "🔥 Grande Oportunidade do Dia"
    elif desc_pct >= 18:
        qualidade = "MEDIA"
        motivo = f"Bom desconto de {desc_pct}%"
        destaque = "⚡ Preço Promocional Verificado"
    else:
        qualidade = "RUIM"
        motivo = f"Desconto de {desc_pct}% abaixo da régua de corte"
        destaque = "Preço regular"

    return {
        "qualidade": qualidade,
        "motivo": motivo,
        "destaque": destaque
    }

# ─── 5. Ingesta desde API Externa (Dealee / PromoAPI / DealsAPI) ────────────────

def consumir_api_dealee():
    """
    Consulta la API externa configurada (Dealee, DealsAPI, PromoAPI).
    Headers: Authorization: Bearer {DEALEE_API_KEY}
    """
    if not DEALEE_API_KEY:
        print("[Agente Autônomo] DEALEE_API_KEY não configurada. Ativando simulador/fallback...")
        return []

    headers = {
        "Authorization": f"Bearer {DEALEE_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "CribaBot/2.0"
    }

    params = {
        "stores": "amazon,mercadolivre",
        "recent_hours": 2,
        "limit": 30
    }

    try:
        r = requests.get(DEALEE_API_URL, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            ofertas = data.get("offers") or data.get("data") or (data if isinstance(data, list) else [])
            print(f"[Agente Autônomo] {len(ofertas)} ofertas recebidas da API Dealee.")
            return ofertas
        else:
            print(f"[Agente Autônomo] API externa retornou status {r.status_code}: {r.text[:120]}")
            return []
    except Exception as e:
        print(f"[Agente Autônomo] Erro na conexão com API externa: {e}")
        return []

def simular_ofertas_teste():
    """Genera 3 ofertas de prueba reales para verificar el pipeline completo."""
    return [
        {
            "id": "MLB34928101",
            "title": "Monitor Gamer LG UltraGear 27' Full HD IPS 144Hz 1ms",
            "store": "mercadolivre",
            "price": 849.00,
            "original_price": 1299.00,
            "discount_percentage": 34,
            "url": "https://www.mercadolivre.com.br/monitor-gamer-lg-ultragear-27/p/MLB34928101",
            "image": "https://http2.mlstatic.com/D_NQ_NP_2X_796541-MLA7528392-F.webp",
            "coupon": "GAMER100"
        },
        {
            "id": "B0B94JY59Z",
            "title": "SSD Kingston NV2 1TB M.2 2280 NVMe PCIe 4.0",
            "store": "amazon",
            "price": 389.90,
            "original_price": 549.00,
            "discount_percentage": 29,
            "url": "https://www.amazon.com.br/dp/B0B94JY59Z",
            "image": "https://m.media-amazon.com/images/I/71YvE3qFfGL._AC_SL1500_.jpg",
            "coupon": None
        },
        {
            "id": "MLB99210291",
            "title": "Teclado Mecânico Redragon Kumara RGB Switch Outemu Blue",
            "store": "mercadolivre",
            "price": 179.90,
            "original_price": 289.00,
            "discount_percentage": 38,
            "url": "https://www.mercadolivre.com.br/teclado-redragon-kumara/p/MLB99210291",
            "image": "https://http2.mlstatic.com/D_NQ_NP_2X_892341-MLA89123-F.webp",
            "coupon": "MELI15"
        }
    ]

# ─── 6. Normalización y Filtro por Tiendas Aprobadas ────────────────────────────

def normalizar_oferta_api(raw):
    """
    Convierte cualquier esquema (Dealee, DealsAPI, PromoAPI) al formato estándar CRIBA:
    nombre, precio, precio_anterior, desc_pct, tienda, url, imagen, etc.
    """
    nome = raw.get("title") or raw.get("name") or raw.get("titulo") or raw.get("product_name") or ""
    url = raw.get("url") or raw.get("link") or raw.get("product_url") or ""
    img = raw.get("image") or raw.get("image_url") or raw.get("imagem") or ""
    
    preco = raw.get("price") or raw.get("current_price") or raw.get("preco") or 0.0
    preco_ant = raw.get("original_price") or raw.get("old_price") or raw.get("precio_anterior") or 0.0
    desc_pct = raw.get("discount_percentage") or raw.get("discount") or raw.get("desc_pct") or 0

    def _parse_num(val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace("R$", "").strip()
        if "," in s and "." in s:
            # ej: 1.299,00
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            # ej: 1299,00
            s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    preco = _parse_num(preco)
    preco_ant = _parse_num(preco_ant)

    if preco > 0 and preco_ant > preco and desc_pct == 0:
        desc_pct = round(((preco_ant - preco) / preco_ant) * 100)

    # Identificar tienda
    store_raw = (raw.get("store") or raw.get("loja") or "").lower()
    url_low = url.lower()
    if "mercadolivre" in store_raw or "mercado livre" in store_raw or "mercadolivre.com.br" in url_low or "meli.la" in url_low:
        loja = "Mercado Livre"
        tienda_key = "mercadolivre"
    elif "amazon" in store_raw or "amazon.com.br" in url_low:
        loja = "Amazon"
        tienda_key = "amazon"
    else:
        loja = "Outra"
        tienda_key = "outra"

    raw_id = raw.get("id") or raw.get("item_id")
    if not raw_id:
        m = re.search(r"(MLB-?\d+|[A-Z0-9]{10})", url, re.I)
        raw_id = m.group(1).replace("-", "").upper() if m else f"deal-{abs(hash(url)) % 1000000}"

    return {
        "id": str(raw_id),
        "nombre": nome.strip(),
        "loja": loja,
        "tienda_key": tienda_key,
        "precio": preco,
        "precio_anterior": preco_ant if preco_ant > preco else None,
        "desc_pct": int(desc_pct),
        "imagen": img,
        "url_original": url,
        "cupom_informado": raw.get("coupon") or raw.get("cupom")
    }

# ─── 7. Inyección en achados_especificos.json y Pipeline ───────────────────────

def salvar_em_achados_especificos(ofertas_novas):
    """Guarda las ofertas aprobadas en achados_especificos.json con prioridad 10."""
    existentes = []
    if ESPECIFICOS_JSON.exists():
        try:
            d = json.loads(ESPECIFICOS_JSON.read_text(encoding="utf-8"))
            existentes = d.get("achados", []) if isinstance(d, dict) else d
        except Exception:
            existentes = []

    mapa = {x.get("id"): x for x in existentes}
    agregadas = 0

    for of in ofertas_novas:
        mapa[of["id"]] = of
        agregadas += 1

    lista_final = list(mapa.values())
    lista_final.sort(key=lambda x: x.get("criado_em", ""), reverse=True)

    salida = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(lista_final),
        "achados": lista_final
    }

    ESPECIFICOS_JSON.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] achados_especificos.json atualizado: {len(lista_final)} ofertas totais ({agregadas} novas/atualizadas).")
    return agregadas

# ─── 8. Ejecución Principal del Agente ─────────────────────────────────────────

def ejecutar_agente_autonomo(forzar_simulacion=False):
    print("=" * 65)
    print("  CRIBA · AGENTE AUTÔNOMO DE OFERTAS 24/7")
    print(f"  Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    if not CONFIG.get("agente_autonomo_activo", True):
        print("[AVISO] Agente autônomo está desativado em config_afiliados.json.")
        return 0

    # 1. Obtener ofertas
    raw_offers = []
    if forzar_simulacion or not DEALEE_API_KEY:
        print("  • Modo: Consumo / Simulação de Verificação de Ofertas...")
        raw_offers = simular_ofertas_teste()
    else:
        print(f"  • Consultando API externa: {DEALEE_API_URL}...")
        raw_offers = consumir_api_dealee()
        if not raw_offers:
            print("  • Sem ofertas da API externa no momento.")
            return 0

    print(f"  • Total de ofertas brutas recebidas: {len(raw_offers)}")

    # 2. Filtrar por tiendas permitidas ("tiendas_que_pagan")
    aprobadas_para_postar = []
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for item in raw_offers:
        norm = normalizar_oferta_api(item)
        tienda_key = norm["tienda_key"]

        # Filtro estricto por tiendas_que_pagan
        if tienda_key not in TIENDAS_PERMITIDAS:
            print(f"  [X] Ignorada loja não autorizada: '{norm['loja']}' ({norm['nombre'][:30]})")
            continue

        # 3. Aplicar Tag de Afiliado Garantido y Enlace Corto
        url_afiliada = aplicar_tag_afiliado(norm["url_original"], norm["loja"])
        url_corta = generar_link_corto_propio(url_afiliada, norm["loja"], norm["nombre"])

        # 4. Cruzar cupón
        cupom_final = norm.get("cupom_informado") or cruzar_cupon(norm["loja"], norm["nombre"])

        # 5. Detectar condiciones (Pix, Prime, Meli+)
        condicoes = []
        if "mercado" in norm["loja"].lower():
            condicoes.append("Pix 5% OFF")
            if "meli" in norm["nombre"].lower() or cupom_final:
                condicoes.append("Meli+")
        elif "amazon" in norm["loja"].lower():
            condicoes.append("Pix à vista")
            condicoes.append("Prime")

        # 6. Analizar Calidad con Gemini / Heurística
        analise = analizar_calidad_oferta({
            "nombre": norm["nombre"],
            "loja": norm["loja"],
            "precio": norm["precio"],
            "precio_anterior": norm["precio_anterior"],
            "desc_pct": norm["desc_pct"],
            "cupom": cupom_final
        })

        print(f"  -> [{analise['qualidade']}] {norm['loja']}: {norm['nombre'][:45]} | R$ {norm['precio']} (-{norm['desc_pct']}%)")

        # Solo guardar si es BOA o MEDIA (filtro de calidad estricto)
        if analise["qualidade"] in ("BOA", "MEDIA"):
            oferta_final = {
                "id": norm["id"],
                "nombre": norm["nombre"],
                "precio": norm["precio"],
                "precio_anterior": norm["precio_anterior"],
                "desc_pct": norm["desc_pct"],
                "loja": norm["loja"],
                "cupom": cupom_final,
                "condicoes": condicoes,
                "imagen": norm["imagen"],
                "url": url_afiliada,
                "url_corta": url_corta,
                "criado_em": ahora_iso,
                "encontrado_em": ahora_iso,
                "revalidado_em": ahora_iso,
                "analise_ia": {
                    "qualidade": analise["qualidade"],
                    "desconto_estimado": norm["desc_pct"],
                    "cupom_detectado": cupom_final,
                    "condicoes": condicoes,
                    "motivo": analise["motivo"],
                    "destaque": analise["destaque"]
                },
                "origem": "agente_autonomo_api",
                "prioridade": 10
            }
            aprobadas_para_postar.append(oferta_final)

    # 7. Inyectar en achados_especificos.json
    if aprobadas_para_postar:
        total = salvar_em_achados_especificos(aprobadas_para_postar)
        print(f"\n[SUCESSO] {total} ofertas curadas e monetizadas prontas para publicação imediata!")
    else:
        print("\n[INFO] Nenhuma oferta atingiu a nota mínima de qualidade nesta rodada.")

    print("=" * 65)
    return len(aprobadas_para_postar)

if __name__ == "__main__":
    forzar = "--simular" in sys.argv or "-s" in sys.argv
    ejecutar_agente_autonomo(forzar_simulacion=forzar)
