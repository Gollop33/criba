#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Publicador de Próximo Post (publicar_proximo.py)
=========================================================
Publica EXACTAMENTE 1 post por ejecución.

¿Por qué 1 y no 2 con sleep?
---------------------------
La cadencia de 7-8 min la aporta un cron EXTERNO (cron-job.org) que llama a la
API `workflow_dispatch` de GitHub cada 7-8 min. El `schedule` nativo de GitHub
NO sirve para esto: está medido que se estrangula y entrega una ejecución cada
~3 horas (mediana 174 min en las últimas 60 corridas), no cada 15 min.

Por eso el publicador NO duerme: si durmiera 7.5 min dentro del job, cada
ejecución ocuparía el runner 10 min y la cadencia dependería otra vez del cron.

Salvaguardas implementadas
--------------------------
- MIN_GAP_MIN: si el último envío real fue hace menos de N minutos, no publica.
  Protege contra disparos duplicados/reintentos del cron externo y contra
  ejecuciones solapadas.
- Ventana horaria Brasília 8h-22h.
- Límite diario de calentamiento del canal.
- Solo productos con foto (nunca posts genéricos de cupones).
- Regla de Oro: se aborta cualquier post cuyo link sea un redirect /go/.
"""

import json
import os
import sys
import io
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

# Tag de afiliado Mercado Livre (Regla de Oro)
ML_TAG = "ja20250119201346"

# Cadencia mínima entre envíos (minutos). El cron externo dispara cada 7-8 min;
# si por reintento/solape llega antes, este guardia evita duplicar.
MIN_GAP_MIN = float(os.environ.get("MIN_GAP_MIN", "6"))

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


# ─── Control de calentamiento del canal ───────────────────────────────────────

def cargar_control_canal():
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not CONTROL_CANAL_JSON.exists():
        return {
            "fecha_inicio": datetime.now(timezone.utc).isoformat(),
            "dias_activo": 3,
            "envios_hoy": 0,
            "fecha_hoy": hoy,
        }
    try:
        data = json.loads(CONTROL_CANAL_JSON.read_text(encoding="utf-8"))
        if data.get("fecha_hoy") != hoy:
            data["fecha_hoy"] = hoy
            data["envios_hoy"] = 0
            data["dias_activo"] = data.get("dias_activo", 1) + 1
        return data
    except Exception:
        return {"dias_activo": 3, "envios_hoy": 0, "fecha_hoy": hoy}


def guardar_control_canal(data):
    try:
        CONTROL_CANAL_JSON.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def limite_diario_calentamiento(dias_activo):
    if dias_activo <= 1:
        return 20
    if dias_activo == 2:
        return 40
    return 120  # 14 h de ventana * ~8 posts/h ≈ 112


def horario_permitido_brt():
    """True si la hora actual en Brasília (UTC-3) está entre 8 y 22h."""
    brt_hour = (datetime.now(timezone.utc).hour - 3) % 24
    return 8 <= brt_hour < 22


# ─── Guardia de cadencia ──────────────────────────────────────────────────────

def ultimo_envio_utc(enviados):
    """Devuelve el datetime (UTC) del envío más reciente registrado, o None."""
    ultimo = None
    for entry in enviados.values():
        if not isinstance(entry, dict):
            continue
        canales = entry.get("canales")
        if isinstance(canales, dict) and canales.get("whatsapp"):
            ts_str = canales["whatsapp"]
        else:
            ts_str = entry.get("ts", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ultimo is None or ts > ultimo:
            ultimo = ts
    return ultimo


# ─── Publicación ──────────────────────────────────────────────────────────────

def resolver_link_afiliado(url, loja, cookie_portal):
    """
    Aplica la Regla de Oro. Nunca devuelve un link /go/ (no monetiza).
    Prioridad ML: meli.la existente > generar meli.la > url con tag #D[A:...]
    """
    if not url:
        return ""
    url_l = url.lower()

    if "/go/" in url_l:
        return None  # señal de aborto

    if "meli.la" in url_l:
        print("  [meli.la] La URL ya es un enlace corto oficial. No se re-acorta.")
        return url

    if "mercado" not in loja.lower():
        return url

    if cookie_portal:
        try:
            from melila_api import generar_melila
            short_ml = generar_melila(url, cookie_str=cookie_portal, tag=ML_TAG)
            if short_ml:
                print(f"  [meli.la] Enlace corto oficial generado: {short_ml}")
                return short_ml
            print("  [meli.la] No se pudo generar (cookie vencida?). Usando URL con tag.")
        except Exception as e:
            print(f"  [meli.la] Error al generar link corto: {e}")
    else:
        print("  [meli.la] ML_PORTAL_COOKIE ausente. Usando URL con tag.")

    if ML_TAG not in url:
        sep = "" if "#" in url else "#"
        return f"{url}{sep}D[A:{ML_TAG}]"
    return url


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

    from modulo_ofertas import cargar_enviados, marcar_enviado, guardar_enviados, ya_enviado
    enviados = cargar_enviados()

    post_a_enviar = None
    for p in posts:
        if p.get("tipo") == "cupons_loja":
            continue  # solo productos con foto
        pid = p.get("id_post") or p.get("titulo", "")[:40]
        if not ya_enviado(pid, enviados, canal="whatsapp"):
            post_a_enviar = p
            break

    if not post_a_enviar:
        print("  [Fila] Todos los posts ya fueron enviados en la ventana anti-repetición.")
        return False, None, None

    pid = post_a_enviar.get("id_post") or post_a_enviar.get("titulo", "")[:40]
    loja = post_a_enviar.get("loja", "Loja")
    titulo = post_a_enviar.get("titulo", "")
    url = post_a_enviar.get("url", "")
    print(f"\n  🎯 Post seleccionado: [{loja.upper()}] {titulo[:55]}")
    print(f"     Link base: {url}")

    # Regla de Oro
    cookie_portal = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    link_final = resolver_link_afiliado(url, loja, cookie_portal)
    if link_final is None:
        print("  ❌ [Regla de Oro] El link es un redirect /go/ que NO monetiza. Post abortado.")
        return False, pid, loja
    if not link_final:
        print("  ❌ [Regla de Oro] Post sin link de afiliado. Abortado.")
        return False, pid, loja

    # Formatear precio y cupón
    precio_raw = post_a_enviar.get("precio", 0)
    cupom = post_a_enviar.get("cupom") or ""
    precio_int = 0
    try:
        precio_int = int(float(precio_raw))
        precio_limpo = str(precio_int)
    except (ValueError, TypeError):
        precio_limpo = str(precio_raw)

    lineas = [f"🔥 {titulo}", ""]
    if precio_int:
        lineas.append(f"💵 R$ {precio_limpo}")
    if cupom:
        lineas.append(f"🎟️ Cupom: {cupom}")
    lineas.append("")
    lineas.append(link_final)
    lineas.append("")
    lineas.append("anúncio")
    mensaje = "\n".join(lineas)

    print("\n--- PREVIEW POST ---")
    print(mensaje)
    print("--- FIN PREVIEW ---\n")

    if es_test:
        return True, pid, loja

    # Enviar con foto si es posible
    import requests as req
    from enviar_whatsapp import enviar_whatsapp, enviar_whatsapp_archivo

    img_url = post_a_enviar.get("imagen")
    img_enviada = False

    if img_url:
        try:
            img_dir = BASE / "img" / "envios"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / f"post_{pid[:15]}.jpg"
            r_img = req.get(img_url, timeout=20)
            if r_img.status_code == 200 and len(r_img.content) > 3000:
                img_path.write_bytes(r_img.content)
                print("  [WhatsApp] Enviando foto del producto con caption...")
                img_enviada = enviar_whatsapp_archivo(img_path, caption=mensaje)
            else:
                print(f"  [WhatsApp] Imagen no válida (HTTP {r_img.status_code}, {len(r_img.content)} bytes).")
        except Exception as e:
            print(f"  [WhatsApp] Error enviando imagen: {e}")

    if img_enviada:
        ok = img_enviada
    else:
        print("  [WhatsApp] Enviando mensaje de texto directo...")
        ok = enviar_whatsapp(mensaje)

    if ok:
        marcar_enviado(pid, enviados, canal="whatsapp")
        guardar_enviados(enviados)
        return True, pid, loja
    return False, pid, loja


def main():
    es_test = "--test" in sys.argv

    print("=" * 60)
    print("  CRIBA · PUBLICADOR (1 post por ejecución)" + (" [MODO TEST]" if es_test else ""))
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} local | "
          f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
    print("=" * 60)

    # 1. Ventana horaria Brasília (8h-22h)
    if not es_test and not horario_permitido_brt():
        print("  [Horario] Fuera de ventana Brasília (8h-22h BRT). Saltando.")
        return

    # 2. Control de calentamiento y límite diario
    control = cargar_control_canal()
    dias = control.get("dias_activo", 3)
    max_dia = limite_diario_calentamiento(dias)
    envios_hoy = control.get("envios_hoy", 0)
    print(f"  • Calentamiento: Día {dias} | Envíos hoy: {envios_hoy}/{max_dia}")

    if not es_test and envios_hoy >= max_dia:
        print(f"  [Límite diario] Cupo alcanzado ({envios_hoy}/{max_dia}). Saltando.")
        return

    # 3. Credenciales Green API
    if not es_test and not (GREEN_API_ID and GREEN_API_TOKEN and WHATSAPP_CHAT_ID):
        print("  ❌ ERROR: Credenciales de Green API no configuradas.")
        return

    # 4. Guardia de cadencia: no publicar si el último envío fue hace < MIN_GAP_MIN
    if not es_test:
        from modulo_ofertas import cargar_enviados
        ultimo = ultimo_envio_utc(cargar_enviados())
        if ultimo is not None:
            delta_min = (datetime.now(timezone.utc) - ultimo).total_seconds() / 60.0
            if delta_min < MIN_GAP_MIN:
                print(f"  [Cadencia] Último envío hace {delta_min:.1f} min "
                      f"(< {MIN_GAP_MIN:.0f} min). Saltando para no duplicar.")
                return
            print(f"  [Cadencia] Último envío hace {delta_min:.1f} min. OK para publicar.")

    # 5. Publicar el siguiente post
    ok, pid, loja = publicar_un_post(es_test=es_test)

    if ok and not es_test:
        control["envios_hoy"] = envios_hoy + 1
        guardar_control_canal(control)
        print(f"  ✅ Publicado [{loja}] {pid} | hoy: {control['envios_hoy']}/{max_dia}")
    elif not ok:
        print("  ⚠️ No se publicó ningún post en esta ejecución.")

    print("=" * 60)


if __name__ == "__main__":
    main()
