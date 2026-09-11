#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Agente Inteligente de Ofertas con Gemini (api_agente.py)
================================================================
Analiza ofertas específicas compartidas por el usuario, evalúa cupones,
condiciones de pago (Pix, Meli+, saldo MP), decide con IA si es una
buena oferta y la agrega a 'achados_especificos.json' para publicación.

Endpoints:
  - POST /adicionar-oferta : {url, descricao, cupom} -> analiza con Gemini y agrega
  - GET  /ofertas-especificas : lista todas las ofertas analizadas y aprobadas
  - GET  / : Interfaz Web interactiva moderna para ingresar ofertas desde PC o celular
"""

import os
import re
import json
import time
import sys
import io
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from bs4 import BeautifulSoup
    BS4_DISPONIBLE = True
except ImportError:
    BS4_DISPONIBLE = False

try:
    from flask import Flask, request, jsonify, render_template_string
    FLASK_DISPONIBLE = True
except ImportError:
    FLASK_DISPONIBLE = False
    Flask = None
    request = None
    jsonify = None
    render_template_string = None

# UTF-8 console fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
ESPECIFICOS_JSON = BASE / "achados_especificos.json"
CONFIG_FILE = BASE / "config_afiliados.json"
ACHADOS_JSON = BASE / "achados.json"

ML_TAG = "ja20250119201346"
AMAZON_TAG = "criba20-20"

app = Flask(__name__) if FLASK_DISPONIBLE else None

# ─── 1. Extracción de Datos de Producto (Scraping Mercado Livre & Amazon) ──────

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

def normalizar(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()

def buscar_datos_producto(url):
    """Extrae título, precio, imagen y tienda de una URL de Mercado Livre o Amazon."""
    info = {
        "url": url,
        "loja": "Outra",
        "nome": "Produto Selecionado",
        "preco": None,
        "preco_anterior": None,
        "desconto_pct": 0,
        "imagen": None,
        "id": f"esp-{int(time.time())}"
    }

    url_lower = url.lower()
    if "mercadolivre.com.br" in url_lower or "mercadolibre.com" in url_lower or "meli.la" in url_lower:
        info["loja"] = "Mercado Livre"
    elif "amazon.com.br" in url_lower:
        info["loja"] = "Amazon"
    else:
        info["loja"] = "Desconhecida"

    try:
        # Resolver redirección si es meli.la
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        final_url = r.url
        info["url_resolvida"] = final_url
        soup = BeautifulSoup(r.text, "html.parser")

        # 1. Título
        title_el = soup.find("h1") or soup.find("meta", property="og:title")
        if title_el:
            info["nome"] = (title_el.get("content") if title_el.name == "meta" else title_el.get_text()).strip()
        elif soup.title:
            info["nome"] = soup.title.get_text().split("|")[0].split("-")[0].strip()

        # 2. Imagen
        img_el = soup.find("meta", property="og:image") or soup.find("img", class_=re.compile(r"gallery|picture|main|front", re.I))
        if img_el:
            info["imagen"] = img_el.get("content") or img_el.get("src")

        # 3. ID
        m_id = re.search(r"(MLB-?\d+)", final_url, re.I)
        if m_id:
            info["id"] = m_id.group(1).replace("-", "").upper()

        # 4. Precios
        # Buscar meta de precio schema.org
        price_meta = soup.find("meta", itemprop="price") or soup.find("meta", property="product:price:amount")
        if price_meta and price_meta.get("content"):
            try:
                info["preco"] = float(price_meta["content"].replace(",", "."))
            except Exception:
                pass

        # Si no se encontró precio en meta, buscar en texto
        if not info["preco"]:
            fraction = soup.find(class_=re.compile(r"andes-money-amount__fraction|a-price-whole", re.I))
            if fraction:
                try:
                    val_str = re.sub(r"[^\d]", "", fraction.get_text())
                    cents = soup.find(class_=re.compile(r"andes-money-amount__cents|a-price-fraction", re.I))
                    cents_str = cents.get_text().strip() if cents else "00"
                    info["preco"] = float(f"{val_str}.{cents_str}")
                except Exception:
                    pass

        # Buscar precio en JSON incrustado (ej: application/ld+json)
        if not info["preco"]:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    jd = json.loads(script.string or "{}")
                    if isinstance(jd, dict) and "offers" in jd:
                        off = jd["offers"]
                        p_val = off.get("price") or (off[0].get("price") if isinstance(off, list) and off else None)
                        if p_val:
                            info["preco"] = float(p_val)
                            break
                except Exception:
                    pass

        # Precio anterior
        prev_el = soup.find(class_=re.compile(r"andes-money-amount--previous|a-text-price", re.I))
        if prev_el:
            m_prev = re.search(r"R\$\s*([\d\.,]+)", prev_el.get_text())
            if m_prev:
                try:
                    p_clean = m_prev.group(1).replace(".", "").replace(",", ".")
                    info["preco_anterior"] = float(p_clean)
                except Exception:
                    pass

        if info["preco_anterior"] and info["preco"] and info["preco_anterior"] > info["preco"]:
            info["desconto_pct"] = round((1 - info["preco"] / info["preco_anterior"]) * 100, 1)

    except Exception as e:
        print(f"[AgenteOfertas] Error extrayendo datos de {url}: {e}")

    return info


# ─── 2. Análisis Inteligente con Gemini ────────────────────────────────────────

def analizar_oferta_con_gemini(produto, contexto_usuario=""):
    """
    Utiliza Gemini AI para razonar si la oferta tiene mérito comercial,
    descuentos reales, condiciones especiales o cupones.
    Si no hay GEMINI_API_KEY o falla la llamada, aplica motor de reglas heurístico.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    prompt = f"""
Você é o especialista chefe de compras e curador de ofertas do CRIBA Ofertas.
Analise criteriosamente esta oferta encontrada para um canal de promoções no Brasil:

- Produto: {produto.get('nome')}
- Loja: {produto.get('loja')}
- Preço Atual: R$ {produto.get('preco')}
- Preço Anterior: R$ {produto.get('preco_anterior')}
- Desconto Visível: {produto.get('desconto_pct')}%
- Contexto / Detalhes informados pelo usuário: "{contexto_usuario}"

CRITÉRIOS DE AVALIAÇÃO:
1. Qualidade BOA:
   - Desconto real significativo (>= 25%), OU
   - Preço histórico excelente com cupom ativo informado, OU
   - Benefícios combinados (ex: Cupom + Pix + Frete Grátis / Meli+).
2. Qualidade MEDIA:
   - Desconto entre 15% e 24% sem cupom, ou produto comum com preço normal.
3. Qualidade RUIM:
   - Preço sem desconto, ou desconto falso, ou produto sem atratividade.

Responda ESTRITAMENTE em formato JSON com as chaves:
{{
  "qualidade": "BOA" | "MEDIA" | "RUIM",
  "desconto_estimado": float,
  "cupom_detectado": "CODIGO" ou null,
  "condicoes": ["Pix", "Meli+", "Prime", etc],
  "motivo": "resumo curto em português explicando por que vale ou não a pena publicar",
  "destaque": "Frase de impacto curta para a mensagem (ex: 'Menor preço histórico com cupom')"
}}
"""

    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            raw_txt = resp.text.strip()
            # Limpiar bloques de código markdown si los hay
            raw_txt = re.sub(r"^```json\s*", "", raw_txt, flags=re.MULTILINE)
            raw_txt = re.sub(r"^```\s*$", "", raw_txt, flags=re.MULTILINE).strip()
            res_json = json.loads(raw_txt)
            return res_json
        except Exception as e:
            print(f"[Gemini] Aviso al analizar con IA ({e}), usando motor heurístico...")

    # Fallback heurístico inteligente (si no hay API key o timeout)
    desc = float(produto.get("desconto_pct") or 0)
    # Extraer cupón del contexto si el usuario escribió por ejemplo 'cupom XYZ'
    m_cup = re.search(r"cupo[mn]?[:\s]+([A-Z0-9_-]{4,20})", contexto_usuario, re.I)
    cupom_encontrado = m_cup.group(1).upper() if m_cup else None

    # Detectar condiciones
    condicoes = []
    if "pix" in contexto_usuario.lower() or "pix" in produto.get("nome", "").lower():
        condicoes.append("Pix 5% OFF")
    if "meli" in contexto_usuario.lower():
        condicoes.append("Meli+")
    if "prime" in contexto_usuario.lower():
        condicoes.append("Prime")

    if desc >= 25 or cupom_encontrado:
        qualidade = "BOA"
        motivo = f"Excelente oportunidade ({desc}% OFF)" + (f" com cupom {cupom_encontrado}" if cupom_encontrado else "")
    elif desc >= 15:
        qualidade = "MEDIA"
        motivo = f"Desconto moderado de {desc}%"
    else:
        qualidade = "BOA" if cupom_encontrado else "RUIM"
        motivo = f"Oferta especial indicada manualmente pelo curador" if cupom_encontrado else "Desconto abaixo do padrão do canal"

    return {
        "qualidade": qualidade,
        "desconto_estimado": desc,
        "cupom_detectado": cupom_encontrado,
        "condicoes": condicoes,
        "motivo": motivo,
        "destaque": "Achado selecionado por curadoria"
    }


