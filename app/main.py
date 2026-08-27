# -*- coding: utf-8 -*-
"""
main.py — consultas.perusistemas.pro
FastAPI: landing conversacional + API + panel interno. Toda la config vive aquí.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature

from . import db, ia

BASE_DIR = Path(__file__).resolve().parent

# --- Config (variables de entorno) ------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "cambia-esto-en-railway").strip()
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "").strip()
WHATSAPP_NUMERO = "".join(c for c in os.getenv("WHATSAPP_NUMERO", "967317946") if c.isdigit())
META_PIXEL_ID = os.getenv("META_PIXEL_ID", "").strip()
ORIGENES_PERMITIDOS = {o.strip() for o in os.getenv("ORIGENES_PERMITIDOS", "").split(",") if o.strip()}
WA_MSG = "Hola, vengo de la página de consultas de Perú Sistemas PRO."

_ser = URLSafeSerializer(SECRET_KEY, salt="sesion")
_ser_panel = URLSafeSerializer(SECRET_KEY, salt="panel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Consultas — Perú Sistemas PRO", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --- CORS SOLO para /api/lead (llamado desde otras landings). Nunca "*". -----
@app.middleware("http")
async def cors_lead(request: Request, call_next):
    origin = request.headers.get("origin", "")
    es_lead = request.url.path == "/api/lead"
    permitido = origin in ORIGENES_PERMITIDOS
    if es_lead and request.method == "OPTIONS":
        h = {}
        if permitido:
            h = {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                 "Access-Control-Allow-Methods": "POST, OPTIONS",
                 "Access-Control-Allow-Headers": "Content-Type",
                 "Access-Control-Max-Age": "600"}
        return Response(status_code=204, headers=h)
    resp = await call_next(request)
    if es_lead and permitido:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


# --- Helpers ----------------------------------------------------------------
def _wa_url() -> str:
    return f"https://wa.me/51{WHATSAPP_NUMERO}?text={quote(WA_MSG)}"


def _ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")) or ""


def _leer_sesion(request: Request) -> dict:
    raw = request.cookies.get("sesion")
    if not raw:
        return {}
    try:
        return _ser.loads(raw)
    except BadSignature:
        return {}


def _set_sesion(resp, request: Request, data: dict) -> None:
    resp.set_cookie("sesion", _ser.dumps(data), httponly=True, samesite="lax",
                    secure=(request.url.scheme == "https"), max_age=60 * 60 * 6, path="/")


def _utm_de_query(request: Request) -> dict:
    q = request.query_params
    return {
        "utm_source": q.get("utm_source"), "utm_medium": q.get("utm_medium"),
        "utm_campaign": q.get("utm_campaign"), "utm_content": q.get("utm_content"),
        "utm_term": q.get("utm_term"), "referrer": request.headers.get("referer"),
    }


async def _cuerpo_sin_ia(cid, motivo):
    """Respuesta cuando NO se llama a la IA (tope diario o fallo): capturamos el
    lead igual y empujamos a contacto + WhatsApp. Nunca pantalla muerta."""
    await db.marcar_fase(cid, "contacto")
    return {"ok": True, "sin_ia": True, "ir_a": "contacto", "motivo": motivo,
            "mensaje": "Gracias, ya registramos tu consulta. Déjanos tus datos y "
                       "te contactamos, o escríbenos ahora por WhatsApp.",
            "whatsapp": _wa_url()}


async def _cierre(cid: str, data: dict) -> None:
    """Al cerrar (resumen listo): evento resumen_visto y, si la IA generó el
    informe con contenido, informe_generado."""
    await db.add_evento(cid, "resumen_visto", {})
    inf = (data or {}).get("informe_visitante") or {}
    if (inf.get("lo_que_entendimos") or "").strip() or (inf.get("preguntas") or []):
        await db.add_evento(cid, "informe_generado", {})


# --- Landing ----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    utm = _utm_de_query(request)
    await db.add_evento(None, "vista", {"utm_campaign": utm.get("utm_campaign")})
    resp = templates.TemplateResponse(request, "landing.html", {
        "request": request, "whatsapp": _wa_url(), "meta_pixel_id": META_PIXEL_ID})
    _set_sesion(resp, request, {"utm": utm})   # UTM firmados en la sesión
    return resp


@app.post("/api/iniciar")
async def api_iniciar(payload: dict, request: Request):
    texto = (payload.get("texto") or "").strip()[:db.MAX_CHARS_MENSAJE]
    if len(texto) < 3:
        return JSONResponse({"ok": False, "error": "Cuéntanos un poco más."}, status_code=422)
    ses = _leer_sesion(request)
    iph = db.ip_hash(_ip(request))
    if not await db.rate_ok(iph):
        return JSONResponse({"ok": False, "limite": True,
                             "mensaje": "Recibimos varias consultas desde tu conexión. "
                                        "Escríbenos por WhatsApp y te atendemos.",
                             "whatsapp": _wa_url()}, status_code=429)
    cid = await db.iniciar_consulta(texto, ses.get("utm") or {}, iph,
                                    request.headers.get("user-agent", ""))
    await db.add_evento(cid, "consulta_iniciada", {})

    if not await db.ia_diaria_ok():
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "tope_diario"))
        _set_sesion(resp, request, {"utm": ses.get("utm") or {}, "cid": cid})
        return resp

    res = await ia.consultar([{"rol": "usuario", "contenido": texto}])
    if not res["ok"]:
        await db.add_evento(cid, "ia_error", {"error": res.get("error"), "detalle": res.get("detalle")})
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))
        _set_sesion(resp, request, {"utm": ses.get("utm") or {}, "cid": cid})
        return resp

    await db.registrar_turno_ia(cid, res["data"], res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    resp = JSONResponse(_turno_resp(cid, res["data"]))
    if res["data"].get("informacion_suficiente"):
        await _cierre(cid, res["data"])
    _set_sesion(resp, request, {"utm": ses.get("utm") or {}, "cid": cid})
    return resp


def _turno_resp(cid, data) -> dict:
    """Da forma a la respuesta del cliente según si toca pregunta o resumen."""
    if data.get("informacion_suficiente"):
        # No se envía la ficha al cliente: contiene datos internos (producto_sugerido,
        # calificación). El informe del visitante se entrega recién en /api/contacto.
        return {"ok": True, "fase": "resumen", "resumen": data.get("resumen_usuario") or ""}
    return {"ok": True, "fase": "pregunta", "mensaje": data.get("respuesta_visible") or "",
            "pregunta": data.get("siguiente_pregunta") or "",
            "chips": data.get("chips_sugeridos") or []}


@app.post("/api/responder")
async def api_responder(payload: dict, request: Request):
    ses = _leer_sesion(request)
    cid = ses.get("cid")
    if not cid:
        return JSONResponse({"ok": False, "error": "sesión expirada"}, status_code=400)
    texto = (payload.get("texto") or "").strip()[:db.MAX_CHARS_MENSAJE]
    if len(texto) < 1:
        return JSONResponse({"ok": False, "error": "Escribe tu respuesta."}, status_code=422)
    await db.add_mensaje_usuario(cid, texto)
    await db.add_evento(cid, "pregunta_respondida", {})

    if await db.llamadas_ia_de(cid) >= db.MAX_LLAMADAS_IA or not await db.ia_diaria_ok():
        return JSONResponse(await _cuerpo_sin_ia(cid, "tope"))

    res = await ia.consultar(await db.turnos_de(cid))
    if not res["ok"]:
        await db.add_evento(cid, "ia_error", {"error": res.get("error"), "detalle": res.get("detalle")})
        return JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))

    data = res["data"]
    # Techo duro de 2 preguntas: si ya se hicieron 2, forzamos el resumen.
    turnos = await db.turnos_de(cid)
    preguntas_hechas = sum(1 for t in turnos if t["rol"] == "asistente")
    if preguntas_hechas >= 2:
        data["informacion_suficiente"] = True
    await db.registrar_turno_ia(cid, data, res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    if data.get("informacion_suficiente"):
        await _cierre(cid, data)
    return JSONResponse(_turno_resp(cid, data))


@app.post("/api/corregir")
async def api_corregir(payload: dict, request: Request):
    ses = _leer_sesion(request)
    cid = ses.get("cid")
    if not cid:
        return JSONResponse({"ok": False, "error": "sesión expirada"}, status_code=400)
    if ses.get("corregido"):
        # Ya se usó la única corrección permitida.
        c = await db.get_consulta(cid)
        return JSONResponse({"ok": True, "fase": "resumen",
                             "resumen": (c or {}).get("resumen_usuario") or ""})
    texto = (payload.get("texto") or "").strip()[:db.MAX_CHARS_MENSAJE]
    await db.add_mensaje_usuario(cid, texto or "(corrección)")
    await db.add_evento(cid, "correccion", {})
    if await db.llamadas_ia_de(cid) >= db.MAX_LLAMADAS_IA or not await db.ia_diaria_ok():
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "tope"))
        _set_sesion(resp, request, {**ses, "corregido": True})
        return resp
    res = await ia.consultar(await db.turnos_de(cid))
    if not res["ok"]:
        await db.add_evento(cid, "ia_error", {"error": res.get("error"), "detalle": res.get("detalle")})
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))
        _set_sesion(resp, request, {**ses, "corregido": True})
        return resp
    data = res["data"]
    data["informacion_suficiente"] = True   # tras corregir, cerramos con resumen
    await db.registrar_turno_ia(cid, data, res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    await _cierre(cid, data)
    resp = JSONResponse(_turno_resp(cid, data))
    _set_sesion(resp, request, {**ses, "corregido": True})
    return resp


@app.post("/api/contacto")
async def api_contacto(payload: dict, request: Request):
    if (payload.get("empresa_web") or "").strip():   # honeypot
        return JSONResponse({"ok": True})
    ses = _leer_sesion(request)
    cid = ses.get("cid")
    if not cid:
        return JSONResponse({"ok": False, "error": "sesión expirada"}, status_code=400)
    for req_campo in ("nombre", "celular", "ciudad"):
        if not (payload.get(req_campo) or "").strip():
            return JSONResponse({"ok": False, "error": "Faltan datos obligatorios."}, status_code=422)
    await db.guardar_contacto(cid, {
        "nombre": payload.get("nombre"), "empresa": payload.get("empresa"),
        "cargo": payload.get("cargo"), "celular": payload.get("celular"),
        "correo": payload.get("correo"), "ciudad": payload.get("ciudad"),
        "consulta_publicable": payload.get("consulta_publicable"),
        "version_publica": payload.get("version_publica")})
    await db.add_evento(cid, "contacto_enviado", {})
    informe = await db.get_informe(cid)   # el entregable que se muestra en la pantalla final
    return JSONResponse({"ok": True, "mensaje": "¡Gracias! Te contactaremos pronto.",
                         "whatsapp": _wa_url(), "informe": informe})


@app.post("/api/regenerar-resumen")
async def api_regenerar_resumen(payload: dict, request: Request):
    """Reintento cuando el resumen llegó vacío: re-genera SOLO el resumen sobre la
    conversación existente (sin agregar un turno del usuario). Cuenta como llamada
    a la IA (tope de 6/consulta)."""
    ses = _leer_sesion(request)
    cid = ses.get("cid")
    if not cid:
        return JSONResponse({"ok": False, "error": "sesión expirada"}, status_code=400)
    if await db.llamadas_ia_de(cid) >= db.MAX_LLAMADAS_IA or not await db.ia_diaria_ok():
        return JSONResponse(await _cuerpo_sin_ia(cid, "tope"))
    res = await ia.consultar(await db.turnos_de(cid))
    if not res["ok"]:
        await db.add_evento(cid, "ia_error", {"error": res.get("error"), "detalle": res.get("detalle")})
        return JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))
    data = res["data"]
    data["informacion_suficiente"] = True
    await db.registrar_turno_ia(cid, data, res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    if (data.get("resumen_usuario") or "").strip():
        await _cierre(cid, data)
    return JSONResponse(_turno_resp(cid, data))


# Valores válidos declarables en la pantalla de datos técnicos (deben calzar con
# los enums del esquema de la ficha).
_CALIF_VALIDOS = {
    "sector": {"privado", "publico", "colegio_profesional", "ong"},
    "tipo_proyecto": {"crear_nuevo", "actualizar_existente", "integrar"},
    "alcance": {"una_tarea", "un_proceso", "area_completa", "organizacion"},
    "plataforma_probable": {"web", "appweb", "android", "escritorio"},
    "conectividad": {"buena", "limitada", "sin_internet"},
    "capacidad_tecnica": {"tiene_personal_sistemas", "usuario_basico"},
    "sistema_actual": {"ninguno", "excel", "software_comprado", "a_medida"},
    "urgencia": {"alta", "media", "baja"},
}
# Para valores DERIVADOS también se admite "desconocido" (p. ej. sistema_actual).
_CALIF_CON_DESCONOCIDO = {k: (v | {"desconocido"}) for k, v in _CALIF_VALIDOS.items()}

# Campos de calificación a mostrar en el panel (orden + etiqueta legible).
# sistema_actual_detalle es texto libre (no declarable por la pantalla de chips).
CALIF_CAMPOS = [
    ("sector", "Sector"), ("tipo_proyecto", "Tipo de proyecto"), ("alcance", "Alcance"),
    ("plataforma_probable", "Plataforma probable"), ("conectividad", "Conectividad"),
    ("capacidad_tecnica", "Capacidad técnica"), ("sistema_actual", "Sistema actual"),
    ("sistema_actual_detalle", "Sistema actual (detalle)"), ("urgencia", "Urgencia"),
]


@app.post("/api/calificacion")
async def api_calificacion(payload: dict, request: Request):
    """Pantalla opcional de datos técnicos. Lo que declara la persona SOBRESCRIBE
    lo inferido (confianza 1.0). Si la salta, no se toca la ficha."""
    ses = _leer_sesion(request)
    cid = ses.get("cid")
    if not cid:
        return JSONResponse({"ok": False, "error": "sesión expirada"}, status_code=400)
    salto = bool(payload.get("salto"))
    declarado, derivado, nota = {}, {}, ""
    if not salto:
        din = payload.get("declarado") or {}
        dde = payload.get("derivado") or {}
        # Declarado: solo valores reales del enum (sin "desconocido").
        for campo, validos in _CALIF_VALIDOS.items():
            v = str(din.get(campo) or "").strip()
            if v in validos:
                declarado[campo] = v
        # Derivado: admite "desconocido"; nunca pisa un campo ya declarado.
        for campo, validos in _CALIF_CON_DESCONOCIDO.items():
            v = str(dde.get(campo) or "").strip()
            if v in validos and campo not in declarado:
                derivado[campo] = v
        nota = str(payload.get("nota") or "").strip()[:500]
    await db.guardar_calificacion(cid, declarado, derivado, nota)
    await db.add_evento(cid, "calificacion_completada",
                        {"salto": salto, "n_declarados": len(declarado)})
    return JSONResponse({"ok": True})


@app.post("/api/evento")
async def api_evento(payload: dict, request: Request):
    # Del cliente solo se aceptan eventos que el servidor NO puede observar por su
    # cuenta: el click de WhatsApp y el momento en que se muestra la calificación.
    tipo = (payload.get("tipo") or "").strip()[:40]
    if tipo not in ("whatsapp_click", "calificacion_mostrada", "informe_descargado"):
        return JSONResponse({"ok": True})   # el resto del embudo se registra en el backend
    ses = _leer_sesion(request)
    await db.add_evento(ses.get("cid"), tipo, {"lugar": payload.get("lugar")})
    return JSONResponse({"ok": True})


# --- Lead sin IA (landings clásicas; CORS arriba) ---------------------------
@app.post("/api/lead")
async def api_lead(payload: dict, request: Request):
    if (payload.get("empresa_web") or "").strip():   # honeypot
        return JSONResponse({"ok": True})
    if not (payload.get("nombre") or "").strip() or not (payload.get("celular") or "").strip():
        return JSONResponse({"ok": False, "error": "Nombre y celular son obligatorios."}, status_code=422)
    utm = {k: payload.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}
    utm["referrer"] = payload.get("referrer") or request.headers.get("referer")
    cid = await db.crear_lead({
        "nombre": payload.get("nombre"), "celular": payload.get("celular"),
        "ciudad": payload.get("ciudad"), "producto": payload.get("producto")},
        utm, db.ip_hash(_ip(request)), request.headers.get("user-agent", ""))
    await db.add_evento(cid, "lead_externo", {"producto": payload.get("producto")})
    return JSONResponse({"ok": True})


# --- Panel interno (contraseña + sesión firmada; NO basta noindex) ----------
def _panel_ok(request: Request) -> bool:
    raw = request.cookies.get("panel")
    if not raw:
        return False
    try:
        return _ser_panel.loads(raw) == "ok"
    except BadSignature:
        return False


@app.get("/panel", response_class=HTMLResponse)
async def panel(request: Request, id: str = "", fase: str = "", campana: str = "",
                estado: str = "", sector: str = "", tipo_proyecto: str = ""):
    if not _panel_ok(request):
        return templates.TemplateResponse(request, "panel.html", {"request": request, "authed": False})
    if id:
        det = await db.panel_detalle(id)
        return templates.TemplateResponse(request, "panel.html",
                                          {"request": request, "authed": True, "detalle": det,
                                           "estados": db.ESTADOS, "calif_campos": CALIF_CAMPOS})
    filas = await db.panel_listar(fase, campana, estado, sector, tipo_proyecto)
    return templates.TemplateResponse(request, "panel.html", {
        "request": request, "authed": True, "filas": filas, "estados": db.ESTADOS,
        "sectores": sorted(_CALIF_VALIDOS["sector"]), "tipos": sorted(_CALIF_VALIDOS["tipo_proyecto"]),
        "f_fase": fase, "f_campana": campana, "f_estado": estado,
        "f_sector": sector, "f_tipo": tipo_proyecto})


@app.post("/panel/login")
async def panel_login(request: Request):
    form = await request.form()
    clave = (form.get("password") or "").strip()
    if not PANEL_PASSWORD or clave != PANEL_PASSWORD:
        return templates.TemplateResponse(request, "panel.html",
                                          {"request": request, "authed": False, "error": True},
                                          status_code=401)
    resp = RedirectResponse("/panel", status_code=303)
    resp.set_cookie("panel", _ser_panel.dumps("ok"), httponly=True, samesite="lax",
                    secure=(request.url.scheme == "https"), max_age=60 * 60 * 8, path="/")
    return resp


@app.post("/panel/estado")
async def panel_estado(request: Request):
    if not _panel_ok(request):
        return JSONResponse({"ok": False}, status_code=401)
    form = await request.form()
    ok = await db.panel_set_estado((form.get("id") or "").strip(), (form.get("estado") or "").strip())
    return RedirectResponse(f"/panel?id={form.get('id')}", status_code=303) if ok \
        else JSONResponse({"ok": False}, status_code=400)


@app.get("/salud")
async def salud():
    return {"ok": True}


@app.get("/robots.txt")
async def robots():
    # Indexa la raíz; bloquea el panel y las APIs.
    cuerpo = "User-agent: *\nAllow: /$\nDisallow: /panel\nDisallow: /api/\n"
    return Response(cuerpo, media_type="text/plain")


@app.get("/favicon.ico")
async def favicon():
    ruta = BASE_DIR / "static" / "favicon.ico"
    if ruta.exists():
        return FileResponse(ruta, media_type="image/x-icon")
    return Response(status_code=204)
