# -*- coding: utf-8 -*-
"""Extrae UNA oferta real de achados.json (solo lectura) y la vuelca a
video/toolchain/oferta.json para que la use el renderizador.

Uso:
    python extraer_oferta.py                    # auto: mejor oferta con cupon+pix
    python extraer_oferta.py "Power Bank"       # busca por texto en el nombre
"""
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
ACHADOS = os.path.join(RAIZ, "achados.json")
SALIDA = os.path.join(AQUI, "oferta.json")

CAMPOS = [
    "nombre", "precio", "precio_anterior", "desc_pct", "imagen",
    "pix", "ml_precio_pix", "ml_precio_cupon", "ml_tiene_cupon",
    "cuotas", "envio_gratis", "loja", "categoria",
]


def num(v):
    """Convierte '1.234,56' o 1234.56 o None a float."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def main():
    with open(ACHADOS, "r", encoding="utf-8") as fh:
        dados = json.load(fh)

    achados = dados.get("achados") if isinstance(dados, dict) else dados
    print("total achados:", len(achados))

    if achados:
        print("campos disponibles:", sorted(achados[0].keys()))

    filtro = sys.argv[1].lower() if len(sys.argv) > 1 else None

    def tem_cupom(o):
        if o.get("ml_tiene_cupon") in (True, "True", "true", 1):
            return True
        if num(o.get("ml_precio_cupon")):
            return True
        c = str(o.get("pix") or "").lower()
        return "cupom" in c or "cupon" in c

    def tem_pix(o):
        if num(o.get("ml_precio_pix")):
            return True
        c = str(o.get("pix") or "").lower()
        return bool(c)

    completos = [o for o in achados if tem_cupom(o) and tem_pix(o) and o.get("imagen")]
    print("con cupon + pix + imagen:", len(completos))

    if filtro:
        alvo = [o for o in completos if filtro in str(o.get("nombre", "")).lower()]
        if alvo:
            completos = alvo

    if not completos:
        completos = [o for o in achados if o.get("imagen")]

    # Ordena por descuento descendente para coger la mas atractiva
    completos.sort(key=lambda o: num(o.get("desc_pct")) or 0.0, reverse=True)
    escolhida = completos[0]

    limpa = {k: escolhida.get(k) for k in CAMPOS}
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump(limpa, fh, ensure_ascii=False, indent=2)

    print("\n=== OFERTA ELEGIDA ===")
    for k in CAMPOS:
        print(" ", k, "=", repr(limpa[k]))
    print("\nescrito en:", SALIDA)


if __name__ == "__main__":
    main()
