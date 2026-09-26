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
API_KEY = os.environ.get("AI_API_KEY", "").strip()
MODELO = os.environ.get("AI_MODEL", "").strip()

# Compatibilidad: si ya hay una clave de Gemini puesta a la antigua, se usa.
if not API_KEY:
    for var, prov in (("GEMINI_API_KEY", "gemini"), ("DEEPSEEK_API_KEY", "deepseek"),
                      ("GROQ_API_KEY", "groq"), ("OPENAI_API_KEY", "openai"),
                      ("OPENROUTER_API_KEY", "openrouter")):
        v = os.environ.get(var, "").strip()
        if v:
            API_KEY, PROVEEDOR = v, PROVEEDOR or prov
            break

# endpoint, modelo por defecto, formato
PROVEEDORES = {
    "deepseek":   ("https://api.deepseek.com/chat/completions", "deepseek-chat", "openai"),
    "groq":       ("https://api.groq.com/openai/v1/chat/completions",
                   "llama-3.3-70b-versatile", "openai"),
    "openai":     ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                   "deepseek/deepseek-chat", "openai"),
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "{modelo}:generateContent", "gemini-2.0-flash", "gemini"),
    "anthropic":  ("https://api.anthropic.com/v1/messages", "claude-3-5-haiku-latest",
                   "anthropic"),
}


def ia_disponible():
    return bool(PROVEEDOR and API_KEY and PROVEEDOR in PROVEEDORES)


def estado():
    """Texto para logs: qué proveedor está activo."""
    if not PROVEEDOR:
        return "IA desactivada (falta AI_PROVIDER)"
    if not API_KEY:
        return f"IA configurada como '{PROVEEDOR}' pero SIN clave (AI_API_KEY)"
    if PROVEEDOR not in PROVEEDORES:
        return f"IA: proveedor '{PROVEEDOR}' no soportado. Usa: {', '.join(PROVEEDORES)}"
    return f"IA activa: {PROVEEDOR} / {MODELO or PROVEEDORES[PROVEEDOR][1]}"


def preguntar(prompt, sistema=None, max_tokens=2000, timeout=60):
    """
    Envía un prompt y devuelve el texto de la respuesta ('' si falla).
    Nunca lanza excepción: si la IA falla, el bot debe seguir funcionando.
    """
    if not ia_disponible():
        return ""
    try:
        import requests
    except ImportError:
        return ""

    endpoint, modelo_def, formato = PROVEEDORES[PROVEEDOR]
    modelo = MODELO or modelo_def
    endpoint = endpoint.format(modelo=modelo)

    try:
        if formato == "gemini":
            cuerpo = {"contents": [{"parts": [{"text": prompt}]}]}
            if sistema:
                cuerpo["systemInstruction"] = {"parts": [{"text": sistema}]}
            r = requests.post(f"{endpoint}?key={API_KEY}", json=cuerpo, timeout=timeout)
            if r.status_code != 200:
                print(f"  [ia] {PROVEEDOR} HTTP {r.status_code}: {r.text[:160]}")
                return ""
            d = r.json()
            return d["candidates"][0]["content"]["parts"][0]["text"]

        if formato == "anthropic":
            cab = {"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
            cuerpo = {"model": modelo, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            if sistema:
                cuerpo["system"] = sistema
            r = requests.post(endpoint, headers=cab, json=cuerpo, timeout=timeout)
            if r.status_code != 200:
                print(f"  [ia] {PROVEEDOR} HTTP {r.status_code}: {r.text[:160]}")
                return ""
            return r.json()["content"][0]["text"]

        # formato OpenAI (deepseek, groq, openai, openrouter)
        cab = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        mensajes = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt})
        cuerpo = {"model": modelo, "messages": mensajes, "max_tokens": max_tokens,
                  "temperature": 0.2}
        r = requests.post(endpoint, headers=cab, json=cuerpo, timeout=timeout)
        if r.status_code != 200:
            print(f"  [ia] {PROVEEDOR} HTTP {r.status_code}: {r.text[:160]}")
            return ""
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [ia] error con {PROVEEDOR}: {e}")
        return ""


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
