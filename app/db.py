# -*- coding: utf-8 -*-
"""
db.py — Acceso a PostgreSQL (asyncpg) para el esquema `consultas`.
Todas las consultas SQL viven aquí. No ejecuta DDL (eso es sql/esquema.sql).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IP_SAL = os.getenv("IP_SAL", "").strip()
LIMITE_IA_DIARIO = int(os.getenv("LIMITE_IA_DIARIO", "500") or "500")

# Anti-abuso (fijos por especificación):
RATE_HORA = 3
RATE_DIA = 15
MAX_LLAMADAS_IA = 6            # por consulta, en duro
MAX_CHARS_MENSAJE = 1500

_pool: Optional[asyncpg.Pool] = None


def ip_hash(ip: str) -> str:
    """Hash de la IP con sal secreta. NUNCA se guarda la IP cruda."""
    return hashlib.sha256(f"{IP_SAL}|{ip or ''}".encode("utf-8")).hexdigest()


async def connect() -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL.")
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# --- Anti-abuso -------------------------------------------------------------
async def rate_ok(iph: str) -> bool:
    """True si el ip_hash NO superó 3 consultas/hora ni 15/día."""
    assert _pool is not None
    hora = await _pool.fetchval(
        "SELECT count(*) FROM consultas.consulta "
        "WHERE ip_hash=$1 AND creada_en > now() - interval '1 hour'", iph)
    dia = await _pool.fetchval(
        "SELECT count(*) FROM consultas.consulta "
        "WHERE ip_hash=$1 AND creada_en > now() - interval '1 day'", iph)
    return (hora or 0) < RATE_HORA and (dia or 0) < RATE_DIA


async def ia_diaria_ok() -> bool:
    """True si el total de llamadas a la IA de hoy no llegó al tope global."""
    assert _pool is not None
    n = await _pool.fetchval(
        "SELECT count(*) FROM consultas.mensaje "
        "WHERE rol='asistente' AND creado_en >= date_trunc('day', now())")
    return (n or 0) < LIMITE_IA_DIARIO


# --- Conversación -----------------------------------------------------------
async def iniciar_consulta(texto: str, utm: dict, iph: str, user_agent: str) -> str:
    """Crea la fila `consulta` + el PRIMER mensaje del usuario. Devuelve el id.
    Se llama ANTES de la IA: si la IA falla luego, el lead ya quedó guardado."""
    assert _pool is not None
    async with _pool.acquire() as con:
        cid = await con.fetchval(
            """
            INSERT INTO consultas.consulta
                (fase, texto_original, ip_hash, user_agent,
                 utm_source, utm_medium, utm_campaign, utm_content, utm_term, referrer)
            VALUES ('iniciada',$1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
            """,
            texto, iph, user_agent[:400] if user_agent else None,
            utm.get("utm_source"), utm.get("utm_medium"), utm.get("utm_campaign"),
            utm.get("utm_content"), utm.get("utm_term"), utm.get("referrer"))
        await con.execute(
            "INSERT INTO consultas.mensaje (consulta_id, rol, contenido) "
            "VALUES ($1,'usuario',$2)", cid, texto)
    return str(cid)


async def get_consulta(cid: str) -> Optional[dict]:
    assert _pool is not None
    row = await _pool.fetchrow("SELECT * FROM consultas.consulta WHERE id=$1::uuid", cid)
    return dict(row) if row else None


async def turnos_de(cid: str) -> list[dict]:
    assert _pool is not None
    rows = await _pool.fetch(
        "SELECT rol, contenido FROM consultas.mensaje WHERE consulta_id=$1::uuid "
        "ORDER BY id", cid)
    return [dict(r) for r in rows]


async def add_mensaje_usuario(cid: str, contenido: str) -> None:
    assert _pool is not None
    await _pool.execute(
        "INSERT INTO consultas.mensaje (consulta_id, rol, contenido) VALUES ($1::uuid,'usuario',$2)",
        cid, contenido)


async def llamadas_ia_de(cid: str) -> int:
    assert _pool is not None
    return await _pool.fetchval(
        "SELECT llamadas_ia FROM consultas.consulta WHERE id=$1::uuid", cid) or 0


async def registrar_turno_ia(cid: str, data: dict, te: int, ts: int, modelo: str) -> None:
    """Guarda el mensaje del asistente, suma tokens/llamadas y vuelca ficha/resumen
    y la fase que corresponde."""
    assert _pool is not None
    suf = bool(data.get("informacion_suficiente"))
    fase = "resumen" if suf else "pregunta_1"
    async with _pool.acquire() as con:
        # ¿ya había preguntas? -> segunda pregunta
        if not suf:
            n = await con.fetchval(
                "SELECT count(*) FROM consultas.mensaje WHERE consulta_id=$1::uuid AND rol='asistente'", cid)
            fase = "pregunta_2" if (n or 0) >= 1 else "pregunta_1"
        await con.execute(
            "INSERT INTO consultas.mensaje (consulta_id, rol, contenido, modelo, tokens_entrada, tokens_salida) "
            "VALUES ($1::uuid,'asistente',$2,$3,$4,$5)",
            cid, data.get("respuesta_visible") or "", modelo, te, ts)
        await con.execute(
            """
            UPDATE consultas.consulta SET
                fase=$2,
                ficha = ficha || $3::jsonb,
                resumen_usuario = COALESCE(NULLIF($4,''), resumen_usuario),
                resumen_interno = COALESCE(NULLIF($5,''), resumen_interno),
                nivel_confianza = $6,
                requiere_revision = $7,
                tokens_entrada = tokens_entrada + $8,
                tokens_salida  = tokens_salida  + $9,
                llamadas_ia = llamadas_ia + 1,
                actualizada_en = now()
            WHERE id=$1::uuid
            """,
            cid, fase, json.dumps(data.get("ficha") or {}, ensure_ascii=False),
            data.get("resumen_usuario") or "", data.get("resumen_interno") or "",
            data.get("nivel_confianza") or 0, bool(data.get("requiere_revision_humana")),
            te, ts)
        # Nota: la columna `producto` queda NULL en consultas conversacionales
        # (proyecto a medida). `producto_sugerido` vive dentro de `ficha` (interno).


async def marcar_fase(cid: str, fase: str) -> None:
    assert _pool is not None
    await _pool.execute(
        "UPDATE consultas.consulta SET fase=$2, actualizada_en=now() WHERE id=$1::uuid", cid, fase)


async def guardar_calificacion(cid: str, declarado: dict, derivado: dict,
                               nota: str = "") -> None:
    """Aplica la pantalla de datos técnicos a la ficha con esta regla:
      - declarado: lo que el chip responde DIRECTAMENTE -> sobrescribe y entra a
        campos_declarados (se marca como 'declarado' en el panel).
      - derivado: deducción nuestra -> se aplica SOLO si el campo no tiene dato real
        (ausente/vacío/'desconocido'); NUNCA entra a campos_declarados.
      - nota: matiz en texto libre -> se acumula en nota_calificacion.
    Lo que ningún chip toca conserva el valor inferido por la IA."""
    assert _pool is not None
    if not declarado and not derivado and not nota:
        # Saltó la pantalla: no se toca la ficha, solo se avanza de fase.
        await _pool.execute(
            "UPDATE consultas.consulta SET fase='contacto', actualizada_en=now() WHERE id=$1::uuid", cid)
        return
    async with _pool.acquire() as con:
        row = await con.fetchrow("SELECT ficha FROM consultas.consulta WHERE id=$1::uuid", cid)
        if not row:
            return
        ficha = row["ficha"]
        if isinstance(ficha, str):
            try:
                ficha = json.loads(ficha)
            except Exception:
                ficha = {}
        ficha = ficha or {}

        for k, v in (declarado or {}).items():          # (a) declarado: sobrescribe
            ficha[k] = v
        for k, v in (derivado or {}).items():            # (b) derivado: solo si no hay dato real
            if k in (declarado or {}):
                continue
            if ficha.get(k) in (None, "", "desconocido"):
                ficha[k] = v
        if nota:                                         # (c) nota libre acumulada
            prev = (ficha.get("nota_calificacion") or "").strip()
            ficha["nota_calificacion"] = (prev + "; " + nota) if prev else nota
        # (d) campos_declarados: SOLO los declarados directamente (nunca los derivados)
        prev_decl = ficha.get("campos_declarados") or []
        ficha["campos_declarados"] = sorted(set(list(prev_decl) + list((declarado or {}).keys())))

        await con.execute(
            "UPDATE consultas.consulta SET ficha=$2::jsonb, fase='contacto', "
            "actualizada_en=now() WHERE id=$1::uuid",
            cid, json.dumps(ficha, ensure_ascii=False))


async def get_informe(cid: str) -> dict:
    """Informe del visitante (4 bloques) desde ficha.informe_visitante. El bloque
    1 cae al resumen aprobado si la IA no lo repitió."""
    assert _pool is not None
    row = await _pool.fetchrow(
        "SELECT resumen_usuario, ficha->'informe_visitante' inf "
        "FROM consultas.consulta WHERE id=$1::uuid", cid)
    if not row:
        return {}
    inf = row["inf"]
    if isinstance(inf, str):
        try:
            inf = json.loads(inf)
        except Exception:
            inf = {}
    inf = inf or {}
    if not (inf.get("lo_que_entendimos") or "").strip():
        inf["lo_que_entendimos"] = row["resumen_usuario"] or ""
    return inf


async def datos_para_pdf(cid: str) -> Optional[dict]:
    """Todo lo que el PDF necesita. None si el id no existe. El bloque 1 cae al
    resumen aprobado si la IA no lo repitió."""
    assert _pool is not None
    row = await _pool.fetchrow(
        "SELECT id, creada_en, resumen_usuario, ficha FROM consultas.consulta WHERE id=$1::uuid", cid)
    if not row:
        return None
    ficha = row["ficha"]
    if isinstance(ficha, str):
        try:
            ficha = json.loads(ficha)
        except Exception:
            ficha = {}
    ficha = ficha or {}
    inf = ficha.get("informe_visitante") or {}
    if not (inf.get("lo_que_entendimos") or "").strip():
        inf["lo_que_entendimos"] = row["resumen_usuario"] or ""
    return {"id": str(row["id"]), "creada_en": row["creada_en"],
            "resumen": row["resumen_usuario"] or "", "problema": ficha.get("problema") or "",
            "titular": ficha.get("titular") or "", "informe": inf,
            "palabras_clave": ficha.get("palabras_clave") or [],
            "costos_aplicables": ficha.get("costos_aplicables") or []}


async def guardar_contacto(cid: str, d: dict) -> None:
    assert _pool is not None
    await _pool.execute(
        """
        UPDATE consultas.consulta SET
            nombre=$2, empresa=$3, cargo=$4, celular=$5, correo=$6, ciudad=$7,
            consulta_publicable=$8, version_publica=$9,
            fase='completada', actualizada_en=now()
        WHERE id=$1::uuid
        """,
        cid, d.get("nombre"), d.get("empresa"), d.get("cargo"), d.get("celular"),
        d.get("correo"), d.get("ciudad"), bool(d.get("consulta_publicable")),
        d.get("version_publica"))


# --- Lead sin IA (landings clásicas: Facturalo.pro, QueVendi.pro, etc.) ------
async def crear_lead(d: dict, utm: dict, iph: str, user_agent: str) -> str:
    assert _pool is not None
    return str(await _pool.fetchval(
        """
        INSERT INTO consultas.consulta
            (fase, estado_lead, nombre, celular, ciudad, producto, ip_hash, user_agent,
             utm_source, utm_medium, utm_campaign, utm_content, utm_term, referrer)
        VALUES ('completada','nuevo',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        RETURNING id
        """,
        d.get("nombre"), d.get("celular"), d.get("ciudad"), d.get("producto"),
        iph, user_agent[:400] if user_agent else None,
        utm.get("utm_source"), utm.get("utm_medium"), utm.get("utm_campaign"),
        utm.get("utm_content"), utm.get("utm_term"), utm.get("referrer")))


# --- Eventos ----------------------------------------------------------------
async def add_evento(cid: Optional[str], tipo: str, metadata: Optional[dict] = None) -> None:
    assert _pool is not None
    await _pool.execute(
        "INSERT INTO consultas.evento (consulta_id, tipo, metadata) VALUES ($1,$2,$3::jsonb)",
        (cid if cid else None), tipo, json.dumps(metadata or {}, ensure_ascii=False))


# --- Panel ------------------------------------------------------------------
async def panel_listar(fase: str = "", campaign: str = "", estado: str = "",
                       sector: str = "", tipo_proyecto: str = "", limite: int = 200) -> list[dict]:
    assert _pool is not None
    cond, args = ["1=1"], []
    for col, val in (("fase", fase), ("utm_campaign", campaign), ("estado_lead", estado)):
        if val:
            args.append(val)
            cond.append(f"{col}=${len(args)}")
    # Filtros de calificación (viven dentro de ficha jsonb):
    for key, val in (("sector", sector), ("tipo_proyecto", tipo_proyecto)):
        if val:
            args.append(val)
            cond.append(f"ficha->>'{key}' = ${len(args)}")
    args.append(limite)
    rows = await _pool.fetch(
        f"""
        SELECT id, creada_en, ciudad, utm_campaign, estado_lead, fase, nivel_confianza,
               requiere_revision, producto, ficha->>'sector' sector, ficha->>'tipo_proyecto' tipo_proyecto,
               left(coalesce(resumen_interno, texto_original,''),140) resumen
        FROM consultas.consulta WHERE {' AND '.join(cond)}
        ORDER BY creada_en DESC LIMIT ${len(args)}
        """, *args)
    return [dict(r) for r in rows]


async def panel_detalle(cid: str) -> Optional[dict]:
    assert _pool is not None
    c = await _pool.fetchrow("SELECT * FROM consultas.consulta WHERE id=$1::uuid", cid)
    if not c:
        return None
    c = dict(c)
    if isinstance(c.get("ficha"), str):   # asyncpg devuelve jsonb como texto
        try:
            c["ficha"] = json.loads(c["ficha"])
        except Exception:
            c["ficha"] = {}
    c["ficha"] = c.get("ficha") or {}
    msgs = await _pool.fetch(
        "SELECT rol, contenido, modelo, tokens_entrada, tokens_salida, creado_en "
        "FROM consultas.mensaje WHERE consulta_id=$1::uuid ORDER BY id", cid)
    evs = await _pool.fetch(
        "SELECT tipo, creado_en FROM consultas.evento WHERE consulta_id=$1::uuid ORDER BY id", cid)
    return {"c": dict(c), "mensajes": [dict(m) for m in msgs], "eventos": [dict(e) for e in evs]}


ESTADOS = ["nuevo", "contactado", "calificado", "reunion", "cotizado", "ganado", "perdido"]


async def panel_set_estado(cid: str, estado: str) -> bool:
    assert _pool is not None
    if estado not in ESTADOS:
        return False
    r = await _pool.fetchrow(
        "UPDATE consultas.consulta SET estado_lead=$2, actualizada_en=now() "
        "WHERE id=$1::uuid RETURNING id", cid, estado)
    return bool(r)
