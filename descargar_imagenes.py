#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Normalizador de Imágenes
Descarga imágenes externas a local y reporta faltantes para generación por IA.

Uso: python descargar_imagenes.py
"""
import json, time, sys, io, re, unicodedata
from pathlib import Path
import requests

# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE     = Path(__file__).parent
IMG_DIR  = BASE / "img"
IMG_DIR.mkdir(exist_ok=True)
LOG_DIR  = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_IMG  = LOG_DIR / "imagenes.log"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

# ─── Utilidades ───────────────────────────────────────────────────────────────

def log(msg):
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_IMG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(f"  {msg}")


def slug_img(nombre):
    """Genera filename seguro desde nombre de producto."""
    s = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:50] if s else "produto"


def descargar_imagen(url, dest_path, reintentos=2):
    """Descarga imagen URL a dest_path. Retorna True si OK."""
    for intento in range(1, reintentos + 2):
        try:
            r = requests.get(url, headers=UA, timeout=15, stream=True)
            if r.status_code == 200:
                content_type = r.headers.get("Content-Type", "")
                # Aceptar cualquier imagen
                if "image" in content_type or any(ext in url.lower() for ext in [".jpg",".jpeg",".png",".webp",".gif"]):
                    with open(dest_path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    if dest_path.stat().st_size > 500:  # > 500 bytes = imagen real
                        return True
                    else:
                        dest_path.unlink(missing_ok=True)
            if intento <= reintentos:
                time.sleep(1)
        except Exception as e:
            if intento > reintentos:
                log(f"    ERROR descargando {url[:60]}: {e}")
            else:
                time.sleep(1)
    return False


def ext_from_url(url):
    """Extrae extension de imagen de la URL."""
    for ext in [".webp", ".jpg", ".jpeg", ".png", ".gif"]:
        if ext in url.lower():
            return ext
    return ".jpg"


# ─── Crear placeholder.png ────────────────────────────────────────────────────

def crear_placeholder():
    """Crea img/placeholder.png simple con PIL o falla silenciosamente."""
    placeholder = IMG_DIR / "placeholder.png"
    if placeholder.exists():
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (400, 300), color=(220, 220, 220))
        draw = ImageDraw.Draw(img)
        # Fondo gris claro, texto CRIBA centrado
        draw.rectangle([0, 0, 399, 299], fill=(220, 220, 220))
        draw.rectangle([10, 10, 389, 289], outline=(180, 180, 180), width=2)
        draw.text((200, 130), "CRIBA", fill=(120, 120, 120), anchor="mm")
        draw.text((200, 165), "Imagen no disponible", fill=(150, 150, 150), anchor="mm")
        img.save(placeholder)
        print(f"  placeholder.png criado com PIL")
    except ImportError:
        # Crear PNG mínimo válido sin PIL (1x1 pixel gris)
        import struct, zlib
        def png_chunk(tipo, datos):
            c = struct.pack(">I", len(dados)) + tipo + datos
            c += struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
            return c
        # PNG 1x1 cinza
        w, h = 1, 1
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        raw = b"\x00" + bytes([200, 200, 200])  # filtro + RGB gris
        idat = zlib.compress(raw)
        png = sig + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", idat) + png_chunk(b"IEND", b"")
        placeholder.write_bytes(png)
        print("  placeholder.png criado (PNG minimo)")


# ─── Procesar manual.json ─────────────────────────────────────────────────────

def procesar_manuales():
    """Descarga imágenes externas de manual.json a img/."""
    f = BASE / "manual.json"
    if not f.exists():
        return []

    manuales = json.loads(f.read_text(encoding="utf-8"))
    ok = 0
    faltantes = []
    modificado = False
    vistos = {}  # nombre -> ruta local (cache para duplicados)

    for prod in manuales:
        nombre  = prod.get("nombre", "Produto")
        imagen  = prod.get("imagen", "")

        # Ya es local
        if imagen and not imagen.startswith("http"):
            if (BASE / imagen).exists():
                continue  # OK
            else:
                # Referencia local pero archivo no existe
                faltantes.append({"id": slug_img(nombre), "nombre": nombre,
                                   "razon": f"archivo local no encontrado: {imagen}"})
                continue

        # Cache de nombre ya procesado
        slug = slug_img(nombre)
        if slug in vistos:
            if vistos[slug]:  # ya fue descargado OK
                prod["imagen"] = vistos[slug]
                modificado = True
            continue

        # Descargar imagen externa
        if imagen and imagen.startswith("http"):
            ext      = ext_from_url(imagen)
            dest     = IMG_DIR / f"{slug}{ext}"
            print(f"  Descargando: {nombre[:45]}...")
            if descargar_imagen(imagen, dest):
                ruta_local = f"img/{dest.name}"
                prod["imagen"] = ruta_local
                vistos[slug]   = ruta_local
                modificado = True
                ok += 1
                log(f"OK: {nombre[:50]} -> {ruta_local}")
            else:
                prod["imagen_faltante"] = True
                vistos[slug] = None
                faltantes.append({"id": slug, "nombre": nombre, "razon": "descarga fallida", "url_original": imagen})
                log(f"FALLO: {nombre[:50]} (URL: {imagen[:60]})")
            time.sleep(1)
        elif not imagen:
            prod["imagen_faltante"] = True
            faltantes.append({"id": slug, "nombre": nombre, "razon": "sin imagen"})

    if modificado:
        f.write_text(json.dumps(manuales, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  manual.json actualizado ({ok} imagenes descargadas)")

    return faltantes


# ─── Procesar productos.json ──────────────────────────────────────────────────

def procesar_productos():
    """Descarga imágenes externas de productos.json a img/."""
    f = BASE / "productos.json"
    if not f.exists():
        return []

    data       = json.loads(f.read_text(encoding="utf-8"))
    productos  = data.get("productos", [])
    ok = 0
    faltantes = []
    modificado = False

    for prod in productos:
        nombre  = prod.get("nombre", "Produto")
        pid     = prod.get("id", slug_img(nombre))
        imagen  = prod.get("imagen", "")

        if imagen and not imagen.startswith("http"):
            if (BASE / imagen).exists():
                continue
            else:
                faltantes.append({"id": pid, "nombre": nombre,
                                   "razon": f"archivo local no encontrado: {imagen}"})
                continue

        if imagen and imagen.startswith("http"):
            ext  = ext_from_url(imagen)
            dest = IMG_DIR / f"{pid}{ext}"
            print(f"  Descargando productos.json: {nombre[:45]}...")
            if descargar_imagen(imagen, dest):
                ruta_local = f"img/{dest.name}"
                prod["imagen"] = ruta_local
                modificado = True
                ok += 1
                log(f"OK (productos.json): {nombre[:50]} -> {ruta_local}")
            else:
                prod["imagen_faltante"] = True
                faltantes.append({"id": pid, "nombre": nombre, "razon": "descarga fallida", "url_original": imagen})
                log(f"FALLO (productos.json): {nombre[:50]}")
            time.sleep(1)
        elif not imagen:
            prod["imagen_faltante"] = True
            faltantes.append({"id": pid, "nombre": nombre, "razon": "sin imagen"})

    if modificado:
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  productos.json actualizado ({ok} imagenes descargadas)")

    return faltantes


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  CRIBA · Normalizador de Imágenes")
    print("=" * 60)

    print("\n[1/4] Criando placeholder.png...")
    crear_placeholder()

    print("\n[2/4] Procesando manual.json...")
    faltantes_manual = procesar_manuales()

    print("\n[3/4] Procesando productos.json...")
    faltantes_prod = procesar_productos()

    # Deduplicar faltantes por id
    todos_faltantes = {}
    for f in faltantes_manual + faltantes_prod:
        todos_faltantes[f["id"]] = f

    faltantes = list(todos_faltantes.values())

    print("\n" + "=" * 60)
    # Contar OK
    imgs_locales = list(IMG_DIR.glob("*.*"))
    imgs_ok = [i for i in imgs_locales if i.name != "placeholder.png" and i.stat().st_size > 500]
    print(f"  Imagenes locales en img/: {len(imgs_ok)}")
    print(f"  Faltantes: {len(faltantes)}")
    print("=" * 60)

    if faltantes:
        print("\n⚠️  PRODUCTOS QUE NECESITAN IMAGEN GENERADA POR IA:")
        print("-" * 60)
        for item in faltantes:
            print(f"  ID: {item['id']}")
            print(f"  Nombre: {item['nombre']}")
            print(f"  Razón: {item['razon']}")
            print()
    else:
        print("\n✅ Todos los productos tienen imagen local.")

    print("=" * 60)
    log(f"Completado: {len(imgs_ok)} OK, {len(faltantes)} faltantes")


if __name__ == "__main__":
    main()
