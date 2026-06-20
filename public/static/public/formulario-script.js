// --- MOTOR MAPAS (TomTom Search API + OSRM Routing) ---
const TOMTOM_API_KEY = 'I3DX7QtpmRRXVyijA67Bh6gvPPt5phYO';
let coordenadas = { origen: null, destino: null };

document.addEventListener('DOMContentLoaded', () => {
  configurarAutocompletado('origen', 'sug-origen');
  configurarAutocompletado('destino', 'sug-destino');
  
  // Generar calendario de reservas
  generarDiasHabiles();

  // Escuchar inputs para validar el botón de reserva final
  document.getElementById("nombre").addEventListener("input", validarBotonReserva);
  document.getElementById("telefono").addEventListener("input", validarBotonReserva);
});

function configurarAutocompletado(inputId, sugerenciasId) {
  const input = document.getElementById(inputId);
  const container = document.getElementById(sugerenciasId);
  let timeout = null;

  input.addEventListener('input', () => {
    coordenadas[inputId] = null; // Reseteamos la coordenada si el usuario escribe
    clearTimeout(timeout);
    const query = input.value.trim();

    if (query.length < 4) {
      container.classList.add('hidden');
      return;
    }

    timeout = setTimeout(() => {
      // Usamos la API de TomTom filtrando solo para Argentina (AR)
      const url = `https://api.tomtom.com/search/2/geocode/${encodeURIComponent(query)}.json?key=${TOMTOM_API_KEY}&countrySet=AR&limit=5`;

      fetch(url)
        .then(res => res.json())
        .then(data => {
          container.innerHTML = '';
          
          if (!data.results || data.results.length === 0) {
            container.classList.add('hidden');
            return;
          }

          data.results.forEach(f => {
            // TomTom devuelve la dirección formateada en 'freeformAddress'
            const nombre = f.address.freeformAddress;
            const div = document.createElement('div');
            div.className = 'sugerencia-item';
            div.textContent = nombre;
            
            div.addEventListener('click', () => {
              input.value = nombre;
              container.classList.add('hidden');
              // Guardamos la latitud y longitud que nos da TomTom
              coordenadas[inputId] = [f.position.lat, f.position.lon];
              calcularRutaGratis();
            });
            
            container.appendChild(div);
          });
          container.classList.remove('hidden');
        })
        .catch(err => console.error('Error en la búsqueda de dirección con TomTom:', err));
    }, 500);
  });

  document.addEventListener('click', (e) => {
    if (e.target !== input) container.classList.add('hidden');
  });
}

function calcularRutaGratis() {
  if (coordenadas.origen && coordenadas.destino) {
    const locOrigen = `${coordenadas.origen[1]},${coordenadas.origen[0]}`;
    const locDestino = `${coordenadas.destino[1]},${coordenadas.destino[0]}`;
    
    const url = `https://router.project-osrm.org/route/v1/driving/${locOrigen};${locDestino}?overview=false`;

    fetch(url)
      .then(res => res.json())
      .then(data => {
        if (data.code === 'Ok' && data.routes.length > 0) {
          const distanciaMetros = data.routes[0].distance;
          const distanciaKm = (distanciaMetros / 1000).toFixed(1);
          
          const inputDistancia = document.getElementById('distancia_km');
          inputDistancia.value = distanciaKm;
          
          inputDistancia.style.transition = 'border-color 0.3s';
          inputDistancia.style.borderColor = 'var(--success)';
          setTimeout(() => {
            inputDistancia.style.borderColor = 'var(--border)';
          }, 1500);
        }
      })
      .catch(err => console.error('Error al calcular distancia con OSRM:', err));
  }
}
// ---------------------------------------------------

// --- LÓGICA DEL INVENTARIO Y CAMIÓN ---
const volumesMuebles = {
  Heladera: 1.20, Lavarropas: 0.50, Cama: 1.60,
  Sofa: 1.50, Mesa: 0.90, Ropero: 1.00
};

