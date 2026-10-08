#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Vigía de cupones (cupones_vigia.py)
===========================================
Detecta un cupón NUEVO de Mercado Livre y lo publica en el grupo EN MINUTOS,
con enlace de afiliado corto.

POR QUÉ EXISTE
--------------
Medido el 2026-10-07: los grupos de la competencia publican un cupón que
Mercado Livre acaba de soltar a las 00:05 casi al momento. Nosotros no, por
dos motivos que este módulo resuelve:

  1. Las fuentes de cupón solo corrían en los runs "full", ANTES del bucle de
     publicación. El bucle de 5.5 h no volvía a mirar nunca, y el cron de
     GitHub tiene un gap mediano medido de 174 min. Resultado: latencia de
     horas. Ahora el bucle llama a este vigilante cada CHEQUEO_CUPONES_SEG
     (def. 300 s), así que la latencia máxima con un job vivo es 5 minutos.

  2. Los posts de cupón se generaban y se TIRABAN (nunca entraban en la fila)
     y además el publicador los saltaba. Este módulo publica por su propio
     camino, sin depender de la fila.

CÓMO DECIDE QUÉ ES "NUEVO"
--------------------------
Registro persistente `logs/cupones_publicados.json`:
    {"codigos": {"OFERTASMELI": {"detectado_em": ..., "publicado_em": ...}}}

  · Si el registro NO existe -> BOOTSTRAP: se marcan todos los códigos actuales
    como ya vistos y NO se publica nada. Sin esto, el primer día escupiríamos
    los 64 códigos de Telegram de golpe y quemaríamos el grupo.
  · Si el código ya está en el registro -> no se toca (se publica UNA vez).
  · Solo se publica lo que aparezca después del bootstrap y esté dentro de la
    ventana de frescura (CUPONES_FRESCURA_HORAS, def. 24 h).

REGLAS DE ORO QUE RESPETA
-------------------------
  · Nunca inventa: sin descuento legible, el post no muestra descuento.
  · Nunca publica un código basura (blobs base64 de ML): ver cupons_ml.
  · Nunca publica un enlace /go/ (no monetiza): solo meli.la o el enlace largo
    con el tag de afiliado.
  · Nunca publica un cupón vencido.

Uso:
    python cupones_vigia.py          # detecta y publica lo nuevo
    python cupones_vigia.py --dry    # dice qué haría, sin enviar nada
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
CUPONES_JSON = BASE / "cupones.json"
ENVIADOS_JSON = BASE / "logs" / "enviados.json"
CONTROL_FILE = BASE / "logs" / "control_canal.json"
REGISTRO = BASE / "logs" / "cupones_publicados.json"
LOG_FILE = BASE / "logs" / "ejecucion.log"

DRY = "--dry" in sys.argv

# ─── Parámetros (configurables sin tocar código) ──────────────────────────────
FRESCURA_HORAS = float(os.environ.get("CUPONES_FRESCURA_HORAS", "24"))
MAX_POR_HORA = int(os.environ.get("MAX_CUPONES_HORA", "3"))
MAX_POR_DIA = int(os.environ.get("MAX_CUPONES_DIA", "15"))
MIN_GAP_MIN = float(os.environ.get("CUPON_MIN_GAP_MIN", "3"))
DIAS_REGISTRO = 30


def log(msg):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CUPONES] {msg}"
    print(f"  {msg}", flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass


# ─── Registro de cupones publicados ───────────────────────────────────────────

def cargar_registro():
    if not REGISTRO.exists():
        return None
    try:
        d = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("codigos"), dict):
            return d
    except Exception as e:
        log(f"❌ Registro ilegible ({e}). Se aborta sin publicar.")
        raise
    return None


