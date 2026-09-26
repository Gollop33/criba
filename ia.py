#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIBA · Capa de IA intercambiable (ia.py)
==========================================
Gemini NO es obligatorio. Este módulo acepta cualquier proveedor con una API
compatible, y se elige con variables de entorno:

    AI_PROVIDER = deepseek | groq | openai | gemini | anthropic | openrouter | none
    AI_API_KEY  = tu clave
    AI_MODEL    = (opcional) modelo concreto

Por qué una capa y no atarse a uno: los precios y la calidad cambian cada mes.
Si un proveedor sube de precio o empeora, cambias dos variables y listo.

RECOMENDACIÓN PARA ESTE PROYECTO
--------------------------------
La IA aquí se usa para tareas PEQUEÑAS y concretas (parsear mensajes de cupones
en texto libre, clasificar productos, reescribir un título). No necesita un
modelo caro. Por relación calidad/precio:

  1. DeepSeek   - el más barato de los buenos. Sobra para esto.
  2. Groq       - tiene nivel gratuito y es el más RÁPIDO (Llama 3.3 70B).
                  Para clasificar 300 productos es la mejor opción por velocidad.
  3. Gemini     - nivel gratuito generoso. Perfectamente válido.
  4. OpenAI/Anthropic - los más caros; aquí sería pagar de más.

Uso:
    from ia import ia_disponible, preguntar
    if ia_disponible():
        texto = preguntar("Extrae los cupones de este mensaje: ...")