let inventarioCantidades = {
  Heladera: 0, Lavarropas: 0, Cama: 0,
  Sofa: 0, Mesa: 0, Ropero: 0
};

function alterarMueble(id, cambio) {
  let nuevaCant = inventarioCantidades[id] + cambio;
  if (nuevaCant < 0) return;
  
  inventarioCantidades[id] = nuevaCant;
  document.getElementById(`cant-${id}`).textContent = nuevaCant;
  actualizarCamionVisual();
}

function actualizarCamionVisual() {
  const caja = document.getElementById("camion-caja-items");
  const tipoTag = document.getElementById("camion-tipo");
  const lblBultos = document.getElementById("metrica-bultos");
  const lblVolumen = document.getElementById("metrica-volumen");
  const svgCaja = document.getElementById("svg-caja-carga");
  const svgCamion = document.getElementById("camion-dibujo");
  
  caja.innerHTML = "";
  let totalBultos = 0;
  let totalVolumen = 0;
  
  Object.keys(inventarioCantidades).forEach(key => {
    let cant = inventarioCantidades[key];
    totalBultos += cant;
    totalVolumen += cant * volumesMuebles[key];
    
    if(cant > 0) {
      const itemNode = document.createElement("div");
      itemNode.className = "item-en-camion";
      itemNode.innerHTML = `<span>${key}</span> <strong>x${cant}</strong>`;
      caja.appendChild(itemNode);
    }
  });

  lblBultos.textContent = totalBultos;
  lblVolumen.textContent = totalVolumen.toFixed(2) + " m³";

  if (totalBultos === 0) {
    caja.innerHTML = `<div class="caja-vacia-msg">Sin bultos seleccionados.</div>`;
    tipoTag.textContent = "Vehículo Requerido: Ninguno";
    tipoTag.style.background = "var(--ink-3)";
    svgCaja.setAttribute("width", "40"); svgCaja.setAttribute("x", "70"); svgCaja.setAttribute("y", "30"); svgCaja.setAttribute("height", "25"); svgCaja.setAttribute("fill", "#cbd5e1");
    svgCamion.style.transform = "scale(1)";
  } 
  else if (totalVolumen <= 3.0) {
    tipoTag.textContent = "Vehículo Recomendado: Utilitario (Furgón)";
    tipoTag.style.background = "#1a5fcc"; 
    svgCaja.setAttribute("width", "55"); svgCaja.setAttribute("x", "55"); svgCaja.setAttribute("y", "26"); svgCaja.setAttribute("height", "29"); svgCaja.setAttribute("fill", "#93c5fd");
    svgCamion.style.transform = "scale(1.05)";
  } 
  else if (totalVolumen <= 8.0) {
    tipoTag.textContent = "Vehículo Recomendado: Camión Ligero";
    tipoTag.style.background = "#166534";
    svgCaja.setAttribute("width", "75"); svgCaja.setAttribute("x", "35"); svgCaja.setAttribute("y", "22"); svgCaja.setAttribute("height", "33"); svgCaja.setAttribute("fill", "#86efac");
    svgCamion.style.transform = "scale(1.15)";
  } 
  else {
    tipoTag.textContent = "Vehículo Recomendado: Camión de Gran Porte";
    tipoTag.style.background = "#991b1b";
    svgCaja.setAttribute("width", "90"); svgCaja.setAttribute("x", "20"); svgCaja.setAttribute("y", "15"); svgCaja.setAttribute("height", "40"); svgCaja.setAttribute("fill", "#fca5a5");
    svgCamion.style.transform = "scale(1.25)";
  }
}

