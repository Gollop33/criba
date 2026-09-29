#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Pruebas del validador (probar_validador.py)
====================================================
Comprueba que NO se publiquen combinaciones incorrectas. Son los escenarios que
pidió el usuario, uno por uno.

    python probar_validador.py
    python validador_oferta.py --probar
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from validador_oferta import validar_oferta  # noqa: E402

AHORA = datetime.now(timezone.utc)
HOY = AHORA.strftime("%Y-%m-%d")
FUTURO = (AHORA + timedelta(days=30)).strftime("%Y-%m-%d")
PASADO = (AHORA - timedelta(days=5)).strftime("%Y-%m-%d")

# Todos los cupones de prueba llevan fuente: es OBLIGATORIA. Un cupón sin fuente
# trazable no se usa. La regla salió del bug reportado por el usuario: TECH20,
# sin fuente y con la tienda mal puesta, salía en TODAS las publicaciones de
# Amazon por ser el único cupón marcado como "Amazon".
FUENTE = "Telegram ML Afiliados"

# ── Cupones de prueba ────────────────────────────────────────────────────────
CUPONES = {
    "VALIDO_TECH": {
        "codigo": "VALIDO_TECH", "tienda": "Mercado Livre", "categoria": "Tecnologia",
        "desconto": "15% OFF", "hasta": FUTURO, "compra_minima": "R$50",
        "fonte": FUENTE,
    },
    "VALIDO_CASA": {
        "codigo": "VALIDO_CASA", "tienda": "Mercado Livre", "categoria": "Casa",
        "desconto": "20% OFF", "hasta": FUTURO, "compra_minima": "R$100",
        "fonte": FUENTE,
    },
    "AMAZON_TECH": {
        "codigo": "AMAZON_TECH", "tienda": "Amazon", "categoria": "Informatica",
        "desconto": "20% OFF", "hasta": FUTURO, "fonte": FUENTE,
    },
    "VENCIDO": {
        "codigo": "VENCIDO", "tienda": "Mercado Livre", "categoria": "Tecnologia",
        "desconto": "30% OFF", "hasta": PASADO, "fonte": FUENTE,
    },
    "MINIMO_ALTO": {
        "codigo": "MINIMO_ALTO", "tienda": "Mercado Livre", "categoria": "Tecnologia",
        "desconto": "25% OFF", "hasta": FUTURO, "compra_minima": "R$5000",
        "fonte": FUENTE,
    },
    # Réplica EXACTA del cupón que reportó el usuario: marcado como Amazon, sin
    # fuente, de una carga manual vieja. Tiene que ser RECHAZADO.
    "TECH20": {
        "codigo": "TECH20", "tienda": "Amazon",
        "titulo": "Cupons de Tecnologia e Informática",
        "desconto": "20% OFF", "valor": 20, "hasta": FUTURO,
    },
}

# ── Productos base ───────────────────────────────────────────────────────────
MONITOR = {
    "titulo": "Monitor Gamer LG UltraGear 27 Full HD IPS 144Hz 1ms",
    "loja": "Mercado Livre",
    "precio": 1200.0,
    "imagen": "https://http2.mlstatic.com/D_NQ_NP_2X_123-MLA.jpg",
    "categoria": "Monitores & Displays",
    "url": ("https://www.mercadolivre.com.br/monitor-gamer-lg-ultragear-27-"
            "full-hd-ips-144hz/p/MLB34928101#D[A:ja20250119201346]"),
    "revalidado_em": AHORA.isoformat(),
}
CADEIRA = {
    "titulo": "Cadeira Portatil Alimentacao Para Bebe Altura Ajustavel 6in1 Verde",
    "loja": "Mercado Livre",
    "precio": 392.0,
    "imagen": "https://http2.mlstatic.com/D_NQ_NP_2X_456-MLA.jpg",
    "categoria": "Casa & Móveis",
    "url": ("https://www.mercadolivre.com.br/cadeira-portatil-alimentacao-para-"
            "bebe-altura-ajustavel-6in1-verde/p/MLB12345678"),
    "revalidado_em": AHORA.isoformat(),
}
AMAZON_MOUSE = {
    "titulo": "Mouse sem fio Logitech Pebble 2 M350s com Clique Silencioso",
    "loja": "Amazon",
    "precio": 119.0,
    "imagen": "https://m.media-amazon.com/images/I/61abc.jpg",
    "categoria": "Periféricos & Setup Gamer",
    "url": "https://www.amazon.com.br/dp/B0CJ3BDN7T?tag=criba20-20",
    "revalidado_em": AHORA.isoformat(),
}


