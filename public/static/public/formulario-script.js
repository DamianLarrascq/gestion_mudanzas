// --- CONFIGURACIÓN E INICIALIZACIÓN ---
let coordenadas = { origen: null, destino: null };
let dataDirecciones = { origen: {}, destino: {} };

let volumesMuebles = {};
let inventarioCantidades = {};

let fechaSeleccionada = null;
let horaSeleccionada = null;
let urlPagoMercadoPago = null;

const horariosBase = ["08:00", "10:00", "13:00", "15:00"];

document.addEventListener('DOMContentLoaded', () => {

  const btnCalcular = document.getElementById('btn-calcular');
  if (btnCalcular) {
    btnCalcular.addEventListener('click', enviarSolicitudPresupuesto)
  }

  // Inicialización dinámica de catálogos desde el DOM estructurado por Django
  document.querySelectorAll('.mueble-item').forEach(el => {
    const id = el.dataset.id;
    const vol = parseFloat(el.dataset.volumen) || 0;
    volumesMuebles[id] = vol;
    inventarioCantidades[id] = 0;
  });

  // Configuración del autocompletado nativo usando Nominatim (OpenStreetMap)
  configurarAutocompletadoNominatim('origen', 'sug-origen');
  configurarAutocompletadoNominatim('destino', 'sug-destino');

  // Calendario de operaciones en días hábiles
  generarDiasHabiles();

  // Escuchadores de entradas obligatorias para validación del botón de envío
  document.getElementById("nombre").addEventListener("input", validarFormularioCompleto);
  document.getElementById("telefono").addEventListener("input", validarFormularioCompleto);
  document.getElementById("origen_numero").addEventListener("input", validarFormularioCompleto);
  document.getElementById("destino_numero").addEventListener("input", validarFormularioCompleto);
});

