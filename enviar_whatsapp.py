#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Envío automático a WhatsApp via Green API
==================================================
Usa secrets de entorno: GREEN_API_ID, GREEN_API_TOKEN, WHATSAPP_CHAT_ID

Si los secrets no están configurados → salta sin error.

Uso: python enviar_whatsapp.py
"""
import json, sys, io, os, time
import requests
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).parent

# ─── Secrets (vía entorno o valores directos) ──────────────────────────────────
GREEN_API_ID    = os.environ.get("GREEN_API_ID", "")
GREEN_API_TOKEN = os.environ.get("GREEN_API_TOKEN", "")
WHATSAPP_CHAT_ID = os.environ.get("WHATSAPP_CHAT_ID", "")
# Formato chatId Green API:
#   Grupo:    "120363XXXXXXXXXX@g.us"
#   Contacto: "5491199999999@c.us"


# ─── Green API ────────────────────────────────────────────────────────────────

def enviar_whatsapp(mensaje, chat_id=None):
    """
    Envía un mensaje de texto a WhatsApp via Green API.
    Retorna True si OK.
    """
    iid   = GREEN_API_ID.strip()
    token = GREEN_API_TOKEN.strip()
    cid   = (chat_id or WHATSAPP_CHAT_ID).strip()

    if not iid or not token or not cid:
        print("  [WhatsApp] Secrets no configurados — saltando")
        return False

    url = f"https://api.green-api.com/waInstance{iid}/sendMessage/{token}"
    payload = {"chatId": cid, "message": mensaje}

    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200 and r.json().get("idMessage"):
            return True
        else:
            print(f"  [WhatsApp] Error {r.status_code}: {r.text[:150]}")
            return False
    except Exception as e:
        print(f"  [WhatsApp] Excepcion: {e}")
        return False


def enviar_whatsapp_archivo(ruta_archivo, caption="", chat_id=None):
    """
    Envía una imagen local a WhatsApp con caption via Green API sendFileByUpload.
    Retorna True si OK.
    """
    iid   = GREEN_API_ID.strip()
    token = GREEN_API_TOKEN.strip()
    cid   = (chat_id or WHATSAPP_CHAT_ID).strip()

    if not iid or not token or not cid:
        print("  [WhatsApp] Secrets no configurados — saltando")
        return False

    p = Path(ruta_archivo)
    if not p.exists():
        print(f"  [WhatsApp] Archivo no existe: {ruta_archivo}")
        return False

    url = f"https://api.green-api.com/waInstance{iid}/sendFileByUpload/{token}"
    payload = {"chatId": cid, "caption": caption}

    try:
        with open(p, "rb") as f:
            files = [("file", (p.name, f, "image/jpeg"))]
            r = requests.post(url, data=payload, files=files, timeout=30)
            if r.status_code == 200 and r.json().get("idMessage"):
                return True
            else:
                print(f"  [WhatsApp Archivo] Error {r.status_code}: {r.text[:150]}")
                return False
    except Exception as e:
        print(f"  [WhatsApp Archivo] Excepcion: {e}")
        return False


def verificar_green_api():
    """Verifica que la instancia de Green API esté activa."""
    iid   = GREEN_API_ID.strip()
    token = GREEN_API_TOKEN.strip()
    if not iid or not token:
        return False
    try:
        url = f"https://api.green-api.com/waInstance{iid}/getStateInstance/{token}"
        r = requests.get(url, timeout=10)
        state = r.json().get("stateInstance", "")
        print(f"  [WhatsApp] Estado instancia: {state}")
        return state == "authorized"
    except Exception as e:
        print(f"  [WhatsApp] Error verificando instancia: {e}")
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    from modulo_ofertas import (
        elegir_mejores_ofertas,
        formatear_mensaje,
        cargar_enviados,
        guardar_enviados,
        marcar_enviado,
    )

    print("=" * 55)
    print("  CRIBA · WhatsApp via Green API")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # Verificar configuración
    if not GREEN_API_ID or not GREEN_API_TOKEN or not WHATSAPP_CHAT_ID:
        print("  [WhatsApp] Variables GREEN_API_ID / GREEN_API_TOKEN / WHATSAPP_CHAT_ID no configuradas")
        print("  Agrega los secrets en GitHub: Settings → Secrets → Actions")
        return

    # Verificar instancia activa
    if not verificar_green_api():
        print("  [WhatsApp] Instancia no autorizada — saltando envíos")
        return

    # Leer productos del radar
    prod_f = BASE / "productos.json"
    productos = []
    if prod_f.exists():
        try:
            data = json.loads(prod_f.read_text(encoding="utf-8"))
            productos = data.get("productos", [])
        except Exception:
            pass

    # Leer también achados.json (ofertas frescas de los agentes ML y Amazon)
    achados_f = BASE / "achados.json"
    if achados_f.exists():
        try:
            data_ach = json.loads(achados_f.read_text(encoding="utf-8"))
            achados_raw = data_ach.get("achados", [])
            for a in achados_raw:
                productos.append({
                    "id": a.get("id"),
                    "nombre": a.get("nombre"),
                    "descuento_pct": a.get("desc_pct"),
                    "score": float(a.get("desc_pct") or 0),
                    "vista": {
                        "precio": a.get("precio"),
                        "tienda": a.get("loja"),
                        "url": a.get("url"),
                    },
                    "historico": [
                        {"precio": a.get("precio_anterior", a.get("precio"))},
                        {"precio": a.get("precio")}
                    ]
                })
        except Exception:
            pass

    if not productos:
        print("  productos.json ni achados.json contienen ofertas")
        return

    # Elegir mejores ofertas
    ofertas = elegir_mejores_ofertas(productos, canal="whatsapp")
    if not ofertas:
        print("  Sin ofertas que cumplan los criterios — no se envía nada")
        return

    print(f"  Ofertas seleccionadas: {len(ofertas)}")

    enviados = cargar_enviados()
    enviados_ok = 0

    # Importar generador de imagen con badges ninja
    try:
        from editar_imagen import procesar_imagen_ninja
    except ImportError:
        procesar_imagen_ninja = None

    for idx, oferta in enumerate(ofertas, 1):
        p   = oferta["producto"]
        pid = p.get("id") or p.get("nombre", "")[:40]
        # 1 de cada 3 envíos incluye invitación al grupo
        incluir_grupo = (idx % 3 == 0)
        msg = formatear_mensaje(oferta, modo="texto", incluir_grupo=incluir_grupo)

        print(f"\n  Enviando ({idx}/{len(ofertas)}): {p.get('nombre','?')[:50]}")
        print(f"  Score: {oferta['score']} | {oferta['motivo']}")

        img_url = p.get("imagen") or p.get("imagem")
        img_procesada = None

        # Intentar procesar imagen con badges ninja si hay URL disponible
        if img_url and procesar_imagen_ninja:
            cupon_codigo = oferta.get("cupon", {}).get("codigo") if isinstance(oferta.get("cupon"), dict) else None
            pix_pct = oferta.get("pix_pct", 0)
            desc_pct = oferta.get("desc_pct", 0)
            try:
                img_procesada = procesar_imagen_ninja(
                    url_o_path=img_url,
                    nombre_salida=f"envio_{pid[:20]}",
                    cupon=cupon_codigo,
                    pix_pct=pix_pct,
                    desc_pct=desc_pct
                )
            except Exception as e:
                print(f"  [Badges] Error procesando imagen: {e}")

        ok = False
        if img_procesada and Path(img_procesada).exists():
            print(f"  [Badges] Enviando imagen con badges ninja...")
            ok = enviar_whatsapp_archivo(img_procesada, caption=msg)
            if not ok:
                print(f"  [Fallback] Falló envío con imagen, intentando mensaje de texto...")
                ok = enviar_whatsapp(msg)
        else:
            ok = enviar_whatsapp(msg)

        if ok:
            marcar_enviado(pid, enviados, canal="whatsapp")
            enviados_ok += 1
            print(f"  ✅ Enviado a WhatsApp")
        else:
            print(f"  ❌ Fallo en envío")

        time.sleep(3)  # Anti-flood entre mensajes

    guardar_enviados(enviados)

    print()
    print("=" * 55)
    print(f"  Enviados: {enviados_ok}/{len(ofertas)}")
    print("=" * 55)


if __name__ == "__main__":
    main()
