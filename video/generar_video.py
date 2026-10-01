#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Generador de vídeos de ofertas (generar_video.py)
=========================================================
Convierte una oferta de `achados.json` en un vídeo vertical 9:16 para
TikTok / Reels / Shorts.

── CÓMO FUNCIONA (y por qué así) ────────────────────────────────────────────
La skill `video` (.agents/skills/video/SKILL.md) avisa de dos cosas:

  1. "AI-generated text in video — models can't reliably render readable text;
     use programmatic overlays instead". Por eso el texto NO se genera con IA:
     se pinta en HTML y se renderiza con Chrome. Así el precio sale nítido.
  2. "85% of social video is watched without sound". Por eso TODO lo que vende
     está escrito en pantalla.

Cadena:
    HTML (una plantilla por escena)
        -> Chrome headless --screenshot  -> PNG 1080x1920
        -> ffmpeg (zoompan + xfade)      -> MP4

Por qué Chrome y no Hyperframes: Chromium ya está instalado, así que no hay que
descargar nada. Y por qué ffmpeg: no estaba en el sistema, se instaló en
tools/ffmpeg.

── USO ──────────────────────────────────────────────────────────────────────
    python video/generar_video.py --listar          # ofertas con más gancho
    python video/generar_video.py --uno 3           # vídeo de la oferta nº 3
    python video/generar_video.py --lote 5          # 5 vídeos
