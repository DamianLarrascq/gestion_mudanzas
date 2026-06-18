// Simulador de correos registrados en base de datos
const correosRegistrados = ["admin@correo.com", "usuario@correo.com"];

// Función para cambiar entre todas las vistas
function toggleView(view) {
    // Ocultamos todas primero
    document.getElementById('login-box').style.display = 'none';
    document.getElementById('register-box').style.display = 'none';
    document.getElementById('forgot-box').style.display = 'none';
    document.getElementById('code-box').style.display = 'none';

    // Mostramos la que pedimos
    document.getElementById(view + '-box').style.display = 'block';

    // Limpiamos errores
    document.getElementById('error-password').style.display = 'none';
    document.getElementById('error-correo').style.display = 'none';
    
    // Si volvemos al login, limpiamos los formularios
    if(view === 'login') {
        document.getElementById('register-form').reset();
        document.getElementById('forgot-correo').value = '';
        document.getElementById('codigo-temp').value = '';
    }
}

// Validación de Registro
function validarRegistro(event) {
    event.preventDefault(); 
    const pass = document.getElementById('reg-password').value;
    const repass = document.getElementById('reg-repassword').value;
    const errorDiv = document.getElementById('error-password');

    errorDiv.style.display = 'none';

    if (pass.length < 8) {
        errorDiv.innerText = "La contraseña debe tener al menos 8 caracteres.";
        errorDiv.style.display = "block";
        return;
    }

    if (pass !== repass) {
        errorDiv.innerText = "Las contraseñas no coinciden. Inténtalo de nuevo.";
        errorDiv.style.display = "block";
        return; 
    }

    alert('¡Usuario creado con éxito!');
    toggleView('login'); 
}

// Validación de Recuperar Contraseña
function validarCorreo(event) {
    event.preventDefault();
    const correoIngresado = document.getElementById('forgot-correo').value;
    const errorDiv = document.getElementById('error-correo');

    // Verificamos si el correo está en nuestra lista de simulador
    if (!correosRegistrados.includes(correoIngresado)) {
        errorDiv.style.display = 'block'; // Mostramos error
    } else {
        errorDiv.style.display = 'none'; // Ocultamos error
        // Mensaje que pediste
        alert("Se te administro el codigo temporal valido por 24 hs para reestrablecer la contraseña.");
        // Pasamos a la ventana del código
        toggleView('code');
    }
}