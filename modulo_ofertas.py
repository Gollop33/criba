#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Módulo de Selección y Formato de Ofertas
=================================================
Centraliza la lógica de:
  - Elegir las mejores ofertas (descuento >= 20% o baja >= 15% vs historial)
  - Priorizar productos con cupón activo
  - Anti-spam: max 5 por ejecución, no repetir en 24h
  - Formatear mensajes exactos:
      🔥 [nombre del producto]
      ✅ R$ [menor precio]
      🎟️ Cupom: [código si existe]
      👉 [link de afiliado con tag]
  - Persistir historial de enviados en logs/enviados.json

Uso:
  from modulo_ofertas import elegir_mejores_ofertas, formatear_mensaje
"""
import json, sys, io, re
from pathlib import Path
from datetime import datetime, timedelta

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE           = Path(__file__).parent
LOG_DIR        = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
ENVIADOS_JSON  = LOG_DIR / "enviados.json"

# ─── Umbrales anti-spam ────────────────────────────────────────────────────────
MIN_DESCUENTO_PCT  = 20    # Descuento mínimo vs precio original/referencia
MIN_BAJO_HIST_PCT  = 15    # % por debajo del precio histórico reciente
MAX_POR_EJECUCION  = 5     # Máximo mensajes por corrida
HORAS_ANTI_SPAM    = 24    # No repetir mismo producto en N horas
AMAZON_TAG         = "criba20-20"
ML_ID              = "ja20250119201346"


# ─── Historial de enviados ─────────────────────────────────────────────────────

def cargar_enviados():
    """Lee el historial de IDs enviados con timestamp."""
    if not ENVIADOS_JSON.exists():
        return {}
    try:
        return json.loads(ENVIADOS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_enviados(enviados):
    """Persiste el historial, purgando entradas > 48h."""
    limite = (datetime.utcnow() - timedelta(hours=48)).isoformat()
    limpio = {k: v for k, v in enviados.items() if v.get("ts", "") >= limite}
    ENVIADOS_JSON.write_text(json.dumps(limpio, ensure_ascii=False, indent=2), encoding="utf-8")


def ya_enviado(pid, enviados, canal=None):
    """
    True si el producto fue enviado por el canal especificado en las últimas HORAS_ANTI_SPAM horas.
    Si canal es None, verifica cualquier canal.
    """
    if pid not in enviados:
        return False
    entry = enviados[pid]
    if not isinstance(entry, dict):
        return False

    if canal:
        canales = entry.get("canales")
        if isinstance(canales, dict) and canal in canales:
            ts_str = canales[canal]
        else:
            ts_str = entry.get("ts", "")
    else:
        ts_str = entry.get("ts", "")

    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str)
        return (datetime.utcnow() - ts) < timedelta(hours=HORAS_ANTI_SPAM)
    except Exception:
        return False


def marcar_enviado(pid, enviados, canal="general"):
    """Registra el envío de un producto para el canal indicado."""
    now = datetime.utcnow().isoformat()
    if pid not in enviados or not isinstance(enviados[pid], dict):
        enviados[pid] = {"ts": now, "canales": {}}
    if not isinstance(enviados[pid].get("canales"), dict):
        enviados[pid]["canales"] = {}
    enviados[pid]["canales"][canal] = now
    enviados[pid]["ts"] = now


# ─── Cupones vigentes ──────────────────────────────────────────────────────────

def _cupones_vigentes():
    """Carga cupones.json y retorna lista plana de cupones activos."""
    f = BASE / "cupones.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            lista = data
        elif isinstance(data, dict) and "cupones" in data:
            lista = data["cupones"]
        elif isinstance(data, dict):
            lista = []
            for tienda, c_list in data.items():
                if isinstance(c_list, list):
                    for c in c_list:
                        if isinstance(c, dict):
                            if "tienda" not in c:
                                c["tienda"] = tienda
                            lista.append(c)
        else:
            lista = []
        hoy = datetime.utcnow().date().isoformat()
        return [c for c in lista if isinstance(c, dict) and c.get("hasta", "9999-12-31") >= hoy]
    except Exception:
        return []


def _obtener_cupon_producto(producto, cupones):
    """Obtiene el cupón activo asociado al producto si existe."""
    vista = producto.get("vista", {})
    cupon_directo = vista.get("cupon")
    if cupon_directo and str(cupon_directo).strip():
        return str(cupon_directo).strip()

    tienda = vista.get("tienda", "").lower()
    nombre_lower = producto.get("nombre", "").lower()

    for c in cupones:
        t_c = c.get("tienda", "").lower()
        if t_c and (t_c in tienda or t_c in nombre_lower):
            cod = c.get("codigo")
            if cod and str(cod).strip():
                return str(cod).strip()
            desc = c.get("desconto")
            if desc and str(desc).strip():
                return str(desc).strip()
    return None


# ─── Link de afiliado ──────────────────────────────────────────────────────────

def _link_afiliado(producto):
    """Construye el link de afiliado correcto según la tienda."""
    vista = producto.get("vista", {})
    url   = vista.get("url", "") or ""
    tienda = vista.get("tienda", "").lower()

    # Priorizar url_ml si existe
    url_ml = producto.get("url_ml", "").strip()
    if url_ml:
        sep = "&" if "?" in url_ml else "#"
        return f"{url_ml}{sep}D[A:{ML_ID}]"

    if "amazon" in tienda or "amazon" in url:
        sep = "&" if "?" in url else "?"
        if "tag=" not in url:
            return f"{url}{sep}tag={AMAZON_TAG}"
        return url

    if "mercadolivre" in tienda or "mercadolivre" in url or "mercadolibre" in url:
        sep = "&" if "?" in url else "#"
        if "D[A:" not in url:
            return f"{url}{sep}D[A:{ML_ID}]"
        return url

    return url


# ─── Extraer historial de precios de forma segura ─────────────────────────────

def _extraer_precios_historico(historico):
    """Extrae una lista de precios numéricos independientemente de si historico es dict o list."""
    precios = []
    if not historico:
        return precios

    if isinstance(historico, list):
        for h in historico:
            if isinstance(h, dict) and "precio" in h:
                try:
                    p = float(h["precio"])
                    if p > 0:
                        precios.append(p)
                except (ValueError, TypeError):
                    pass
            elif isinstance(h, (int, float)) and h > 0:
                precios.append(float(h))

    elif isinstance(historico, dict):
        for tienda, entries in historico.items():
            if isinstance(entries, list):
                for h in entries:
                    if isinstance(h, dict) and "precio" in h:
                        try:
                            p = float(h["precio"])
                            if p > 0:
                                precios.append(p)
                        except (ValueError, TypeError):
                            pass
    return precios


# ─── Evaluación y Score de Oferta ─────────────────────────────────────────────

def _evaluar_oferta(producto, cupones):
    """
    Verifica reglas anti-spam:
      - Descuento >= 20%
      - O precio bajo >= 15% vs historial
    Retorna (cumple, score, motivo, cupon_str)
    """
    vista       = producto.get("vista", {})
    precio_act  = vista.get("precio", 0) or 0
    if precio_act <= 0:
        return False, 0, "", None

    desc_pct = float(producto.get("descuento_pct", 0) or 0)
    cupon_str = _obtener_cupon_producto(producto, cupones)
    historico = producto.get("historico")
    precios_hist = _extraer_precios_historico(historico)

    cumple_descuento = desc_pct >= MIN_DESCUENTO_PCT
    cumple_historial = False
    motivos = []

    if cumple_descuento:
        motivos.append(f"-{desc_pct:.0f}% de desconto")

    if precios_hist:
        precio_max_hist = max(precios_hist)
        if precio_max_hist > 0:
            bajada_hist = round((precio_max_hist - precio_act) / precio_max_hist * 100, 1)
            if bajada_hist >= MIN_BAJO_HIST_PCT:
                cumple_historial = True
                motivos.append(f"-{bajada_hist:.0f}% vs histórico")

    # Regla: solo enviar si cumple descuento >= 20% O baja >= 15% vs historial
    if not (cumple_descuento or cumple_historial):
        return False, 0, "", None

    # Puntuación base
    score = float(producto.get("score", 0) or 0)
    score += desc_pct * 1.5

    # PRIORIDAD: productos con cupón activo reciben fuerte bonus
    if cupon_str:
        score += 50
        motivos.append(f"Cupom ativo: {cupon_str}")

    if producto.get("bajo"):
        score += 20
        motivos.append("Baixou de preço")

    if vista.get("pix"):
        score += 10

    return True, score, " | ".join(motivos), cupon_str


# ─── Selección de mejores ofertas ─────────────────────────────────────────────

def elegir_mejores_ofertas(productos, max_ofertas=MAX_POR_EJECUCION, canal=None):
    """
    Filtra y ordena las mejores ofertas para enviar (0-5 por ejecución).
    Respeta anti-spam de 24h (por canal si se especifica).
    Retorna lista de dicts: {producto, score, motivo, cupon, link}.
    """
    cupones  = _cupones_vigentes()
    enviados = cargar_enviados()
    candidatos = []

    for p in productos:
        pid = p.get("id") or p.get("nombre", "")[:40]
        vista = p.get("vista", {})
        if not vista.get("precio") or not vista.get("url"):
            continue

        if ya_enviado(pid, enviados, canal=canal):
            continue

        cumple, score, motivo, cupon_str = _evaluar_oferta(p, cupones)
        if not cumple:
            continue

        candidatos.append({
            "producto": p,
            "score":    score,
            "motivo":   motivo,
            "cupon":    cupon_str,
            "link":     _link_afiliado(p),
        })

    # Ordenar por score descendente (cupones y mejores descuentos primero)
    candidatos.sort(key=lambda x: x["score"], reverse=True)
    return candidatos[:max_ofertas]


# ─── Formateo de mensaje (EXACTO según requerimiento) ─────────────────────────

def fmt_brl(n):
    """Formatea número como R$ brasileño."""
    try:
        return f"{float(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(n)


def formatear_mensaje(oferta, modo="texto"):
    """
    Genera el mensaje exacto según especificación:
    🔥 [nombre del producto]
    ✅ R$ [menor precio]
    🎟️ Cupom: [código si existe]
    👉 [link de afiliado con tag]

    modo='texto' -> WhatsApp / texto plano
    modo='html'  -> Telegram con etiquetas HTML
    """
    p      = oferta["producto"]
    nombre = p.get("nombre", "Produto")
    vista  = p.get("vista", {})
    precio = vista.get("precio", 0)
    cupon  = oferta.get("cupon")
    link   = oferta.get("link", "")

    if modo == "html":
        lineas = [
            f"🔥 <b>{nombre}</b>",
            f"✅ <b>R$ {fmt_brl(precio)}</b>",
        ]
        if cupon:
            lineas.append(f"🎟️ Cupom: <code>{cupon}</code>")
        lineas.append(f"👉 {link}")
    else:
        lineas = [
            f"🔥 {nombre}",
            f"✅ R$ {fmt_brl(precio)}",
        ]
        if cupon:
            lineas.append(f"🎟️ Cupom: {cupon}")
        lineas.append(f"👉 {link}")

    return "\n".join(lineas)


# ─── Test rápido ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    prod_f = BASE / "productos.json"
    if not prod_f.exists():
        print("productos.json no encontrado — ejecuta bot_precios.py primero")
    else:
        data      = json.loads(prod_f.read_text(encoding="utf-8"))
        productos = data.get("productos", [])
        ofertas   = elegir_mejores_ofertas(productos)
        print(f"Ofertas seleccionadas: {len(ofertas)}/{len(productos)}")
        for o in ofertas:
            print("\n" + "=" * 40)
            print(f"Score: {o['score']} | {o['motivo']}")
            print("-" * 40)
            print(formatear_mensaje(o, modo="texto"))
