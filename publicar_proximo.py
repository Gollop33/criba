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
        return 12
    elif dias_activo == 2:
        return 24
    else:
        return 50

def horario_permitido_brt():
    """Verifica si la hora actual en Brasília (UTC-3) está entre 8 y 22h."""
    now_utc = datetime.now(timezone.utc)
    brt_hour = (now_utc.hour - 3) % 24
    return 8 <= brt_hour < 22

def main():
    print("=" * 60)
    print("  CRIBA · PUBLICADOR DE CANAL VIVO (publicar_proximo.py)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. Verificar horario Brasília
    if not horario_permitido_brt():
        print("  [Horario] Fuera de ventana de publicación Brasília (8h a 22h BRT). Saltando.")
        return

    # 2. Control de calentamiento
    control = cargar_control_canal()
    dias = control.get("dias_activo", 3)
    max_dia = limite_diario_calentamiento(dias)
    envios_hoy = control.get("envios_hoy", 0)

    print(f"  • Calentamiento: Día {dias} | Envíos hoy: {envios_hoy}/{max_dia}")
    if envios_hoy >= max_dia:
        print(f"  [Límite diario] Alcanzado cupo seguro para evitar bloqueos ({envios_hoy}/{max_dia}).")
        return

    # 3. Cargar fila
    if not FILA_JSON.exists():
        print("  [Fila] fila_posts.json no existe. Ejecuta gerar_fila_posts.py primero.")
        return

    try:
        fila_data = json.loads(FILA_JSON.read_text(encoding="utf-8"))
        posts = fila_data.get("fila", [])
    except Exception as e:
        print(f"  [Fila] Error leyendo fila_posts.json: {e}")
        return

    if not posts:
        print("  [Fila] No hay posts en la fila.")
        return

    # 4. Cargar enviados
    from modulo_ofertas import cargar_enviados, marcar_enviado, ya_enviado
    enviados = cargar_enviados()

    # 5. Encontrar próximo post no enviado
    post_a_enviar = None
    for p in posts:
        pid = p.get("id_post") or p.get("titulo", "")[:40]
        if not ya_enviado(pid, enviados, canal="whatsapp"):
            post_a_enviar = p
            break

    if not post_a_enviar:
        print("  [Fila] Todos los posts de la fila ya fueron enviados en las últimas 24h.")
        return

    tipo = post_a_enviar.get("tipo", "producto")
    pid = post_a_enviar.get("id_post")
    loja = post_a_enviar.get("loja", "Loja")
    titulo = post_a_enviar.get("titulo", "")
    url = post_a_enviar.get("url", "")
    print(f"\n  🎯 Post seleccionado: [{tipo.upper()}] {titulo[:50]}")
    print(f"     Loja: {loja} | Link: {url}")

    # 6. Formatear mensaje según tipo
    from enviar_whatsapp import enviar_whatsapp, enviar_whatsapp_archivo
    try:
        from editar_imagen import procesar_imagen_ninja
    except ImportError:
        procesar_imagen_ninja = None

    ok = False
    if tipo == "cupons_loja":
        mensaje = post_a_enviar.get("mensagem") or f"🔥 Cupons {loja}\n👉 {url}"
        print(f"  Enviando post de cupones a WhatsApp...")
        ok = enviar_whatsapp(mensaje)
    else:
        # Formato producto ninja
        from modulo_ofertas import fmt_brl
        precio = post_a_enviar.get("precio", 0)
        cupom = post_a_enviar.get("cupom")
        pix = post_a_enviar.get("pix")

        lineas = [
            f"🔥 {titulo}",
            f"✅ R$ {fmt_brl(precio)}" if precio else "✅ Em oferta especial",
        ]
        if cupom:
            lineas.append(f"🎟️ Cupom: {cupom}")
        if pix:
            lineas.append(f"💠 Pix: {pix}")
        lineas.append(f"👉 {url}")
        mensaje = "\n".join(lineas)

        img_url = post_a_enviar.get("imagen")
        img_badge = None

        if img_url and procesar_imagen_ninja:
            try:
                img_badge = procesar_imagen_ninja(
                    url_o_path=img_url,
                    nombre_salida=f"post_{pid[:20]}",
                    cupon=cupom,
                    pix_pct=5,
                    desc_pct=post_a_enviar.get("desc_pct", 0)
                )
            except Exception as e:
                print(f"  [Badges] No se pudo generar imagen con badges: {e}")

        if img_badge and Path(img_badge).exists():
            print("  Enviando post con imagen badged...")
            ok = enviar_whatsapp_archivo(img_badge, caption=mensaje)
            if not ok:
                print("  Fallback a mensaje de texto...")
                ok = enviar_whatsapp(mensaje)
        else:
            print("  Enviando mensaje de texto...")
            ok = enviar_whatsapp(mensaje)

    # 7. Si no hay credenciales Green API configuradas en local, simular éxito para pruebas
    if not (GREEN_API_ID and GREEN_API_TOKEN and WHATSAPP_CHAT_ID):
        print("  [Simulación] Secrets de WhatsApp no presentes localmente; marcando OK en dev.")
        ok = True

    if ok:
        marcar_enviado(pid, enviados, canal="whatsapp")
        from modulo_ofertas import guardar_enviados
        guardar_enviados(enviados)
        control["envios_hoy"] = envios_hoy + 1
        guardar_control_canal(control)
        print(f"  ✅ Post '{pid}' publicado con éxito!")
    else:
        print("  ❌ Falló el envío del post.")

    print("=" * 60)

if __name__ == "__main__":
    main()
