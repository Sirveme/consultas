/* app.js — flujo conversacional (vanilla). El servidor registra los eventos del
   embudo; aquí solo se registra whatsapp_click (el servidor no puede verlo). */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var WA = document.body.getAttribute("data-wa");

  function show(id) {
    ["s1", "s2", "s3", "s4", "sg"].forEach(function (s) {
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

  // WhatsApp: registra el click en el servidor (no bloquea la apertura del enlace).
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-wa-click]");
    if (a) post("/api/evento", { tipo: "whatsapp_click", lugar: a.getAttribute("data-wa-click") });
  });

  // Render de un turno de la IA (pregunta o resumen).
  function pintarTurno(j) {
    if (j.sin_ia || j.ir_a === "contacto") { irAContacto(j.mensaje, j.whatsapp); return; }
    if (j.fase === "resumen") { pintarResumen(j.resumen); return; }
    // pregunta
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
  function pintarResumen(txt) {
    $("resumen").textContent = txt || "";
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
    b.textContent = j.mensaje || "Escríbenos por WhatsApp.";
    conv.appendChild(b);
    $("chips").innerHTML = ""; $("txt2").style.display = "none"; $("b-responder").style.display = "none";
    show("s2");
  }

  // Pantalla 1 -> iniciar
  $("b-continuar").onclick = function () {
    var t = $("txt").value.trim();
    if (t.length < 3) { $("txt").focus(); return; }
    this.disabled = true; var self = this;
    post("/api/iniciar", { texto: t }).then(function (r) {
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
    post("/api/responder", { texto: t }).then(function (r) {
      $("b-responder").disabled = false;
      if (r.j && r.j.ok) pintarTurno(r.j);
    }).catch(function () { $("b-responder").disabled = false; irAContacto("Tuvimos un problema. Escríbenos por WhatsApp.", WA); });
  }
  $("b-responder").onclick = function () { responder(); };

  // Pantalla 3 -> ok / corregir
  $("b-ok").onclick = function () { irAContacto("Déjanos tus datos y te contactamos.", WA); };
  $("b-corregir").onclick = function () { $("corregir-box").classList.remove("oculto"); };
  $("b-enviar-correccion").onclick = function () {
    var t = $("txt3").value.trim();
    this.disabled = true;
    post("/api/corregir", { texto: t }).then(function (r) {
      if (r.j && r.j.sin_ia) { irAContacto(r.j.mensaje, r.j.whatsapp); return; }
      if (r.j && r.j.ok) pintarResumen(r.j.resumen);
    });
  };

  // Pantalla 4 -> contacto
  $("b-contacto").onclick = function () {
    var d = {
      nombre: $("c-nombre").value.trim(), empresa: $("c-empresa").value.trim(),
      cargo: $("c-cargo").value.trim(), celular: $("c-celular").value.trim(),
      correo: $("c-correo").value.trim(), ciudad: $("c-ciudad").value.trim(),
      consulta_publicable: $("c-pub").checked, version_publica: null,
      empresa_web: $("c-hp").value
    };
    if (!d.nombre || !d.celular || !d.ciudad) { $("c-msg").textContent = "Completa nombre, celular y ciudad."; $("c-msg").className = "msg err"; return; }
    $("b-contacto").disabled = true; $("c-msg").textContent = "Enviando…"; $("c-msg").className = "msg";
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
