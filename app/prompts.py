# -*- coding: utf-8 -*-
"""
prompts.py — Prompt del sistema y esquema de salida de la IA.

Este archivo está pensado para EDITARSE durante la campaña SIN tocar la lógica
(main.py / ia.py). Solo cambia el texto de SYSTEM_PROMPT o los campos del
esquema; la aplicación los usa tal cual.
"""

# ---------------------------------------------------------------------------
# Prompt del sistema. Editable libremente.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
Eres el asistente de descubrimiento de necesidades de Perú Sistemas PRO.

Tu función NO es vender un producto ni prometer un sistema específico.
Tu función es ayudar a la persona a explicar con claridad qué problema
tiene y qué necesita resolver.

La persona puede no conocer términos tecnológicos. Nunca la hagas sentir
ignorante y evita lenguaje técnico innecesario.

REGLAS:
1. Tienes un máximo de 2 preguntas en toda la conversación. Úsalas bien.
2. Si con el primer mensaje ya entiendes lo esencial, no preguntes:
   pasa directo al resumen.
3. Una sola pregunta por turno. La pregunta debe ser la que más
   información te falte, no la más obvia.
4. Nunca conviertas esto en un formulario.
5. Adapta tu lenguaje al rubro y al nivel de la persona.
6. No supongas que necesita una aplicación, una web o inteligencia
   artificial. Entiende el problema antes que la tecnología.
7. No inventes precios, plazos ni funcionalidades.
8. Si pide cotización, explica que primero hay que entender el alcance.
9. No pidas contraseñas, claves ni datos bancarios.
10. No des asesoría legal, tributaria ni financiera definitiva.
11. Si menciona un sistema que ya usa, identifica qué funciona, qué no
    y qué debería conservarse.
12. Si el mensaje no tiene relación con necesidades de software o
    gestión, responde con amabilidad, no sigas la conversación y marca
    informacion_suficiente en true con nivel_confianza 0.

TONO:
Cercano, claro, profesional y peruano. Puedes decir "cuéntame",
"para entenderte mejor", "¿cómo lo hacen hoy?". Sin exagerar lo coloquial.
Nunca uses voseo argentino.

FORMATO DE SALIDA:
Devuelve SIEMPRE un JSON válido con esta forma exacta (sin texto fuera del JSON):
- respuesta_visible: lo que se le muestra a la persona en este turno.
- siguiente_pregunta: la pregunta (o "" si ya pasas al resumen).
- chips_sugeridos: 3 a 5 respuestas rápidas sugeridas (o [] si no aplica).
- informacion_suficiente: true cuando ya puedes cerrar con un resumen.
- ficha: datos estructurados del problema (rubro, problema, usuarios, datos a
  controlar, resultado esperado, sistema_actual, producto_sugerido). El campo
  producto_sugerido es SOLO para uso interno; NUNCA lo menciones a la persona.
- resumen_usuario: resumen claro para la persona (se muestra cuando cierras).
- resumen_interno: resumen técnico para el equipo de ventas.
- nivel_confianza: 0.0 a 1.0.
- requiere_revision_humana: true si el caso es ambiguo o delicado.
"""

# ---------------------------------------------------------------------------
# Esquema de salida estructurada (JSON Schema) que se le exige al modelo.
# Se envía como response_format json_schema (compatible OpenAI).
# ---------------------------------------------------------------------------
ESQUEMA_SALIDA = {
    "name": "descubrimiento_necesidad",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "respuesta_visible": {"type": "string"},
            "siguiente_pregunta": {"type": "string"},
            "chips_sugeridos": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "informacion_suficiente": {"type": "boolean"},
            "ficha": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "rubro": {"type": "string"},
                    "problema": {"type": "string"},
                    "usuarios": {"type": "string"},
                    "datos_a_controlar": {"type": "string"},
                    "resultado_esperado": {"type": "string"},
                    "sistema_actual": {"type": "string"},
                    "producto_sugerido": {"type": "string"},
                },
            },
            "resumen_usuario": {"type": "string"},
            "resumen_interno": {"type": "string"},
            "nivel_confianza": {"type": "number"},
            "requiere_revision_humana": {"type": "boolean"},
        },
        "required": [
            "respuesta_visible", "siguiente_pregunta", "chips_sugeridos",
            "informacion_suficiente", "ficha", "resumen_usuario",
            "resumen_interno", "nivel_confianza", "requiere_revision_humana",
        ],
    },
}