"""

import argparse
import html
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent.parent
VIDEO = BASE / "video"
SALIDA = VIDEO / "salida"
TMP = VIDEO / "tmp"
FUENTE = BASE / "achados.json"

# Salida vertical: 9:16 es lo que piden TikTok, Reels y Shorts.
ANCHO, ALTO = 1080, 1920
FPS = 30

CHROME_CANDS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def chrome():
    for c in CHROME_CANDS:
        if Path(c).exists():
            return c
    return None


def ffmpeg():
    for c in (BASE / "tools" / "ffmpeg",):
        if c.exists():
            for f in c.rglob("ffmpeg.exe"):
                return str(f)
    return shutil.which("ffmpeg")


def fmt_precio(v):
    """R$ 1.234,56 — formato brasileño."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    s = f"{n:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def titulo_corto(nombre, limite=58):
    """Recorta el título sin cortar a mitad de palabra."""
    n = str(nombre or "").strip()
    if len(n) <= limite:
        return n
    corte = n[:limite].rsplit(" ", 1)[0]
    return corte + "..."


def elegir_ofertas(limite=5):
    """
    Elige las ofertas con más gancho para vídeo.

    Criterio: primero las que tienen cupón Y pix (dan dos precios que enseñar),
    y dentro de esas, las de mayor descuento. Medido: hay ~30 así sobre 400.
    """
    if not FUENTE.exists():
        return []
    d = json.loads(FUENTE.read_text(encoding="utf-8-sig"))
    todas = d.get("achados", [])

    def gancho(x):
        puntos = 0
        if x.get("ml_precio_cupon"):
            puntos += 100
        if x.get("ml_precio_pix"):
            puntos += 50
        if x.get("envio_gratis"):
            puntos += 10
        try:
            puntos += float(x.get("desc_pct") or 0)
        except (TypeError, ValueError):
            pass
        return puntos

    validas = [x for x in todas if x.get("imagen") and x.get("precio")]
    validas.sort(key=gancho, reverse=True)
    return validas[:limite]


# ══════════════════════════════════════════════════════════════════════════════
#  PLANTILLAS HTML — una por escena
# ══════════════════════════════════════════════════════════════════════════════
CSS_BASE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  width: 1080px; height: 1920px; overflow: hidden;
  font-family: "Segoe UI", Roboto, Arial, sans-serif;
  background: #0b0f14; color: #fff;
  display: flex; flex-direction: column;
  align-items: stretch; justify-content: center;
}
.grad { position: absolute; inset: 0; background:
  radial-gradient(circle at 50% 0%, #12b76a 0%, transparent 55%),
  radial-gradient(circle at 50% 100%, #ff5c1c 0%, transparent 55%),
  #0b0f14; z-index: 0; }
.wrap { position: relative; z-index: 2; padding: 90px 70px; text-align: center; }
.gancho {
  font-size: 132px; font-weight: 900; line-height: 1.02;
  letter-spacing: -4px; text-transform: uppercase;
  color: #ffe066; text-shadow: 0 8px 0 rgba(0,0,0,.35);
}
.sub { font-size: 54px; font-weight: 700; color: #fff; margin-top: 34px; line-height: 1.25; }
.imgbox {
  width: 100%; height: 780px; background: #fff; border-radius: 40px;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
  margin: 40px 0;
}
.imgbox img { max-width: 92%; max-height: 92%; object-fit: contain; }
.titulo { font-size: 52px; font-weight: 700; line-height: 1.22; color: #e8eef6; }
.prezo { font-size: 190px; font-weight: 900; color: #4ade80; line-height: 1; letter-spacing: -6px; }
.prezo small { font-size: 74px; font-weight: 800; }
.de { font-size: 54px; color: #8b9bb0; text-decoration: line-through; margin-bottom: 8px; }
.linea { font-size: 68px; font-weight: 800; margin: 18px 0; }
.pix { color: #38bdf8; }
.cupom { color: #fbbf24; }
.frete { color: #4ade80; font-size: 56px; font-weight: 700; margin-top: 12px; }
.cta {
  margin-top: 60px; background: #12b76a; color: #04120a;
  font-size: 68px; font-weight: 900; padding: 38px 60px; border-radius: 28px;
  display: inline-block;
}
.zap { font-size: 46px; color: #8b9bb0; margin-top: 26px; }
.badge {
  display: inline-block; background: #ff5c1c; color: #fff;
  font-size: 46px; font-weight: 900; padding: 16px 38px; border-radius: 60px;
  margin-bottom: 30px; letter-spacing: 1px;
}
"""


def escena_gancho(o):
    g = (o.get("_gancho") or "OLHA O PRECO DISSO").upper()
    pedazos = g.split(" ")
    if len(pedazos) > 3:
        g = " ".join(pedazos[:3])
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>{CSS_BASE}</style></head><body>
<div class="grad"></div>
<div class="wrap">
  <div class="gancho">{html.escape(g)}</div>
  <div class="sub">Achado do dia<br>com preço conferido</div>
</div></body></html>"""


def escena_produto(o):
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>{CSS_BASE}</style></head><body>
<div class="grad"></div>
<div class="wrap">
  <div class="badge">PREÇO CONFERIDO</div>
  <div class="imgbox"><img src="{html.escape(str(o.get('imagen') or ''))}"></div>
  <div class="titulo">{html.escape(titulo_corto(o.get('nombre')))}</div>
  <div style="margin-top:34px">
    {f'<div class="de">{fmt_precio(o.get("precio_anterior"))}</div>' if o.get('precio_anterior') else ''}
    <div class="prezo">{fmt_precio(o.get('precio')).replace('R$ ', 'R$<small> ')}</small></div>
  </div>
</div></body></html>"""


def pix_real(o):
    """
    Devuelve el precio con Pix SOLO si es realmente más bajo que el precio.

    Detalle detectado al listar: en varias ofertas `ml_precio_pix` es igual al
    `precio` (R$ 98,91 vs R$ 98,91). Enseñar "No Pix: R$ 98,91" cuando es el
    mismo número no es un descuento, es ruido — y encima insinúa un ahorro que
    no existe. Si no baja, no se muestra.
    """
    try:
        pp = float(o.get("ml_precio_pix") or 0)
        pr = float(o.get("precio") or 0)
    except (TypeError, ValueError):
        return None
    if pp > 0 and pr > 0 and pp < pr - 0.5:
        return pp
    return None


def escena_precios(o):
    p = []
    pp = pix_real(o)
    if pp:
        etiqueta = f"  ({o.get('pix')})" if o.get("pix") else ""
        p.append(f'<div class="linea pix">No Pix: {fmt_precio(pp)}{etiqueta}</div>')
    if o.get("ml_precio_cupon"):
        p.append(f'<div class="linea cupom">Com cupom: {fmt_precio(o["ml_precio_cupon"])}</div>')
    if o.get("envio_gratis"):
        p.append('<div class="frete">Frete grátis</div>')
    if not p:
        p.append('<div class="linea pix">Preço caiu de verdade</div>')
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>{CSS_BASE}</style></head><body>
<div class="grad"></div>
<div class="wrap">
  <div class="imgbox" style="height:520px"><img src="{html.escape(str(o.get('imagen') or ''))}"></div>
  <div class="titulo" style="margin-bottom:40px">{html.escape(titulo_corto(o.get('nombre'), 46))}</div>
  {''.join(p)}
</div></body></html>"""


def escena_cta(o):
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>{CSS_BASE}</style></head><body>
<div class="grad"></div>
<div class="wrap">
  <div class="gancho" style="font-size:104px">ISSO CAI<br>TODO DIA</div>
  <div class="sub" style="margin-top:50px">Achadinhos com preço conferido<br>
     no Mercado Livre e na Amazon</div>
  <div class="cta">ENTRA NO GRUPO</div>
  <div class="zap">grátis · sem spam · ofertas todo dia</div>
</div></body></html>"""


def escena_aviso():
    """Escena de cierre: el diferencial. Es lo que nadie más puede decir."""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>{CSS_BASE}</style></head><body>
<div class="grad"></div>
<div class="wrap">
  <div class="gancho" style="font-size:92px;color:#4ade80">PRECO<br>CONFERIDO</div>
  <div class="sub" style="margin-top:56px;font-size:48px;line-height:1.5">
    O cupom que aparece aqui<br><b style="color:#fbbf24">é o cupom que aplica</b><br><br>
    Conferido no checkout de verdade<br>antes de sair no grupo
  </div>
</div></body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER
# ══════════════════════════════════════════════════════════════════════════════
def html_a_png(html_txt, destino, navegador, timeout=60):
    """
    Renderiza HTML a PNG con Chrome headless.

    Se usa Chrome en vez de Pillow porque el texto sale perfecto: fuentes,
    sombras y saltos de línea correctos. Pillow obligaría a colocar cada frase
    a mano y a pelearse con las fuentes.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_txt)
        ruta_html = f.name
    try:
        cmd = [
            navegador, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-sandbox", "--disable-dev-shm-usage",
            f"--screenshot={destino}",
            f"--window-size={ANCHO},{ALTO}",
            f"--default-background-color=00000000",
            "--virtual-time-budget=2500",
            Path(ruta_html).as_uri(),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return Path(destino).exists() and Path(destino).stat().st_size > 1000
    except Exception as e:
        print(f"    [!] chrome fallo: {type(e).__name__}")
        return False
    finally:
        try:
            Path(ruta_html).unlink()
        except Exception:
            pass


def ensamblar(pngs, duraciones, salida, ff):
    """
    Une los PNG en un MP4 con movimiento.

    No es un simple pase de diapositivas: cada escena lleva un zoompan lento
    (acerca la imagen poco a poco) y entre escenas hay un fundido. Eso es lo que
    hace que se vea como vídeo y no como presentación.
    """
    if not ff or not pngs:
        return False
    tmp = TMP / "clips"
    tmp.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, (png, dur) in enumerate(zip(pngs, duraciones)):
        clip = tmp / f"c{i}.mp4"
        frames = max(1, int(dur * FPS))
        # zoompan: zoom lento de 1.0 a 1.08 durante la escena
        vf = (f"scale={ANCHO*2}:{ALTO*2},"
              f"zoompan=z='min(zoom+0.0004,1.10)':d={frames}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={ANCHO}x{ALTO},"
              f"format=yuv420p")
        cmd = [ff, "-y", "-loop", "1", "-i", str(png), "-t", str(dur),
               "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
               "-crf", "20", str(clip)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if not clip.exists():
            print(f"    [!] clip {i} fallo: {r.stderr[-200:]}")
            return False
        clips.append(clip)

    if len(clips) == 1:
        shutil.copy2(clips[0], salida)
        return True

    # Fundido encadenado entre clips
    entradas = []
    for c in clips:
        entradas += ["-i", str(c)]
    filtros, prev = [], "0:v"
    offset = duraciones[0] - 0.5
    for i in range(1, len(clips)):
        salida_lbl = f"v{i}" if i < len(clips) - 1 else "vout"
        filtros.append(
            f"[{prev}][{i}:v]xfade=transition=fade:duration=0.5:offset={offset:.2f}[{salida_lbl}]")
        prev = salida_lbl
        offset += duraciones[i] - 0.5
    cmd = [ff, "-y"] + entradas + [
        "-filter_complex", ";".join(filtros),
        "-map", "[vout]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(salida)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not salida.exists():
        print(f"    [!] ensamblado fallo: {r.stderr[-300:]}")
        return False
    return True


def generar_uno(o, idx, navegador, ff, guion=None):
    print(f"\n  [{idx}] {str(o.get('nombre'))[:56]}")
    print(f"      precio {fmt_precio(o.get('precio'))}"
          + (f" | pix {fmt_precio(o.get('ml_precio_pix'))}" if o.get("ml_precio_pix") else "")
          + (f" | cupom {fmt_precio(o.get('ml_precio_cupon'))}" if o.get("ml_precio_cupon") else ""))

    o = dict(o)
    if guion and guion.get("gancho_0_2s"):
        o["_gancho"] = guion["gancho_0_2s"]

    escenas = [
        (escena_gancho(o), 2.6),
        (escena_produto(o), 5.0),
        (escena_precios(o), 5.5),
        (escena_aviso(), 3.4),
        (escena_cta(o), 4.5),
    ]

    TMP.mkdir(parents=True, exist_ok=True)
    pngs, durs = [], []
    for j, (html_txt, dur) in enumerate(escenas):
        png = TMP / f"e{idx}_{j}.png"
        if html_a_png(html_txt, png, navegador):
            pngs.append(png)
            durs.append(dur)
        else:
            print(f"      [!] escena {j} no renderizo")

    if not pngs:
        print("      RECHAZADO: ninguna escena se pudo renderizar")
        return None

    SALIDA.mkdir(parents=True, exist_ok=True)
    salida = SALIDA / f"oferta_{idx:02d}.mp4"
    if not ensamblar(pngs, durs, salida, ff):
        print("      RECHAZADO: no se pudo ensamblar")
        return None

    kb = salida.stat().st_size / 1024
    dur_total = sum(durs)
    print(f"      OK -> {salida.name}  ({kb:.0f} KB, ~{dur_total:.0f}s, {ANCHO}x{ALTO})")
    return salida


def main():
    ap = argparse.ArgumentParser(description="Genera vídeos verticales de ofertas")
    ap.add_argument("--listar", action="store_true", help="ver las ofertas con más gancho")
    ap.add_argument("--uno", type=int, help="genera el vídeo de esa posición (1..N)")
    ap.add_argument("--lote", type=int, default=0, help="genera N vídeos")
    args = ap.parse_args()

    ofertas = elegir_ofertas(10)

    if args.listar or (not args.uno and not args.lote):
        print("=" * 78)
        print("  OFERTAS CON MÁS GANCHO PARA VÍDEO")
        print("=" * 78)
        for i, o in enumerate(ofertas, 1):
            cup = fmt_precio(o.get("ml_precio_cupon")) if o.get("ml_precio_cupon") else "-"
            pix = fmt_precio(o.get("ml_precio_pix")) if o.get("ml_precio_pix") else "-"
            print(f"  {i:>2}. {str(o.get('nombre'))[:46]:48s}")
            print(f"      {fmt_precio(o.get('precio')):>14s} | pix {pix:>14s} | cupom {cup:>14s} "
                  f"| {o.get('desc_pct')}% OFF")
        print()
        print("  Genera uno con:  python video/generar_video.py --uno 1")
        return 0

    nav = chrome()
    ff = ffmpeg()
    print(f"  chrome: {'OK' if nav else 'NO ENCONTRADO'}")
    print(f"  ffmpeg: {ff or 'NO ENCONTRADO'}")
    if not nav:
        print("  sin Chrome no se puede renderizar el texto")
        return 1

    guiones = {}
    gf = VIDEO / "guiones.json"
    if gf.exists():
        try:
            g = json.loads(gf.read_text(encoding="utf-8-sig"))
            for p in g.get("productos", []):
                guiones[str(p.get("nombre", ""))[:40]] = p
        except Exception:
            pass

    if args.uno:
        i = args.uno - 1
        if not (0 <= i < len(ofertas)):
            print(f"  --uno debe estar entre 1 y {len(ofertas)}")
            return 1
        o = ofertas[i]
        guion = next((v for k, v in guiones.items() if k[:20] in str(o.get("nombre"))), None)
        return 0 if generar_uno(o, args.uno, nav, ff, guion) else 1

    if args.lote:
        hechos = 0
        for i, o in enumerate(ofertas[:args.lote], 1):
            if generar_uno(o, i, nav, ff):
                hechos += 1
        print(f"\n  generados: {hechos}/{args.lote} -> {SALIDA}")
        return 0 if hechos else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
