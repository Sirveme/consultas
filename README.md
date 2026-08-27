# consultas.perusistemas.pro

Landing conversacional para tráfico frío de Facebook (Iquitos). El visitante
escribe su necesidad, una IA le hace **máximo 2 preguntas**, le muestra un
resumen y captura el contacto. Servicio independiente en Railway, apuntando a
`consultas.perusistemas.pro`. Comparte la Postgres del ecosistema (esquema
`consultas`), pero **no depende del proyecto de perusistemas.pro**.

Stack: FastAPI + asyncpg + Jinja2 + JS vanilla. Sin HTMX, sin frameworks CSS.

## Estructura

```
app/
  __init__.py
  main.py            FastAPI: rutas, config, CORS de /api/lead, sesión, panel, Pixel
  db.py              asyncpg + todas las consultas + ip_hash + rate-limit + tope IA
  ia.py              cliente IA async (httpx, JSON Schema, tokens, manejo de fallo)
  prompts.py         SYSTEM_PROMPT + esquema de salida (lo que más se edita)
  templates/  landing.html, panel.html
  static/     estilos.css, app.js
sql/esquema.sql      DDL para correr A MANO en PGAdmin
Procfile, requirements.txt, .python-version, .gitignore, .env.example
```

## Variables de entorno

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Conexión a la Postgres compartida (la misma del ecosistema). |
| `SECRET_KEY` | Firma las cookies de sesión y del panel (itsdangerous). Larga y aleatoria. |
| `PANEL_PASSWORD` | Contraseña única del panel interno `/panel`. |
| `IP_SAL` | Sal secreta para hashear la IP. **Nunca se guarda la IP cruda.** |
| `MODELO_IA` | Nombre del modelo de IA. Se lee tal cual; no se asume ninguno. |
| `IA_API_URL` | Endpoint del proveedor (contrato OpenAI-compatible `/chat/completions`). |
| `IA_API_KEY` | Clave del proveedor de IA. |
| `LIMITE_IA_DIARIO` | Tope global de llamadas a la IA por día. Al superarlo, se captura el lead **sin IA** (texto + WhatsApp). |
| `WHATSAPP_NUMERO` | WhatsApp de contacto (Perú, 9 dígitos). En `wa.me` va como `51` + número. Actual: `967317946`. |
| `ORIGENES_PERMITIDOS` | Lista blanca (coma-separada) de dominios que pueden llamar `POST /api/lead` (facturalo.pro, quevendi.pro, alerta.pe, metraes.com). **Nunca `*`.** |
| `META_PIXEL_ID` | Si está vacío, el Meta Pixel no se inserta. |

## Endpoints

- `GET /` landing · `POST /api/iniciar` · `POST /api/responder` · `POST /api/corregir`
- `POST /api/contacto` · `POST /api/evento` (solo `whatsapp_click`)
- `POST /api/lead` (sin IA, CORS para landings clásicas) · `GET /panel` · `POST /panel/login`
- `POST /panel/estado` · `GET /salud`

## Despliegue en Railway (orden exacto)

1. **Base de datos:** en PGAdmin, conectado a la MISMA Postgres, corre
   `sql/esquema.sql` (crea el esquema `consultas` y sus tablas/índices). Es
   idempotente; no toca `public`.
2. **Nuevo servicio** en Railway (deploy manual por lotes de ~25 archivos): sube
   todo el repo (respeta `.gitignore`; no subas `.env` ni `venv/`).
3. **Variables:** carga las de la tabla de arriba en *Variables* del servicio.
   `DATABASE_URL` = la misma cadena del Postgres del proyecto (Railway la ofrece
   como referencia si el Postgres está en el mismo proyecto).
4. **Dominio:** en *Settings → Networking → Custom Domain* añade
   `consultas.perusistemas.pro`. Railway te da un destino CNAME y emite el TLS.
5. **Arranque:** el `Procfile` corre `uvicorn app.main:app`. `.python-version`
   fija Python 3.12. Verifica en `/salud` que responde `{"ok": true}`.

## DNS + redirección en Cloudflare

**Subdominio (para que el servicio sea accesible):**
- Registro **CNAME** · Nombre: `consultas` · Destino: el CNAME que dio Railway ·
  Proxy: activado (naranja).

**Redirección `perusistemas.pro/consultas` → `consultas.perusistemas.pro`
preservando el query string** (para no perder los UTM de los anuncios):

- Cloudflare → **Rules → Redirect Rules → Create rule**:
  - **When incoming requests match:** `Hostname equals perusistemas.pro` **AND**
    `URI Path starts with /consultas`
  - **Then:** *Dynamic redirect*, **301 (permanent)**, expresión:
    ```
    concat("https://consultas.perusistemas.pro", substring(http.request.uri.path, 10), if(http.request.uri.query != "", concat("?", http.request.uri.query), ""))
    ```
    (`substring(...,10)` quita el prefijo `/consultas`; el `if` reengancha el
    query string tal cual, así que `?utm_source=...` se conserva.)
  - Alternativa simple si no necesitas recortar el path: *Preserve query string*
    activado y destino `https://consultas.perusistemas.pro/`.

## Notas de operación

- **Todo el embudo se registra en `consultas.evento` desde el servidor**
  (`vista`, `consulta_iniciada`, `pregunta_respondida`, `resumen_visto`,
  `contacto_enviado`, `ia_error`). El único evento del cliente es
  `whatsapp_click`. El Pixel es secundario (los bloqueadores lo silencian).
- **Nunca se envía a Meta** el texto de la consulta ni datos de contacto.
- **Costos:** cada `mensaje` guarda `tokens_entrada`/`tokens_salida`; el total
  por lead vive en `consulta`. Tope duro de 6 llamadas de IA por consulta y
  `LIMITE_IA_DIARIO` global.
- **Anti-abuso:** rate-limit por `ip_hash` (3/h, 15/día), honeypot en contacto y
  en `/api/lead`, y máx. 1500 caracteres por mensaje.
- El proveedor de IA se asume **OpenAI-compatible** (`/chat/completions` con
  `response_format` JSON Schema y `usage.prompt_tokens/completion_tokens`). Si el
  tuyo difiere, `app/ia.py` es el único archivo a ajustar.
