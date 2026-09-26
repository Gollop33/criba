#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Publicador en redes sociales (publicar_redes.py)
=========================================================
Publica los achadinhos en Facebook (Página) e Instagram (cuenta profesional)
usando la API OFICIAL de Meta (Graph API).

── LO IMPORTANTE QUE TIENES QUE SABER ───────────────────────────────────────
Facebook e Instagram SÍ se pueden automatizar de forma legítima (y sin riesgo
de baneo) con la Graph API. TikTok NO: su API de publicación exige revisión de
app, y además es una red de VÍDEO, así que un post de imagen no sirve — habría
que generar un vídeo por oferta. Por eso TikTok no está aquí.

NO uses automatizaciones no oficiales (Selenium, bots de terceros) en estas
redes: es la vía rápida a que te cierren las cuentas. La API oficial es la
única forma sostenible.

── QUÉ NECESITAS (una sola vez, 15-20 min) ──────────────────────────────────
1. Una PÁGINA de Facebook (no un perfil) para tu marca.
2. Una cuenta de Instagram PROFESIONAL (Business/Creator).
3. Vincular la cuenta de Instagram a la Página de Facebook.
4. Un token de acceso de página con permisos:
       pages_manage_posts, pages_read_engagement, instagram_basic,
       instagram_content_publish
   Se saca en https://developers.facebook.com/tools/explorer/
   (marca los permisos, "Generate Access Token", y luego extiéndelo a
    token de larga duración en /tools/debugger/)
5. El ID de la Página y el ID de la cuenta de Instagram (se ven en el
   explorador de la API: GET /me/accounts  y  GET /{page-id}?fields=instagram_business_account)

Con eso, pon estos secrets en GitHub:
       META_ACCESS_TOKEN   (el token de página de larga duración)
       META_PAGE_ID        (id de la Página de Facebook)
       IG_USER_ID          (id de la cuenta profesional de Instagram)

── Uso ──────────────────────────────────────────────────────────────────────
    python publicar_redes.py                 # publica el siguiente achado
    python publicar_redes.py --test           # NO publica, solo muestra
    python publicar_redes.py --estado         # comprueba credenciales
