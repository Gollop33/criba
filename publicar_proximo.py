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
import re
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
        for line in _env_file.read_text(encoding="utf-8-sig").splitlines():
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
    """
    Tope de posts/día. Con intervalos aleatorios de 1-10 min (media 5.5) una
    ventana de 14 h daría ~150 posts, así que el tope es lo que realmente
    limita. Se puede subir con la variable de entorno MAX_ENVIOS_DIA.
    """
    override = os.environ.get("MAX_ENVIOS_DIA", "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    if dias_activo <= 1:
        return 20
    if dias_activo == 2:
        return 40
    return 120  # día 3+: tope de seguridad del canal


def ventana_brt():
    """
    Ventana de publicación en hora de Brasília, leída de VENTANA_BRT.

      VENTANA_BRT="8-22"   -> horario comercial (comportamiento histórico)
      VENTANA_BRT="0-24"   -> 24/7 (lo que pidió el usuario el 2026-10-07)

    Acepta también una ventana que cruza medianoche (p.ej. "22-6").
    """
    bruto = os.environ.get("VENTANA_BRT", "8-22").strip().replace(" ", "")
    if bruto in ("0-24", "24", "24h", "24/7", "*"):
        return 0, 24
    try:
        ini_s, fin_s = bruto.split("-")
        ini, fin = int(ini_s), int(fin_s)
    except Exception:
        ini, fin = 8, 22
    ini = max(0, min(23, ini))
    fin = max(0, min(24, fin))
    return ini, fin


def horario_permitido_brt():
    """
    True si la hora actual de Brasília (UTC-3) cae dentro de la ventana.

    Se puede forzar con FORZAR_ENVIO=1 para una publicación manual de prueba.
    """
    if os.environ.get("FORZAR_ENVIO", "").strip().lower() in ("1", "true", "si", "sí"):
        return True
    ini, fin = ventana_brt()
    if fin - ini >= 24:
        return True
    brt_hour = (datetime.now(timezone.utc).hour - 3) % 24
    if ini <= fin:
        return ini <= brt_hour < fin
    # ventana que cruza medianoche: 22-6 -> 22,23,0..5
    return brt_hour >= ini or brt_hour < fin


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


# ─── Carga del historial (fail-safe) ──────────────────────────────────────────

def cargar_enviados_estricto():
    """
    Carga logs/enviados.json SIN tragarse los errores.

    `modulo_ofertas.cargar_enviados()` devuelve {} si el JSON está corrupto, y eso
    haría que el bot creyera que nunca envió nada y **republicara todo el
    catálogo**. Si el archivo existe pero no parsea, abortamos.
    """
    if not ENVIADOS_JSON.exists():
        return {}
    try:
        # utf-8-sig: tolera el BOM que meten algunas herramientas de Windows
        d = json.loads(ENVIADOS_JSON.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except Exception as e:
        print(f"  ❌ [ABORTA] logs/enviados.json existe pero no es JSON válido: {e}")
        print("     Publicar ahora trataría el historial como vacío y republicaría")
        print("     todo el catálogo. Arréglalo con:  python reparar_estado.py")
        sys.exit(2)


# ─── Precio final con descuentos aplicados ────────────────────────────────────

def extraer_pct(texto):
    """'mais 5% OFF' -> 5.0 ; 'à vista' -> None."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(texto or ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def calcular_precio_final(precio, post):
    """
    Calcula lo que el cliente paga DE VERDAD aplicando cupón + descuento Pix.

    Es lo que más convierte: la gente no calcula porcentajes, quiere ver el
    número final. Devuelve (precio_final, etiqueta) o (None, None) si no hay
    datos suficientes para calcularlo con honestidad.

    Orden aplicado: cupón primero (con su tope máximo, porque un "30% OFF" con
    tope de R$50 sobre R$500 descuenta 50, no 150) y luego el Pix sobre el
    resto. Es el orden que usan las tiendas brasileñas.
    """
    try:
        p = float(precio)
    except (TypeError, ValueError):
        return None, None
    if p <= 0:
        return None, None

    partes = []

    # CONFIANZA DEL CUPÓN: si el cupón es "general" (sin categoría declarada),
    # Mercado Livre decide qué "produtos são elegíveis" y nosotros NO podemos
    # saberlo. En ese caso no se usa para calcular el precio final: prometer un
    # descuento que puede no aplicar engaña al grupo, y la confianza es el único
    # activo real de un canal de ofertas.
    confianza = post.get("cupom_confianza", "alta")
    pct_cupon = post.get("cupom_pct") if confianza != "baja" else None
    if pct_cupon:
        try:
            desc = p * (float(pct_cupon) / 100.0)
            tope = post.get("cupom_max")
            if tope:
                desc = min(desc, float(tope))
            if desc > 0:
                p -= desc
                partes.append(f"cupom {float(pct_cupon):.0f}%")
        except (TypeError, ValueError):
            pass
    elif post.get("cupom_valor") and confianza != "baja":
        try:
            desc = min(float(post["cupom_valor"]), p)
            if desc > 0:
                p -= desc
                partes.append("cupom")
        except (TypeError, ValueError):
            pass

    pct_pix = extraer_pct(post.get("pix"))
    if pct_pix:
        p -= p * (pct_pix / 100.0)
        partes.append(f"Pix {pct_pix:.0f}%")

    if not partes or p >= float(precio):
        return None, None
    return p, " + ".join(partes)


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
            import melila_api
            short_ml = melila_api.generar_melila(url, cookie_str=cookie_portal, tag=ML_TAG)
            if short_ml:
                print(f"  [meli.la] Enlace corto oficial generado: {short_ml}")
                return short_ml
            # NO ELEGIBLE: ML dice explícitamente que ese producto no está en el
            # programa de afiliados, así que el respaldo #D[A:tag] NO pagaría
            # comisión. Es mejor descartar el post que regalar el clic: el
            # publicador pasará al siguiente candidato con link que sí cobra.
            if getattr(melila_api, "ULTIMO_MOTIVO", None) == "no_elegible":
                print("  ❌ [Dinero] Producto NO elegible para afiliados: no paga comisión. Se descarta.")
                return None
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

    from modulo_ofertas import marcar_enviado, guardar_enviados, ya_enviado
    enviados = cargar_enviados_estricto()

    # Candidatos: no enviados, sin posts genéricos de cupón
    candidatos = []
    for p in posts:
        if p.get("tipo") == "cupons_loja":
            continue
        pid_c = p.get("id_post") or p.get("titulo", "")[:40]
        if not ya_enviado(pid_c, enviados, canal="whatsapp"):
            candidatos.append(p)
        if len(candidatos) >= 6:
            break

    if not candidatos:
        print("  [Fila] Todos los posts ya fueron enviados en la ventana anti-repetición.")
        return False, None, None

    # Regla de Oro + agente de calidad + VALIDADOR: se elige el primer candidato
    # que pase TODAS las puertas.
    #
    # El validador se ejecuta AQUÍ, en el momento de enviar, no al generar la
    # fila. Esa es la diferencia clave: la fila se generó hace horas, y en esas
    # horas el precio puede haber cambiado, el cupón haber vencido o el enlace
    # haberse quedado viejo. Antes se validaba al generar y el bucle publicaba
    # 5,5 h después con datos caducados (de ahí los cupones vencidos en el
    # canal). Ahora cada envío se valida contra el estado REAL del momento.
    cookie_portal = os.environ.get("ML_PORTAL_COOKIE", "").strip()
    post_a_enviar = None
    link_final = None
    try:
        from validador_oferta import validar_oferta, cargar_cupones as _cargar_cupones
        _cupones_validacion = _cargar_cupones()
    except Exception as e:
        _cupones_validacion = {}
        print(f"  [Validador] no disponible: {e}")

    for cand in candidatos:
        tit_c = cand.get("titulo", "")

        # ── PUERTA 0: VALIDADOR (producto → enlace → cupón → PIX) ──────────
        if _cupones_validacion is not None:
            try:
                ok_val, motivo_val, cand_limpio = validar_oferta(
                    cand, _cupones_validacion)
            except Exception as e:
                ok_val, motivo_val, cand_limpio = True, f"validador falló: {e}", cand
            if not ok_val:
                print(f"  ⛔ [VALIDACIÓN] RECHAZADO: {tit_c[:44]}")
                print(f"     Motivo: {motivo_val}")
                continue
            if motivo_val:
                print(f"  ✔️  [VALIDACIÓN] {motivo_val[:80]}")
            cand = cand_limpio

        # ── PUERTA 0.5: VERIFICACIÓN CONTRA LA API DE MERCADO LIVRE ───────
        # Comprueba que el producto EXISTE, sigue ACTIVO y que el nombre real
        # coincide con el del post. Es lo que detecta las OFERTAS MUERTAS:
        # medido sobre 191 posts, 2 apuntaban a productos que ya no existen en
        # el catálogo y se iban a publicar igual (el "todo está atrasado" que
        # reportó el usuario).
        #
        # Si la API no responde (sin token, 403 por permisos, timeout) NO se
        # descarta nada: la verificación es un extra, nunca un requisito. Solo
        # se descarta cuando la API dice claramente que el producto no existe.
        if "Mercado" in str(cand.get("loja", "")):
            try:
                from verificar_producto import verificar_post
                v = verificar_post(cand)
                if v.get("verificable"):
                    if v.get("alerta"):
                        print(f"  ⛔ [API ML] {v['alerta'][:74]}")
                        print("     Se descarta: el enlace NO es de este producto.")
                        continue
                    if v.get("inactivo"):
                        print(f"  ⛔ [API ML] producto inactivo "
                              f"({(v.get('real') or {}).get('estado')}): {tit_c[:38]}")
                        continue

                    real = v.get("real") or {}
                    precio_api = real.get("precio")

                    # ── CORRECCIÓN DE PRECIO ────────────────────────────────
                    # Si la API da un precio distinto al del post, se publica
                    # con el DE LA API, que es el real. El post se generó hace
                    # horas y el precio puede haber cambiado: es exactamente el
                    # "precios errados" que reportó el usuario.
                    # Medido: la Colcha Cobre Leito estaba a R$ 335,92 en el
                    # post y a R$ 519,90 en la API -> 184 reales de diferencia.
                    try:
                        p_post = float(cand.get("precio") or 0)
                        p_api = float(precio_api or 0)
                    except (TypeError, ValueError):
                        p_post = p_api = 0
                    if p_api and p_post and abs(p_api - p_post) > 1:
                        cand["precio_scrapeado"] = p_post
                        cand["precio"] = p_api
                        cand["precio_corregido_por_api"] = True
                        print(f"  🔧 [API ML] PRECIO CORREGIDO: "
                              f"R$ {p_post:.2f} -> R$ {p_api:.2f} (el real)")
                    # Precio original (tachado) real, si la API lo trae
                    if real.get("precio_lista"):
                        try:
                            pl = float(real["precio_lista"])
                            if pl > float(cand.get("precio") or 0):
                                cand["precio_anterior"] = pl
                        except (TypeError, ValueError):
                            pass
                    # Envío gratis real, no el que dijo el scraper
                    if real.get("envio_gratis") is not None:
                        cand["envio_gratis"] = bool(real["envio_gratis"])

                    if v.get("sin_precio_api"):
                        print("  ✅ [API ML] producto verificado (activo + nombre OK)")
                    else:
                        print(f"  ✅ [API ML] verificado: estado "
                              f"{real.get('estado')}, precio R$ {precio_api}")
                elif "404" in str(v.get("motivo", "")):
                    print(f"  ⛔ [API ML] el producto YA NO EXISTE (404): {tit_c[:38]}")
                    print("     Se descarta: el enlace llevaría a una página muerta.")
                    continue
            except Exception as e:
                print(f"  ℹ️  [API ML] sin verificar ({type(e).__name__})")

        lf = resolver_link_afiliado(cand.get("url", ""), cand.get("loja", ""), cookie_portal)
        if lf is None:
            print(f"  ⏭️  [Regla de Oro] /go/ no monetiza: {tit_c[:45]}")
            continue
        if not lf:
            print(f"  ⏭️  Sin link de afiliado: {tit_c[:45]}")
            continue
        try:
            from agente_calidad import verificar_link
            ok_link, det_link = verificar_link(lf)
        except Exception as e:
            ok_link, det_link = None, f"agente no disponible: {e}"
        if ok_link is False:
            print(f"  ⏭️  [Agente] link ROTO ({det_link}): {tit_c[:45]}")
            continue
        post_a_enviar, link_final = cand, lf
        if ok_link:
            print(f"  [Agente] link verificado: {det_link}")
        break

    if not post_a_enviar:
        print("  ❌ Ningún candidato tiene un link válido. No se publica nada esta pasada.")
        return False, None, None

    pid = post_a_enviar.get("id_post") or post_a_enviar.get("titulo", "")[:40]
    loja = post_a_enviar.get("loja", "Loja")
    titulo = post_a_enviar.get("titulo", "")
    url = post_a_enviar.get("url", "")
    print(f"\n  🎯 Post seleccionado: [{loja.upper()}] {titulo[:55]}")
    print(f"     Link base: {url}")

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

    # Sello de bajada: si el producto se repite porque el precio mejoró, hay que
    # DECIRLO. Repetir sin explicar por qué parece spam; con el sello es una
    # noticia ("bajó") y es justo lo que hace que la gente vuelva al canal.
    if post_a_enviar.get("bajada"):
        antes = post_a_enviar.get("precio_antes_publicado")
        try:
            antes = float(antes)
            if antes > 0:
                lineas.append(f"📉 BAJÓ DE PRECIO: antes R$ {int(antes)}")
            else:
                lineas.append("📉 BAJÓ DE PRECIO")
        except (TypeError, ValueError):
            lineas.append("📉 BAJÓ DE PRECIO")
        lineas.append("")

    # ── SELLO DE MEJOR PRECIO ────────────────────────────────────────────────
    # Lo que más vende en un canal de ofertas no es el precio: es saber que ese
    # precio es MEJOR que en otros lados. Va arriba del todo, justo debajo del
    # título, porque es lo primero que tiene que leer la gente.
    if post_a_enviar.get("mejor_precio") and post_a_enviar.get("comparativa"):
        lineas.append("🏆 MAIS BARATO QUE NAS OUTRAS LOJAS")
        lineas.append(f"   {post_a_enviar['comparativa']}")
        lineas.append("")

    if precio_int:
        lineas.append(f"💵 R$ {precio_limpo}")

    # ── LOS TRES PRECIOS DE MERCADO LIVRE ────────────────────────────────────
    # Descubrimiento del usuario, mirando la ficha de una TV: ML publica TRES
    # precios por producto, y los tres están en el JSON de la tarjeta:
    #
    #     R$ 1.859,98  em 10x         <- normal   (installments.price_total)
    #     R$ 1.673,98  no Pix         <- con PIX  (tracks.price.price)
    #     R$ 1.628,98  com Cupom      <- con cupón (promotions[type=coupon])
    #
    # El descuento Pix se buscaba en el TEXTO de la tarjeta, donde solo dice
    # "no Pix" sin porcentaje, así que nunca se encontraba y el bot acabó
    # inventándolo. El porcentaje sale de comparar los dos primeros precios.
    # Medido: 112 de 400 productos (28%) con descuento Pix real, del 5% al 26%.
    pix = (post_a_enviar.get("pix") or "").strip()
    precio_pix_ml = post_a_enviar.get("ml_precio_pix")
    try:
        pp = float(precio_pix_ml) if precio_pix_ml else 0
    except (TypeError, ValueError):
        pp = 0

    if pp > 0 and precio_int and pp < precio_int:
        lineas.append(f"⚡ No Pix: R$ {int(round(pp))}"
                      + (f"  ({pix})" if pix else ""))
    elif pix and pix.lower() not in ("à vista", "a vista", "-"):
        lineas.append(f"⚡ No Pix: {pix}")

    # Cuotas sin interés: el disparador de conversión más fuerte en Brasil
    # después del propio precio. La gente decide por "cuánto me sale al mes".
    cuotas = post_a_enviar.get("cuotas") or post_a_enviar.get("parcelas")
    try:
        n_cuotas = int(cuotas)
    except (TypeError, ValueError):
        n_cuotas = None
    if n_cuotas and n_cuotas > 1:
        sufijo = " sem juros" if post_a_enviar.get("cuotas_sin_interes") else ""
        texto_cuota = f"💳 em até {n_cuotas}x{sufijo}"
        try:
            valor_cuota = float(post_a_enviar.get("cuota_valor") or 0)
            if valor_cuota > 0:
                texto_cuota += f" de R$ {valor_cuota:.2f}".replace(".", ",")
        except (TypeError, ValueError):
            pass
        lineas.append(texto_cuota)

    # Envío gratis: en Brasil decide más compras de las que parece.
    if post_a_enviar.get("envio_gratis"):
        lineas.append("🚚 Frete grátis")

    # ── CUPÓN ────────────────────────────────────────────────────────────────
    # CAMBIO DE FONDO, tras comprobarlo con el usuario:
    #
    # Los códigos de afiliado (BARRATINHOJA, HOJEVAI...) son cupones GENERALES de
    # Mercado Livre, válidos para "produtos elegíveis" que solo ML conoce, y
    # ponerlos en un producto cualquiera FALLA:
    #     "Seu cupom foi salvo em 'Cupons', pois não se aplica a esta compra."
    #     "Este cupom já foi adicionado, mas ainda pode ser usado em produtos
    #      selecionados."
    #
    # Y NO existe forma de saber qué código aplica a qué producto: se buscó y
    # ML no lo expone en ninguna parte (ni la página de ofertas, ni la de
    # cupones, ni la API). El cupón de ML que sí aplica NO TIENE CÓDIGO: es un
    # cupón de vendedor que se activa en la propia página del producto.
    #
    # Así que se muestra lo que ML garantiza, sin inventar código:
    #     🎟️ Com cupom: R$ 674      (el precio real con el cupón de ML)
    # Si ML no dice que el producto tenga cupón, no se muestra nada.
    #
    # OJO: antes esto estaba dentro de `if cupom:`, y como ya no se asigna
    # ningún código el bloque nunca se ejecutaba -> los posts salían SIN cupón.
    # Ahora la condición es el precio con cupón que da ML.
    precio_cupon_ml = post_a_enviar.get("ml_precio_cupon")
    try:
        pc = float(precio_cupon_ml) if precio_cupon_ml else 0
    except (TypeError, ValueError):
        pc = 0

    if pc > 0 and precio_int and pc < precio_int * 0.995:
        # El cupón mejora el precio: se muestra el precio que ML garantiza.
        ahorro = precio_int - pc
        lineas.append(f"🎟️ Com cupom: R$ {int(round(pc))}"
                      f"  (economiza R$ {int(round(ahorro))})")
        lineas.append("   ative o cupom na página do produto")
    elif pc > 0:
        # ML confirma cupón PERO no mejora el precio actual. Caso real: la API
        # corrigió el precio a R$ 135 y el cupón daba R$ 140,31 -> el cupón era
        # PEOR que el precio. No se muestra nada: prometer un ahorro inexistente
        # es justo lo que el usuario venía denunciando.
        pass
    elif post_a_enviar.get("ml_tiene_cupon"):
        # ML confirma que el producto tiene cupón pero no da su precio. Se dice
        # que hay cupón SIN código: el código de afiliado es OTRO cupón distinto
        # y ponerlo hace que la compra falle ("nao se aplica a esta compra").
        lineas.append("🎟️ Tem cupom — ative na página do produto")
    # Sin confirmación de ML: NO se muestra ningún cupón. Antes se ponía el
    # código de afiliado por categoría y en el checkout no aplicaba.

    # ── PRECIO FINAL CON TODO APLICADO ────────────────────────────────────────
    # Es lo que más convierte: la gente no calcula porcentajes de cabeza, quiere
    # ver el número que va a pagar. Solo se muestra si hay datos reales para
    # calcularlo (porcentaje del cupón y/o descuento Pix conocidos y su tope).
    #
    # NO se muestra si coincide con el precio con Pix que ya está arriba: sería
    # repetir el mismo número dos veces en el post ("No Pix: R$ 1196" y
    # "Sai por R$ 1196 com Pix 10%").
    precio_final, etiqueta_final = calcular_precio_final(precio_int, post_a_enviar)
    repetido = False
    try:
        if precio_final and pp > 0 and abs(float(precio_final) - pp) < 1:
            repetido = True
    except (TypeError, ValueError):
        pass
    if precio_final and not repetido:
        lineas.append("")
        lineas.append(f"✅ Sai por R$ {int(round(precio_final))} com {etiqueta_final}")

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
        marcar_enviado(pid, enviados, canal="whatsapp", precio=precio_int)
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
        ultimo = ultimo_envio_utc(cargar_enviados_estricto())
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
