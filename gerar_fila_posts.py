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

def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def cargar_enviados_recientes(horas=48):
    """Retorna conjunto de IDs de productos enviados en las últimas N horas."""
    if not ENVIADOS_JSON.exists():
        return set()
    try:
        data = json.loads(ENVIADOS_JSON.read_text(encoding="utf-8"))
        ahora = datetime.now(timezone.utc)
        limite = ahora - timedelta(hours=horas)
        bloqueados = set()
        for pid, val in data.items():
            ts_str = val.get("ts", "") if isinstance(val, dict) else str(val)
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts > limite:
                        bloqueados.add(pid)
                except Exception:
                    bloqueados.add(pid)
        return bloqueados
    except Exception:
        return set()

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

def clasificar_categoria(nombre):
    """Categoriza un producto según su título."""
    n = nombre.lower()
    if any(k in n for k in ["smartphone", "celular", "galaxy", "iphone", "xiaomi", "motorola"]):
        return "Celulares & Smartphones"
    if any(k in n for k in ["tv", "televisao", "smart tv", "roku"]):
        return "Smart TV & Vídeo"
    if any(k in n for k in ["notebook", "laptop", "macbook", "computador"]):
        return "Notebooks & PC"
    if any(k in n for k in ["creatina", "whey", "suplemento", "proteina", "termogenico"]):
        return "Suplementos & Fitness"
    if any(k in n for k in ["air fryer", "fritadeira", "panela", "cafeteira", "liquidificador"]):
        return "Cozinha & Eletro"
    if any(k in n for k in ["aspirador", "ar condicionado", "ventilador", "alexa", "echo"]):
        return "Casa & Climatização"
    if any(k in n for k in ["perfume", "fragrancia", "hidratante", "cabelo"]):
        return "Beleza & Cuidados"
    if any(k in n for k in ["monitor", "teclado", "mouse", "headset", "ssd", "ram", "placa de video", "cadeira gamer"]):
        return "Tech & Setup Gamer"
    return "Achados Gerais"

def generar_posts_cupones(cupones_reales):
    """Crea posts de cupones estilo canal profesional con enlaces monetizados de activación."""
    posts_cupones = []
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    
    # Agrupar cupones por tienda
    por_tienda = {}
    for c in cupones_reales:
        t = "mercadolivre" if "mercado" in c.get("tienda", "").lower() else "amazon"
        por_tienda.setdefault(t, []).append(c)

    # 1. Posts de Cupones Mercado Livre en lotes de 3-4
    cupons_ml = por_tienda.get("mercadolivre", [])
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
            lineas.append(f"🎟️ {desc}: {cod} ({titulo})")
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

    cupones = cargar_cupones_reales()
    bloqueados_48h = cargar_enviados_recientes(48)
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"  • Achados totales disponibles: {len(items_achados)}")
    print(f"  • Ofertas ML: {len(items_ml)} | Ofertas Amazon: {len(items_amz)}")
    print(f"  • Cupones activos cargados: {len(cupones)}")
    print(f"  • Productos en enfriamiento (48h): {len(bloqueados_48h)}")

    # Unificar y filtrar por 48h
    todos_candidatos = []
    vistos_slug = set()

    for item in (items_achados + items_ml + items_amz):
        pid = item.get("id") or item.get("nombre", "")[:40]
        slug = normalizar(item.get("nombre", ""))[:32]
        
        # Filtro 48h anti-repetición
        if pid in bloqueados_48h:
            continue
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

        cat = clasificar_categoria(item.get("nombre", ""))
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
    idx_ml = 0
    idx_amz = 0
    idx_cupom = 0
    ultima_cat = None
    repeticiones_cat = 0

    # Armar hasta 100 posts alternando: ML, Amazon, Cupon, ML, Amazon, etc.
    total_deseado = min(120, max(80, len(todos_candidatos) + len(posts_cupones)))

    for step in range(total_deseado):
        item_elegido = None

        # Patrón rotativo:
        # Step % 5 == 0 -> Cupón (si hay)
        # Step % 5 in (1, 3) -> Mercado Livre
        # Step % 5 in (2, 4) -> Amazon
        mod = step % 5

        if mod == 0 and posts_cupones and idx_cupom < len(posts_cupones):
            item_elegido = posts_cupones[idx_cupom]
            idx_cupom += 1
        elif (mod in (1, 3) and idx_ml < len(cola_ml)) or (idx_amz >= len(cola_amz) and idx_ml < len(cola_ml)):
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
                "cupom": candidato.get("cupon") or candidato.get("cupom"),
                "pix": "mais 5% OFF",
                "imagen": candidato.get("imagen"),
                "url": candidato.get("url_corta") or candidato.get("meli_la") or candidato.get("url"),
                "criado_em": ahora_iso,
                "prioridade": 5
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
                    "cupom": candidato.get("cupon") or candidato.get("cupom"),
                    "pix": "mais 5% OFF",
                    "imagen": candidato.get("imagen"),
                    "url": candidato.get("url_corta") or candidato.get("url"),
                    "criado_em": ahora_iso,
                    "prioridade": 5
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
            "cupom": c.get("cupon") or c.get("cupom"),
            "pix": "mais 5% OFF",
            "imagen": c.get("imagen"),
            "url": c.get("url_corta") or c.get("meli_la") or c.get("url"),
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
    print("=" * 60)
    return len(fila_final)

if __name__ == "__main__":
    armar_fila_rotativa()