"""

import io
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# Cargar .env local
_env_file = Path(__file__).parent / ".env"
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

PROVEEDOR = os.environ.get("AI_PROVIDER", "").strip().lower()

# CADENA DE RESPALDO: AI_PROVIDER acepta varios separados por coma y se prueban
# en orden hasta que uno responda. Es la solución a que FreeLLMAPI viva en
# 127.0.0.1 (tu PC) y GitHub Actions no pueda alcanzarlo: en local usa el router
# con sus ~250 modelos gratis, y en la nube cae solo al siguiente.
#
#     AI_PROVIDER = freellmapi,huggingface
#
# CADA PROVEEDOR USA SU PROPIA CLAVE (una sola AI_API_KEY no serviría: el router
# local y Hugging Face usan claves distintas). Se busca en este orden:
#   1. AI_API_KEY_<PROVEEDOR>   (p.ej. AI_API_KEY_HUGGINGFACE)
#   2. la variable típica del proveedor (HUGGINGFACE_API_KEY, GROQ_API_KEY...)
#   3. AI_API_KEY como genérica
PROVEEDORES_ACTIVOS = [p.strip() for p in PROVEEDOR.split(",") if p.strip()]

CLAVES_POR_PROVEEDOR = {
    "huggingface": ["HUGGINGFACE_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"],
    "freellmapi":  ["FREELMAPI_API_KEY", "FREELLMAPI_API_KEY"],
    "local":       ["FREELMAPI_API_KEY", "FREELLMAPI_API_KEY"],
    "groq":        ["GROQ_API_KEY"],
    "deepseek":    ["DEEPSEEK_API_KEY"],
    "openai":      ["OPENAI_API_KEY"],
    "openrouter":  ["OPENROUTER_API_KEY"],
    "gemini":      ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "anthropic":   ["ANTHROPIC_API_KEY"],
}

# Modelo por defecto por proveedor (se puede pisar con AI_MODEL o
# AI_MODEL_<PROVEEDOR>).
MODELO_GENERICO = os.environ.get("AI_MODEL", "").strip()


def clave_de(proveedor):
    """Devuelve la clave que corresponde a ese proveedor ('' si no hay)."""
    k = os.environ.get(f"AI_API_KEY_{proveedor.upper()}", "").strip()
    if k:
        return k
    for var in CLAVES_POR_PROVEEDOR.get(proveedor, []):
        k = os.environ.get(var, "").strip()
        if k:
            return k
    return os.environ.get("AI_API_KEY", "").strip()


def modelo_de(proveedor):
    """Modelo para ese proveedor: AI_MODEL_<PROV> > AI_MODEL > por defecto."""
    m = os.environ.get(f"AI_MODEL_{proveedor.upper()}", "").strip()
    if m:
        return m
    if MODELO_GENERICO:
        return MODELO_GENERICO
    return PROVEEDORES.get(proveedor, ("", "", ""))[1]


def API_KEY_compat():  # noqa: N802  (compatibilidad con código antiguo)
    for p in PROVEEDORES_ACTIVOS:
        k = clave_de(p)
        if k:
            return k
    return ""

# endpoint, modelo por defecto, formato
PROVEEDORES = {
    "deepseek":   ("https://api.deepseek.com/chat/completions", "deepseek-chat", "openai"),
    "groq":       ("https://api.groq.com/openai/v1/chat/completions",
                   "llama-3.3-70b-versatile", "openai"),
    # Hugging Face: desde julio 2025 su servicio de Inference Providers habla la
    # API compatible con OpenAI. Se apunta a router.huggingface.co/v1 y el
    # proveedor real se puede poner en el nombre del modelo, p.ej.
    # "deepseek-ai/DeepSeek-V3-0324:novita". Con el nivel gratuito hay un cupo
    # mensual de creditos; para el volumen de este bot sobra.
    "huggingface": ("https://router.huggingface.co/v1/chat/completions",
                    "meta-llama/Llama-3.3-70B-Instruct", "openai"),
    "openai":     ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                   "deepseek/deepseek-chat", "openai"),
    # FreeLLMAPI: router LOCAL del usuario (app de escritorio que escucha en
    # 127.0.0.1:31415) con API compatible OpenAI y ~250 modelos detrás, muchos
    # con nivel gratuito. El modelo "auto" deja que el router elija.
    #
    # IMPORTANTE: al ser local, SOLO funciona ejecutando el bot en esta máquina.
    # GitHub Actions NO puede alcanzar 127.0.0.1 de tu PC. Sirve para pruebas
    # locales y para cuando el bot viva en un sitio donde puedas instalar la app
    # (un VPS, o tu PC siempre encendido). Para la nube usa groq / huggingface.
    "freellmapi": ("http://127.0.0.1:31415/v1/chat/completions", "auto", "openai"),
    "local":      ("http://127.0.0.1:31415/v1/chat/completions", "auto", "openai"),
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "{modelo}:generateContent", "gemini-2.0-flash", "gemini"),
    "anthropic":  ("https://api.anthropic.com/v1/messages", "claude-3-5-haiku-latest",
                   "anthropic"),
}


def ia_disponible():
    """True si al menos un proveedor de la cadena tiene clave."""
    return any(p in PROVEEDORES and clave_de(p) for p in PROVEEDORES_ACTIVOS)


def estado():
    """Texto para logs: la cadena de proveedores y si cada uno tiene clave."""
    if not PROVEEDORES_ACTIVOS:
        return "IA desactivada (falta AI_PROVIDER)"
    if not ia_disponible():
        return (f"IA configurada como '{', '.join(PROVEEDORES_ACTIVOS)}' "
                f"pero NINGUNO tiene clave")
    validos = [p for p in PROVEEDORES_ACTIVOS if p in PROVEEDORES]
    desconocidos = [p for p in PROVEEDORES_ACTIVOS if p not in PROVEEDORES]
    if validos:
        partes = []
        for p in validos:
            tiene = "clave OK" if clave_de(p) else "SIN CLAVE"
            partes.append(f"{p}/{modelo_de(p)} [{tiene}]")
        txt = "IA activa: " + " -> ".join(partes)
    else:
        txt = "IA: sin proveedores válidos"
    if desconocidos:
        txt += f" | no soportados: {', '.join(desconocidos)}"
    return txt


def _intentar(proveedor, prompt, sistema, max_tokens, timeout):
    """Un intento con un proveedor concreto, con SU clave. '' si falla."""
    endpoint, modelo_def, formato = PROVEEDORES[proveedor]
    modelo = modelo_de(proveedor)
    clave = clave_de(proveedor)
    endpoint = endpoint.format(modelo=modelo)

    if not clave:
        print(f"  [ia] {proveedor}: sin clave configurada, se salta")
        return ""

    if formato == "gemini":
        cuerpo = {"contents": [{"parts": [{"text": prompt}]}]}
        if sistema:
            cuerpo["systemInstruction"] = {"parts": [{"text": sistema}]}
        r = requests.post(f"{endpoint}?key={clave}", json=cuerpo, timeout=timeout)
        if r.status_code != 200:
            print(f"  [ia] {proveedor} HTTP {r.status_code}: {r.text[:120]}")
            return ""
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    if formato == "anthropic":
        cab = {"x-api-key": clave, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
        cuerpo = {"model": modelo, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if sistema:
            cuerpo["system"] = sistema
        r = requests.post(endpoint, headers=cab, json=cuerpo, timeout=timeout)
        if r.status_code != 200:
            print(f"  [ia] {proveedor} HTTP {r.status_code}: {r.text[:120]}")
            return ""
        return r.json()["content"][0]["text"]

    # formato OpenAI (deepseek, groq, huggingface, openai, openrouter, freellmapi)
    cab = {"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}
    mensajes = []
    if sistema:
        mensajes.append({"role": "system", "content": sistema})
    mensajes.append({"role": "user", "content": prompt})
    cuerpo = {"model": modelo, "messages": mensajes, "max_tokens": max_tokens,
              "temperature": 0.2}
    r = requests.post(endpoint, headers=cab, json=cuerpo, timeout=timeout)
    if r.status_code != 200:
        print(f"  [ia] {proveedor} HTTP {r.status_code}: {r.text[:120]}")
        return ""
    return r.json()["choices"][0]["message"]["content"]


def preguntar(prompt, sistema=None, max_tokens=2000, timeout=60):
    """
    Envía un prompt probando la CADENA de proveedores en orden y devuelve el
    texto del primero que responda ('' si fallan todos).

    Nunca lanza excepción: si la IA falla, el bot debe seguir publicando. Un
    agente de apoyo no puede tumbar el negocio.
    """
    if not ia_disponible():
        return ""
    global ULTIMO_PROVEEDOR
    try:
        import requests  # noqa: F401
    except ImportError:
        return ""

    for proveedor in PROVEEDORES_ACTIVOS:
        if proveedor not in PROVEEDORES:
            continue
        try:
            texto = _intentar(proveedor, prompt, sistema, max_tokens, timeout)
            if texto:
                ULTIMO_PROVEEDOR = proveedor
                return texto
        except Exception as e:
            print(f"  [ia] {proveedor} falló: {type(e).__name__}: {str(e)[:90]}")
            continue
    return ""


ULTIMO_PROVEEDOR = None


def preguntar_json(prompt, sistema=None, timeout=60):
    """Como preguntar() pero parsea JSON de la respuesta. Devuelve None si falla."""
    txt = preguntar(prompt, sistema, timeout=timeout)
    if not txt:
        return None
    txt = txt.strip()
    # Quitar vallas de código si el modelo las añade
    if txt.startswith("```"):
        txt = txt.split("```")[1] if "```" in txt[3:] else txt[3:]
        if txt.startswith("json"):
            txt = txt[4:]
    inicio, fin = txt.find("["), txt.rfind("]")
    if inicio == -1:
        inicio, fin = txt.find("{"), txt.rfind("}")
    if inicio == -1:
        return None
    try:
        return json.loads(txt[inicio:fin + 1])
    except Exception:
        return None


if __name__ == "__main__":
    print(estado())
    if ia_disponible():
        print()
        print("Prueba:", preguntar("Responde solo con la palabra OK")[:80])