function calcularPresupuesto() {
  const km = parseFloat(document.getElementById("distancia_km").value) || 0;
  
  let volTotal = 0; let bultosTotal = 0;
  Object.keys(inventarioCantidades).forEach(k => {
    bultosTotal += inventarioCantidades[k];
    volTotal += inventarioCantidades[k] * volumesMuebles[k];
  });

  if (!coordenadas.origen || !coordenadas.destino) return alert("Por favor, buscá y seleccioná una dirección válida de la lista sugerida para el origen y el destino.");
  if (bultosTotal === 0) return alert("Por favor, seleccioná al menos un artículo para transportar.");

  let tarifaBaseVehiculo = 0; 
  if(volTotal > 0 && volTotal <= 3) tarifaBaseVehiculo = 25000;
  else if(volTotal > 3 && volTotal <= 8) tarifaBaseVehiculo = 45000;
  else if(volTotal > 8) tarifaBaseVehiculo = 70000;

  const costoPorKm = km * 400;
  const subtotal = tarifaBaseVehiculo + costoPorKm;
  const iva = subtotal * 0.21;
  const total = subtotal + iva;

  const fmt = n => "$ " + Math.round(n).toLocaleString("es-AR");

  document.getElementById("lineas-presupuesto").innerHTML = `
    <div class="linea-item"><span>Asignación de vehículo base</span><span class="linea-monto">${fmt(tarifaBaseVehiculo)}</span></div>
    <div class="linea-item"><span>Kilometraje en ruta (${km} km)</span><span class="linea-monto">${fmt(costoPorKm)}</span></div>
    <div class="linea-item"><span>Cubicaje total estimado (${volTotal.toFixed(2)} m³)</span><span class="linea-monto cero">—</span></div>
  `;
  document.getElementById("val-subtotal").textContent = fmt(subtotal);
  document.getElementById("val-iva").textContent = fmt(iva);
  document.getElementById("val-total").textContent = fmt(total);

  document.getElementById("resumen-datos").innerHTML = `
    <div class="resumen-item"><div class="resumen-label">Métricas de carga</div><div class="resumen-value">${bultosTotal} artículos / ${volTotal.toFixed(2)} m³</div></div>
    <div class="resumen-item"><div class="resumen-label">Ruta</div><div class="resumen-value">${km} KM</div></div>
  `;
  setStep(2);
}

// --- NAVEGACIÓN Y FLUJO ---
function setStep(n) {
  [1,2,3].forEach(i => {
    document.getElementById(`paso-${i}`).classList.toggle("hidden", i !== n);
    const dot = document.getElementById(`dot-${i}`);
    if(dot) {
      dot.classList.toggle("active", i === n);
      dot.classList.toggle("done", i < n);
    }
  });
}

function volverPaso1() { setStep(1); }
function volverPaso2() { setStep(2); }

function irAReserva() {
  setStep(3);
  document.getElementById("reserva-card").classList.remove("hidden");
  document.getElementById("mensaje-final").classList.add("hidden");
}

function cancelarMudanza() {
  setStep(3);
  document.getElementById("reserva-card").classList.add("hidden");
  document.getElementById("mensaje-final").classList.remove("hidden");
  document.getElementById("resultado-cancelado").classList.remove("hidden");
  document.getElementById("resultado-confirmado").classList.add("hidden");
}

// --- LÓGICA DEL CALENDARIO Y RESERVAS ---
const horariosBase = ["08:00", "10:00", "13:00", "15:00"];
let fechaSeleccionada = null;
let horaSeleccionada = null;
let reservasGuardadas = JSON.parse(localStorage.getItem('gdm_reservas')) || {};

