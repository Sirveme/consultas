# -*- coding: utf-8 -*-
"""
ia.py — Cliente de IA (async, httpx). Salida estructurada (JSON Schema).

Diseñado provider-agnóstico sobre el contrato OpenAI-compatible de
`/chat/completions` (el más portable: OpenAI, OpenRouter, Together, etc.).
El endpoint, la clave y el MODELO se leen de variables de entorno; NO se
hardcodea ningún modelo. Si tu proveedor usa otro formato, este es el único
archivo a ajustar.

Devuelve SIEMPRE un dict:
  { "ok": bool, "data": <dict del esquema> | None,
    "tokens_entrada": int, "tokens_salida": int, "modelo": str,
    "error": str | None }
Nunca lanza: si algo falla, ok=False y el llamador ofrece WhatsApp.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from .prompts import SYSTEM_PROMPT, ESQUEMA_SALIDA

log = logging.getLogger("uvicorn.error")

IA_API_URL = os.getenv("IA_API_URL", "https://api.openai.com/v1/chat/completions").strip()
IA_API_KEY = os.getenv("IA_API_KEY", "").strip()
MODELO_IA = os.getenv("MODELO_IA", "").strip()   # nunca se asume un modelo por defecto
TIMEOUT_S = 25.0


def _mensajes_api(turnos: list[dict]) -> list[dict]:
    """turnos = [{'rol': 'usuario'|'asistente', 'contenido': str}] -> formato chat."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for t in turnos:
        role = "assistant" if t.get("rol") == "asistente" else "user"
        msgs.append({"role": role, "content": t.get("contenido") or ""})
    return msgs


async def consultar(turnos: list[dict]) -> dict:
    """Un turno de la IA sobre la conversación completa (lista de turnos)."""
    base = {"ok": False, "data": None, "tokens_entrada": 0, "tokens_salida": 0,
            "modelo": MODELO_IA, "error": None, "detalle": None}
    if not IA_API_KEY or not MODELO_IA:
        base["error"] = "config_incompleta"   # falta IA_API_KEY o MODELO_IA
        return base

    payload = {
        "model": MODELO_IA,
        "messages": _mensajes_api(turnos),
        # Sin `temperature`: algunos modelos (p. ej. gpt-5.6-luna) solo aceptan el
        # valor por defecto y devuelven 400 con cualquier otro. No se envía.
        "response_format": {"type": "json_schema", "json_schema": ESQUEMA_SALIDA},
    }
    headers = {"Authorization": f"Bearer {IA_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(IA_API_URL, json=payload, headers=headers)
    except Exception as e:
        base["error"] = f"red:{type(e).__name__}"
        return base

    if r.status_code != 200:
        # Guarda y loguea el CUERPO de la respuesta (truncado) para poder
        # diagnosticar: 'http_400' a secas no dice nada.
        cuerpo = (r.text or "")[:500]
        base["error"] = f"http_{r.status_code}"
        base["detalle"] = cuerpo
        log.warning("IA %s -> %s | cuerpo: %s", MODELO_IA, base["error"], cuerpo)
        return base

    try:
        body = r.json()
        usage = body.get("usage") or {}
        base["tokens_entrada"] = int(usage.get("prompt_tokens") or 0)
        base["tokens_salida"] = int(usage.get("completion_tokens") or 0)
        contenido = body["choices"][0]["message"]["content"]
        data = json.loads(contenido) if isinstance(contenido, str) else contenido
    except Exception as e:
        base["error"] = f"parseo:{type(e).__name__}"
        return base

    # Normaliza faltantes para que el resto del código no reviente.
    data.setdefault("respuesta_visible", "")
    data.setdefault("siguiente_pregunta", "")
    data.setdefault("chips_sugeridos", [])
    data.setdefault("informacion_suficiente", False)
    data.setdefault("ficha", {})
    data.setdefault("resumen_usuario", "")
    data.setdefault("resumen_interno", "")
    data.setdefault("nivel_confianza", 0)
    data.setdefault("requiere_revision_humana", True)
    base["ok"] = True
    base["data"] = data
    return base