def guardar_registro(datos):
    # Purga a DIAS_REGISTRO para que el archivo no crezca sin fin.
    limite = (datetime.now(timezone.utc) - timedelta(days=DIAS_REGISTRO)).isoformat()
    codigos = {}
    for cod, info in (datos.get("codigos") or {}).items():
        marca = info.get("publicado_em") or info.get("detectado_em") or ""
        if marca >= limite:
            codigos[cod] = info
    datos["codigos"] = codigos
    datos["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REGISTRO.parent.mkdir(exist_ok=True)
    REGISTRO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Fuente de cupones ────────────────────────────────────────────────────────

def refrescar_fuente():
    """
    Actualiza cupones.json con la página OFICIAL de cupones de Mercado Livre
    (la fuente más fresca que tenemos; verificada el 2026-10-07: 137 cupones,
    11 con código válido tras el filtro de higiene). Si falla, se sigue con lo
    que ya haya en cupones.json (p.ej. lo que trajo Telegram).
    """
    try:
        import cupons_ml as cm
    except Exception as e:
        log(f"⚠️  cupons_ml no disponible: {e}")
        return False
    cookie = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    if not cookie:
        log("⚠️  Sin ML_PORTAL_COOKIE: no se puede consultar la página oficial.")
        return False
    try:
        nuevos = cm.obtener_cupones_oficiales_ml(cookie)
        if nuevos:
            cm.limpiar_y_actualizar_cupones(nuevos)
            log(f"Fuente oficial ML refrescada: {len(nuevos)} cupón(es).")
            return True
        log("⚠️  La página oficial no devolvió cupones (¿cookie caducada?). "
            "Se sigue con cupones.json.")
    except Exception as e:
        log(f"⚠️  Error refrescando la fuente oficial: {e}")
    return False


def cargar_cupones():
    if not CUPONES_JSON.exists():
        return []
    try:
        d = json.loads(CUPONES_JSON.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log(f"❌ cupones.json ilegible ({e}). Se aborta sin publicar.")
        raise
    lista = d.get("cupones", []) if isinstance(d, dict) else d
    return [c for c in lista if isinstance(c, dict)]


# ─── Filtros ──────────────────────────────────────────────────────────────────

def _fecha_cupon(c):
    for campo in ("hasta", "vencimento"):
        v = c.get(campo)
        if v:
            try:
                return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
            except Exception:
                continue
    return None


def _detectado(c):
    for campo in ("detectado_em", "capturado_em"):
        v = c.get(campo)
        if v:
            try:
                ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            except Exception:
                continue
    return None


def es_cupon_publicable(c):
    """(ok, motivo). Solo cupones reales, vigentes y frescos de tienda que paga."""
    from cupons_ml import codigo_valido

    codigo = str(c.get("codigo") or "").strip().upper()
    if not codigo_valido(codigo):
        return False, "código inválido"
    if "mercado" not in str(c.get("tienda") or "").lower():
        return False, "tienda no monetizada"
    if c.get("vigente") is False:
        return False, "marcado no vigente"

    vence = _fecha_cupon(c)
    hoy = datetime.now(timezone.utc).date()
    if vence and vence < hoy:
        return False, "vencido"

    detectado = _detectado(c)
    if detectado:
        horas = (datetime.now(timezone.utc) - detectado).total_seconds() / 3600.0
        if horas > FRESCURA_HORAS:
            return False, f"detectado hace {horas:.0f}h (> {FRESCURA_HORAS:.0f}h)"
    return True, "ok"


# ─── Enlace de afiliado ───────────────────────────────────────────────────────

def _tag_ml():
    try:
        cfg = json.loads((BASE / "config_afiliados.json").read_text(encoding="utf-8"))
        return cfg.get("mercadolivre", {}).get("id") or "ja20250119201346"
    except Exception:
        return "ja20250119201346"


def registrar_publicados(codigos, motivo="tanda"):
    """
    Marca códigos como publicados en el registro compartido.

    Lo usan DOS caminos, y por eso vive aquí:
      · este vigía, cuando publica un cupón nuevo al momento;
      · el publicador de tandas (publicar_proximo.py), cuando manda un lote.

    Al compartir un único registro, la rotación de tandas sabe qué cupones ya
    salieron y deja de repetir los mismos cada pocas horas (el 2026-10-08 el
    usuario lo reportó: "estancado con un cupón antiguo").
    """
    codigos = [str(c).strip().upper() for c in (codigos or []) if c]
    if not codigos:
        return
    try:
        datos = cargar_registro()
    except Exception as e:
        log(f"⚠️  Registro ilegible, no se pudo anotar la tanda: {e}")
        return
    if datos is None:
        datos = {"bootstrap_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "codigos": {}}
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for cod in codigos:
        entrada = datos["codigos"].get(cod) or {}
        entrada["publicado_em"] = ahora
        entrada["motivo"] = motivo
        datos["codigos"][cod] = entrada
    guardar_registro(datos)
    log(f"Anotados {len(codigos)} código(s) como publicados ({motivo}).")


def _link_go_verificado(largo, tag):
    """
    Crea (o reutiliza) un enlace corto en NUESTRO dominio:
        https://achadinhosnozap.com.br/go/<codigo>/
    cuyo HTML de redirección apunta a la página de cupones CON el tag de
    afiliado. Se VERIFICA leyendo el archivo generado: si el tag no está
    dentro, el enlace se descarta. Un /go/ sin tag no cobra y el clic se
    regalaría (Regla de Oro).
    """
    try:
        import acortador
        url_corta, codigo = acortador.procesar_oferta(
            largo, "Mercado Livre", "Cupons Mercado Livre")
        archivo = BASE / "go" / codigo / "index.html"
        html = archivo.read_text(encoding="utf-8", errors="replace")
        if tag and tag in html:
            return url_corta
        log(f"⚠️  El enlace corto /go/{codigo}/ no contiene el tag: se descarta.")
    except Exception as e:
        log(f"⚠️  No se pudo crear el enlace corto propio: {e}")
    return None


def link_afiliado_cupones():
    """
    Devuelve (link, es_corto). Orden de preferencia, MEDIDO:

      1. meli.la oficial. OJO: probado el 2026-10-07, Mercado Livre RECHAZA la
         página de cupones con "NO ELEGIBLE para el programa de afiliados"
         (también /ofertas). Solo acepta URLs de producto. Así que por aquí
         normalmente no se pasa; queda por si algún día lo permiten.
      2. Enlace corto propio /go/<codigo>/ con el tag dentro y VERIFICADO.
         Es lo que hace la competencia: un enlace corto. El tag es lo que
         acredita la comisión, y está comprobado en el HTML generado.
      3. Enlace largo con tag (último recurso, también cobra).

    Nunca se devuelve un /go/ sin tag.
    """
    tag = _tag_ml()
    largo = f"https://www.mercadolivre.com.br/cupons#D[A:{tag}]"
    try:
        from gerador_melila import obtener_link_afiliado_ml
        link, _es_meli = obtener_link_afiliado_ml(
            "https://www.mercadolivre.com.br/cupons", etiqueta=tag)
        if link and "meli.la" in link:
            return link, True
    except Exception as e:
        log(f"⚠️  meli.la no disponible ({e}).")

    corto = _link_go_verificado(largo, tag)
    if corto:
        return corto, True
    return largo, False


# ─── Plantilla ────────────────────────────────────────────────────────────────

def mensaje_cupon(c, link):
    lineas = ["🎟️ CUPOM NOVO — Mercado Livre"]
    if c.get("desconto"):
        lineas.append(f"💰 {c['desconto']}")
    lineas.append(f"🔑 Código: {c['codigo']}")
    if c.get("compra_minima"):
        lineas.append(f"🧾 Compra mínima: {c['compra_minima']}")
    if c.get("limite"):
        lineas.append(f"🎯 Limite: {c['limite']}")
    vence = c.get("hasta") or c.get("vencimento")
    if vence:
        faltan = (_fecha_cupon(c) - datetime.now(timezone.utc).date()).days
        if faltan <= 0:
            lineas.append("⏰ Vence HOJE")
        else:
            lineas.append(f"⏰ Vence em {faltan} dia(s) ({vence})")
    lineas.append("")
    lineas.append("⭐️ Ative no carrinho:")
    lineas.append(link)
    lineas.append("")
    lineas.append("anúncio")
    return "\n".join(lineas)


# ─── Topes ────────────────────────────────────────────────────────────────────

def _publicados(registro, desde):
    n = 0
    for info in (registro.get("codigos") or {}).values():
        pub = info.get("publicado_em")
        if pub and pub >= desde:
            n += 1
    return n


def cupo_disponible(registro):
    """(ok, motivo). Topes por hora y por día + tope diario global + cadencia."""
    ahora = datetime.now(timezone.utc)
    desde_hora = (ahora - timedelta(hours=1)).isoformat()
    desde_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    if _publicados(registro, desde_hora) >= MAX_POR_HORA:
        return False, f"tope por hora alcanzado ({MAX_POR_HORA})"
    if _publicados(registro, desde_dia) >= MAX_POR_DIA:
        return False, f"tope diario de cupones alcanzado ({MAX_POR_DIA})"

    try:
        import publicar_proximo as pp
        control = pp.cargar_control_canal()
        max_dia = pp.limite_diario_calentamiento(control.get("dias_activo", 3))
        if control.get("envios_hoy", 0) >= max_dia:
            return False, f"tope diario global alcanzado ({control.get('envios_hoy')}/{max_dia})"
        if not pp.horario_permitido_brt():
            return False, "fuera de la ventana de publicación"
    except Exception as e:
        log(f"⚠️  No se pudo comprobar el tope global ({e}); se aplica solo el de cupones.")

    # Cadencia: no pegar dos mensajes seguidos
    try:
        import publicar_proximo as pp
        ultimo = pp.ultimo_envio_utc(pp.cargar_enviados_estricto())
        if ultimo:
            minutos = (datetime.now(timezone.utc) - ultimo).total_seconds() / 60.0
            if minutos < MIN_GAP_MIN:
                return False, f"último envío hace {minutos:.1f} min (< {MIN_GAP_MIN:.0f} min)"
    except Exception:
        pass

    return True, "ok"


# ─── Publicación ──────────────────────────────────────────────────────────────

def publicar(mensaje, codigo):
    """Envía el cupón y lo registra en los TRES sitios de estado."""
    from enviar_whatsapp import enviar_whatsapp
    from modulo_ofertas import cargar_enviados, guardar_enviados, marcar_enviado

    if not enviar_whatsapp(mensaje):
        return False

    enviados = cargar_enviados()
    marcar_enviado(f"cupon-{codigo}", enviados, canal="whatsapp")
    guardar_enviados(enviados)

    try:
        import publicar_proximo as pp
        control = pp.cargar_control_canal()
        control["envios_hoy"] = control.get("envios_hoy", 0) + 1
        pp.guardar_control_canal(control)
    except Exception as e:
        log(f"⚠️  No se pudo incrementar el contador diario: {e}")
    return True


def main():
    print("=" * 66)
    print("  CRIBA · VIGÍA DE CUPONES" + ("  [MODO DRY]" if DRY else ""))
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 66)

    try:
        registro_previo = cargar_registro()
    except Exception:
        return 2

    # Refrescar la fuente oficial ANTES de leer cupones.json: es la más fresca.
    # (En modo dry también, porque no escribe: solo actualiza cupones.json.)
    refrescar_fuente()

    cupones = cargar_cupones()
    if not cupones:
        log("No hay cupones en cupones.json. Nada que hacer.")
        return 0

    # ── BOOTSTRAP ─────────────────────────────────────────────────────────────
    if registro_previo is None:
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        registro = {"bootstrap_em": ahora, "codigos": {}}
        for c in cupones:
            codigo = str(c.get("codigo") or "").strip().upper()
            if codigo:
                registro["codigos"][codigo] = {
                    # Si la fuente no trae fecha, se usa el momento del bootstrap
                    # para que la purga del registro (30 días) tenga con qué
                    # trabajar y no borre estas entradas al día siguiente.
                    "detectado_em": c.get("detectado_em") or c.get("capturado_em") or ahora,
                    "publicado_em": None,
                    "motivo": "bootstrap: ya existía cuando se activó el vigía",
                }
        if DRY:
            log(f"[DRY] Bootstrap: se marcarían {len(registro['codigos'])} códigos "
                f"como ya vistos y NO se publicaría ninguno.")
            return 0
        guardar_registro(registro)
        log(f"BOOTSTRAP: {len(registro['codigos'])} código(s) existentes marcados como "
            f"ya vistos. A partir de ahora solo se publica lo NUEVO.")
        return 0

    # ── DETECCIÓN ─────────────────────────────────────────────────────────────
    ya_vistos = registro_previo.get("codigos") or {}
    candidatos = []
    for c in cupones:
        codigo = str(c.get("codigo") or "").strip().upper()
        if codigo in ya_vistos:
            continue
        ok, motivo = es_cupon_publicable(c)
        if not ok:
            log(f"Descartado {codigo or '(sin código)'}: {motivo}")
            if codigo:
                ya_vistos[codigo] = {
                    "detectado_em": (c.get("detectado_em") or c.get("capturado_em")
                                     or datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    "publicado_em": None,
                    "motivo": motivo,
                }
            continue
        candidatos.append((codigo, c))

    if not candidatos:
        log(f"Sin cupones nuevos ({len(ya_vistos)} códigos ya vistos).")
        if not DRY:
            registro_previo["codigos"] = ya_vistos
            guardar_registro(registro_previo)
        return 0

    def _peso(cupon):
        # Primero los que TIENEN descuento, y entre ellos el mayor.
        desc = str(cupon.get("desconto") or "")
        numeros = "".join(ch for ch in desc if ch.isdigit())
        return (0 if desc else 1, -int(numeros or 0))

    candidatos.sort(key=lambda x: _peso(x[1]))
    log(f"Cupones NUEVOS detectados: {len(candidatos)} "
        f"({', '.join(cod for cod, _ in candidatos[:6])}{'...' if len(candidatos) > 6 else ''})")

    link, es_corto = link_afiliado_cupones()
    log(f"Enlace de afiliado: {'meli.la (corto)' if es_corto else 'largo con tag'} -> {link}")

    publicados = 0
    for codigo, c in candidatos:
        ok, motivo = cupo_disponible(registro_previo)
        if not ok:
            log(f"Se corta aquí: {motivo}.")
            break

        # Puerta del validador: código con forma real, fuente trazable, no
        # caducado y enlace que DEMUESTRA llevar nuestro tag de afiliado.
        try:
            from validador_oferta import validar_cupon
            ok_val, motivo_val = validar_cupon(c, link)
            if not ok_val:
                log(f"❌ Cupón {codigo} bloqueado por el validador: {motivo_val}")
                continue
        except Exception as e:
            log(f"⚠️  Validador no disponible ({e}); se omite la comprobación.")

        mensaje = mensaje_cupon(c, link)
        detectado = c.get("detectado_em") or c.get("capturado_em")

        if DRY:
            print("\n--- [DRY] SE PUBLICARÍA ---")
            print(mensaje)
            print("--- FIN ---")
            publicados += 1
            continue

        if publicar(mensaje, codigo):
            ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            registro_previo["codigos"][codigo] = {
                "detectado_em": detectado,
                "publicado_em": ahora,
                "descuento": c.get("desconto"),
                "link_corto": es_corto,
                "motivo": "publicado",
            }
            publicados += 1
            latencia = "?"
            if detectado:
                try:
                    ts = datetime.fromisoformat(str(detectado).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    latencia = f"{(datetime.now(timezone.utc) - ts).total_seconds() / 60:.1f} min"
                except Exception:
                    pass
            log(f"✅ Publicado cupón {codigo} (detectado -> publicado: {latencia})")
        else:
            log(f"❌ Falló el envío del cupón {codigo}.")
            break

    if not DRY:
        registro_previo["codigos"] = ya_vistos
        guardar_registro(registro_previo)

    print("-" * 66)
    log(f"Fin. Cupones publicados en esta pasada: {publicados}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