def _t(nombre, post, cupones=None, espera_ok=True, espera_sin_cupon=False,
       espera_motivo=None):
    """Ejecuta un escenario y comprueba el resultado."""
    ok, motivo, limpio = validar_oferta(post, cupones if cupones is not None else CUPONES,
                                        registrar=False)
    fallos = []
    if ok != espera_ok:
        fallos.append(f"esperaba ok={espera_ok} y dio ok={ok}")
    if espera_sin_cupon and limpio.get("cupom"):
        fallos.append(f"debía salir SIN cupón y salió con {limpio.get('cupom')}")
    if espera_motivo and espera_motivo.lower() not in str(motivo).lower():
        fallos.append(f"motivo inesperado: {motivo!r}")
    estado = "OK  " if not fallos else "FALLO"
    print(f"  [{estado}] {nombre}")
    print(f"         resultado: {'aceptada' if ok else 'RECHAZADA'} | {motivo}")
    cup = limpio.get("cupom")
    if cup:
        print(f"         cupón final: {cup} (confianza {limpio.get('cupom_confianza')})")
    if limpio.get("pix"):
        print(f"         pix final: {limpio['pix']}")
    for f in fallos:
        print(f"         !! {f}")
    return not fallos


def main():
    print("=" * 78)
    print("  PRUEBAS DEL VALIDADOR DE OFERTAS")
    print("=" * 78)
    print(f"  cupones de prueba: {len(CUPONES)} | hoy: {HOY}")
    print()

    resultados = []

    # ── 1. Producto SIN cupón ───────────────────────────────────────────────
    print("── 1. PRODUCTO SIN CUPÓN ──")
    p = dict(MONITOR)
    resultados.append(_t("Monitor sin cupón asignado", p, espera_ok=True))

    # ── 2. Producto CON cupón válido (misma tienda y categoría) ─────────────
    print("\n── 2. PRODUCTO CON CUPÓN VÁLIDO ──")
    p = dict(MONITOR, cupom="VALIDO_TECH")
    resultados.append(_t("Monitor + cupón de Tecnología (correcto)", p,
                         espera_ok=True))

    # ── 3. Cupón de OTRA TIENDA (el bug reportado: Amazon con cupón de ML) ──
    print("\n── 3. CUPÓN DE OTRA TIENDA ──")
    p = dict(AMAZON_MOUSE, cupom="VALIDO_TECH")   # Amazon + cupón de Mercado Livre
    resultados.append(_t("Producto Amazon + cupón de Mercado Livre", p,
                         espera_ok=True, espera_sin_cupon=True,
                         espera_motivo="es de mercadolivre"))

    # ── 4. Cupón de CATEGORÍA equivocada (silla de bebé + Tecnología) ───────
    print("\n── 4. CUPÓN DE CATEGORÍA EQUIVOCADA ──")
    p = dict(CADEIRA, cupom="VALIDO_TECH")   # Casa & Móveis + cupón Tecnología
    resultados.append(_t("Silla de bebé (Casa) + cupón de Tecnología", p,
                         espera_ok=True, espera_sin_cupon=True,
                         espera_motivo="tecnologia"))

    # ── 5. ENLACE INCORRECTO (de otra tienda que el producto) ───────────────
    print("\n── 5. ENLACE INCORRECTO ──")
    p = dict(MONITOR, url="https://www.amazon.com.br/dp/B0CJ3BDN7T?tag=criba20-20")
    resultados.append(_t("Producto de ML con enlace de Amazon", p,
                         espera_ok=False, espera_motivo="enlace de amazon"))

    # Enlace que no corresponde al producto (otro producto distinto)
    p = dict(MONITOR, url=("https://www.mercadolivre.com.br/cadeira-de-escritorio-"
                           "gamer-reclinavel-preta/p/MLB99999999"))
    resultados.append(_t("Monitor con enlace de una silla de escritorio", p,
                         espera_ok=False, espera_motivo="no parece del producto"))

    # ── 6. Enlace /go/ (no monetiza) ────────────────────────────────────────
    print("\n── 6. ENLACE /go/ (no monetiza) ──")
    p = dict(MONITOR, url="https://www.mercadolivre.com.br/go/monitor-gamer-lg")
    resultados.append(_t("Enlace /go/", p, espera_ok=False, espera_motivo="/go/"))

    # ── 7. DESCUENTO PIX: solo si existe ────────────────────────────────────
    print("\n── 7. DESCUENTO PIX ──")
    p = dict(MONITOR, cupom="VALIDO_TECH", pix="5% OFF")
    resultados.append(_t("Producto CON PIX real (5% OFF)", p, espera_ok=True))

    p = dict(MONITOR, cupom="VALIDO_TECH", pix="")
    ok, motivo, limpio = validar_oferta(p, CUPONES, registrar=False)
    sin_pix = not limpio.get("pix")
    print(f"  [{'OK  ' if sin_pix else 'FALLO'}] Producto SIN PIX: no debe inventarse")
    print(f"         pix final: {limpio.get('pix')!r} (debe ser None/'' vacío)")
    resultados.append(sin_pix)

    p = dict(MONITOR, cupom="VALIDO_TECH", pix="à vista")
    ok, motivo, limpio = validar_oferta(p, CUPONES, registrar=False)
    solo_medio = not limpio.get("pix")
    print(f"  [{'OK  ' if solo_medio else 'FALLO'}] 'à vista' no es descuento: no se muestra")
    resultados.append(solo_medio)

    # ── 8. Cupón + PIX juntos ───────────────────────────────────────────────
    print("\n── 8. CUPÓN + PIX ──")
    p = dict(MONITOR, cupom="VALIDO_TECH", pix="5% OFF")
    resultados.append(_t("Monitor + cupón válido + PIX", p, espera_ok=True))

    # ── 9. Cupón VENCIDO ────────────────────────────────────────────────────
    print("\n── 9. CUPÓN VENCIDO ──")
    p = dict(MONITOR, cupom="VENCIDO")
    resultados.append(_t(f"Monitor + cupón vencido el {PASADO}", p,
                         espera_ok=True, espera_sin_cupon=True,
                         espera_motivo="vencido"))

    # ── 10. Compra mínima del cupón no alcanzada ────────────────────────────
    print("\n── 10. COMPRA MÍNIMA NO ALCANZADA ──")
    p = dict(MONITOR, precio=100.0, cupom="MINIMO_ALTO")
    resultados.append(_t("Monitor de R$100 + cupón que exige R$5000", p,
                         espera_ok=True, espera_sin_cupon=True,
                         espera_motivo="mínimo"))

    # ── 11. Precio promocional (precio_anterior) ────────────────────────────
    print("\n── 11. PRECIO PROMOCIONAL ──")
    p = dict(MONITOR, precio=999.0, precio_anterior=1499.0, desc_pct=33.0,
             cupom="VALIDO_TECH")
    ok, motivo, limpio = validar_oferta(p, CUPONES, registrar=False)
    correcto = ok and limpio.get("precio") == 999.0 and limpio.get("precio_anterior") == 1499.0
    print(f"  [{'OK  ' if correcto else 'FALLO'}] Precio promocional conservado")
    print(f"         precio={limpio.get('precio')} anterior={limpio.get('precio_anterior')} "
          f"desc={limpio.get('desc_pct')}%")
    resultados.append(correcto)

    # ── 12. DATOS ANTIGUOS vs NUEVOS ────────────────────────────────────────
    print("\n── 12. DATOS ANTIGUOS ──")
    viejo = (AHORA - timedelta(days=4)).isoformat()
    p = dict(MONITOR, cupom="VALIDO_TECH", revalidado_em=viejo)
    resultados.append(_t("Dato de hace 4 días (debe rechazarse)", p,
                         espera_ok=False, espera_motivo="hace"))

    # ── 13. Producto sin precio / sin imagen / sin tienda ───────────────────
    print("\n── 13. PRODUCTO INCOMPLETO ──")
    for campo, valor, etiqueta in (
        ("precio", 0, "sin precio"),
        ("imagen", None, "sin imagen"),
        ("loja", "Tienda Rara", "tienda no reconocida"),
        ("titulo", "Corto", "título inservible"),
    ):
        p = dict(MONITOR, cupom="VALIDO_TECH")
        p[campo] = valor
        ok, motivo, limpio = validar_oferta(p, CUPONES, registrar=False)
        bien = (not ok) and not limpio.get("cupom")
        print(f"  [{'OK  ' if bien else 'FALLO'}] {etiqueta} -> "
              f"{'rechazado' if not ok else 'ACEPTADO (mal)'} | {motivo}")
        resultados.append(bien)

    # ── 14. Cupón de tienda no declarada ────────────────────────────────────
    print("\n── 14. CUPÓN SIN TIENDA DECLARADA ──")
    cupones2 = dict(CUPONES)
    cupones2["SIN_TIENDA"] = {"codigo": "SIN_TIENDA", "desconto": "30% OFF",
                              "hasta": FUTURO}
    p = dict(MONITOR, cupom="SIN_TIENDA")
    resultados.append(_t("Cupón sin tienda (no verificable)", p, cupones=cupones2,
                         espera_ok=True, espera_sin_cupon=True,
                         espera_motivo="sin tienda"))

    # ── 15. EL BUG REPORTADO: TECH20 en TODAS las publicaciones de Amazon ───
    print("\n── 15. BUG REPORTADO: CUPÓN SIN FUENTE EN AMAZON (TECH20) ──")
    # El usuario lo reportó así: 'TECH20 sale en todas las publicaciones de
    # Amazon y no es cupón de allí, es de Mercado Livre y además está viejo'.
    # Era el ÚNICO cupón marcado como Amazon y no tenía fuente: una entrada
    # manual vieja que los scripts resucitaban en cada ejecución.
    p = dict(AMAZON_MOUSE, cupom="TECH20")
    ok, motivo, limpio = validar_oferta(p, CUPONES, registrar=False)
    bien = ok and not limpio.get("cupom") and "fuente" in motivo.lower()
    print(f"  [{'OK  ' if bien else 'FALLO'}] Producto Amazon + TECH20 (sin fuente)")
    print(f"         resultado: {'aceptada' if ok else 'rechazada'} | {motivo}")
    print(f"         cupón final: {limpio.get('cupom')!r} (debe ser None)")
    resultados.append(bien)

    # Y comprobar que un cupón de Amazon CON fuente sí se acepta
    p2 = dict(AMAZON_MOUSE, cupom="AMAZON_TECH")
    resultados.append(_t("Producto Amazon + cupón de Amazon CON fuente (correcto)",
                         p2, espera_ok=True))

    # ── 16. limpiar_cupones(): la función que impide que resuciten ──────────
    print("\n── 16. LIMPIEZA DE CUPONES HUÉRFANOS Y CADUCADOS ──")
    from validador_oferta import limpiar_cupones
    mezcla = [
        {"codigo": "BUENO", "tienda": "Mercado Livre", "hasta": FUTURO,
         "fonte": FUENTE},
        {"codigo": "SIN_FUENTE", "tienda": "Amazon", "hasta": FUTURO},
        {"codigo": "CADUCO", "tienda": "Mercado Livre", "hasta": PASADO,
         "fonte": FUENTE},
        {"codigo": "SIN_TIENDA", "hasta": FUTURO, "fonte": FUENTE},
        "esto no es un cupón",
    ]
    conservados, descartados = limpiar_cupones(mezcla)
    bien = (len(conservados) == 1 and conservados[0]["codigo"] == "BUENO"
            and len(descartados) == 4)
    print(f"  [{'OK  ' if bien else 'FALLO'}] de 5 entradas -> "
          f"{len(conservados)} conservada, {len(descartados)} descartadas")
    for c, m in descartados:
        cod = c.get("codigo") if isinstance(c, dict) else c
        print(f"         X {cod}: {m}")
    resultados.append(bien)

    # ── RESUMEN ─────────────────────────────────────────────────────────────
    total = len(resultados)
    bien = sum(1 for r in resultados if r)
    print()
    print("=" * 78)
    print(f"  RESULTADO: {bien}/{total} pruebas pasadas")
    if bien == total:
        print("  TODAS LAS PRUEBAS PASAN: no se publican combinaciones incorrectas.")
    else:
        print(f"  HAY {total - bien} FALLOS. Revisar arriba.")
    print("=" * 78)
    return 0 if bien == total else 1


if __name__ == "__main__":
    sys.exit(main())
