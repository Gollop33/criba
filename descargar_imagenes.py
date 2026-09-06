#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Pipeline Automático de Imágenes
=======================================
- Lee productos.json y manual.json
- Descarga imágenes externas a img/<id>.jpg (nombres estables)
- Si la imagen ya existe localmente, la omite (no re-descarga)
- Si la descarga falla: imagen → img/placeholder.png, imagen_faltante: true
- Genera faltantes_imagenes.json para revisión/IA
- Notifica por Telegram si hay faltantes (si TELEGRAM_BOT_TOKEN está disponible)
- Registra todo en logs/imagenes.log

Uso: python descargar_imagenes.py
"""
import json, time, sys, io, re, unicodedata, os
from datetime import datetime
from pathlib import Path
import requests

# ─── Fix codificación Windows ──────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE         = Path(__file__).parent
IMG_DIR      = BASE / "img"
LOG_DIR      = BASE / "logs"
LOG_IMG      = LOG_DIR / "imagenes.log"
PLACEHOLDER  = IMG_DIR / "placeholder.png"
FALTANTES_F  = BASE / "faltantes_imagenes.json"

IMG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

# ─── Logger ────────────────────────────────────────────────────────────────────
def log(msg, nivel="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{ts}] [{nivel}] {msg}"
    try:
        with open(LOG_IMG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass
    print(f"  {msg}")


# ─── Crear placeholder.png ─────────────────────────────────────────────────────
def crear_placeholder():
    """Crea img/placeholder.png con PIL, o un PNG mínimo válido si no está disponible."""
    if PLACEHOLDER.exists() and PLACEHOLDER.stat().st_size > 200:
        return  # Ya existe

    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (400, 300), color=(230, 228, 220))
        draw = ImageDraw.Draw(img)
        draw.rectangle([2, 2, 397, 297], outline=(180, 175, 160), width=2)
        # Texto CRIBA centrado
        draw.rectangle([150, 110, 250, 150], fill=(200, 195, 185))
        draw.text((200, 130), "CRIBA", fill=(100, 95, 80), anchor="mm")
        draw.text((200, 175), "Sin imagen", fill=(140, 135, 125), anchor="mm")
        img.save(PLACEHOLDER, "PNG")
        print("  placeholder.png creado (PIL)")
    except ImportError:
        # PNG mínimo 1x1 píxel gris sin PIL
        import struct, zlib
        def chunk(tipo, datos):
            return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
        w, h = 1, 1
        raw = b"\x00" + bytes([210, 207, 200])  # filtro + RGB
        PLACEHOLDER.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )
        print("  placeholder.png creado (PNG minimo)")


# ─── Utilidades ────────────────────────────────────────────────────────────────
def slug_estable(pid, nombre):
    """Genera filename estable: usa id del producto si existe, sino slug del nombre."""
    if pid and pid != "?":
        s = re.sub(r"[^a-z0-9\-]", "", pid.lower())[:50]
        if s:
            return s
    s = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:50] if s else "produto"


def ext_url(url):
    """Infiere extensión desde la URL."""
    url_lower = url.lower().split("?")[0]
    for ext in [".webp", ".jpg", ".jpeg", ".png", ".gif"]:
        if url_lower.endswith(ext):
            return ext
    # KaBuM, Pichau, etc. sirven imágenes sin extensión
    return ".jpg"


def imagen_local_valida(ruta_str):
    """Devuelve True si la ruta local existe y pesa más de 1KB."""
    if not ruta_str or ruta_str.startswith("http"):
        return False
    p = BASE / ruta_str
    return p.exists() and p.stat().st_size > 1024


def descargar(url, dest, reintentos=2):
    """Descarga url → dest. Retorna True si OK."""
    for intento in range(1, reintentos + 2):
        try:
            r = requests.get(url, headers=UA, timeout=18, stream=True)
            if r.status_code == 200:
                ct = r.headers.get("Content-Type", "")
                if "image" in ct or any(e in url.lower() for e in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    if dest.stat().st_size > 1024:
                        return True
                    dest.unlink(missing_ok=True)
            if intento <= reintentos:
                time.sleep(1.5)
        except Exception as e:
            log(f"    intento {intento} fallido: {e}", "WARN")
            if intento <= reintentos:
                time.sleep(1.5)
    return False


# ─── Procesar productos de un JSON ────────────────────────────────────────────
def procesar_lista(items, fuente="?"):
    """
    Procesa una lista de dicts de productos.
    Descarga imágenes externas, usa nombres estables.
    Retorna (items_modificados, lista_faltantes).
    """
    ok_count = 0
    faltantes = []
    modificado = False
    vistos = {}  # slug → ruta_local (cache para duplicados)

    for prod in items:
        nombre = prod.get("nombre", "Produto")
        pid    = prod.get("id") or prod.get("ean") or ""
        imagen = prod.get("imagen", "")

        slug = slug_estable(str(pid), nombre)

        # ── Ya tiene imagen local válida ──────────────────────────────────────
        if imagen_local_valida(imagen):
            ok_count += 1
            continue  # No tocar

        # ── Cache: mismo slug ya procesado ────────────────────────────────────
        if slug in vistos:
            ruta_cached = vistos[slug]
            if ruta_cached and prod.get("imagen") != ruta_cached:
                prod["imagen"] = ruta_cached
                prod.pop("imagen_faltante", None)
                modificado = True
            elif not ruta_cached:
                prod["imagen"] = "img/placeholder.png"
                prod["imagen_faltante"] = True
                modificado = True
            continue

        # ── Imagen externa: descargar ─────────────────────────────────────────
        if imagen and imagen.startswith("http"):
            ext  = ext_url(imagen)
            dest = IMG_DIR / f"{slug}{ext}"

            print(f"  [{fuente}] Descargando: {nombre[:45]}...")
            if descargar(imagen, dest):
                ruta_local = f"img/{dest.name}"
                prod["imagen"] = ruta_local
                prod.pop("imagen_faltante", None)
                vistos[slug] = ruta_local
                ok_count += 1
                modificado = True
                log(f"OK [{fuente}] {nombre[:50]} → {ruta_local}")
                time.sleep(0.8)
            else:
                prod["imagen"] = "img/placeholder.png"
                prod["imagen_faltante"] = True
                vistos[slug] = None
                modificado = True
                log(f"FALLO [{fuente}] {nombre[:50]} (URL: {imagen[:60]})", "ERROR")
                faltantes.append(build_faltante(prod))
                time.sleep(0.8)

        # ── Sin imagen en absoluto ────────────────────────────────────────────
        elif not imagen:
            prod["imagen"] = "img/placeholder.png"
            prod["imagen_faltante"] = True
            vistos[slug] = None
            modificado = True
            log(f"SIN-IMAGEN [{fuente}] {nombre[:50]}", "WARN")
            faltantes.append(build_faltante(prod))

        # ── Imagen local referenciada pero archivo no existe ──────────────────
        else:
            prod["imagen"] = "img/placeholder.png"
            prod["imagen_faltante"] = True
            vistos[slug] = None
            modificado = True
            log(f"ARCHIVO-LOCAL-FALTANTE [{fuente}] {nombre[:50]}: {imagen}", "WARN")
            faltantes.append(build_faltante(prod))

    return items, ok_count, faltantes, modificado


def build_faltante(prod):
    """Construye un registro de faltante para el reporte."""
    # Buscar url_amazon en las tiendas del producto
    url_amazon = ""
    url_ml = prod.get("url_ml", "")
    for tienda_key in ["url", "url_amazon"]:
        v = prod.get(tienda_key, "")
        if v and "amazon" in v:
            url_amazon = v
            break

    return {
        "id":            prod.get("id") or prod.get("ean") or slug_estable("", prod.get("nombre", "")),
        "nombre":        prod.get("nombre", ""),
        "imagen_actual": prod.get("imagen", ""),
        "url_ml":        url_ml,
        "url_amazon":    url_amazon,
    }


# ─── Notificación Telegram ─────────────────────────────────────────────────────
def notificar_telegram(n_faltantes):
    """Envía mensaje Telegram si hay imágenes faltantes. Usa vars de entorno."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or n_faltantes == 0:
        return

    msg = (
        f"🖼 CRIBA: hay {n_faltantes} producto(s) sin imagen.\n"
        f"Revisar faltantes_imagenes.json en el repositorio.\n"
        f"https://github.com/Gollop33/criba/blob/main/faltantes_imagenes.json"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10,
        )
        if r.status_code == 200:
            print(f"  [Telegram] Notificacion enviada: {n_faltantes} faltantes")
        else:
            print(f"  [Telegram] Error: {r.status_code}")
    except Exception as e:
        print(f"  [Telegram] Fallo: {e}")


# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 62)
    print("  CRIBA · Pipeline Automático de Imágenes")
    print(f"  {ahora}")
    print("=" * 62)

    # 1. Placeholder
    print("\n[1/4] Verificando placeholder.png...")
    crear_placeholder()

    todos_faltantes = []
    total_ok = 0

    # 2. manual.json
    print("\n[2/4] Procesando manual.json...")
    manual_f = BASE / "manual.json"
    if manual_f.exists():
        manuales = json.loads(manual_f.read_text(encoding="utf-8"))
        manuales, ok, falt, mod = procesar_lista(manuales, fuente="manual")
        total_ok += ok
        todos_faltantes.extend(falt)
        if mod:
            manual_f.write_text(json.dumps(manuales, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  manual.json guardado ({ok} OK, {len(falt)} faltantes)")
    else:
        print("  manual.json no encontrado")

    # 3. productos.json
    print("\n[3/4] Procesando productos.json...")
    prod_f = BASE / "productos.json"
    if prod_f.exists():
        data = json.loads(prod_f.read_text(encoding="utf-8"))
        lista = data.get("productos", []) if isinstance(data, dict) else data
        lista, ok, falt, mod = procesar_lista(lista, fuente="productos")
        total_ok += ok
        todos_faltantes.extend(falt)
        if mod:
            if isinstance(data, dict):
                data["productos"] = lista
            else:
                data = lista
            prod_f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  productos.json guardado ({ok} OK, {len(falt)} faltantes)")
    else:
        print("  productos.json no encontrado aun (normal si el bot no ha corrido)")

    # 4. Deduplicar faltantes y generar reporte
    print("\n[4/4] Generando reporte de faltantes...")
    vistos_ids = set()
    faltantes_unicos = []
    for f in todos_faltantes:
        if f["id"] not in vistos_ids:
            vistos_ids.add(f["id"])
            faltantes_unicos.append(f)

    reporte = {
        "generado_en": ahora,
        "total_faltantes": len(faltantes_unicos),
        "instruccion": "Generar imagen con IA y guardar en img/<id>.jpg, luego actualizar manual.json",
        "faltantes": faltantes_unicos,
    }
    FALTANTES_F.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. Notificación Telegram
    if faltantes_unicos:
        notificar_telegram(len(faltantes_unicos))

    # ─── Resumen ───────────────────────────────────────────────────────────────
    imgs_en_disco = [
        p for p in IMG_DIR.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        and p.name != "placeholder.png"
        and p.stat().st_size > 1024
    ]

    print()
    print("=" * 62)
    print(f"  Imágenes en img/:       {len(imgs_en_disco)}")
    print(f"  Descargadas OK hoy:     {total_ok}")
    print(f"  Faltantes:              {len(faltantes_unicos)}")
    print(f"  placeholder.png:        {'OK' if PLACEHOLDER.exists() else 'FALTA'}")
    print("=" * 62)

    if faltantes_unicos:
        print("\n  PRODUCTOS SIN IMAGEN (ver faltantes_imagenes.json):")
        for item in faltantes_unicos:
            print(f"  - {item['id'][:50]}")
            print(f"    {item['nombre'][:60]}")
    else:
        print("\n  Todos los productos tienen imagen local. ")

    log(f"Pipeline completo: {total_ok} OK, {len(faltantes_unicos)} faltantes")
    return len(faltantes_unicos)  # exit code 0 si todo bien (ignorado por GH Actions)


if __name__ == "__main__":
    main()