// --- MOTOR DE MAPAS: NOMINATIM CON ADDRESSDETAILS=1 ---
function configurarAutocompletadoNominatim(inputId, sugerenciasId) {
  const input = document.getElementById(inputId);
  const container = document.getElementById(sugerenciasId);
  let timeout = null;

  input.addEventListener('input', () => {
    coordenadas[inputId] = null;
    dataDirecciones[inputId] = {};
    document.getElementById(`${inputId}_calle`).value = "";
    document.getElementById(`${inputId}_localidad`).value = "";
    clearTimeout(timeout);

    const query = input.value.trim();
    if (query.length < 4) {
      container.classList.add('hidden');
      return;
    }

    timeout = setTimeout(() => {
      // Inyección mandatoria del parámetro addressdetails=1 filtrado para Argentina
      const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&q=${encodeURIComponent(query)}&countrycodes=ar&limit=5`;

      fetch(url, { headers: { 'Accept-Language': 'es' } })
        .then(res => res.json())
        .then(data => {
          container.innerHTML = '';
          if (!data || data.length === 0) {
            container.classList.add('hidden');
            return;
          }

          data.forEach(result => {
            const addr = result.address;
            // Extracción y fallbacks según directivas contractuales
            const calle = addr.road || addr.pedestrian || "";
            const numero = addr.house_number || "";
            const localidad = addr.city || addr.town || addr.village || "";

            if (!calle) return; // Saltamos direcciones inconsistentes

            const div = document.createElement('div');
            div.className = 'sugerencia-item';
            div.textContent = result.display_name;

            div.addEventListener('click', () => {
              input.value = result.display_name;
              container.classList.add('hidden');

              // Mapeo físico en variables globales
              coordenadas[inputId] = [parseFloat(result.lat), parseFloat(result.lon)];
              dataDirecciones[inputId] = { calle, numero, localidad };

              // Inyección visual en campos desglosados
              document.getElementById(`${inputId}_calle`).value = calle;
              document.getElementById(`${inputId}_localidad`).value = localidad;

              const inputNumero = document.getElementById(`${inputId}_numero`);
              if (numero) {
                inputNumero.value = numero;
              } else {
                inputNumero.value = "";
                inputNumero.placeholder = "Falta altura *";
                inputNumero.focus();
              }

              calcularRutaOSRM();
              validarFormularioCompleto();
            });
            container.appendChild(div);
          });
          container.classList.remove('hidden');
        })
        .catch(err => console.error('Error buscando rutas en Nominatim:', err));
    }, 500);
  });

  document.addEventListener('click', (e) => {
    if (e.target !== input) container.classList.add('hidden');
  });
}

// --- CALCULO DE DISTANCIAS POR OSRM ---
function calcularRutaOSRM() {
  if (coordenadas.origen && coordenadas.destino) {
    const locOrigen = `${coordenadas.origen[1]},${coordenadas.origen[0]}`;
    const locDestino = `${coordenadas.destino[1]},${coordenadas.destino[0]}`;
    const url = `https://router.project-osrm.org/route/v1/driving/${locOrigen};${locDestino}?overview=false`;

    fetch(url)
      .then(res => res.json())
      .then(data => {
        if (data.code === 'Ok' && data.routes.length > 0) {
          const distanciaKm = (data.routes[0].distance / 1000).toFixed(2);
          document.getElementById('distancia_km').value = distanciaKm;
          validarFormularioCompleto();
        }
      })
      .catch(err => console.error('Error procesando trazado OSRM:', err));
  }
}

// --- MANEJO DEL INVENTARIO DINÁMICO ---
function alterarMueble(id, cambio) {
  let nuevaCant = inventarioCantidades[id] + cambio;
  if (nuevaCant < 0) return;

  inventarioCantidades[id] = nuevaCant;
  document.getElementById(`cant-${id}`).textContent = nuevaCant;
  actualizarCamionVisual();
  validarFormularioCompleto();
}

function actualizarCamionVisual() {
  const caja = document.getElementById("camion-caja-items");
  const tipoTag = document.getElementById("camion-tipo");
  const lblBultos = document.getElementById("metrica-bultos");
  const lblVolumen = document.getElementById("metrica-volumen");
  const svgCaja = document.getElementById("svg-caja-carga");

  caja.innerHTML = "";
  let totalBultos = 0;
  let totalVolumen = 0;

  Object.keys(inventarioCantidades).forEach(id => {
    let cant = inventarioCantidades[id];
    totalBultos += cant;
    totalVolumen += cant * volumesMuebles[id];

    if (cant > 0) {
      const itemNode = document.createElement("div");
      itemNode.className = "item-en-camion";
      const itemEl = document.querySelector(`.mueble-item[data-id="${id}"] .mueble-nombre`);
      const txtNombre = itemEl ? itemEl.textContent : "Mueble";
      itemNode.innerHTML = `<span>${txtNombre}</span> <strong>x${cant}</strong>`;
      caja.appendChild(itemNode);
    }
  });

  lblBultos.textContent = totalBultos;
  lblVolumen.textContent = totalVolumen.toFixed(2) + " m³";

  if (totalBultos === 0) {
    caja.innerHTML = `<div class="caja-vacia-msg">Sin bultos seleccionados.</div>`;
    tipoTag.textContent = "Vehículo Requerido: Ninguno";
    svgCaja.setAttribute("fill", "#cbd5e1");
  } else if (totalVolumen <= 3.0) {
    tipoTag.textContent = "Vehículo Recomendado: Utilitario (Furgón)";
    svgCaja.setAttribute("fill", "#93c5fd");
  } else if (totalVolumen <= 8.0) {
    tipoTag.textContent = "Vehículo Recomendado: Camión Ligero";
    svgCaja.setAttribute("fill", "#86efac");
  } else {
    tipoTag.textContent = "Vehículo Recomendado: Camión de Gran Porte";
    svgCaja.setAttribute("fill", "#fca5a5");
  }
}

// --- AGENDA INTERACTIVA ---
function generarDiasHabiles() {
  const contenedorDias = document.getElementById("calendario-dias");
  if (!contenedorDias) return;
  contenedorDias.innerHTML = "";
  let hoy = new Date(), diasGenerados = 0, fechaIteradora = new Date(hoy);

  while (diasGenerados < 10) {
    fechaIteradora.setDate(fechaIteradora.getDate() + 1);
    if (fechaIteradora.getDay() !== 0 && fechaIteradora.getDay() !== 6) {
      crearBotonDia(new Date(fechaIteradora));
      diasGenerados++;
    }
  }
}

function crearBotonDia(fecha) {
  const contenedor = document.getElementById("calendario-dias");
  const nombreDia = fecha.toLocaleDateString('es-AR', { weekday: 'short' }).replace('.', '');
  const numDia = fecha.getDate();
  const strFecha = fecha.toISOString().split('T')[0];

  const btn = document.createElement("div");
  btn.className = "btn-3d day-btn";
  btn.dataset.fecha = strFecha;
  btn.innerHTML = `<span class="day-name">${nombreDia}</span><span class="day-number">${numDia}</span>`;
  btn.onclick = () => seleccionarDia(btn, strFecha);
  contenedor.appendChild(btn);
}

function seleccionarDia(botonElemento, strFecha) {
  document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("selected"));
  botonElemento.classList.add("selected");
  fechaSeleccionada = strFecha;
  horaSeleccionada = null;

  const seccionHorarios = document.getElementById("seccion-horarios");
  if (seccionHorarios) seccionHorarios.style.display = "block";
  generarHorarios();
  validarFormularioCompleto();
}

function generarHorarios() {
  const contenedorHorarios = document.getElementById("grilla-horarios");
  if (!contenedorHorarios) return;
  contenedorHorarios.innerHTML = "";

  horariosBase.forEach(hora => {
    const btn = document.createElement("div");
    btn.className = "btn-3d btn-hora";
    btn.textContent = hora;
    btn.onclick = () => {
      document.querySelectorAll(".btn-hora").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      horaSeleccionada = hora;
      validarFormularioCompleto();
    };
    contenedorHorarios.appendChild(btn);
  });
}

// --- VALIDACIÓN DE BOTÓN DE ENVÍO DE FORMULARIO ---
function validarFormularioCompleto() {
  const nombre = document.getElementById("nombre").value.trim();
  const telefono = document.getElementById("telefono").value.trim();
  const origNum = document.getElementById("origen_numero").value.trim();
  const destNum = document.getElementById("destino_numero").value.trim();
  const km = parseFloat(document.getElementById("distancia_km").value) || 0;

  let totalBultos = 0;
  Object.keys(inventarioCantidades).forEach(k => totalBultos += inventarioCantidades[k]);

  const inputsValidos = nombre !== "" && telefono !== "" && origNum !== "" && destNum !== "" && km >= 1 && totalBultos > 0;
  const agendaValida = fechaSeleccionada !== null && horaSeleccionada !== null;

  const btnCalcular = document.getElementById("btn-calcular");
  if (btnCalcular) {
    btnCalcular.disabled = !(inputsValidos && agendaValida);
  }
}

// --- INTEGRACIÓN ASÍNCRONA CON EL ENDPOINT BACKEND (POST JSON) ---
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function enviarSolicitudPresupuesto() {
  // 1. Capturar y congelar el botón para evitar doble submit instantáneamente
  const btnCalcular = document.getElementById("btn-calcular");
  if (btnCalcular) {
    btnCalcular.disabled = true;
    btnCalcular.textContent = "Procesando cotización... ⏳";
  }

  // Limpieza inicial de contenedores de error (adaptado a tus IDs del HTML)
  document.querySelectorAll(".error-msg").forEach(e => e.textContent = "");
  const errAll = document.getElementById("err-__all__");
  if (errAll) errAll.textContent = "";

  // Construcción estructurada del array de inventario con IDs reales
  const arrayInventario = [];
  Object.keys(inventarioCantidades).forEach(id => {
    const cant = inventarioCantidades[id];
    if (cant > 0) {
      arrayInventario.push({
        "catalogo_item_id": parseInt(id),
        "cantidad": cant
      });
    }
  });

  // Ensamblado del Payload definitivo
  const payload = {
    "nombre": document.getElementById("nombre").value.trim(),
    "telefono": document.getElementById("telefono").value.trim(),
    "email": document.getElementById("email").value.trim(),

    "origen_calle": document.getElementById("origen_calle").value.trim(),
    "origen_numero": document.getElementById("origen_numero").value.trim(),
    "origen_localidad": document.getElementById("origen_localidad").value.trim(),
    "origen_piso": document.getElementById("pisos_origen").value,
    "origen_ascensor": document.getElementById("asc_origen").checked,
    "origen_lat": coordenadas.origen ? coordenadas.origen[0] : null,
    "origen_lng": coordenadas.origen ? coordenadas.origen[1] : null,

    "destino_calle": document.getElementById("destino_calle").value.trim(),
    "destino_numero": document.getElementById("destino_numero").value.trim(),
    "destino_localidad": document.getElementById("destino_localidad").value.trim(),
    "destino_piso": document.getElementById("pisos_destino").value,
    "destino_ascensor": document.getElementById("asc_destino").checked,
    "destino_lat": coordenadas.destino ? coordenadas.destino[0] : null,
    "destino_lng": coordenadas.destino ? coordenadas.destino[1] : null,

    "fecha_deseada": fechaSeleccionada,
    "hora_deseada": horaSeleccionada,
    "distancia_km": document.getElementById("distancia_km").value,
    "inventario": arrayInventario
  };

  // Despacho vía Fetch API con inyección de cabecera CSRF Token
  fetch('/presupuesto/solicitar/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken')
    },
    body: JSON.stringify(payload)
  })
  .then(res => res.json().then(data => ({ status: res.status, body: data })))
  .then(response => {
    if (response.status === 200 && response.body.ok) {
      manejarExitoServidor(response.body);
    } else if (response.status === 422) {
      // Si hay errores de validación, rehabilitamos el botón para corregir
      if (btnCalcular) {
        btnCalcular.disabled = false;
        btnCalcular.textContent = "Calcular tarifa y ver resumen →";
      }
      manejarErroresValidacion(response.body.errores);
    } else if (response.status === 502) {
      alert("La cotización fue registrada exitosamente, pero el portal de pagos se encuentra saturado. Podrá saldar la seña más tarde.");
      manejarExitoServidor(response.body);
    } else {
      // Error 500 u otros del servidor
      if (btnCalcular) {
        btnCalcular.disabled = false;
        btnCalcular.textContent = "Calcular tarifa y ver resumen →";
      }
      if (document.getElementById("err-__all__")) {
        document.getElementById("err-__all__").textContent = "Error inesperado en la comunicación con el servidor central.";
      }
    }
  })
  .catch(err => {
    console.error("Fallo crítico en operación de red:", err);
    if (btnCalcular) {
      btnCalcular.disabled = false;
      btnCalcular.textContent = "Calcular tarifa y ver resumen →";
    }
    if (document.getElementById("err-__all__")) {
      document.getElementById("err-__all__").textContent = "Error de red. Verifique su conectividad.";
    }
  });
}

