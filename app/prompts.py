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
13. Nunca inventes ni modifiques cantidades, cifras, fechas ni nombres propios.
    Usa exactamente los números que la persona mencionó. Si no mencionó una
    cantidad, no la supongas: deja el campo vacío en la ficha.
14. Cuando la persona corrija el resumen, REGENERA el resumen_usuario COMPLETO
    incorporando su aclaración. Nunca devuelvas un resumen vacío ni parcial:
    resumen_usuario siempre debe tener el resumen final legible para la persona.

CALIFICACIÓN (SOLO INFERENCIA, NUNCA PREGUNTAS):
No agregues preguntas técnicas a la conversación (sigue el máximo de 2 preguntas
en lenguaje cotidiano). Además de lo anterior, DEDUCE de lo que la persona contó
los campos de calificación de la ficha (sector, tipo_proyecto, alcance,
plataforma_probable, conectividad, capacidad_tecnica, sistema_actual, urgencia).
Usa "desconocido" cuando no haya evidencia suficiente: está permitido y esperado
dejarlos en "desconocido"; inventarlos es peor que no tenerlos. Agrega
confianza_calificacion (0.0 a 1.0): si dedujiste casi todo por contexto, que sea
baja. La persona NUNCA debe notar esta calificación.

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
- ficha: datos estructurados. Descriptivos (texto o null si no hay dato): rubro,
  problema, usuarios, datos_a_controlar, resultado_esperado, producto_sugerido
  (este último SOLO interno, NUNCA lo menciones). Calificación INFERIDA (usa el
  valor "desconocido" si no hay evidencia): sector, tipo_proyecto, alcance,
  plataforma_probable, conectividad, capacidad_tecnica, sistema_actual, urgencia.
  Además sistema_actual_detalle: texto libre con lo que describió del sistema que
  usa hoy (o null). Y confianza_calificacion (0.0 a 1.0).
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
        # STRICT: cada objeto lleva additionalProperties:false y required con TODAS
        # sus propiedades. No hay opcionales: lo que puede venir vacío se declara
        # igual en required y admite null en su tipo (p. ej. ["string","null"]).
        "properties": {
            "respuesta_visible": {"type": "string"},
            # Vacía ("") cuando pasa directo al resumen -> string basta.
            "siguiente_pregunta": {"type": "string"},
            # Vacío ([]) cuando no aplica. Sin maxItems (no soportado en strict);
            # el rango 3-5 se pide en el prompt.
            "chips_sugeridos": {"type": "array", "items": {"type": "string"}},
            "informacion_suficiente": {"type": "boolean"},
            "ficha": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    # Descriptivos (texto libre o null si no hay dato).
                    "rubro": {"type": ["string", "null"]},
                    "problema": {"type": ["string", "null"]},
                    "usuarios": {"type": ["string", "null"]},
                    "datos_a_controlar": {"type": ["string", "null"]},
                    "resultado_esperado": {"type": ["string", "null"]},
                    "producto_sugerido": {"type": ["string", "null"]},
                    # Calificación INFERIDA (enums con "desconocido"; nunca null).
                    "sector": {"type": "string",
                               "enum": ["privado", "publico", "colegio_profesional", "ong", "desconocido"]},
                    "tipo_proyecto": {"type": "string",
                                      "enum": ["crear_nuevo", "actualizar_existente", "integrar", "desconocido"]},
                    "alcance": {"type": "string",
                                "enum": ["una_tarea", "un_proceso", "area_completa", "organizacion", "desconocido"]},
                    "plataforma_probable": {"type": "string",
                                            "enum": ["web", "appweb", "android", "escritorio", "desconocido"]},
                    "conectividad": {"type": "string",
                                     "enum": ["buena", "limitada", "sin_internet", "desconocido"]},
                    "capacidad_tecnica": {"type": "string",
                                          "enum": ["tiene_personal_sistemas", "usuario_basico", "desconocido"]},
                    "sistema_actual": {"type": "string",
                                       "enum": ["ninguno", "excel", "software_comprado", "a_medida", "desconocido"]},
                    # Descripción libre de lo que usan hoy ("un programa que nos hizo
                    # un sobrino", "el POS que vino con la caja"). Clave antes de
                    # llamar a un lead que quiere migrar. null si no describió nada.
                    "sistema_actual_detalle": {"type": ["string", "null"]},
                    "urgencia": {"type": "string",
                                 "enum": ["alta", "media", "baja", "desconocido"]},
                    "confianza_calificacion": {"type": "number"},
                },
                "required": [
                    "rubro", "problema", "usuarios", "datos_a_controlar",
                    "resultado_esperado", "producto_sugerido",
                    "sector", "tipo_proyecto", "alcance", "plataforma_probable",
                    "conectividad", "capacidad_tecnica", "sistema_actual",
                    "sistema_actual_detalle", "urgencia", "confianza_calificacion",
                ],
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