function generarDiasHabiles() {
  const contenedorDias = document.getElementById("calendario-dias");
  contenedorDias.innerHTML = "";
  
  let hoy = new Date();
  let diasGenerados = 0;
  let fechaIteradora = new Date(hoy);

  while (diasGenerados < 10) {
    fechaIteradora.setDate(fechaIteradora.getDate() + 1);
    const diaSemana = fechaIteradora.getDay(); 
    if (diaSemana !== 0 && diaSemana !== 6) {
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

  const ocupadosHoy = reservasGuardadas[strFecha] || [];
  if (ocupadosHoy.length >= horariosBase.length) {
    btn.classList.add("disabled"); btn.title = "Sin disponibilidad";
  } else {
    btn.onclick = () => seleccionarDia(btn, strFecha);
  }
  contenedor.appendChild(btn);
}

function seleccionarDia(botonElemento, strFecha) {
  document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("selected"));
  botonElemento.classList.add("selected");
  
  fechaSeleccionada = strFecha;
  horaSeleccionada = null;
  validarBotonReserva();

  document.getElementById("seccion-horarios").style.display = "block";
  generarHorarios(strFecha);
}

function generarHorarios(strFecha) {
  const contenedorHorarios = document.getElementById("grilla-horarios");
  contenedorHorarios.innerHTML = "";
  const ocupadosHoy = reservasGuardadas[strFecha] || [];

  horariosBase.forEach(hora => {
    const btn = document.createElement("div");
    btn.className = "btn-3d btn-hora";
    btn.textContent = hora;

    if (ocupadosHoy.includes(hora)) {
      btn.classList.add("disabled"); btn.textContent += " (Ocupado)";
    } else {
      btn.onclick = () => seleccionarHora(btn, hora);
    }
    contenedorHorarios.appendChild(btn);
  });
}

function seleccionarHora(botonElemento, hora) {
  document.querySelectorAll(".btn-hora").forEach(b => b.classList.remove("selected"));
  botonElemento.classList.add("selected");
  horaSeleccionada = hora;
  validarBotonReserva();
}

function validarBotonReserva() {
  const nombre = document.getElementById("nombre").value.trim();
  const telefono = document.getElementById("telefono").value.trim();
  const btnSubmit = document.getElementById("btn-confirmar-reserva");

  if (nombre !== "" && telefono !== "" && fechaSeleccionada && horaSeleccionada) {
    btnSubmit.disabled = false;
  } else {
    btnSubmit.disabled = true;
  }
}

function procesarReserva() {
  if (!reservasGuardadas[fechaSeleccionada]) reservasGuardadas[fechaSeleccionada] = [];
  reservasGuardadas[fechaSeleccionada].push(horaSeleccionada);
  localStorage.setItem('gdm_reservas', JSON.stringify(reservasGuardadas));

  document.getElementById("reserva-card").classList.add("hidden");
  document.getElementById("mensaje-final").classList.remove("hidden");
  document.getElementById("resultado-confirmado").classList.remove("hidden");
  document.getElementById("resultado-cancelado").classList.add("hidden");
}

function reiniciarTodo() {
  // Limpiar Inventario
  Object.keys(inventarioCantidades).forEach(k => { inventarioCantidades[k] = 0; document.getElementById(`cant-${k}`).textContent = 0; });
  // Limpiar Formulario de datos 1
  document.getElementById("origen").value = "";
  document.getElementById("destino").value = "";
  document.getElementById("distancia_km").value = "0";
  document.getElementById("notas").value = "";
  coordenadas = { origen: null, destino: null };
  // Limpiar Formulario de Reserva (Paso 3)
  document.getElementById("nombre").value = "";
  document.getElementById("telefono").value = "";
  document.getElementById("email").value = "";
  fechaSeleccionada = null;
  horaSeleccionada = null;
  document.getElementById("seccion-horarios").style.display = "none";
  document.getElementById("grilla-horarios").innerHTML = "";
  document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("selected"));
  
  // Re-iniciar vistas
  actualizarCamionVisual();
  generarDiasHabiles(); 
  validarBotonReserva();
  
  // Ocultar mensajes y restaurar forms
  document.getElementById("mensaje-final").classList.add("hidden");
  document.getElementById("resultado-confirmado").classList.add("hidden");
  document.getElementById("resultado-cancelado").classList.add("hidden");
  
  setStep(1);
}