function manejarExitoServidor(datos) {
  urlPagoMercadoPago = datos.pago_url;

  const kmActuales = document.getElementById("distancia_km").value;
  document.getElementById("lineas-presupuesto").innerHTML = `
    <div class="linea-item"><span>Tarifa base de asignación logística</span><span class="linea-monto">Operación Procesada</span></div>
    <div class="linea-item"><span>Kilometraje en ruta calculada (${kmActuales} km)</span><span class="linea-monto">Incluido</span></div>
  `;

  document.getElementById("val-senia").textContent = "$ " + parseFloat(datos.monto_senia).toLocaleString("es-AR");
  document.getElementById("val-total").textContent = "$ " + parseFloat(datos.monto_total).toLocaleString("es-AR");

  document.getElementById("resumen-datos").innerHTML = `
    <div class="resumen-item"><div class="resumen-label">ID Mudanza Registrada</div><div class="resumen-value">#${datos.mudanza_id}</div></div>
    <div class="resumen-item"><div class="resumen-label">Itinerario Planificado</div><div class="resumen-value">${kmActuales} KM totales</div></div>
  `;

  setStep(2);
}

function manejarErroresValidacion(errores) {
  Object.keys(errores).forEach(campo => {
    // Corregido: mapea a 'error-campo' tal como figura en tu HTML
    const contenedorError = document.getElementById(`error-${campo}`);
    if (contenedorError) {
      contenedorError.textContent = errores[campo].join(" ");
    } else if (campo === "__all__" && document.getElementById("err-__all__")) {
      document.getElementById("err-__all__").textContent = errores[campo].join(" ");
    }
  });
}

