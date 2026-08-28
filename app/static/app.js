/* app.js — flujo conversacional (vanilla). El servidor registra los eventos del
   embudo; el cliente solo emite whatsapp_click, calificacion_mostrada e
   informe_descargado. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var WA = document.body.getAttribute("data-wa");

  // Riel de expediente: refleja la fase real del flujo.
  var RIEL = {
    iniciada:   ["activo", "pendiente", "pendiente", "pendiente"],
    contexto:   ["completo", "activo", "pendiente", "pendiente"],
    alcance:    ["completo", "completo", "activo", "pendiente"],
    entrega:    ["completo", "completo", "completo", "activo"],
    completada: ["completo", "completo", "completo", "completo"]
  };
  function setRiel(fase) {
    var pasos = document.querySelectorAll("#riel .paso");
    var est = RIEL[fase] || RIEL.iniciada;
    pasos.forEach(function (p, i) { p.className = "paso " + est[i]; });
    $("riel").setAttribute("data-fase", fase);
  }
  var PANTALLA_FASE = { s1: "iniciada", s2: "contexto", s3: "alcance", sc: "alcance", s4: "entrega", sg: "completada" };
  function show(id) {
    ["s1", "s2", "s3", "sc", "s4", "sg"].forEach(function (s) { $(s).classList.toggle("oculto", s !== id); });
    setRiel(PANTALLA_FASE[id] || "iniciada");
    $("wa-fijo").classList.toggle("oculto", id === "sg");  // WhatsApp en todo el flujo salvo el informe
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function pixel(ev) { try { if (window.fbq) window.fbq("track", ev); } catch (e) {} }

  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); });
  }

  // Indicador = riel. Texto rotativo cada 2.5s bajo el riel; aviso de WhatsApp a los 15s.
  var TEXTOS = ["Leyendo lo que escribiste...", "Entendiendo tu necesidad...", "Preparando la siguiente pregunta..."];
  var timerTxt = null, timer15 = null;
  function cargarOn() {
    var i = 0; $("riel-carga").classList.remove("oculto"); $("riel-wa").classList.add("oculto");
    $("riel-carga").textContent = TEXTOS[0];
    timerTxt = setInterval(function () { i = (i + 1) % TEXTOS.length; $("riel-carga").textContent = TEXTOS[i]; }, 2500);
    timer15 = setTimeout(function () { $("riel-wa").classList.remove("oculto"); }, 15000);
  }
  function cargarOff() { $("riel-carga").classList.add("oculto"); $("riel-wa").classList.add("oculto"); clearInterval(timerTxt); clearTimeout(timer15); }
  function postIA(url, body) {
    cargarOn();
    return post(url, body).then(function (r) { cargarOff(); return r; }, function (e) { cargarOff(); throw e; });
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-wa-click]");
    if (a) post("/api/evento", { tipo: "whatsapp_click", lugar: a.getAttribute("data-wa-click") });
  });

  // Video: play manual (sin autoplay).
  var vplay = $("vplay");
  if (vplay) vplay.onclick = function () { try { $("vid").play(); } catch (e) {} vplay.classList.add("oculto"); };

  function burbuja(tipo, txt) { var d = document.createElement("div"); d.className = "burbuja " + tipo; d.textContent = txt; return d; }
  function pintarUsuario(t) { $("conv").appendChild(burbuja("usuario", t)); }
  function pintarChips(chips) {
    var c = $("chips"); c.innerHTML = "";
    (chips || []).forEach(function (t) {
      var ch = document.createElement("button"); ch.className = "chip"; ch.textContent = t;
      ch.onclick = function () { responder(t); }; c.appendChild(ch);
    });
  }
  // respuesta_visible (reconocimiento) y siguiente_pregunta van SIEMPRE en bloques
  // separados, nunca concatenados.
  function pintarRespuesta(j) {
    if (j.sin_ia || j.ir_a === "contacto") { irAContacto(j.mensaje, j.whatsapp); return; }
    if (j.fase === "resumen") { pintarResumen(j.resumen); return; }
    show("s2");
    var conv = $("conv");
    if (j.mensaje && j.mensaje.trim()) conv.appendChild(burbuja("ia", j.mensaje.trim()));
    if (j.pregunta && j.pregunta.trim()) conv.appendChild(burbuja("pregunta", j.pregunta.trim()));
    pintarChips(j.chips);
    $("txt2").value = "";
  }
  function pintarResumen(txt, yaReintento) {
    if (!txt || !txt.trim()) {
      if (!yaReintento) {
        postIA("/api/regenerar-resumen", {}).then(function (r) {
          if (r.j && r.j.sin_ia) { irAContacto(r.j.mensaje, r.j.whatsapp); return; }
          pintarResumen((r.j && r.j.resumen) || "", true);
        }).catch(function () { irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
        return;
      }
      irAContacto("No pudimos preparar el resumen esta vez. Escríbenos por WhatsApp, o déjanos tus datos.", WA);
      return;
    }
    $("resumen").textContent = txt; $("corregir-box").classList.add("oculto");
    pixel("ViewContent"); show("s3");
  }
  function irAContacto(msg, wa) { $("s4-msg").textContent = msg || "Déjanos tus datos y te contactamos."; if (wa) WA = wa; show("s4"); }
  function limite(j) {
    show("s2"); var conv = $("conv"); conv.innerHTML = "";
    conv.appendChild(burbuja("ia", j.mensaje || "Escríbenos por WhatsApp."));
    $("chips").innerHTML = ""; $("txt2").style.display = "none"; $("b-responder").style.display = "none";
  }

  // Pantalla 1 -> iniciar
  $("b-continuar").onclick = function () {
    var t = $("txt").value.trim();
    if (t.length < 3) { $("txt").focus(); return; }
    var self = this; self.disabled = true;
    postIA("/api/iniciar", { texto: t }).then(function (r) {
      self.disabled = false;
      if (r.status === 429) { limite(r.j); return; }
      if (r.j && r.j.ok) { if (r.j.fase === "pregunta") { show("s2"); $("conv").innerHTML = ""; pintarUsuario(t); } pintarRespuesta(r.j); }
    }).catch(function () { self.disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  };

  // Pantalla 2 -> responder
  function responder(texto) {
    var t = (texto != null ? texto : $("txt2").value).trim();
    if (t.length < 1) return;
    pintarUsuario(t); $("txt2").value = ""; $("b-responder").disabled = true;
    postIA("/api/responder", { texto: t }).then(function (r) {
      $("b-responder").disabled = false;
      if (r.j && r.j.ok) pintarRespuesta(r.j);
    }).catch(function () { $("b-responder").disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  }
  $("b-responder").onclick = function () { responder(); };

  // Pantalla 3 -> ok / corregir
  $("b-ok").onclick = function () { mostrarCalificacion(); };
  $("b-corregir").onclick = function () { $("corregir-box").classList.remove("oculto"); };
  $("b-enviar-correccion").onclick = function () {
    var t = $("txt3").value.trim(); var self = this; self.disabled = true;
    postIA("/api/corregir", { texto: t }).then(function (r) {
      self.disabled = false;
      if (r.j && r.j.sin_ia) { irAContacto(r.j.mensaje, r.j.whatsapp); return; }
      if (r.j && r.j.ok) pintarResumen(r.j.resumen);
    }).catch(function () { self.disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  };

  // --- Calificación ---
  function mostrarCalificacion() { show("sc"); post("/api/evento", { tipo: "calificacion_mostrada" }); }
  var sc = $("sc");
  if (sc) sc.addEventListener("click", function (e) {
    var o = e.target.closest(".opt"); if (!o) return; var g = o.closest(".grupo");
    if (g.getAttribute("data-tipo") === "single") { g.querySelectorAll(".opt").forEach(function (x) { x.classList.remove("sel"); }); o.classList.add("sel"); }
    else { o.classList.toggle("sel"); }
  });
  var EFECTOS = {
    sist_ninguno: { declarado: { sistema_actual: "ninguno" } },
    sist_excel:   { declarado: { sistema_actual: "excel" } },
    sist_corto:   { declarado: { tipo_proyecto: "actualizar_existente" }, derivado: { sistema_actual: "desconocido" } },
    sist_mejorar: { declarado: { tipo_proyecto: "actualizar_existente" }, derivado: { sistema_actual: "desconocido" } },
    uso_celular:  { nota: "usarían desde celular" },
    uso_pc:       { nota: "usarían desde computadora" },
    uso_varios:   { declarado: { alcance: "organizacion" } },
    uso_sinint:   { declarado: { conectividad: "sin_internet" } },
    cap_tecnico:  { declarado: { capacidad_tecnica: "tiene_personal_sistemas" } },
    cap_arregla:  { declarado: { capacidad_tecnica: "usuario_basico" } },
    cap_ninguno:  { declarado: { capacidad_tecnica: "usuario_basico" } },
    org_privada:  { declarado: { sector: "privado" } },
    org_publica:  { declarado: { sector: "publico" } },
    org_colegio:  { declarado: { sector: "colegio_profesional" } },
    org_emprend:  { declarado: { sector: "privado" }, derivado: { alcance: "una_tarea" }, nota: "Emprendimiento personal (no es empresa con planilla)" }
  };
  function recolectarCalif() {
    var declarado = {}, derivado = {}, notas = [];
    document.querySelectorAll("#sc .opt.sel").forEach(function (o) {
      var ef = EFECTOS[o.getAttribute("data-key")]; if (!ef) return;
      if (ef.declarado) Object.keys(ef.declarado).forEach(function (k) { declarado[k] = ef.declarado[k]; });
      if (ef.derivado) Object.keys(ef.derivado).forEach(function (k) { if (!(k in derivado)) derivado[k] = ef.derivado[k]; });
      if (ef.nota) notas.push(ef.nota);
    });
    return { declarado: declarado, derivado: derivado, nota: notas.join("; ") };
  }
  $("b-calif-continuar").onclick = function () {
    this.disabled = true; var d = recolectarCalif();
    post("/api/calificacion", { declarado: d.declarado, derivado: d.derivado, nota: d.nota, salto: false })
      .then(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); })
      .catch(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); });
  };
  $("b-calif-saltar").onclick = function () {
    post("/api/calificacion", { salto: true }).then(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); })
      .catch(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); });
  };

  // --- Contacto -> informe ---
  var PDF_URL = null;
  function lista(ul, arr) { ul.innerHTML = ""; (arr || []).forEach(function (t) { var li = document.createElement("li"); li.textContent = t; ul.appendChild(li); }); }
  function informeConContenido(inf) {
    inf = inf || {};
    return (inf.preguntas || []).length || (inf.minimo_para_implementar || []).length || (inf.falta_definir || []).length;
  }
  function pintarInforme(inf) {
    inf = inf || {};
    var dl = document.querySelector("#sg .row-btns");
    if (!informeConContenido(inf)) {
      // Sin informe útil: NO mostramos secciones vacías ni el botón de descarga
      // (el PDF daría 404). Mensaje honesto + WhatsApp.
      $("informe").classList.add("oculto");
      if (dl) dl.classList.add("oculto");
      var wa = $("sg-wa"); if (wa && WA) wa.href = WA;
      $("sg-simple").classList.remove("oculto");
      show("sg"); return;
    }
    $("sg-simple").classList.add("oculto");
    $("informe").classList.remove("oculto");
    if (dl) dl.classList.remove("oculto");
    $("inf-1").textContent = inf.lo_que_entendimos || $("resumen").textContent || "";
    lista($("inf-2"), inf.preguntas);
    lista($("inf-3"), inf.minimo_para_implementar);
    lista($("inf-4"), inf.falta_definir);
    show("sg");
  }
  $("b-contacto").onclick = function () {
    var d = {
      nombre: $("c-nombre").value.trim(), empresa: $("c-empresa").value.trim(), cargo: $("c-cargo").value.trim(),
      celular: $("c-celular").value.trim(), correo: $("c-correo").value.trim(), ciudad: $("c-ciudad").value.trim(),
      consulta_publicable: $("c-pub").checked, version_publica: null, empresa_web: $("c-hp").value
    };
    if (!d.nombre || !d.celular || !d.ciudad) { $("c-msg").textContent = "Completa nombre, celular y ciudad."; $("c-msg").className = "msg err"; return; }
    $("b-contacto").disabled = true; $("c-msg").textContent = "Enviando..."; $("c-msg").className = "msg";
    post("/api/contacto", d).then(function (r) {
      if (r.j && r.j.ok) { pixel("Lead"); if (r.j.whatsapp) WA = r.j.whatsapp; PDF_URL = r.j.pdf_url || null; pintarInforme(r.j.informe); }
      else { $("b-contacto").disabled = false; $("c-msg").textContent = (r.j && r.j.error) || "No se pudo enviar."; $("c-msg").className = "msg err"; }
    }).catch(function () { $("b-contacto").disabled = false; $("c-msg").textContent = "Error de red."; $("c-msg").className = "msg err"; });
  };

  // Descargar informe = PDF generado en el servidor (Content-Disposition attachment).
  $("b-descargar").onclick = function () {
    post("/api/evento", { tipo: "informe_descargado" });
    if (PDF_URL) window.location.href = PDF_URL;
  };

  // Estado inicial del riel: Necesidad activo.
  setRiel("iniciada");
})();
