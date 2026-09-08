#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Acortador Propio con Tracking (acortador.py)
===================================================
Genera enlaces cortos y páginas estáticas de redirección:
  - Lee achados.json (y opcionalmente productos.json)
  - Para cada oferta crea un código corto único (5-6 chars alfanuméricos)
  - Crea carpeta go/<CODIGO>/index.html con:
      * Redirección HTML inmediata: <meta http-equiv="refresh" content="0;url=...">
      * Tracking GA4 gtag('event', 'click_afiliado', {loja, producto}) antes de redirigir
      * Fallback en JavaScript window.location.replace(...)
      * Enlace <a> visible por si falla la redirección automática
  - Guarda mapa en links.json (codigo -> {url, loja, producto, creado_em, desc_pct})
  - Devuelve la URL corta configurada (dominio_curto + "/go/" + CODIGO)
"""
import json, hashlib, re, os, sys, io
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 fix for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
GO_DIR = BASE / "go"
LINKS_JSON = BASE / "links.json"
CONFIG_JSON = BASE / "config_afiliados.json"
ACHADOS_JSON = BASE / "achados.json"
GA4_ID = "G-NFQTYQ0HXH"

def cargar_config():
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

CONFIG = cargar_config()
DOMINIO_CURTO = CONFIG.get("dominio_curto", "https://gollop33.github.io/criba").rstrip("/")

def cargar_links_existentes():
    if LINKS_JSON.exists():
        try:
            return json.loads(LINKS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def generar_codigo(url_larga, nombre="", longitud=6):
    """Genera código alfanumérico estable a partir de URL y nombre."""
    raw = f"{url_larga}|{nombre}".encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    # Usar caracteres alfanuméricos en minúsculas y números (evitando caracteres confusos)
    chars = "23456789abcdefghkmnpqrstuvwxyz"
    num = int(h[:12], 16)
    codigo = []
    for _ in range(longitud):
        codigo.append(chars[num % len(chars)])
        num //= len(chars)
    return "".join(codigo)

def generar_html_redirect(url_larga, loja, producto, codigo):
    """Genera el HTML estático con meta-refresh, tracking GA4 y fallback JS."""
    # Escapar comillas para JS y atributos HTML
    url_esc_attr = url_larga.replace('"', '&quot;')
    url_esc_js = url_larga.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    loja_esc_js = loja.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    prod_esc_js = producto.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    prod_esc_html = producto.replace('<', '&lt;').replace('>', '&gt;')

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Redirecionando para {loja}... · CRIBA</title>
<meta http-equiv="refresh" content="1;url={url_esc_attr}">
<link rel="canonical" href="{url_esc_attr}">
<!-- Google Analytics 4 -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA4_ID}');
</script>
<style>
  body {{
    background: #0b0f14;
    color: #e8eef5;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    text-align: center;
    box-sizing: border-box;
  }}
  .card {{
    background: #121821;
    border: 1px solid #1e2836;
    border-radius: 16px;
    padding: 32px 24px;
    max-width: 480px;
    width: 100%;
    box-shadow: 0 12px 30px rgba(0,0,0,0.5);
  }}
  .spin {{
    width: 44px;
    height: 44px;
    border: 4px solid #1e2836;
    border-top: 4px solid #ff5c1c;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 20px;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  h1 {{ font-size: 1.25rem; margin: 0 0 10px; color: #fff; }}
  p {{ color: #8fa1b3; font-size: 0.9rem; margin: 0 0 20px; line-height: 1.4; }}
  a.btn {{
    display: inline-block;
    background: linear-gradient(90deg, #ff5c1c, #ff8a3d);
    color: #fff;
    text-decoration: none;
    font-weight: bold;
    padding: 12px 24px;
    border-radius: 99px;
    font-size: 0.95rem;
    transition: 0.2s;
  }}
  a.btn:hover {{ filter: brightness(1.1); }}
</style>
</head>
<body>
<div class="card">
  <div class="spin"></div>
  <h1>Abrindo oferta na {loja}...</h1>
  <p>{prod_esc_html}</p>
  <a class="btn" href="{url_esc_attr}" id="linkDest">Clique aqui se não abrir automaticamente →</a>
</div>
<script>
  (function(){{
    var target = "{url_esc_js}";
    var redirected = false;
    function redirect(){{
      if(!redirected){{
        redirected = true;
        window.location.replace(target);
      }}
    }}
    try {{
      gtag('event', 'click_afiliado', {{
        'event_category': 'afiliados',
        'loja': "{loja_esc_js}",
        'produto': "{prod_esc_js}",
        'codigo': "{codigo}",
        'event_callback': function(){{ redirect(); }}
      }});
    }} catch(e) {{}}
    setTimeout(redirect, 600);
  }})();
</script>
</body>
</html>
"""
    return html

