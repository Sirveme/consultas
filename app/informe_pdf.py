# -*- coding: utf-8 -*-
"""
informe_pdf.py — Informe del visitante como pieza EDITORIAL en PDF (ReportLab).

Pensado para leerse en celular (no para imprimir): formato A5 vertical, portada y
contraportada oscuras a sangre, interior claro en dos columnas asimétricas
numeradas. Se genera al vuelo (bytes en memoria). reportlab se importa aquí, así
que la app no paga su costo de import en el arranque. Fuentes IBM Plex si están en
static/fuentes/, si no Helvetica/Courier (nunca revienta por fuente faltante).

Solo cambia el DISEÑO: el contenido, los textos, el endpoint y el nombre de
archivo son los de zClaude-6.
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape as _xml

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
                                Table, TableStyle, HRFlowable, Indenter, ListFlowable,
                                ListItem, NextPageTemplate, PageBreak)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Paleta -----------------------------------------------------------------
# Portada / contraportada (oscuras, a sangre)
PORT_FONDO = HexColor("#08110e"); PORT_TEXTO = HexColor("#e6f0ea")
PORT_VERDE = HexColor("#22c55e"); PORT_AMBAR = HexColor("#e8a33d"); PORT_LINEA = HexColor("#2a4438")
# Interior (claro)
INT_FONDO = HexColor("#fbfcfb"); INT_TEXTO = HexColor("#1a2420"); INT_SUAVE = HexColor("#5c6b64")
INT_VERDE = HexColor("#1a9e4b"); INT_AMBAR = HexColor("#b8781f"); INT_LINEA = HexColor("#d8e0da")
INT_REALCE = HexColor("#f0f5f1")

A5W, A5H = A5                      # 148 x 210 mm
ML = MR = 14 * mm                 # márgenes exteriores
MT = MB = 12 * mm
COL_NUM = 22 * mm                 # columna izquierda (número de sección)
CONT_W = A5W - ML - MR            # ancho de contenido = 120 mm
FUENTES_DIR = Path(__file__).parent / "static" / "fuentes"
_F = None


def _fuentes() -> dict:
    global _F
    if _F is not None:
        return _F
    reg = {"normal": "Helvetica", "medium": "Helvetica", "semibold": "Helvetica-Bold",
           "display": "Helvetica-Bold", "mono": "Courier"}
    tt = [("Plex", "IBMPlexSans-Regular.ttf", "normal"),
          ("Plex-Med", "IBMPlexSans-Medium.ttf", "medium"),
          ("Plex-SB", "IBMPlexSans-SemiBold.ttf", "semibold"),
          ("PlexMono", "IBMPlexMono-Medium.ttf", "mono")]
    for nombre, arch, rol in tt:
        try:
            p = FUENTES_DIR / arch
            if p.exists():
                pdfmetrics.registerFont(TTFont(nombre, str(p)))
                reg[rol] = nombre
        except Exception:
            pass
    reg["display"] = reg["semibold"]   # el display cae al SemiBold de Plex, o Helvetica-Bold
    _F = reg
    return reg


_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "setiembre", "octubre", "noviembre", "diciembre"]


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def nombre_archivo(palabras, creada_en) -> str:
    fecha = creada_en.strftime("%Y%m%d") if creada_en else "sinfecha"
    slug = "-".join(x for x in (_slug(w) for w in (palabras or [])) if x)[:60].strip("-")
    return f"informe-{slug}-{fecha}.pdf" if slug else f"informe-consulta-{fecha}.pdf"


def expediente(cid: str) -> str:
    return "EXP-" + (cid or "").replace("-", "")[:8].upper()


# --- Contenido FIJO (nunca lo redacta la IA) --------------------------------
PRECIOS_AVISO = ("El desarrollo se cotiza aparte, porque depende de lo que necesite cada "
                 "proyecto. Lo de abajo es solo el costo de mantener el sistema en línea.")
# (etiqueta, precio_grande, sufijo, incluye[])
PRECIOS_CARDS = [
    ("OPCIÓN 1 — DOMINIO COMPARTIDO", "US$ 20", "/mes",
     ["Dirección del tipo miproyecto.perusistemas.pro", "Base de datos incluida",
      "Hosting en servidor Python", "Certificado SSL (conexión cifrada)",
      "Capa de seguridad con Cloudflare"]),
    ("OPCIÓN 2 — DOMINIO PROPIO", "desde US$ 10", "/mes",
     ["Dominio miproyecto.com: US$ 25 el primer año, US$ 45 desde el segundo año",
      "Hosting Python: US$ 10/mes pequeños, US$ 25/mes medianos",
      "Base de datos incluida", "Certificado SSL (conexión cifrada)",
      "Capa de seguridad con Cloudflare", "Cuentas de correo: US$ 7 al año por cuenta"]),
]
PRECIOS_OTROS = [
    ("apis_ia", "Uso de modelos de inteligencia artificial (APIs de IA)"),
    ("validacion_documentos", "Validación de DNI o RUC"),
    ("almacenamiento", "Almacenamiento en la nube"),
    ("whatsapp", "API de WhatsApp"),
]
PRECIOS_CIERRE = "Precios en dólares, referenciales a la fecha de este informe."
MARCADORES = ["NECESIDAD", "CONTEXTO", "ALCANCE", "ENTREGA"]


# --- Estilos (flowables) ----------------------------------------------------
def _S():
    f = _fuentes()
    S = {}
    S["num"] = ParagraphStyle("num", fontName=f["display"], fontSize=20, textColor=INT_AMBAR, leading=22)
    S["titulo"] = ParagraphStyle("tit", fontName=f["mono"], fontSize=9.5, textColor=INT_TEXTO, leading=12, spaceAfter=0)
    S["cuerpo"] = ParagraphStyle("cue", fontName=f["normal"], fontSize=10.5, textColor=INT_TEXTO, leading=15, alignment=TA_LEFT)
    S["preg"] = ParagraphStyle("preg", fontName=f["normal"], fontSize=10.5, textColor=INT_TEXTO, leading=15,
                               leftIndent=14, firstLineIndent=-14, bulletIndent=0,
                               bulletFontName=f["display"], bulletFontSize=13, bulletColor=INT_AMBAR)
    S["req"] = ParagraphStyle("req", fontName=f["normal"], fontSize=9.5, textColor=INT_TEXTO, leading=13)
    S["pend"] = ParagraphStyle("pend", fontName=f["normal"], fontSize=10, textColor=INT_SUAVE, leading=14)
    S["dec_a"] = ParagraphStyle("da", fontName=f["medium"], fontSize=10, textColor=INT_TEXTO, leading=14)
    S["dec_b"] = ParagraphStyle("db", fontName=f["normal"], fontSize=9.5, textColor=INT_SUAVE, leading=13)
    S["aviso"] = ParagraphStyle("avi", fontName=f["medium"], fontSize=9.5, textColor=INT_TEXTO, leading=13)
    S["card_lbl"] = ParagraphStyle("cl", fontName=f["mono"], fontSize=7.5, textColor=INT_SUAVE, leading=10)
    S["card_incl"] = ParagraphStyle("ci", fontName=f["normal"], fontSize=8.5, textColor=INT_TEXTO, leading=11.5,
                                    leftIndent=10, firstLineIndent=-10, bulletIndent=0,
                                    bulletFontName=f["normal"], bulletFontSize=8.5, bulletColor=INT_VERDE)
    S["otros_on"] = ParagraphStyle("oo", fontName=f["medium"], fontSize=9.5, textColor=INT_TEXTO, leading=13)
    S["otros_off"] = ParagraphStyle("of", fontName=f["normal"], fontSize=9.5, textColor=INT_SUAVE, leading=13)
    S["cierre"] = ParagraphStyle("cie", fontName=f["normal"], fontSize=8, textColor=INT_SUAVE, leading=11, spaceBefore=4)
    # Contraportada (oscura)
    S["c_titulo"] = ParagraphStyle("ct", fontName=f["display"], fontSize=26, textColor=PORT_TEXTO, leading=30)
    S["c_parr"] = ParagraphStyle("cp", fontName=f["normal"], fontSize=11, textColor=PORT_TEXTO, leading=16, rightIndent=30 * mm)
    S["c_lbl"] = ParagraphStyle("clb", fontName=f["mono"], fontSize=8, textColor=PORT_LINEA, leading=11)
    S["c_val"] = ParagraphStyle("cv", fontName=f["semibold"], fontSize=13, textColor=PORT_VERDE, leading=17)
    S["c_wa"] = ParagraphStyle("cw", fontName=f["semibold"], fontSize=17, textColor=PORT_VERDE, leading=21)
    S["c_prod"] = ParagraphStyle("cpr", fontName=f["normal"], fontSize=9, textColor=PORT_TEXTO, leading=13)
    return S


def _link(texto, url, color="#22c55e"):
    return f'<a href="{url}"><font color="{color}"><u>{texto}</u></font></a>'


# --- Fondos a sangre + check vectorial --------------------------------------
def _bleed(canv, color):
    canv.saveState(); canv.setFillColor(color)
    canv.rect(0, 0, A5W, A5H, fill=1, stroke=0); canv.restoreState()


def _check(canv, x, y, color, s=3.4):
    canv.saveState(); canv.setStrokeColor(color); canv.setLineWidth(1.1); canv.setLineCap(1)
    p = canv.beginPath(); p.moveTo(x, y + s * 0.35); p.lineTo(x + s * 0.45, y); p.lineTo(x + s * 1.1, y + s)
    canv.drawPath(p); canv.restoreState()


def _txt(canv, x, y, s, font, size, color, cs=0.0):
    """Dibuja texto (con tracking opcional vía text object) y devuelve el ancho total."""
    to = canv.beginText(); to.setTextOrigin(x, y); to.setFont(font, size)
    to.setFillColor(color)
    if cs:
        to.setCharSpace(cs)
    to.textOut(s); canv.drawText(to)
    return canv.stringWidth(s, font, size) + cs * max(0, len(s) - 1)


def _interior_bg(canv, doc):
    _bleed(canv, INT_FONDO); canv._interior = True


# --- Portada (canvas) -------------------------------------------------------
def _titular_par(texto, fuentes):
    """Titular de portada ROBUSTO: escala 25->17pt para no pasar de 4 líneas; si
    en el piso aún no entra, trunca por palabras con puntos suspensivos. La
    portada nunca se rompe por un titular largo. Devuelve (Paragraph, alto)."""
    ancho = CONT_W - 8 * mm
    texto = (texto or "Tu necesidad").strip()
    size, piso = 25.0, 17.0
    par, h, lineas, st = None, 0, 1, None
    while True:
        st = ParagraphStyle("h", fontName=fuentes["display"], fontSize=size,
                            leading=size + 4, textColor=PORT_TEXTO)
        par = Paragraph(_xml(texto), st)
        _, h = par.wrap(ancho, 400)
        lineas = max(1, int(round(h / (size + 4))))
        if lineas <= 4 or size <= piso:
            break
        size = max(piso, size - 1.5)   # nunca por debajo del piso (17pt)
    if lineas > 4:                       # en el piso y aún no entra -> truncar
        palabras = texto.split()
        while len(palabras) > 1:
            palabras.pop()
            par = Paragraph(_xml(" ".join(palabras) + "…"), st)
            _, h = par.wrap(ancho, 400)
            if int(round(h / (size + 4))) <= 4:
                break
    return par, h


def _mk_portada(datos):
    f = _fuentes()
    titular = (datos.get("titular") or datos.get("problema")
               or (datos.get("informe") or {}).get("lo_que_entendimos") or "").strip()
    exp = expediente(datos.get("id"))
    fecha = datos.get("creada_en")
    fecha_txt = (f"{fecha.day} de {_MESES[fecha.month]} de {fecha.year}") if fecha else ""

    def draw(canv, doc):
        _bleed(canv, PORT_FONDO); canv._interior = False
        # Wordmark arriba-izquierda (mono, tracking); el PRO en verde.
        yw = A5H - MT - 4 * mm
        w1 = _txt(canv, ML, yw, "PERÚ SISTEMAS ", f["mono"], 10, PORT_TEXTO, cs=1.6)
        _txt(canv, ML + w1, yw, "PRO", f["mono"], 10, PORT_VERDE, cs=1.6)
        # Eyebrow (mono ámbar)
        _txt(canv, ML, A5H - 78 * mm, "INFORME PRELIMINAR DE NECESIDAD", f["mono"], 8, PORT_AMBAR, cs=2.2)
        # Titular (robusto: escala/trunca; envuelto en CONT_W-8mm para dar aire a la derecha).
        par, h = _titular_par(titular, f)
        par.drawOn(canv, ML, A5H - 84 * mm - h)
        # Regla verde corta (40mm)
        yr = A5H - 84 * mm - h - 8 * mm
        canv.setStrokeColor(PORT_VERDE); canv.setLineWidth(1.4); canv.line(ML, yr, ML + 40 * mm, yr)
        # Marcadores del riel (mono verde) con check VECTORIAL, abajo.
        x = ML; ym = 32 * mm
        for etq in MARCADORES:
            wx = _txt(canv, x, ym, etq, f["mono"], 7.5, PORT_VERDE, cs=1.2)
            _check(canv, x + wx + 2, ym + 0.4, PORT_VERDE)
            x += wx + 9 * mm
        # Pie: expediente + fecha (mono, línea)
        _txt(canv, ML, MB + 2 * mm, exp, f["mono"], 8, PORT_LINEA, cs=1)
        canv.setFont(f["mono"], 8); canv.setFillColor(PORT_LINEA)
        canv.drawRightString(A5W - MR, MB + 2 * mm, fecha_txt)
    return draw


def _mk_contra(datos):
    def draw(canv, doc):
        _bleed(canv, PORT_FONDO); canv._interior = False
    return draw


# --- Secciones interiores ---------------------------------------------------
def _seccion(story, S, numero, titulo, contenido):
    """Cabecera de 2 columnas (número | título+regla) y el contenido indentado."""
    cab = Table([[Paragraph(f"{numero:02d}", S["num"]),
                  [Paragraph(titulo, S["titulo"]),
                   HRFlowable(width="100%", thickness=0.6, color=INT_LINEA, spaceBefore=3, spaceAfter=6)]]],
                colWidths=[COL_NUM, CONT_W - COL_NUM])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    cab.keepWithNext = 1   # el título no queda huérfano al pie de página
    story.append(cab)
    story.append(Indenter(left=COL_NUM))
    story += contenido
    story.append(Indenter(left=-COL_NUM))
    story.append(Spacer(1, 10 * mm))


def _req_fila(S, texto, color=INT_VERDE):
    """Fila con fondo int_realce, esquinas suaves y un cuadrado de color. Verde
    para 'lo mínimo', ámbar para 'qué cambiaría' (bloque de valor)."""
    cuadro = Table([[""]], colWidths=[3.2 * mm], rowHeights=[3.2 * mm])
    cuadro.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    t = Table([[cuadro, Paragraph(texto, S["req"])]], colWidths=[8 * mm, (CONT_W - COL_NUM) - 8 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INT_REALCE),
                           ("ROUNDEDCORNERS", [5, 5, 5, 5]), ("VALIGN", (0, 0), (0, 0), "TOP"),
                           ("VALIGN", (1, 1), (1, 1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (0, 0), 8), ("LEFTPADDING", (1, 0), (1, 0), 2),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _decision_fila(S, texto):
    """Decisión: barra ámbar corta a la izquierda; disyuntiva en medium y su
    implicancia en normal (si se puede separar el texto en dos partes)."""
    txt = (texto or "").strip()
    p1, p2 = txt, ""
    for sep in (" — ", " – ", "—", ": "):
        if sep in txt:
            p1, p2 = txt.split(sep, 1); break
    cont = [Paragraph(_xml(p1.strip()), S["dec_a"])]
    if p2.strip():
        cont.append(Paragraph(_xml(p2.strip()), S["dec_b"]))
    t = Table([[cont]], colWidths=[CONT_W - COL_NUM])
    t.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 2.4, INT_AMBAR),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _card(S, etq, precio, sufijo, incluye):
    f = _fuentes()
    precio_par = Paragraph(
        f'<font name="{f["display"]}" size="21" color="#1a9e4b">{precio}</font> '
        f'<font name="{f["normal"]}" size="9" color="#5c6b64">{sufijo}</font>', S["cuerpo"])
    # Viñetas como Paragraph+bulletText (dentro de celda de tabla el ListFlowable
    # rompe el flujo y tira cada viñeta a su propia línea).
    cel = [Paragraph(etq, S["card_lbl"]), Spacer(1, 3), precio_par, Spacer(1, 9)]
    for x in incluye:
        cel.append(Paragraph(_xml(x), S["card_incl"], bulletText="•"))
    t = Table([[cel]], colWidths=[CONT_W - COL_NUM])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INT_REALCE), ("BOX", (0, 0), (-1, -1), 0.7, INT_LINEA),
                           ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                           ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11)]))
    return t


def _interiores(datos):
    S = _S(); f = _fuentes()
    inf = datos.get("informe") or {}
    story = []
    secciones = []   # (titulo, contenido_flowables)

    if (inf.get("lo_que_entendimos") or "").strip():
        secciones.append(("LO QUE ENTENDIMOS", [Paragraph(_xml(inf["lo_que_entendimos"].strip()), S["cuerpo"])]))

    # Qué cambiaría (bloque de valor): filas int_realce con cuadrado ÁMBAR.
    camb = [x for x in (inf.get("que_cambiaria") or []) if (x or "").strip()]
    if camb:
        cont = []
        for x in camb:
            cont.append(_req_fila(S, _xml(x), color=INT_AMBAR)); cont.append(Spacer(1, 5))
        secciones.append(("QUÉ CAMBIARÍA EN TU DÍA A DÍA", cont))

    preg = [x for x in (inf.get("preguntas") or []) if (x or "").strip()]
    if preg:
        cont = []
        for q in preg:
            p = Paragraph(_xml(q), S["preg"]); p.bulletText = "?"
            cont.append(p); cont.append(Spacer(1, 3))
        secciones.append(("PREGUNTAS QUE DEBERÍAS TENER RESUELTAS", cont))

    # Decisiones a tomar: barra ámbar corta + disyuntiva/implicancia.
    dec = [x for x in (inf.get("decisiones_a_tomar") or []) if (x or "").strip()]
    if dec:
        cont = []
        for d in dec:
            cont.append(_decision_fila(S, d)); cont.append(Spacer(1, 5))
        secciones.append(("DECISIONES QUE VAS A TENER QUE TOMAR", cont))

    req = [x for x in (inf.get("minimo_para_implementar") or []) if (x or "").strip()]
    if req:
        cont = []
        for r in req:
            cont.append(_req_fila(S, _xml(r))); cont.append(Spacer(1, 5))
        secciones.append(("LO MÍNIMO PARA IMPLEMENTARLO", cont))

    pend = [x for x in (inf.get("falta_definir") or []) if (x or "").strip()]
    if pend:
        cont = [ListFlowable([ListItem(Paragraph(_xml(x), S["pend"]), leftIndent=10, value="•") for x in pend],
                             bulletType="bullet", bulletColor=INT_SUAVE, leftIndent=8)]
        secciones.append(("LO QUE TODAVÍA FALTA DEFINIR", cont))

    # Costos (fijo, siempre presente)
    aplican = set(datos.get("costos_aplicables") or [])
    aviso = Table([[Paragraph(PRECIOS_AVISO, S["aviso"])]], colWidths=[CONT_W - COL_NUM])
    aviso.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INT_REALCE),
                               ("LINEBEFORE", (0, 0), (0, -1), 2.4, INT_AMBAR),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    cont = [aviso, Spacer(1, 8)]
    for etq, precio, suf, incl in PRECIOS_CARDS:
        cont.append(_card(S, etq, precio, suf, incl)); cont.append(Spacer(1, 7))
    cont.append(Paragraph("OTROS COSTOS POSIBLES, SEGÚN EL PROYECTO", S["card_lbl"]))
    cont.append(Spacer(1, 3))
    otros = []
    for clave, txt in PRECIOS_OTROS:
        on = clave in aplican
        otros.append(ListItem(Paragraph(txt, S["otros_on"] if on else S["otros_off"]),
                              leftIndent=9, value="•"))
    cont.append(ListFlowable(otros, bulletType="bullet", bulletColor=INT_AMBAR, leftIndent=8))
    cont.append(Paragraph(PRECIOS_CIERRE, S["cierre"]))
    secciones.append(("LO QUE CUESTA MANTENERLO FUNCIONANDO", cont))

    # Numeración recalculada (secciones vacías ya se omitieron)
    for i, (titulo, contenido) in enumerate(secciones, start=1):
        _seccion(story, S, i, titulo, contenido)
    return story


def _contra_flow(datos):
    S = _S()
    story = [Paragraph("¿Conversamos?", S["c_titulo"]), Spacer(1, 6 * mm),
             Paragraph("Este informe es tuyo, lo uses con nosotros o no. Si quieres que lo "
                       "revisemos juntos y te preparemos una propuesta, escríbenos.", S["c_parr"]),
             Spacer(1, 9 * mm),
             Paragraph("WHATSAPP", S["c_lbl"]),
             Paragraph(_link("967317946", "https://wa.me/51967317946"), S["c_wa"]),
             Spacer(1, 6 * mm),
             Paragraph("WEB", S["c_lbl"]),
             Paragraph(_link("perusistemas.pro", "https://perusistemas.pro"), S["c_val"]),
             Spacer(1, 5 * mm),
             Paragraph("CORREO", S["c_lbl"]),
             Paragraph(_link("info@perusistemas.pro", "mailto:info@perusistemas.pro"), S["c_val"]),
             Spacer(1, 9 * mm),
             HRFlowable(width=40 * mm, thickness=0.8, color=PORT_LINEA, spaceAfter=6 * mm),
             Paragraph("También tenemos sistemas listos para usar: facturación electrónica (" +
                       _link("facturalo.pro", "https://facturalo.pro") + "), punto de venta (" +
                       _link("quevendi.pro", "https://quevendi.pro") + "), avisos de SUNAT (" +
                       _link("alerta.pe", "https://alerta.pe") + "), restaurantes (" +
                       _link("metraes.com", "https://metraes.com") + ").", S["c_prod"])]
    return story


# --- Canvas con paginación SOLO de interiores -------------------------------
def _canvas_factory(exp):
    fnt = _fuentes()["mono"]

    class Num(canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._pgs = []
        def showPage(self):
            self._pgs.append(dict(self.__dict__)); self._startPage()
        def save(self):
            interiores = [i for i, st in enumerate(self._pgs) if st.get("_interior")]
            total = len(interiores)
            pos = {idx: k + 1 for k, idx in enumerate(interiores)}
            for i, st in enumerate(self._pgs):
                self.__dict__.update(st)
                if st.get("_interior"):
                    self._footer(pos[i], total)
                super().showPage()
            super().save()
        def _footer(self, n, total):
            self.setFont(fnt, 7); self.setFillColor(INT_SUAVE)
            y = MB - 4 * mm
            self.drawString(ML, y, exp)
            self.drawRightString(A5W - MR, y, f"{n} de {total}")
            self.drawCentredString(A5W / 2, y, "perusistemas.pro")
    return Num


# --- Generación -------------------------------------------------------------
def generar(datos: dict) -> bytes:
    _fuentes()
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A5, leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB,
        title="Informe preliminar de necesidad", author="Perú Sistemas PRO",
        subject="Informe preliminar de necesidad — Perú Sistemas PRO")
    f_int = Frame(ML, 14 * mm, CONT_W, A5H - MT - 16 * mm, id="int",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_full = Frame(0, 0, A5W, A5H, id="full", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_contra = Frame(ML, 18 * mm, CONT_W, A5H - 40 * mm, id="contra",
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="portada", frames=[f_full], onPage=_mk_portada(datos)),
        PageTemplate(id="interior", frames=[f_int], onPage=_interior_bg),
        PageTemplate(id="contra", frames=[f_contra], onPage=_mk_contra(datos)),
    ])
    story = [Spacer(1, 1), NextPageTemplate("interior"), PageBreak()]
    story += _interiores(datos)
    story += [NextPageTemplate("contra"), PageBreak()] + _contra_flow(datos)
    doc.build(story, canvasmaker=_canvas_factory(expediente(datos.get("id"))))
    return buf.getvalue()
