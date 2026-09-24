#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Publicador de Próximo Post (publicar_proximo.py)
=========================================================
Modo Canal Vivo:
- Lee 'fila_posts.json'.
- Lee 'logs/enviados.json' y 'logs/control_canal.json'.
- Respeta reglas de calentamiento de canal (Day 1: 10/día, Day 2: 20/día, Day 3+: 50/día).
- Respeta ventana horaria Brasília (8h a 22h BRT).
- Elige el próximo post no enviado según rotación.
- Si es post de cupones, envía mensaje de cupones.
- Si es post de producto, intenta generar imagen con badges ninja y envía con Green API.
- Actualiza estado en 'logs/enviados.json'.
"""

import json
import os
import sys
import io
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# UTF-8 console fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
FILA_JSON = BASE / "fila_posts.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
ENVIADOS_JSON = LOG_DIR / "enviados.json"
CONTROL_CANAL_JSON = LOG_DIR / "control_canal.json"
CONFIG_FILE = BASE / "config_afiliados.json"

# Cargar variables locales desde .env si existe (desarrollo local)
_env_file = BASE / ".env"
if _env_file.exists():
    try:
        for line in _env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

# Green API Secrets
GREEN_API_ID = os.environ.get("GREEN_API_ID", "").strip()
GREEN_API_TOKEN = os.environ.get("GREEN_API_TOKEN", "").strip()
WHATSAPP_CHAT_ID = os.environ.get("WHATSAPP_CHAT_ID", "").strip()

def cargar_control_canal():
    if not CONTROL_CANAL_JSON.exists():
        ahora_iso = datetime.now(timezone.utc).isoformat()
        return {
            "fecha_inicio": ahora_iso,
            "dias_activo": 3,  # Modo activo normal o calentamiento
            "envios_hoy": 0,
            "fecha_hoy": datetime.now(timezone.utc).strftime("%Y-%m-%d")
        }
    try:
        data = json.loads(CONTROL_CANAL_JSON.read_text(encoding="utf-8"))
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("fecha_hoy") != hoy:
            data["fecha_hoy"] = hoy
            data["envios_hoy"] = 0
            # Incrementar días activo si cambia de día
            data["dias_activo"] = data.get("dias_activo", 1) + 1
        return data
    except Exception:
        return {"dias_activo": 3, "envios_hoy": 0, "fecha_hoy": datetime.now(timezone.utc).strftime("%Y-%m-%d")}

def guardar_control_canal(data):
    try:
        CONTROL_CANAL_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def limite_diario_calentamiento(dias_activo):
    if dias_activo <= 1:
        return 20
    elif dias_activo == 2:
        return 40
    else:
        return 120  # Soporta cadencia de 7-8 minutos durante todo el día pico (14h * ~8 = ~112)

def horario_permitido_brt():
    """Verifica si la hora actual en Brasília (UTC-3) está entre 8 y 22h."""
    now_utc = datetime.now(timezone.utc)
    brt_hour = (now_utc.hour - 3) % 24
    return 8 <= brt_hour < 22

def main():
    es_test = "--test" in sys.argv
    print("=" * 60)
    print("  CRIBA · PUBLICADOR DE CANAL VIVO (publicar_proximo.py)" + (" [MODO TEST]" if es_test else ""))
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. Verificar horario Brasília
    if not es_test and not horario_permitido_brt():
        print("  [Horario] Fuera de ventana de publicación Brasília (8h a 22h BRT). Saltando.")
        return

    # 2. Control de calentamiento
    control = cargar_control_canal()
    dias = control.get("dias_activo", 3)
    max_dia = limite_diario_calentamiento(dias)
    envios_hoy = control.get("envios_hoy", 0)

    print(f"  • Calentamiento: Día {dias} | Envíos hoy: {envios_hoy}/{max_dia}")
    if not es_test and envios_hoy >= max_dia:
        print(f"  [Límite diario] Alcanzado cupo seguro para evitar bloqueos ({envios_hoy}/{max_dia}).")
        return

    # 3. Validar credenciales de Green API (skip en modo test)
    if not es_test and not (GREEN_API_ID and GREEN_API_TOKEN and WHATSAPP_CHAT_ID):
        print("  ❌ ERROR: Credenciales de Green API no configuradas en variables de entorno.")
        print("     Verifica GREEN_API_ID, GREEN_API_TOKEN y WHATSAPP_CHAT_ID en GitHub Secrets o en tu archivo .env.")
        return

def publicar_un_post(es_test=False):
    """Selecciona y publica exactamente 1 post no enviado. Retorna (ok, pid, tienda)."""
    if not FILA_JSON.exists():
        print("  [Fila] fila_posts.json no existe.")
        return False, None, None

    try:
        fila_data = json.loads(FILA_JSON.read_text(encoding="utf-8"))
        posts = fila_data.get("fila", [])
    except Exception as e:
        print(f"  [Fila] Error leyendo fila_posts.json: {e}")
        return False, None, None

    if not posts:
        print("  [Fila] No hay posts en la fila.")
        return False, None, None

    from modulo_ofertas import cargar_enviados, marcar_enviado, ya_enviado
    enviados = cargar_enviados()

    post_a_enviar = None
    for p in posts:
        if p.get("tipo") == "cupons_loja":
            continue
        pid = p.get("id_post") or p.get("titulo", "")[:40]
        if not ya_enviado(pid, enviados, canal="whatsapp"):
            post_a_enviar = p
            break

    if not post_a_enviar:
        print("  [Fila] Todos los posts ya fueron enviados en las últimas 24h.")
        return False, None, None

    tipo = post_a_enviar.get("tipo", "producto")
    pid = post_a_enviar.get("id_post")
    loja = post_a_enviar.get("loja", "Loja")
    titulo = post_a_enviar.get("titulo", "")
    url = post_a_enviar.get("url", "")
    print(f"\n  🎯 Post seleccionado: [{loja.upper()}] {titulo[:55]}")
    print(f"     Link base: {url}")

    # Resolver link corto meli.la si es Mercado Libre
    link_final = url
    if "mercado" in loja.lower():
        cookie_portal = os.environ.get("ML_PORTAL_COOKIE", "").strip()
        if cookie_portal:
            try:
                from melila_api import generar_melila
                short_ml = generar_melila(url, cookie_str=cookie_portal, tag="ja20250119201346")
                if short_ml:
                    link_final = short_ml
                    print(f"  [meli.la] Enlace corto oficial: {short_ml}")
            except Exception as e:
                print(f"  [meli.la] Error al generar link corto: {e}")

    from enviar_whatsapp import enviar_whatsapp, enviar_whatsapp_archivo
    import requests as req

    # Formatear precio y cupón
    precio_raw = post_a_enviar.get("precio", 0)
    cupom = post_a_enviar.get("cupom") or ""
    try:
        precio_int = int(float(precio_raw))
        precio_limpo = str(precio_int)
    except (ValueError, TypeError):
        precio_limpo = str(precio_raw)

    lineas = [f"🔥 {titulo}"]
    lineas.append("")
    if precio_int:
        lineas.append(f"💵 R$ {precio_limpo}")
    if cupom:
        lineas.append(f"🎟️ Cupom: {cupom}")
    lineas.append("")
    lineas.append(link_final)
    lineas.append("")
    lineas.append("anúncio")

    mensaje = "\n".join(lineas)

    print(f"\n--- PREVIEW POST ({loja}) ---")
    print(mensaje)
    print(f"--- FIN PREVIEW ---\n")

    if es_test:
        return True, pid, loja

    img_url = post_a_enviar.get("imagen")
    img_enviada = False

    if img_url:
        try:
            img_dir = BASE / "img" / "envios"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / f"post_{pid[:15]}.jpg"
            r_img = req.get(img_url, timeout=15)
            if r_img.status_code == 200 and len(r_img.content) > 3000:
                img_path.write_bytes(r_img.content)
                print("  [WhatsApp] Enviando foto grande del producto con mensaje...")
                img_enviada = enviar_whatsapp_archivo(img_path, caption=mensaje)
        except Exception as e:
            print(f"  [WhatsApp] Error enviando imagen: {e}")

    if not img_enviada:
        print("  [WhatsApp] Enviando mensaje de texto directo...")
        ok = enviar_whatsapp(mensaje)
    else:
        ok = img_enviada

    if ok:
        marcar_enviado(pid, enviados, canal="whatsapp")
        from modulo_ofertas import guardar_enviados
        guardar_enviados(enviados)
        return True, pid, loja
    return False, pid, loja

def main():
    es_test = "--test" in sys.argv
    solo_uno = "--single" in sys.argv

    print("=" * 60)
    print("  CRIBA · PUBLICADOR DE CANAL VIVO (publicar_proximo.py)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. Verificar horario Brasília
    if not es_test and not horario_permitido_brt():
        print("  [Horario] Fuera de ventana Brasília (8h a 22h BRT). Saltando.")
        return

    # 2. Control de calentamiento y límite diario
    control = cargar_control_canal()
    dias = control.get("dias_activo", 3)
    max_dia = limite_diario_calentamiento(dias)
    envios_hoy = control.get("envios_hoy", 0)

    print(f"  • Calentamiento: Día {dias} | Envíos hoy: {envios_hoy}/{max_dia}")
    if not es_test and envios_hoy >= max_dia:
        print(f"  [Límite diario] Alcanzado cupo seguro para evitar bloqueos ({envios_hoy}/{max_dia}).")
        return

    # 3. Validar credenciales Green API
    if not es_test and not (GREEN_API_ID and GREEN_API_TOKEN and WHATSAPP_CHAT_ID):
        print("  ❌ ERROR: Credenciales de Green API no configuradas.")
        return

    # 4. Publicar Post 1
    ok1, pid1, loja1 = publicar_un_post(es_test=es_test)
    if ok1 and not es_test:
        control["envios_hoy"] += 1
        guardar_control_canal(control)
        print(f"  ✅ Post 1 [{loja1}] publicado con éxito!")

    # 5. Si no es prueba ni single, esperar 7.5 minutos (450s) y publicar Post 2 (de la otra tienda)
    if not es_test and not solo_uno and ok1 and control["envios_hoy"] < max_dia:
        espera_seg = 450  # 7 minutos y medio exactos
        print(f"\n  ⏱️ [Cadencia 7-8 min] Pausa de {espera_seg}s (~7.5 min) antes de la siguiente tienda...")
        time.sleep(espera_seg)

        ok2, pid2, loja2 = publicar_un_post(es_test=False)
        if ok2:
            control["envios_hoy"] += 1
            guardar_control_canal(control)
            print(f"  ✅ Post 2 [{loja2}] publicado con éxito!")

    print("=" * 60)

if __name__ == "__main__":
    main()