function manejarExitoServidor(datos) {
  urlPagoMercadoPago = datos.pago_url;

  const kmActuales = document.getElementById("distancia_km").value;
  document.getElementById("lineas-presupuesto").innerHTML = `
    <div class="linea-item"><span>Tarifa base de asignación logística</span><span class="linea-monto">Operación Procesada</span></div>
    <div class="linea-item"><span>Kilometraje en ruta calculada (${kmActuales} km)</span><span class="linea-monto">Incluido</span></div>
  `;

  document.getElementById("val-senia").textContent = "$ " + parseFloat(datos.monto_senia).toLocaleString("es-AR");
  document.getElementById("val-total").textContent = "$ " + parseFloat(datos.monto_total).toLocaleString("es-AR");

  document.getElementById("resumen-datos").innerHTML = `
    <div class="resumen-item"><div class="resumen-label">ID Mudanza Registrada</div><div class="resumen-value">#${datos.mudanza_id}</div></div>
    <div class="resumen-item"><div class="resumen-label">Itinerario Planificado</div><div class="resumen-value">${kmActuales} KM totales</div></div>
  `;

  setStep(2);
}

function manejarErroresValidacion(errores) {
  Object.keys(errores).forEach(campo => {
    const contenedorError = document.getElementById(`err-${campo}`);
    if (contenedorError) {
      contenedorError.textContent = errores[campo].join(" ");
    } else if (campo === "__all__") {
      const errAll = document.getElementById("err-__all__");
      if (errAll) errAll.textContent = errores[campo].join(" ");
    }
  });
}

