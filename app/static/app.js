/* app.js — flujo conversacional (vanilla). El servidor registra los eventos del
   embudo; el cliente solo emite whatsapp_click y calificacion_mostrada. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var WA = document.body.getAttribute("data-wa");

  function show(id) {
    ["s1", "s2", "s3", "sc", "s4", "sg"].forEach(function (s) {
      $(s).classList.toggle("oculto", s !== id);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function pixel(ev) { try { if (window.fbq) window.fbq("track", ev); } catch (e) {} }

  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); });
  }

  // --- Indicador de carga: texto que rota cada 2.5s + aviso de WhatsApp a los 15s ---
  var TEXTOS = ["Leyendo lo que escribiste...", "Entendiendo tu necesidad...", "Preparando la siguiente pregunta..."];
  var timerTxt = null, timer15 = null;
  function cargarOn() {
    var i = 0; $("cargando").classList.remove("oculto");
    $("cargando-wa").classList.add("oculto"); $("cargando-txt").textContent = TEXTOS[0];
    timerTxt = setInterval(function () { i = (i + 1) % TEXTOS.length; $("cargando-txt").textContent = TEXTOS[i]; }, 2500);
    timer15 = setTimeout(function () { $("cargando-wa").classList.remove("oculto"); }, 15000);
  }
  function cargarOff() { $("cargando").classList.add("oculto"); clearInterval(timerTxt); clearTimeout(timer15); }
  function postIA(url, body) {
    cargarOn();
    return post(url, body).then(function (r) { cargarOff(); return r; },
                                function (e) { cargarOff(); throw e; });
  }

  // WhatsApp: registra el click en el servidor (no bloquea la apertura del enlace).
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-wa-click]");
    if (a) post("/api/evento", { tipo: "whatsapp_click", lugar: a.getAttribute("data-wa-click") });
  });

  function pintarTurno(j) {
    if (j.sin_ia || j.ir_a === "contacto") { irAContacto(j.mensaje, j.whatsapp); return; }
    if (j.fase === "resumen") { pintarResumen(j.resumen); return; }
    var conv = $("conv");
    var b = document.createElement("div"); b.className = "burbuja ia";
    b.textContent = (j.mensaje ? j.mensaje + " " : "") + (j.pregunta || "");
    conv.appendChild(b);
    var chips = $("chips"); chips.innerHTML = "";
    (j.chips || []).forEach(function (c) {
      var ch = document.createElement("button"); ch.className = "chip"; ch.textContent = c;
      ch.onclick = function () { responder(c); };
      chips.appendChild(ch);
    });
    $("txt2").value = "";
    show("s2");
  }

  // Resumen: si llega vacío, NO pintamos la pantalla. Reintentamos UNA vez; si
  // vuelve vacío, mensaje amable + WhatsApp. Nunca resumen en blanco.
  function pintarResumen(txt, yaReintento) {
    if (!txt || !txt.trim()) {
      if (!yaReintento) {
        postIA("/api/regenerar-resumen", {}).then(function (r) {
          if (r.j && r.j.sin_ia) { irAContacto(r.j.mensaje, r.j.whatsapp); return; }
          pintarResumen((r.j && r.j.resumen) || "", true);
        }).catch(function () { irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
        return;
      }
      irAContacto("No pudimos preparar el resumen esta vez. Escríbenos por WhatsApp y te ayudamos, o déjanos tus datos.", WA);
      return;
    }
    $("resumen").textContent = txt;
    $("corregir-box").classList.add("oculto");
    pixel("ViewContent");
    show("s3");
  }

  function irAContacto(msg, wa) {
    $("s4-msg").textContent = msg || "Déjanos tus datos y te contactamos.";
    if (wa) WA = wa;
    show("s4");
  }
  function limite(j) {
    var conv = $("conv"); conv.innerHTML = "";
    var b = document.createElement("div"); b.className = "burbuja ia";
    b.textContent = j.mensaje || "Escríbenos por WhatsApp."; conv.appendChild(b);
    $("chips").innerHTML = ""; $("txt2").style.display = "none"; $("b-responder").style.display = "none";
    show("s2");
  }

  // Pantalla 1 -> iniciar
  $("b-continuar").onclick = function () {
    var t = $("txt").value.trim();
    if (t.length < 3) { $("txt").focus(); return; }
    var self = this; self.disabled = true;
    postIA("/api/iniciar", { texto: t }).then(function (r) {
      self.disabled = false;
      if (r.status === 429) { limite(r.j); return; }
      if (r.j && r.j.ok) pintarTurno(r.j);
    }).catch(function () { self.disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  };

  // Pantalla 2 -> responder
  function responder(texto) {
    var t = (texto != null ? texto : $("txt2").value).trim();
    if (t.length < 1) return;
    $("b-responder").disabled = true;
    postIA("/api/responder", { texto: t }).then(function (r) {
      $("b-responder").disabled = false;
      if (r.j && r.j.ok) pintarTurno(r.j);
    }).catch(function () { $("b-responder").disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  }
  $("b-responder").onclick = function () { responder(); };

  // Pantalla 3 -> ok (a calificación) / corregir
  $("b-ok").onclick = function () { mostrarCalificacion(); };
  $("b-corregir").onclick = function () { $("corregir-box").classList.remove("oculto"); };
  $("b-enviar-correccion").onclick = function () {
    var t = $("txt3").value.trim(); this.disabled = true; var self = this;
    postIA("/api/corregir", { texto: t }).then(function (r) {
      self.disabled = false;
      if (r.j && r.j.sin_ia) { irAContacto(r.j.mensaje, r.j.whatsapp); return; }
      if (r.j && r.j.ok) pintarResumen(r.j.resumen);
    }).catch(function () { self.disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  };

  // --- Pantalla de calificación (opcional) ---
  function mostrarCalificacion() {
    show("sc");
    post("/api/evento", { tipo: "calificacion_mostrada" });
  }
  // Selección de opciones (single = una por grupo; multi = varias).
  var sc = $("sc");
  if (sc) sc.addEventListener("click", function (e) {
    var o = e.target.closest(".opt"); if (!o) return;
    var g = o.closest(".grupo");
    if (g.getAttribute("data-tipo") === "single") {
      g.querySelectorAll(".opt").forEach(function (x) { x.classList.remove("sel"); });
      o.classList.add("sel");
    } else { o.classList.toggle("sel"); }
  });
  // Efecto de cada chip. `declarado` = lo que el chip responde DIRECTAMENTE (va a
  // campos_declarados, sobrescribe). `derivado` = deducción nuestra (el servidor
  // solo la aplica si la IA no tenía dato; NUNCA se marca como declarado). `nota`
  // = matiz en texto libre. Un chip solo toca los campos que realmente responde.
  var EFECTOS = {
    sist_ninguno: { declarado: { sistema_actual: "ninguno" } },
    sist_excel:   { declarado: { sistema_actual: "excel" } },
    // No sabemos si lo compraron o se lo hicieron a medida -> sistema_actual queda
    // desconocido (derivado); lo que el chip SÍ dice es que quieren actualizarlo.
    sist_corto:   { declarado: { tipo_proyecto: "actualizar_existente" }, derivado: { sistema_actual: "desconocido" } },
    sist_mejorar: { declarado: { tipo_proyecto: "actualizar_existente" }, derivado: { sistema_actual: "desconocido" } },
    // El dispositivo no declara la plataforma (podría ser web, android o escritorio):
    // se guarda como matiz, no como plataforma_probable.
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
    // Emprendimiento personal ≠ empresa con planilla: sector privado (declarado),
    // alcance una_tarea SOLO si no hay otro dato (derivado), y el matiz en la nota.
    org_emprend:  { declarado: { sector: "privado" }, derivado: { alcance: "una_tarea" },
                    nota: "Emprendimiento personal (no es empresa con planilla)" },
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
    this.disabled = true;
    var d = recolectarCalif();
    post("/api/calificacion", { declarado: d.declarado, derivado: d.derivado, nota: d.nota, salto: false })
      .then(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); })
      .catch(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); });
  };
  $("b-calif-saltar").onclick = function () {
    post("/api/calificacion", { salto: true }).then(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); })
      .catch(function () { irAContacto("Déjanos tus datos y te contactamos.", WA); });
  };

  // Pantalla 4 -> contacto
  $("b-contacto").onclick = function () {
    var d = {
      nombre: $("c-nombre").value.trim(), empresa: $("c-empresa").value.trim(),
      cargo: $("c-cargo").value.trim(), celular: $("c-celular").value.trim(),
      correo: $("c-correo").value.trim(), ciudad: $("c-ciudad").value.trim(),
      consulta_publicable: $("c-pub").checked, version_publica: null, empresa_web: $("c-hp").value
    };
    if (!d.nombre || !d.celular || !d.ciudad) { $("c-msg").textContent = "Completa nombre, celular y ciudad."; $("c-msg").className = "msg err"; return; }
    $("b-contacto").disabled = true; $("c-msg").textContent = "Enviando..."; $("c-msg").className = "msg";
    post("/api/contacto", d).then(function (r) {
      if (r.j && r.j.ok) {
        pixel("Lead");
        if (r.j.whatsapp) WA = r.j.whatsapp;
        $("sg-msg").textContent = r.j.mensaje || "Te contactaremos pronto.";
        var wag = document.querySelector("#sg .wa"); if (wag) wag.href = WA;
        show("sg");
      } else {
        $("b-contacto").disabled = false;
        $("c-msg").textContent = (r.j && r.j.error) || "No se pudo enviar."; $("c-msg").className = "msg err";
      }
    }).catch(function () { $("b-contacto").disabled = false; $("c-msg").textContent = "Error de red."; $("c-msg").className = "msg err"; });
  };
})();