"""

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
FILA = BASE / "fila_posts.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
ENVIADOS_REDES = LOG_DIR / "enviados_redes.json"

_env_file = BASE / ".env"
if _env_file.exists():
    try:
        for line in _env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

TOKEN = os.environ.get("META_ACCESS_TOKEN", "").strip()
PAGE_ID = os.environ.get("META_PAGE_ID", "").strip()
IG_ID = os.environ.get("IG_USER_ID", "").strip()
API = "https://graph.facebook.com/v21.0"

HORAS_ANTI_REPESCA = int(os.environ.get("HORAS_ANTI_REDES", "48"))


def hay_credenciales():
    return bool(TOKEN and (PAGE_ID or IG_ID))


def cargar_enviados():
    if not ENVIADOS_REDES.exists():
        return {}
    try:
        return json.loads(ENVIADOS_REDES.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def guardar_enviados(d):
    ENVIADOS_REDES.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def ya_publicado(pid, enviados):
    e = enviados.get(pid)
    if not isinstance(e, dict):
        return False
    try:
        ts = datetime.fromisoformat(str(e.get("ts", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() < HORAS_ANTI_REPESCA * 3600
    except Exception:
        return False


def elegir_post(enviados):
    """El siguiente post de la fila que no se haya publicado en redes."""
    if not FILA.exists():
        return None
    try:
        fila = json.loads(FILA.read_text(encoding="utf-8-sig")).get("fila", [])
    except Exception:
        return None
    for p in fila:
        if p.get("tipo") == "cupons_loja":
            continue
        if not p.get("imagen"):          # sin foto no sirve para IG/FB
            continue
        pid = p.get("id_post") or (p.get("titulo") or "")[:40]
        if not ya_publicado(pid, enviados):
            return p
    return None


def formatear_caption(post):
    """
    Texto para redes. En Instagram el enlace del caption NO es clicable, asi que
    ademas del enlace se anade el gancho del cupon y el precio final.
    """
    titulo = post.get("titulo", "")
    try:
        precio = int(float(post.get("precio") or 0))
    except (TypeError, ValueError):
        precio = 0

    lineas = [f"🔥 {titulo}", ""]
    if post.get("bajada"):
        try:
            antes = int(float(post.get("precio_antes_publicado") or 0))
            if antes > 0:
                lineas.append(f"📉 BAIXOU DE PREÇO: antes R$ {antes}")
        except (TypeError, ValueError):
            pass

    if precio:
        lineas.append(f"💵 R$ {precio}")

    pix = (post.get("pix") or "").strip()
    if pix and pix.lower() not in ("à vista", "a vista", "-"):
        lineas.append(f"⚡ No Pix: {pix}")

    if post.get("envio_gratis"):
        lineas.append("🚚 Frete grátis")

    cupom = post.get("cupom")
    if cupom:
        pct = post.get("cupom_pct")
        lineas.append(f"🎟️ Cupom: {cupom}" + (f" ({float(pct):.0f}% OFF)" if pct else ""))

    # Precio final, si se puede calcular
    try:
        sys.path.insert(0, str(BASE))
        from publicar_proximo import calcular_precio_final
        final, etiqueta = calcular_precio_final(precio, post)
        if final:
            lineas.append("")
            lineas.append(f"✅ Sai por R$ {int(round(final))} com {etiqueta}")
    except Exception:
        pass

    link = post.get("url") or ""
    if link:
        lineas.append("")
        lineas.append(f"🛒 {link}")

    lineas.append("")
    lineas.append("#achadinhos #promoção #desconto #ofertas #brasil")
    return "\n".join(lineas)


def publicar_facebook(post, caption, seco=False):
    """POST /{page-id}/photos con la URL publica de la imagen."""
    if not (TOKEN and PAGE_ID):
        return False, "sin META_PAGE_ID o META_ACCESS_TOKEN"
    img = post.get("imagen")
    datos = {"caption": caption, "access_token": TOKEN}
    if img:
        datos["url"] = img
    endpoint = f"{API}/{PAGE_ID}/photos" if img else f"{API}/{PAGE_ID}/feed"
    if not img:
        datos["message"] = caption
        datos.pop("caption", None)
    if seco:
        return True, f"[SECO] POST {endpoint}"
    try:
        import requests
        r = requests.post(endpoint, data=datos, timeout=60)
        if r.status_code in (200, 201):
            return True, f"publicado (id {r.json().get('id', r.json().get('post_id'))})"
        return False, f"HTTP {r.status_code}: {r.text[:180]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def publicar_instagram(post, caption, seco=False):
    """
    Instagram va en DOS pasos: crear el contenedor y luego publicarlo.
    La imagen TIENE que ser una URL publica (las nuestras lo son).
    """
    if not (TOKEN and IG_ID):
        return False, "sin IG_USER_ID o META_ACCESS_TOKEN"
    img = post.get("imagen")
    if not img:
        return False, "sin imagen (Instagram exige foto)"
    if seco:
        return True, f"[SECO] POST {API}/{IG_ID}/media + media_publish"
    try:
        import requests
        r1 = requests.post(f"{API}/{IG_ID}/media",
                           data={"image_url": img, "caption": caption,
                                 "access_token": TOKEN}, timeout=60)
        if r1.status_code != 200:
            return False, f"contenedor HTTP {r1.status_code}: {r1.text[:160]}"
        cid = r1.json().get("id")
        if not cid:
            return False, f"sin creation_id: {r1.text[:140]}"
        r2 = requests.post(f"{API}/{IG_ID}/media_publish",
                           data={"creation_id": cid, "access_token": TOKEN}, timeout=60)
        if r2.status_code == 200:
            return True, f"publicado (id {r2.json().get('id')})"
        return False, f"publish HTTP {r2.status_code}: {r2.text[:160]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def estado():
    print("=" * 70)
    print("  PUBLICADOR EN REDES (Facebook + Instagram)")
    print("=" * 70)
    print(f"  META_ACCESS_TOKEN : {'configurado' if TOKEN else 'FALTA'}")
    print(f"  META_PAGE_ID      : {PAGE_ID or 'FALTA (sin Facebook)'}")
    print(f"  IG_USER_ID        : {IG_ID or 'FALTA (sin Instagram)'}")
    print()
    if not hay_credenciales():
        print("  Sin credenciales: el modulo se salta solo, no rompe nada.")
        print("  Sigue las instrucciones de la cabecera del archivo para sacarlas.")
        return 1
    import requests
    for nombre, endpoint, params in (
        ("Pagina FB", f"{API}/{PAGE_ID}", {"fields": "name,fan_count",
                                           "access_token": TOKEN}),
        ("Cuenta IG", f"{API}/{IG_ID}", {"fields": "username,followers_count",
                                         "access_token": TOKEN}),
    ):
        if "FALTA" in nombre:
            continue
        try:
            r = requests.get(endpoint, params=params, timeout=30)
            print(f"  {nombre:10s} -> {r.status_code}  {r.text[:140]}")
        except Exception as e:
            print(f"  {nombre:10s} -> ERROR {type(e).__name__}")
    return 0


def main():
    seco = "--test" in sys.argv or "--dry" in sys.argv
    if "--estado" in sys.argv:
        return estado()

    if not hay_credenciales():
        print("  [redes] sin credenciales de Meta configuradas: nada que hacer.")
        return 0

    enviados = cargar_enviados()
    post = elegir_post(enviados)
    if not post:
        print("  [redes] no hay posts nuevos para publicar en redes.")
        return 0

    pid = post.get("id_post") or (post.get("titulo") or "")[:40]
    caption = formatear_caption(post)

    print("=" * 70)
    print(f"  PUBLICANDO EN REDES: {str(post.get('titulo'))[:50]}")
    print("=" * 70)
    print(caption)
    print("-" * 70)

    ok_fb, msg_fb = publicar_facebook(post, caption, seco)
    print(f"  Facebook  : {'OK  ' if ok_fb else 'FALLO'} {msg_fb}")
    ok_ig, msg_ig = publicar_instagram(post, caption, seco)
    print(f"  Instagram : {'OK  ' if ok_ig else 'FALLO'} {msg_ig}")

    if (ok_fb or ok_ig) and not seco:
        enviados[pid] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "facebook": ok_fb,
            "instagram": ok_ig,
        }
        guardar_enviados(enviados)
        print("  registrado en logs/enviados_redes.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