def procesar_oferta(url_larga, loja, producto, desc_pct=0, links_map=None):
    """
    Obtiene o crea un código corto para la oferta y genera el archivo go/<CODIGO>/index.html.
    Retorna la url_corta completa.
    """
    if links_map is None:
        links_map = cargar_links_existentes()

    # Buscar si ya existe la URL larga registrada
    codigo_existente = None
    for cod, info in links_map.items():
        if info.get("url") == url_larga:
            codigo_existente = cod
            break

    codigo = codigo_existente or generar_codigo(url_larga, producto)

    # Si por colisión el código ya existe para otra URL, añadir sufijo
    if not codigo_existente and codigo in links_map and links_map[codigo].get("url") != url_larga:
        for i in range(1, 10):
            nuevo_cod = f"{codigo[:5]}{i}"
            if nuevo_cod not in links_map or links_map[nuevo_cod].get("url") == url_larga:
                codigo = nuevo_cod
                break

    # Crear carpeta y archivo de redirección
    dest_dir = GO_DIR / codigo
    dest_dir.mkdir(parents=True, exist_ok=True)
    html_content = generar_html_redirect(url_larga, loja, producto, codigo)
    (dest_dir / "index.html").write_text(html_content, encoding="utf-8")

    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    links_map[codigo] = {
        "url": url_larga,
        "loja": loja,
        "producto": producto,
        "desc_pct": desc_pct,
        "creado_em": links_map.get(codigo, {}).get("creado_em") or ahora_iso
    }

    url_corta = f"{DOMINIO_CURTO}/go/{codigo}/"
    return url_corta, codigo

def acortar_catalogo(path_json=ACHADOS_JSON):
    """Procesa todas las ofertas de un archivo JSON y actualiza url_corta en cada una."""
    if not path_json.exists():
        print(f"[Acortador] {path_json.name} no encontrado")
        return 0

    try:
        data = json.loads(path_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Acortador] Error leyendo {path_json.name}: {e}")
        return 0

    items = data.get("achados", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    links_map = cargar_links_existentes()
    actualizados = 0

    for item in items:
        url_larga = item.get("url", "")
        if not url_larga:
            continue
        loja = item.get("loja", "Loja")
        producto = item.get("nombre", "Produto")
        desc = float(item.get("desc_pct") or 0)

        url_corta, codigo = procesar_oferta(url_larga, loja, producto, desc, links_map)
        item["url_corta"] = url_corta
        item["codigo_curto"] = codigo
        actualizados += 1

    # Guardar mapa de links
    LINKS_JSON.write_text(json.dumps(links_map, ensure_ascii=False, indent=2), encoding="utf-8")

    # Guardar achados con url_corta inyectada
    if isinstance(data, dict):
        data["achados"] = items
        path_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    elif isinstance(data, list):
        path_json.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[Acortador] {actualizados} enlaces procesados en {path_json.name}. links.json actualizado ({len(links_map)} links totales).")
    return actualizados

def obtener_url_corta(url_larga, loja="Loja", producto="Produto"):
    """Función de utilidad para acortar una URL al vuelo."""
    links_map = cargar_links_existentes()
    url_corta, _ = procesar_oferta(url_larga, loja, producto, 0, links_map)
    LINKS_JSON.write_text(json.dumps(links_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return url_corta

if __name__ == "__main__":
    print("=" * 60)
    print("  CRIBA · ACORTADOR PROPIO CON TRACKING")
    print(f"  Dominio base: {DOMINIO_CURTO}/go/<codigo>/")
    print("=" * 60)
    total = acortar_catalogo()
    print(f"[OK] Finalizado con éxito.")
