#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Editor de Imagen con Badges Estilo Ninja (editar_imagen.py)
===================================================================
Descarga la imagen del producto y genera los badges idénticos al formato Ninja:
  - Badge superior izquierdo: "🎟️ [CÓDIGO]" con fondo naranja (#FF5C1C) y texto blanco/negro
  - Barra inferior semi-transparente (#0B0F14 a 85% opacidad):
      "💠 PIX -[X]%  |  🔥 -[desc]%"
  - Guarda el resultado en img/envios/<codigo>.jpg
  - Si la descarga o edición falla, retorna None (para fallback a imagen original o texto).

Uso: python editar_imagen.py
"""
import io, re, sys, os
from pathlib import Path
import requests

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

# UTF-8 fix for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = Path(__file__).parent
ENVIOS_DIR = BASE / "img" / "envios"
ENVIOS_DIR.mkdir(parents=True, exist_ok=True)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
}

def obtener_fuente(size=24, bold=True):
    """Carga una fuente TTF del sistema o usa la fuente por defecto de Pillow."""
    font_paths = [
        # Windows
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        # Linux (GitHub Actions)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def descargar_imagen(url):
    """Descarga la imagen desde URL con reintentos y retorna objeto PIL.Image."""
    if not url or not PIL_DISPONIBLE:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=12)
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content))
            return img.convert("RGB")
    except Exception as e:
        print(f"  [Editor Imagen] Error descargando {url[:50]}: {e}")
    return None

def procesar_imagen_ninja(url_imagen, codigo_archivo, cupon=None, pix_pct=None, desc_pct=None):
    """
    Descarga la imagen original, aplica los badges estilo Ninja y la guarda en img/envios/<codigo>.jpg.
    Retorna Path de la imagen guardada o None si falla.
    """
    if not PIL_DISPONIBLE:
        print("  [Editor Imagen] PIL/Pillow no está disponible.")
        return None
    if not url_imagen:
        return None

    img = descargar_imagen(url_imagen)
    if not img:
        return None

    try:
        # Asegurar tamaño estándar cómodo (mínimo 600x600, manteniendo aspecto o expandiendo)
        w, h = img.size
        target_w = max(600, w)
        target_h = max(600, h)

        # Si es pequeña, redimensionar suavemente
        if w < 600 or h < 600:
            ratio = max(600.0 / w, 600.0 / h)
            new_w, new_h = int(w * ratio), int(h * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            w, h = new_w, new_h

        # Crear capa de dibujo
        draw = ImageDraw.Draw(img, "RGBA")

        # 1. BADGE SUPERIOR IZQUIERDO: Cupón activo (Fondo naranja brillante estilo Ninja)
        if cupon and str(cupon).strip():
            txt_cupon = f"CUPOM: {str(cupon).strip().upper()}"
            font_badge = obtener_fuente(size=int(h * 0.045), bold=True)
            
            # Medir texto
            bbox = font_badge.getbbox(txt_cupon)
            bw = (bbox[2] - bbox[0]) + 32
            bh = (bbox[3] - bbox[1]) + 20

            bx, by = 24, 24
            # Fondo naranja con bordes redondeados
            draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=(255, 92, 28, 245))
            # Texto blanco nítido
            draw.text((bx + 16, by + 8), txt_cupon, fill=(255, 255, 255, 255), font=font_badge)

        # 2. BARRA INFERIOR: Descuento Pix + Porcentaje total de ahorro
        partes_inferiores = []
        if pix_pct and int(pix_pct) > 0:
            partes_inferiores.append(f"PIX -{int(pix_pct)}%")
        if desc_pct and float(desc_pct) > 0:
            partes_inferiores.append(f"-{int(round(float(desc_pct)))}% OFF")

        if partes_inferiores:
            txt_barra = "  |  ".join(partes_inferiores)
            font_barra = obtener_fuente(size=int(h * 0.05), bold=True)
            
            bar_height = int(h * 0.12)
            bar_y = h - bar_height

            # Fondo negro semi-transparente
            draw.rectangle([0, bar_y, w, h], fill=(11, 15, 20, 220))
            
            # Borde superior sutil naranja
            draw.line([(0, bar_y), (w, bar_y)], fill=(255, 92, 28, 200), width=3)

            # Centrar texto en la barra inferior
            bbox_b = font_barra.getbbox(txt_barra)
            tw = bbox_b[2] - bbox_b[0]
            th = bbox_b[3] - bbox_b[1]
            tx = (w - tw) // 2
            ty = bar_y + (bar_height - th) // 2 - 2

            # Texto en verde brillante / blanco
            draw.text((tx, ty), txt_barra, fill=(141, 255, 182, 255), font=font_barra)

        # Guardar en img/envios/<codigo>.jpg
        salida_path = ENVIOS_DIR / f"{codigo_archivo}.jpg"
        img.save(salida_path, "JPEG", quality=90, optimize=True)
        return salida_path

    except Exception as e:
        print(f"  [Editor Imagen] Error aplicando badges a {codigo_archivo}: {e}")
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("  CRIBA · TEST EDITOR DE IMAGEN NINJA")
    print("=" * 60)
    # Probar con una imagen de muestra
    url_test = "https://http2.mlstatic.com/D_Q_NP_2X_792279-MLA99822565951_112025-AB.webp"
    p = procesar_imagen_ninja(url_test, "test_ninja", cupon="TECH20", pix_pct=5, desc_pct=43)
    if p and p.exists():
        print(f"[OK] Imagen generada con éxito: {p} ({p.stat().st_size} bytes)")
    else:
        print("[ERROR] No se pudo generar la imagen de test.")