# ─── 3. Persistencia y Blindaje de Afiliados (Regla de Oro) ────────────────────

def carregar_especificos():
    if not ESPECIFICOS_JSON.exists():
        return []
    try:
        data = json.loads(ESPECIFICOS_JSON.read_text(encoding="utf-8"))
        return data.get("achados", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    except Exception:
        return []

def salvar_especificos(lista):
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    salida = {
        "actualizado": ahora_iso,
        "total": len(lista),
        "achados": lista
    }
    ESPECIFICOS_JSON.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

def aplicar_afiliado_garantido(url, loja):
    """Garantiza la etiqueta de afiliado según la tienda."""
    u = url.split("#")[0].strip()
    loja_low = (loja or "").lower()

    if "mercado" in loja_low or "mercadolivre" in u:
        # Resolver meli.la si existe o tag directa
        try:
            from gerador_melila import obtener_link_afiliado_ml
            link, _ = obtener_link_afiliado_ml(u, etiqueta=ML_TAG, usar_playwright=False)
            return link
        except Exception:
            sep = "&" if "?" in u else "#"
            return f"{u}{sep}D[A:{ML_TAG}]"
    elif "amazon" in loja_low or "amazon.com.br" in u:
        sep = "&" if "?" in u else "?"
        if "tag=" not in u:
            return f"{u}{sep}tag={AMAZON_TAG}"
        return u
    return u


def injetar_na_fila_e_achados(oferta_dict):
    """Inyecta la oferta inmediatamente en achados.json y al inicio de fila_posts.json."""
    # 1. Inyectar en achados.json
    if ACHADOS_JSON.exists():
        try:
            d = json.loads(ACHADOS_JSON.read_text(encoding="utf-8"))
            items = d.get("achados", []) if isinstance(d, dict) else d
            # Deduplicar por id
            items = [x for x in items if x.get("id") != oferta_dict.get("id")]
            items.insert(0, oferta_dict)
            if isinstance(d, dict):
                d["achados"] = items
                d["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                d["total_achados"] = len(items)
                ACHADOS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Injeção achados.json] {e}")

    # 2. Inyectar con prioridad alta en fila_posts.json
    fila_f = BASE / "fila_posts.json"
    if fila_f.exists():
        try:
            d = json.loads(fila_f.read_text(encoding="utf-8"))
            fila = d.get("fila", [])
            post = {
                "id_post": oferta_dict.get("id"),
                "tipo": "producto_destacado",
                "loja": oferta_dict.get("loja"),
                "categoria": oferta_dict.get("categoria", "Destaque IA"),
                "titulo": oferta_dict.get("nombre"),
                "precio": oferta_dict.get("precio"),
                "precio_anterior": oferta_dict.get("precio_anterior"),
                "desc_pct": oferta_dict.get("desc_pct"),
                "cupom": oferta_dict.get("cupom"),
                "pix": "mais 5% OFF",
                "imagen": oferta_dict.get("imagen"),
                "url": oferta_dict.get("url_corta") or oferta_dict.get("url"),
                "criado_em": oferta_dict.get("criado_em"),
                "prioridade": 100 # Prioridad máxima
            }
            fila.insert(0, post)
            d["fila"] = fila
            d["total_posts"] = len(fila)
            fila_f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Injeção fila_posts.json] {e}")


