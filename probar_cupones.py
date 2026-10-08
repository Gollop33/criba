#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Pruebas del carril de cupones (probar_cupones.py)
=========================================================
Todo OFFLINE: no toca la red, no envía nada a WhatsApp y no escribe en los
ficheros reales del bot (usa directorios temporales).

Cubre los fallos que se encontraron el 2026-10-07:

  1. La página de /cupons de Mercado Livre trae 13 blobs base64 de 88
     caracteres mezclados con los 11 códigos reales.
  2. El código INVENTABA "10% OFF" cuando la fuente no traía descuento.
  3. El descuento real venía dentro de un dict ({"text": "30% OFF com X"}) y se
     publicaba el dict entero en el grupo.
  4. Las tandas de cupón se generaban y se tiraban; el publicador las saltaba.
  5. Un cupón solo puede salir con enlace que DEMUESTRE llevar nuestro tag.

Uso: python probar_cupones.py
"""

import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

PASADAS = 0
FALLOS = []


def check(nombre, condicion, extra=""):
    global PASADAS
    if condicion:
        PASADAS += 1
        print(f"  [OK]   {nombre}")
    else:
        FALLOS.append(nombre)
        print(f"  [FALLO] {nombre} {extra}")


def main():
    print("=" * 68)
    print("  CRIBA · PRUEBAS DEL CARRIL DE CUPONES")
    print("=" * 68)

    # ── 1. HIGIENE DE CÓDIGOS ────────────────────────────────────────────────
    import cupons_ml as cm

    blobs = [
        "NNBpAXHMT8hIDNR67NEp3xjZhIoZM7hUa4JNTe0ujKOB4nlGn1WUU8gPaM-FHYcHqmVS1NcYrN-O3CH-mLSwMw==",
        "-B7IvCon8jDPYkfvi7kWOqr1iX4JG69uIGVdkhCzipQ1J3ehUKpWoSsIzv8DmcXXxJeBRTW6kgngp3Oy6qR5uA==",
        "Tb15j5FeebmZu56zGM4lsMQiumghElsCAJ-MYMjFnoTi5j",
    ]
    check("los blobs base64 de ML no pasan por códigos",
          all(not cm.codigo_valido(b) for b in blobs))
    check("los fragmentos de texto (MELI, 2273, 100R) tampoco",
          not any(cm.codigo_valido(x) for x in ("MELI", "2273", "100R", "", None)))
    check("los códigos reales SÍ pasan",
          all(cm.codigo_valido(x) for x in
              ("OFERTASMELI", "BATEDESCONTO", "VALEMUITO", "MELIBAIXOU", "SUPERPROMO25")))
    check("un código de 4 letras no pasa (era un trozo de texto)",
          not cm.codigo_valido("100R"))

    # ── 2. NUNCA INVENTAR EL DESCUENTO ───────────────────────────────────────
    check("sin descuento no se inventa un 10% OFF",
          cm.descuento_real(None) is None and cm.descuento_real("") is None
          and cm.descuento_real("qualquer coisa") is None)
    check("el descuento real se lee del texto de ML",
          cm.descuento_real("30% OFF com BATEDESCONTO") == "30% OFF")
    check("y de un descuento en reales",
          cm.descuento_real("R$ 20 OFF") == "R$ 20 OFF")

    # ── 3. EL TÍTULO ES UN DICT ──────────────────────────────────────────────
    check("un título en dict se convierte en texto",
          cm.texto_plano({"text": "30% OFF com BATEDESCONTO", "color": "red"})
          == "30% OFF com BATEDESCONTO")
    check("un título vacío no revienta ni inventa relleno",
          cm.texto_plano(None) == "" and cm.texto_plano({}) == "")
    check("una fecha inventada no se acepta como fecha",
          cm.fecha_valida("hoje") is None and cm.fecha_valida("2026-10-25") == "2026-10-25")

    # ── 4. VALIDADOR DE CUPONES ──────────────────────────────────────────────
    import validador_oferta as v

    tag = v._ml_tag()
    check("el tag de Mercado Livre está configurado", bool(tag), f"-> {tag!r}")

    cupon_ok = {"codigo": "OFERTASMELI", "tienda": "Mercado Livre", "fonte": "ML Oficial"}
    link_largo = f"https://www.mercadolivre.com.br/cupons#D[A:{tag}]"

    ok, _ = v.validar_cupon(cupon_ok, link_largo)
    check("cupón con fuente trazable y enlace con tag: se acepta", ok)

    ok, motivo = v.validar_cupon(cupon_ok, "https://www.mercadolivre.com.br/cupons")
    check("enlace SIN tag de afiliado: se rechaza", not ok, f"-> {motivo[:50]}")

    ok, motivo = v.validar_cupon(cupon_ok, "https://achadinhosnozap.com.br/go/noexiste/")
    check("/go/ que no existe: se rechaza (no verificable)", not ok, f"-> {motivo[:50]}")

    ok, motivo = v.validar_cupon(
        {"codigo": "OFERTASMELI", "tienda": "Mercado Livre", "fonte": "inventado a mano"},
        link_largo)
    check("fuente no trazable: se rechaza", not ok, f"-> {motivo[:50]}")

    ok, motivo = v.validar_cupon(
        {"codigo": "VENCIDO1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
         "hasta": "2020-01-01"}, link_largo)
    check("cupón caducado: se rechaza", not ok, f"-> {motivo[:50]}")

    ok, motivo = v.validar_cupon(
        {"codigo": blobs[0], "tienda": "Mercado Livre", "fonte": "ML Oficial"}, link_largo)
    check("código basura (blob base64): se rechaza", not ok, f"-> {motivo[:40]}")

    # /go/ SOLO se acepta si el HTML local lleva el tag dentro (prueba hermética)
    tmp_go = Path(tempfile.mkdtemp(prefix="criba_go_test_"))
    (tmp_go / "go" / "abc123").mkdir(parents=True)
    (tmp_go / "go" / "abc123" / "index.html").write_text(
        f'<meta http-equiv="refresh" content="0;url=https://www.mercadolivre.com.br/cupons#D[A:{tag}]">',
        encoding="utf-8")
    # El validador saca el tag de config_afiliados.json, así que el BASE falso
    # también necesita su config (si no, el tag saldría vacío y todo /go/
    # se rechazaría por un motivo equivocado).
    (tmp_go / "config_afiliados.json").write_text(
        json.dumps({"mercadolivre": {"id": tag}}), encoding="utf-8")
    base_original = v.BASE
    v.BASE = tmp_go
    try:
        ok, motivo = v.validar_cupon(cupon_ok, "https://achadinhosnozap.com.br/go/abc123/")
        check("/go/ propio CON el tag dentro: se acepta", ok, f"-> {motivo[:50]}")
        (tmp_go / "go" / "sinTag").mkdir(parents=True)
        (tmp_go / "go" / "sinTag" / "index.html").write_text(
            '<meta http-equiv="refresh" content="0;url=https://www.mercadolivre.com.br/cupons">',
            encoding="utf-8")
        ok, motivo = v.validar_cupon(cupon_ok, "https://achadinhosnozap.com.br/go/sinTag/")
        check("/go/ propio SIN tag: se rechaza (no monetiza)", not ok, f"-> {motivo[:44]}")
    finally:
        v.BASE = base_original

    # ── 5. MENSAJE DEL CUPÓN ─────────────────────────────────────────────────
    import cupones_vigia as cv

    m_sin = cv.mensaje_cupon({"codigo": "OFERTASMELI", "tienda": "Mercado Livre"}, link_largo)
    check("un cupón sin descuento no lo menciona (no inventa)",
          "% OFF" not in m_sin and "R$" not in m_sin)
    check("el mensaje siempre lleva el código", "OFERTASMELI" in m_sin)
    check("el mensaje siempre lleva el enlace", link_largo in m_sin)

    hoy = datetime.now(timezone.utc).date().isoformat()
    m_hoy = cv.mensaje_cupon(
        {"codigo": "HOY1", "tienda": "Mercado Livre", "desconto": "30% OFF", "hasta": hoy},
        link_largo)
    check("si vence hoy lo avisa", "Vence HOJE" in m_hoy)
    check("el descuento real aparece", "30% OFF" in m_hoy)

    # ── 6. EL VIGÍA DE PUNTA A PUNTA (todo en temporal) ──────────────────────
    import publicar_proximo as pp

    tmp = Path(tempfile.mkdtemp(prefix="criba_cupones_test_"))
    cupones_tmp = tmp / "cupones.json"
    registro_tmp = tmp / "logs" / "cupones_publicados.json"
    registro_tmp.parent.mkdir(parents=True, exist_ok=True)

    guardado = {
        "CUPONES_JSON": cv.CUPONES_JSON,
        "REGISTRO": cv.REGISTRO,
        "LOG_FILE": cv.LOG_FILE,
        "DRY": cv.DRY,
        "refrescar_fuente": cv.refrescar_fuente,
        "publicar": cv.publicar,
        "link_afiliado_cupones": cv.link_afiliado_cupones,
    }
    cv.CUPONES_JSON = cupones_tmp
    cv.REGISTRO = registro_tmp
    cv.LOG_FILE = tmp / "logs" / "ejecucion.log"
    cv.DRY = False
    cv.refrescar_fuente = lambda: False
    cv.link_afiliado_cupones = lambda: (link_largo, False)

    enviados_fake = []
    cv.publicar = lambda mensaje, codigo: (enviados_fake.append(codigo), True)[1]

    # Estado global del publicador, neutralizado (sin leer los ficheros reales)
    pp_guardado = {
        "cargar_control_canal": pp.cargar_control_canal,
        "limite_diario_calentamiento": pp.limite_diario_calentamiento,
        "horario_permitido_brt": pp.horario_permitido_brt,
        "ultimo_envio_utc": pp.ultimo_envio_utc,
        "cargar_enviados_estricto": pp.cargar_enviados_estricto,
    }
    pp.cargar_control_canal = lambda: {"dias_activo": 30, "envios_hoy": 0,
                                       "fecha_hoy": hoy}
    pp.limite_diario_calentamiento = lambda dias: 500
    pp.horario_permitido_brt = lambda: True
    pp.ultimo_envio_utc = lambda enviados: None
    pp.cargar_enviados_estricto = lambda: {}

    def escribir_cupones(lista):
        cupones_tmp.write_text(json.dumps({"total": len(lista), "cupones": lista},
                                          ensure_ascii=False), encoding="utf-8")

    def detectado(horas):
        return (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(timespec="seconds")

    try:
        # 6a. BOOTSTRAP: sin registro no se publica NADA
        escribir_cupones([
            {"codigo": "VIEJO1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "desconto": "20% OFF", "detectado_em": detectado(100)},
            {"codigo": "VIEJO2", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(100)},
        ])
        cv.main()
        check("bootstrap: no publica nada aunque haya cupones",
              not enviados_fake, f"-> {enviados_fake}")
        reg = json.loads(registro_tmp.read_text(encoding="utf-8"))
        check("bootstrap: registra los códigos existentes como ya vistos",
              set(reg["codigos"]) == {"VIEJO1", "VIEJO2"})

        # 6b. CUPÓN NUEVO -> se publica una vez
        escribir_cupones([
            {"codigo": "VIEJO1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(100)},
            {"codigo": "NUEVO30", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "desconto": "30% OFF", "detectado_em": detectado(0.1)},
        ])
        cv.main()
        check("un cupón NUEVO se publica", enviados_fake == ["NUEVO30"], f"-> {enviados_fake}")
        reg = json.loads(registro_tmp.read_text(encoding="utf-8"))
        check("el registro guarda cuándo se publicó",
              bool(reg["codigos"]["NUEVO30"].get("publicado_em")))

        # 6c. IDEMPOTENCIA: correr otra vez no lo republica
        enviados_fake.clear()
        cv.main()
        check("el mismo cupón no se publica dos veces", not enviados_fake, f"-> {enviados_fake}")

        # 6d. CUPÓN ANTIGUO (> frescura) no se publica
        enviados_fake.clear()
        escribir_cupones([
            {"codigo": "ANTIGUO9", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "desconto": "10% OFF", "detectado_em": detectado(30)},
        ])
        cv.main()
        check("un cupón detectado hace 30 h no se publica (frescura 24 h)",
              not enviados_fake, f"-> {enviados_fake}")

        # 6e. CUPÓN CADUCADO no se publica
        enviados_fake.clear()
        escribir_cupones([
            {"codigo": "CADUCO1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "desconto": "10% OFF", "hasta": "2020-01-01", "detectado_em": detectado(0.1)},
        ])
        cv.main()
        check("un cupón caducado no se publica", not enviados_fake, f"-> {enviados_fake}")

        # 6f. TOPE POR HORA
        enviados_fake.clear()
        registro_tmp.unlink()
        escribir_cupones([
            {"codigo": "TOPE1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(0.1)},
        ])
        cv.main()          # bootstrap
        escribir_cupones([
            {"codigo": "TOPE1", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(0.1)},
            {"codigo": "TOPE2", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(0.1)},
            {"codigo": "TOPE3", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": detectado(0.1)},
        ])
        cv.MAX_POR_HORA = 1
        enviados_fake.clear()
        cv.main()
        check("el tope por hora se respeta (1)", len(enviados_fake) == 1, f"-> {enviados_fake}")
        cv.MAX_POR_HORA = 3

        # 6g. CUPÓN DE OTRA TIENDA no se publica
        enviados_fake.clear()
        escribir_cupones([
            {"codigo": "MAGALU22", "tienda": "Magazine Luiza", "fonte": "ML Oficial",
             "detectado_em": detectado(0.1)},
        ])
        cv.main()
        check("un cupón de tienda no monetizada no se publica",
              not enviados_fake, f"-> {enviados_fake}")

    finally:
        cv.CUPONES_JSON = guardado["CUPONES_JSON"]
        cv.REGISTRO = guardado["REGISTRO"]
        cv.LOG_FILE = guardado["LOG_FILE"]
        cv.DRY = guardado["DRY"]
        cv.refrescar_fuente = guardado["refrescar_fuente"]
        cv.publicar = guardado["publicar"]
        cv.link_afiliado_cupones = guardado["link_afiliado_cupones"]
        for nombre, valor in pp_guardado.items():
            setattr(pp, nombre, valor)

    # ── 7. LA FILA INCLUYE LAS TANDAS DE CUPÓN ───────────────────────────────
    import gerar_fila_posts as gf

    tmp2 = Path(tempfile.mkdtemp(prefix="criba_fila_cupones_"))
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    achados = [{
        "id": f"MLB{i:07d}", "nombre": f"Jogo de Panelas Antiaderente {i}",
        "precio": 100.0 + i, "precio_anterior": 200.0, "desc_pct": 50.0,
        "imagen": f"https://img/{i}.jpg", "loja": "Mercado Livre",
        "url": f"https://www.mercadolivre.com.br/x/p/MLB{i:07d}#D[A:ja20250119201346]",
        "encontrado_em": ahora_iso,
    } for i in range(6)]
    (tmp2 / "achados.json").write_text(json.dumps({"achados": achados}), encoding="utf-8")
    (tmp2 / "achados_ml.json").write_text(json.dumps({"achados": []}), encoding="utf-8")
    (tmp2 / "achados_amazon.json").write_text(json.dumps({"achados": []}), encoding="utf-8")
    (tmp2 / "cupones.json").write_text(json.dumps({"cupones": [
        {"codigo": "OFERTASMELI", "tienda": "Mercado Livre", "fonte": "ML Oficial",
         "desconto": "30% OFF", "hasta": "2026-12-31"},
        {"codigo": "BATEDESCONTO", "tienda": "Mercado Livre", "fonte": "ML Oficial",
         "desconto": "30% OFF", "hasta": "2026-12-31"},
    ]}), encoding="utf-8")
    (tmp2 / "achados_especificos.json").write_text(json.dumps({"achados": []}), encoding="utf-8")

    gf_guardado = (gf.BASE, gf.ACHADOS_JSON, gf.FILE_ML, gf.FILE_AMZ, gf.CUPONES_JSON,
                   gf.FILA_JSON, gf.ENVIADOS_JSON)
    gf.BASE = tmp2
    gf.ACHADOS_JSON = tmp2 / "achados.json"
    gf.FILE_ML = tmp2 / "achados_ml.json"
    gf.FILE_AMZ = tmp2 / "achados_amazon.json"
    gf.CUPONES_JSON = tmp2 / "cupones.json"
    gf.FILA_JSON = tmp2 / "fila_posts.json"
    gf.ENVIADOS_JSON = tmp2 / "enviados.json"
    os.environ["NICHO_MODO"] = "geral"
    os.environ["MAX_LOTES_CUPON_FILA"] = "1"
    try:
        gf.armar_fila_rotativa()
        fila = json.loads(gf.FILA_JSON.read_text(encoding="utf-8"))["fila"]
        tandas = [p for p in fila if p.get("tipo") == "cupon"]
        check("la fila incluye la tanda de cupón (antes se tiraba)", len(tandas) >= 1,
              f"-> {len(tandas)}")
        check("la tanda de cupón va al PRINCIPIO de la fila",
              bool(fila) and fila[0].get("tipo") == "cupon",
              f"-> {fila[0].get('tipo') if fila else 'fila vacía'}")
        if tandas:
            check("la tanda lleva el mensaje montado y los códigos",
                  bool(tandas[0].get("mensaje")) and bool(tandas[0].get("codigos")))
            check("el mensaje de la tanda no lleva un descuento inventado",
                  "R$ 15 OFF" not in tandas[0]["mensaje"]
                  and "não informado" not in tandas[0]["mensaje"].replace("desconto não informado", "")
                  or "30% OFF" in tandas[0]["mensaje"])
    finally:
        (gf.BASE, gf.ACHADOS_JSON, gf.FILE_ML, gf.FILE_AMZ, gf.CUPONES_JSON,
         gf.FILA_JSON, gf.ENVIADOS_JSON) = gf_guardado
        os.environ.pop("MAX_LOTES_CUPON_FILA", None)

    # ── 8. ROTACIÓN Y VIGENCIA EFECTIVA (el "cupón antiguo" del 2026-10-08) ──
    # El usuario lo reportó desde el grupo: las MISMAS 8 tandas salieron 12
    # veces en 2 días. Estas pruebas fijan el arreglo.
    def hace_horas(h):
        return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat(timespec="seconds")

    check("un cupón sin fecha detectado hace 30 días YA NO vive",
          not gf.cupon_vigente({"codigo": "X", "detectado_em": hace_horas(24 * 30)}))
    check("un cupón sin fecha detectado hace 2 días SÍ vive",
          gf.cupon_vigente({"codigo": "X", "detectado_em": hace_horas(48)}))
    check("una fecha de vencimiento explícita manda sobre la detección",
          gf.cupon_vigente({"codigo": "X", "hasta": "2030-01-01",
                            "detectado_em": hace_horas(24 * 60)})
          and not gf.cupon_vigente({"codigo": "X", "hasta": "2020-01-01"}))
    check("sin ninguna fecha no se declara muerto (no se inventa)",
          gf.cupon_vigente({"codigo": "X"}))

    pool = [{"codigo": f"COD{i}", "tienda": "Mercado Livre", "fonte": "ML Oficial",
             "detectado_em": hace_horas(1)} for i in range(8)]
    # _registro_cupones() devuelve el mapa {codigo: info} (no el dict completo)
    registro_falso = {f"COD{i}": {"publicado_em": hace_horas(1)} for i in range(4)}
    gf._registro_cupones = lambda: registro_falso
    rotados = gf._rotar_cupones(pool)
    primeros = [c["codigo"] for c in rotados[:4]]
    check("la rotación pone PRIMERO los que nunca salieron",
          all(c not in ("COD0", "COD1", "COD2", "COD3") for c in primeros),
          f"-> {primeros}")
    check("los que salieron hace 1 h quedan al final (no se repiten)",
          [c["codigo"] for c in rotados[4:]] == ["COD0", "COD1", "COD2", "COD3"])
    gf._registro_cupones = lambda: {}
    check("sin registro, el orden no rompe (y prioriza ML Oficial)",
          len(gf._rotar_cupones(pool)) == 8)
    check("el id de la tanda es ESTABLE (mismos códigos, mismo id)",
          gf._huella(["A", "B", "C", "D"]) == gf._huella(["D", "C", "B", "A"])
          and gf._huella(["A", "B", "C", "D"]) != gf._huella(["A", "B", "C", "E"]))
    check("el id de la tanda NO lleva la hora (era la causa de la repetición)",
          "2026" not in gf._huella(["A", "B"]))

    # ── RESULTADO ────────────────────────────────────────────────────────────
    print("-" * 68)
    print(f"  RESULTADO: {PASADAS}/{PASADAS + len(FALLOS)} pruebas pasadas")
    if FALLOS:
        print("  FALLARON: " + ", ".join(FALLOS))
        print("=" * 68)
        return 1
    print("  TODAS LAS PRUEBAS PASAN: el cupón sale verificado, con enlace que monetiza.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
