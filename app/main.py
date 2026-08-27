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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
        await db.add_evento(cid, "ia_error", {"error": res.get("error")})
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))
        _set_sesion(resp, request, {"utm": ses.get("utm") or {}, "cid": cid})
        return resp

    await db.registrar_turno_ia(cid, res["data"], res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    resp = JSONResponse(_turno_resp(cid, res["data"]))
    if res["data"].get("informacion_suficiente"):
        await db.add_evento(cid, "resumen_visto", {})
    _set_sesion(resp, request, {"utm": ses.get("utm") or {}, "cid": cid})
    return resp


def _turno_resp(cid, data) -> dict:
    """Da forma a la respuesta del cliente según si toca pregunta o resumen."""
    if data.get("informacion_suficiente"):
        return {"ok": True, "fase": "resumen", "resumen": data.get("resumen_usuario") or "",
                "ficha": data.get("ficha") or {}}
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
        await db.add_evento(cid, "ia_error", {"error": res.get("error")})
        return JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))

    data = res["data"]
    # Techo duro de 2 preguntas: si ya se hicieron 2, forzamos el resumen.
    turnos = await db.turnos_de(cid)
    preguntas_hechas = sum(1 for t in turnos if t["rol"] == "asistente")
    if preguntas_hechas >= 2:
        data["informacion_suficiente"] = True
    await db.registrar_turno_ia(cid, data, res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    if data.get("informacion_suficiente"):
        await db.add_evento(cid, "resumen_visto", {})
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
        await db.add_evento(cid, "ia_error", {"error": res.get("error")})
        resp = JSONResponse(await _cuerpo_sin_ia(cid, "ia_error"))
        _set_sesion(resp, request, {**ses, "corregido": True})
        return resp
    data = res["data"]
    data["informacion_suficiente"] = True   # tras corregir, cerramos con resumen
    await db.registrar_turno_ia(cid, data, res["tokens_entrada"], res["tokens_salida"], res["modelo"])
    await db.add_evento(cid, "resumen_visto", {})
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
    return JSONResponse({"ok": True, "mensaje": "¡Gracias! Te contactaremos pronto.",
                         "whatsapp": _wa_url()})


@app.post("/api/evento")
async def api_evento(payload: dict, request: Request):
    # Solo whatsapp_click viene del cliente (el servidor no puede verlo).
    tipo = (payload.get("tipo") or "").strip()[:40]
    if tipo != "whatsapp_click":
        return JSONResponse({"ok": True})   # el resto se registra en el backend
    ses = _leer_sesion(request)
    await db.add_evento(ses.get("cid"), "whatsapp_click", {"lugar": payload.get("lugar")})
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
async def panel(request: Request, id: str = "", fase: str = "", campana: str = "", estado: str = ""):
    if not _panel_ok(request):
        return templates.TemplateResponse(request, "panel.html", {"request": request, "authed": False})
    if id:
        det = await db.panel_detalle(id)
        return templates.TemplateResponse(request, "panel.html",
                                          {"request": request, "authed": True, "detalle": det,
                                           "estados": db.ESTADOS})
    filas = await db.panel_listar(fase, campana, estado)
    return templates.TemplateResponse(request, "panel.html", {
        "request": request, "authed": True, "filas": filas, "estados": db.ESTADOS,
        "f_fase": fase, "f_campana": campana, "f_estado": estado})


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