# ─── 4. Rutas de la API y Vista Web ───────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CRIBA · Agente de Ofertas IA</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0f14;--card:#121821;--line:#1e2836;--txt:#e8eef5;--mut:#8fa1b3;--acc:#ff5c1c;--acc2:#ffb800;--green:#25D366}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Space Grotesk',sans-serif;background:var(--bg);color:var(--txt);padding:24px 16px;max-width:800px;margin:auto}
h1{font-size:1.8rem;margin-bottom:8px;font-weight:700}
h1 b{color:var(--acc)}
p.sub{color:var(--mut);font-size:0.95rem;margin-bottom:24px}
.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:28px}
label{display:block;font-size:0.88rem;font-weight:600;margin-bottom:6px;color:#c3d2e3}
input, textarea{width:100%;background:#0a0d12;border:1px solid var(--line);border-radius:10px;padding:12px 14px;color:#fff;font-family:inherit;font-size:0.95rem;margin-bottom:16px}
input:focus, textarea:focus{border-color:var(--acc);outline:none}
button{background:linear-gradient(90deg,var(--acc),#ff833b);color:#fff;font-weight:700;padding:14px 24px;border-radius:99px;border:none;cursor:pointer;font-size:1rem;width:100%;transition:0.2s}
button:hover{filter:brightness(1.1)}
.res{margin-top:20px;padding:16px;border-radius:12px;display:none}
.res.ok{background:#0e2d1d;border:1px solid #1c663d;color:#7dffb0}
.res.err{background:#351313;border:1px solid #6d2727;color:#ff9b9b}
.card-item{background:#0d121a;border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px;display:flex;gap:16px;align-items:center}
.card-item img{width:70px;height:70px;object-fit:cover;border-radius:8px;background:#151b24}
.card-item .det{flex:1}
.card-item h3{font-size:0.95rem;margin-bottom:4px}
.card-item .price{font-weight:700;color:var(--acc2);font-size:1.1rem}
.badge-boa{background:#14724a;color:#fff;padding:3px 8px;border-radius:6px;font-size:0.75rem;font-weight:700}
</style>
</head>
<body>
  <h1>CRIBA <b>IA</b> · Agente Curador de Ofertas</h1>
  <p class="sub">Viu uma oferta quente em outro canal? Cole aqui para o Agente analisar com Gemini e adicionar à fila de publicação com sua comissão.</p>

  <div class="box">
    <label>Link do Produto (Mercado Livre ou Amazon)</label>
    <input type="url" id="url" placeholder="https://www.mercadolivre.com.br/monitor-lg.../p/MLB..." required>

    <label>Contexto / Cupom / Condições Especiais</label>
    <textarea id="desc" rows="2" placeholder="Ex: Monitor LG com cupom MELIMAISPOSDD saindo por R$ 477 no Pix"></textarea>

    <button onclick="adicionarOferta()" id="btn-env">🤖 Analisar com IA & Adicionar Oferta</button>
    <div id="resultado" class="res"></div>
  </div>

  <h2>📋 Ofertas Adicionadas pelo Agente (<span id="total-esp">0</span>)</h2>
  <div id="lista" style="margin-top:14px"></div>

<script>
async function carregarLista(){
  try{
    const r = await fetch('/ofertas-especificas');
    const d = await r.json();
    const items = d.achados || [];
    document.getElementById('total-esp').textContent = items.length;
    const l = document.getElementById('lista');
    if(!items.length){
      l.innerHTML = '<p style="color:#6e8297;font-size:0.9rem">Nenhuma oferta adicionada manualmente ainda.</p>';
      return;
    }
    l.innerHTML = items.map(it => `
      <div class="card-item">
        <img src="${it.imagen || ''}" onerror="this.style.display='none'">
        <div class="det">
          <span class="badge-boa">${it.analise_ia?.qualidade || 'BOA'}</span>
          <h3>${it.nombre}</h3>
          <div class="price">R$ ${it.precio} ${it.desc_pct ? ('<span style="font-size:0.8rem;color:#8fa1b3">(-'+it.desc_pct+'%)</span>') : ''}</div>
          <div style="font-size:0.8rem;color:#8fa1b3;margin-top:4px">
            ${it.cupom ? ('🎟️ Cupom: <b>'+it.cupom+'</b> · ') : ''}
            Loja: <b>${it.loja}</b> · 
            <a href="${it.url_corta || it.url}" target="_blank" style="color:#ffb800;text-decoration:underline">Ver link monetizado</a>
          </div>
        </div>
      </div>
    `).join('');
  }catch(e){}
}

async function adicionarOferta(){
  const url = document.getElementById('url').value.trim();
  const desc = document.getElementById('desc').value.trim();
  const resEl = document.getElementById('resultado');
  const btn = document.getElementById('btn-env');

  if(!url){ alert('Por favor, informe a URL do produto.'); return; }

  btn.disabled = true;
  btn.textContent = '⏳ Agente minerando e analisando com IA...';
  resEl.style.display = 'none';

  try{
    const r = await fetch('/adicionar-oferta', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url, descricao: desc})
    });
    const d = await r.json();
    resEl.style.display = 'block';

    if(d.status === 'ok'){
      resEl.className = 'res ok';
      resEl.innerHTML = '<b>' + d.mensagem + '</b><br>' +
        (d.produto?.nome ? ('<br>📦 ' + d.produto.nome + '<br>💰 R$ ' + d.produto.preco + (d.produto.cupom ? (' | 🎟️ Cupom: ' + d.produto.cupom) : '')) : '') +
        '<br>💡 <i>' + (d.analise?.motivo || '') + '</i>';
      document.getElementById('url').value = '';
      document.getElementById('desc').value = '';
      carregarLista();
    } else {
      resEl.className = 'res err';
      resEl.innerHTML = '<b>' + d.mensagem + '</b><br><small>' + (d.motivo || '') + '</small>';
    }
  }catch(e){
    resEl.style.display = 'block';
    resEl.className = 'res err';
    resEl.textContent = 'Erro ao se comunicar com o agente: ' + e;
  }finally{
    btn.disabled = false;
    btn.textContent = '🤖 Analisar com IA & Adicionar Oferta';
  }
}

carregarLista();
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    """Interfaz Web para que el usuario o el equipo ingresen ofertas."""
    return render_template_string(HTML_TEMPLATE)

@app.route("/ofertas-especificas", methods=["GET"])
def listar_ofertas_especificas():
    """Retorna las ofertas específicas agregadas."""
    return jsonify({
        "status": "ok",
        "total": len(carregar_especificos()),
        "achados": carregar_especificos()
    })

@app.route("/adicionar-oferta", methods=["POST"])
def adicionar_oferta():
    """
    Endpoint principal del Agente:
    Recibe {url, descricao}, busca el producto, analiza con Gemini y si es BOA/MEDIA agrega.
    """
    data = request.get_json(force=True, silent=True) or {}
    url = data.get("url", "").strip()
    descricao = data.get("descricao", "").strip()

    if not url:
        return jsonify({"status": "erro", "mensagem": "URL obrigatória."}), 400

    # 1. Buscar producto y extraer precio
    produto = buscar_datos_producto(url)

    # Permitir extraer precio del contexto si el usuario escribió por ejemplo 'por R$ 477' o 'preço 477'
    m_p = re.search(r"(?:por|pre[çc]o|sai\s+por|valor)\s*(?:R\$\s*)?([\d\.,]+)", descricao, re.I)
    if m_p:
        try:
            val_p = float(m_p.group(1).replace(".", "").replace(",", "."))
            if val_p > 0:
                produto["preco"] = val_p
        except Exception:
            pass

    if not produto.get("preco") and (not produto.get("nome") or produto.get("nome") == "Produto Selecionado"):
        return jsonify({
            "status": "erro",
            "mensagem": "Não foi possível extrair dados do produto.",
            "motivo": "A página pode exigir login ou bloqueou requisições automáticas. Você pode incluir o preço no texto (ex: 'Monitor LG por R$ 477 com cupom')."
        }), 422

    # 2. Analizar con Gemini AI
    analise = analizar_oferta_con_gemini(produto, descricao)
    qualidade = analise.get("qualidade", "MEDIA")

    # 3. Decisión del agente
    if qualidade == "RUIM":
        return jsonify({
            "status": "recusada",
            "mensagem": "❌ Oferta não aprovada pelo Agente.",
            "motivo": analise.get("motivo", "Desconto insuficiente ou sem apelo comercial.")
        })

    # 4. Aplicar link de afiliado oficial (Regla de Oro garantizada)
    link_monetizado = aplicar_afiliado_garantido(produto["url"], produto["loja"])

    # 5. Generar enlace corto propio con tracking
    url_corta = link_monetizado
    try:
        from acortador import obtener_url_corta
        url_corta = obtener_url_corta(link_monetizado, loja=produto["loja"], producto=produto["nome"])
    except Exception:
        pass

    cupom_final = analise.get("cupom_detectado") or data.get("cupom")
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    oferta_especifica = {
        "id": produto["id"],
        "nombre": produto["nome"],
        "precio": produto["preco"],
        "precio_anterior": produto["preco_anterior"],
        "desc_pct": analise.get("desconto_estimado") or produto.get("desconto_pct"),
        "loja": produto["loja"],
        "cupom": cupom_final,
        "condicoes": analise.get("condicoes", []),
        "imagen": produto["imagen"],
        "url": link_monetizado,
        "url_corta": url_corta,
        "criado_em": ahora_iso,
        "encontrado_em": ahora_iso,
        "revalidado_em": ahora_iso,
        "analise_ia": analise,
        "origem": "curadoria_agente_ia"
    }

    # 6. Guardar en achados_especificos.json
    lista = carregar_especificos()
    lista = [x for x in lista if x.get("id") != oferta_especifica["id"]]
    lista.insert(0, oferta_especifica)
    salvar_especificos(lista)

    # 7. Inyectar inmediatamente en achados.json y en la fila de posts
    injetar_na_fila_e_achados(oferta_especifica)

    return jsonify({
        "status": "ok",
        "mensagem": "✅ Oferta aprovada pela IA e adicionada à fila!",
        "analise": analise,
        "produto": oferta_especifica
    })


if __name__ == "__main__":
    if not FLASK_DISPONIBLE:
        print("[ERRO] Flask não está instalado. Instale com: pip install flask")
        sys.exit(1)
    puerto = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print(f"  CRIBA · AGENTE INTELIGENTE GEMINI (api_agente.py)")
    print(f"  Iniciando servidor na porta {puerto}...")
    print(f"  Acesse no navegador: http://localhost:{puerto}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=puerto, debug=False)
