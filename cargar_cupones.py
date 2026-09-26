#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Cargador Rápido de Cupones desde Telegram / WhatsApp (cargar_cupones.py)
================================================================================
Permite pegar el texto tal cual llega del canal oficial de Mercado Livre Afiliados
y actualiza cupones.json y la fila_posts.json automáticamente.

Uso:
  1. Pega el texto en 'cupones_hoy.txt' y ejecuta:
     python cargar_cupones.py
  2. O pásalo por argumento o entrada interactiva.
"""
import re
import json
import sys
import io
from pathlib import Path
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
CUPONES_JSON = BASE / "cupones.json"
TXT_FILE = BASE / "cupones_hoy.txt"
DEFAULT_TAG = "ja20250119201346"

def parsear_texto_cupones(texto):
    """
    Extrae bloques como:
    🎟️ CODIGO 👉 10% OFF
    Tecnologia | Compra mínima: R$149 | Desconto máx: R$200
    Válido somente em 24.09 (o até 25.10)...
    """
    hoy = datetime.now(timezone.utc)
    ano_actual = hoy.year
    cupones_encontrados = []

    # Separar por bloques que empiezan con 🎟️ o códigos en mayúsculas
    lineas = texto.splitlines()
    bloque_actual = []

    for l in lineas:
        linea = l.strip()
        if not linea:
            continue
        if "🎟️" in linea or re.search(r"^[A-Z0-9]{5,20}\s*(?:👉|:|OFF|-)", linea):
            if bloque_actual:
                cupones_encontrados.append("\n".join(bloque_actual))
                bloque_actual = []
        bloque_actual.append(linea)

    if bloque_actual:
        cupones_encontrados.append("\n".join(bloque_actual))

    resultado = []
    for b in cupones_encontrados:
        # 1. Código
        m_cod = re.search(r"🎟️?\s*([A-Z0-9]{4,25})", b)
        if not m_cod:
            continue
        codigo = m_cod.group(1).strip()
        if codigo in ["CUPOM", "CUPONS", "CANAL", "AFILIADOS", "APENAS"]:
            continue

        # 2. Descuento (% o R$)
        m_desc = re.search(r"(\d+%\s*OFF|R\$\s*\d+\s*OFF)", b, re.IGNORECASE)
        desconto = m_desc.group(1).upper() if m_desc else "Desconto Especial"

        # 3. Compra mínima
        # OJO: antes se inventaba "R$ 1" cuando no aparecía. Un valor inventado
        # en un cupón es tan malo como un precio tachado inventado: se muestra
        # como si fuera un dato real. Si no está, se deja vacío.
        m_min = re.search(
            r"(?:Compra\s*m[ií]nima|m[ií]nimo)[.:\s]*(?:de\s*)?(R\$\s*[\d.,]+)",
            b, re.IGNORECASE)
        compra_minima = m_min.group(1) if m_min else ""

        # 4. Descuento máximo
        # Bug real encontrado: el canal escribe "Desconto máx.: R$200" CON PUNTO,
        # y la regex solo aceptaba ":" o espacio. Al no coincidir, se inventaba un
        # "R$ 500" por defecto, lo que inflaba el descuento calculado en el
        # precio final (OFFMLHOJE salía con tope 500 en vez de 200).
        m_max = re.search(
            r"(?:Desconto\s*m[aá]x|limite|tope)[.:\s]*(?:de\s*)?(R\$\s*[\d.,]+)",
            b, re.IGNORECASE)
        limite = m_max.group(1) if m_max else ""

        # 5. Fecha de vencimiento
        # Antes, si no había fecha, se ponía 31/12 del año en curso: un cupón
        # vencido parecía válido todo el año. Sin fecha = sin fecha.
        m_fecha = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", b)
        if m_fecha:
            dia = int(m_fecha.group(1))
            mes = int(m_fecha.group(2))
            ano_txt = m_fecha.group(3)
            try:
                if ano_txt:
                    ano_v = int(ano_txt)
                    ano_v = ano_v + 2000 if ano_v < 100 else ano_v
                else:
                    ano_v = ano_actual
                vencimiento = f"{ano_v}-{mes:02d}-{dia:02d}"
            except Exception:
                vencimiento = ""
        else:
            vencimiento = ""

        # 6. Categoría
        categoria = "Geral"
        if re.search(r"tecnologia|tech|inform[aá]tica", b, re.IGNORECASE):
            categoria = "Tecnologia"
        elif re.search(r"beleza|cuidado", b, re.IGNORECASE):
            categoria = "Beleza"
        elif re.search(r"casa|cozinha|eletro", b, re.IGNORECASE):
            categoria = "Casa & Eletro"
        elif re.search(r"moda|roupa|calcado", b, re.IGNORECASE):
            categoria = "Moda"

        resultado.append({
            "tienda": "Mercado Livre",
            "titulo": f"{desconto} em {categoria}",
            "codigo": codigo,
            "desconto": desconto,
            "compra_minima": compra_minima,
            "limite": limite,
            "vencimento": vencimiento,
            "hasta": vencimiento,
            "estado": "ativo",
            "categoria": categoria,
            "fonte": "ML Oficial Afiliados Telegram",
            "vigente": True,
            "url_afiliado": f"https://www.mercadolivre.com.br/cupons#D[A:{DEFAULT_TAG}]"
        })

    return resultado

def main():
    print("=" * 60)
    print("  CRIBA · CARGADOR DE CUPONES TELEGRAM / WHATSAPP")
    print("=" * 60)

    texto = ""
    if len(sys.argv) > 1:
        texto = " ".join(sys.argv[1:])
    elif TXT_FILE.exists():
        texto = TXT_FILE.read_text(encoding="utf-8").strip()

    if not texto:
        print(f"  Pega el texto del canal en '{TXT_FILE.name}' y vuelve a ejecutar.")
        print("  O escribe/pega el texto aquí y presiona Ctrl+Z (Enter):")
        try:
            texto = sys.stdin.read().strip()
        except Exception:
            return

    if not texto:
        print("  [!] No se ingresó texto.")
        return

    nuevos = parsear_texto_cupones(texto)
    print(f"  • Cupones detectados en el texto: {len(nuevos)}")

    if not nuevos:
        print("  [!] No se pudieron extraer cupones con formato válido.")
        return

    # Cargar cupones existentes
    data = {}
    existentes = []
    if CUPONES_JSON.exists():
        try:
            data = json.loads(CUPONES_JSON.read_text(encoding="utf-8"))
            existentes = data.get("cupones", [])
        except Exception:
            pass

    # Mantener cupones de otras tiendas (Amazon, etc.)
    otras_tiendas = [c for c in existentes if "mercado" not in (c.get("tienda") or "").lower()]

    # Unir nuevos cupones
    codigos_vistos = set()
    cupones_finales = []

    for c in nuevos:
        cod = c.get("codigo")
        if cod not in codigos_vistos:
            cupones_finales.append(c)
            codigos_vistos.add(cod)
            print(f"    🎟️ [{cod}] {c.get('desconto')} (Mín: {c.get('compra_minima')}) Vence: {c.get('vencimento')}")

    cupones_finales.extend(otras_tiendas)

    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "total": len(cupones_finales),
        "fuentes": ["ML Oficial Afiliados Telegram", "Amazon", "Shopee", "KaBuM!"],
        "cupones": cupones_finales
    }

    CUPONES_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✅ {len(nuevos)} cupones de Mercado Libre guardados en cupones.json!")

    # Regenerar fila de posts
    print("  • Regenerando fila de posts...")
    try:
        import subprocess
        subprocess.run([sys.executable, "gerar_fila_posts.py"], check=True)
    except Exception as e:
        print(f"  Error regenerando fila: {e}")

    print("=" * 60)

if __name__ == "__main__":
    main()