function procederAlPago() {
  if (urlPagoMercadoPago) {
    setStep(3);
    document.getElementById("link-pago-fallback").href = urlPagoMercadoPago;
    window.location.href = urlPagoMercadoPago;
  }
}

// --- FLUJO NAVEGACIONAL ---
function setStep(n) {
  [1, 2, 3].forEach(i => {
    const pasoEl = document.getElementById(`paso-${i}`);
    if (pasoEl) pasoEl.classList.toggle("hidden", i !== n);
    const dot = document.getElementById(`dot-${i}`);
    if (dot) {
      dot.classList.toggle("active", i === n);
      dot.classList.toggle("done", i < n);
    }
  });
}

function volverPaso1() { setStep(1); }

function reiniciarTodo() {
  Object.keys(inventarioCantidades).forEach(k => {
    inventarioCantidades[k] = 0;
    const cantEl = document.getElementById(`cant-${k}`);
    if (cantEl) cantEl.textContent = 0;
  });
  document.getElementById("origen").value = "";
  document.getElementById("destino").value = "";
  document.getElementById("origen_calle").value = "";
  document.getElementById("origen_numero").value = "";
  document.getElementById("origen_localidad").value = "";
  document.getElementById("destino_calle").value = "";
  document.getElementById("destino_numero").value = "";
  document.getElementById("destino_localidad").value = "";
  document.getElementById("distancia_km").value = "";
  document.getElementById("nombre").value = "";
  document.getElementById("telefono").value = "";
  document.getElementById("email").value = "";
  document.getElementById("notas").value = "";

  fechaSeleccionada = null;
  horaSeleccionada = null;
  urlPagoMercadoPago = null;

  const seccionHorarios = document.getElementById("seccion-horarios");
  if (seccionHorarios) seccionHorarios.style.display = "none";
  document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("selected"));

  actualizarCamionVisual();
  validarFormularioCompleto();
  setStep(1);
}