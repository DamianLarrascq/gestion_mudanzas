# SGM — Sistema de Gestión de Mudanzas

Sistema web full-stack para la gestión integral de una empresa de mudanzas. Cubre todo el ciclo de vida de una mudanza: desde la cotización automática del cliente vía landing page o chatbot de WhatsApp, pasando por la coordinación de flota y personal, hasta el cobro de la seña mediante pasarela de pagos y las notificaciones automáticas por WhatsApp.

---

## Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python / Django |
| Base de datos | SQLite (dev) / PostgreSQL (prod) |
| Tareas asíncronas | Celery + Redis |
| Mensajería | Twilio WhatsApp API |
| Geocodificación | Nominatim (OpenStreetMap) |
| Pagos | Mercado Pago (Checkout Pro) |
| Análisis de seguridad | CodeQL |

---

## Arquitectura — Flujo Simplificado

```
Cliente (browser)
      │
      │  HTTP request
      ▼
┌─────────────┐        ┌──────────────────┐
│   Django    │──ORM──▶│  SQLite / Postgres│
│  (web app)  │        └──────────────────┘
└──────┬──────┘
       │  .delay()          ┌─────────────────────┐
       ▼                    │                     │
┌─────────────┐   tareas   │       Redis         │
│   Celery    │◀──────────▶│  (message broker)   │
│  (worker)   │            │                     │
└──────┬──────┘            └─────────────────────┘
       │
       │  SDK
       ▼
┌─────────────────────┐     ┌──────────────────────┐
│  Twilio WhatsApp    │     │  Mercado Pago API     │
│  (notificaciones    │     │  (seña + pago final)  │
│   y chatbot)        │     └──────────────────────┘
└─────────────────────┘

Nominatim (OSM) ←── llamada desde el frontend (JS)
para geocodificar direcciones y calcular distancia (Haversine)
```

**Flujo de una cotización:**

1. El cliente completa el formulario público → el frontend consulta Nominatim para obtener coordenadas y calcula la distancia con Haversine.
2. Django recibe la distancia, calcula el presupuesto contra la tarifa vigente y genera el link de pago de Mercado Pago.
3. Se encola una tarea en Redis → el worker de Celery la ejecuta y envía el presupuesto al cliente por WhatsApp vía Twilio.
4. Al confirmar el pago, Mercado Pago notifica via webhook → Django actualiza el estado de la mudanza automáticamente.

---

## Instalación y Ejecución

### Requisitos previos

- Python 3.11+
- Redis (via Docker o instalación local)
- Git

---

### 1. Clonar el repositorio

```bash
git clone https://github.com/DamianLarrascq/gestion_mudanzas
cd gestion_mudanzas
```

### 2. Crear y activar el entorno virtual

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con las credenciales reales:

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Base de datos (desarrollo usa SQLite por defecto)
# DATABASE_URL=postgresql://user:password@localhost:5432/sgm_db

# Redis / Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Twilio (WhatsApp)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=join ring-eat
TWILIO_WHATSAPP_NUMBER=whatsapp:+1 586 238 1803

# Mercado Pago
MP_ACCESS_TOKEN=TEST-xxxxxxxxxxxx

# Nominatim no requiere API key (instancia pública de OSM)
# Para uso en producción con alto volumen, configurar instancia propia:
# NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org
```

### 5. Correr las migraciones

```bash
python manage.py migrate
python manage.py createsuperuser   # crear usuario administrador
```

### 6. Levantar los servicios

Necesitás **tres terminales** corriendo en paralelo:

**Terminal 1 — Redis** (requiere Docker(produccion)):
```bash
docker run -d -p 6379:6379 --name redis-sgm redis:7-alpine
```

**Terminal 2 — Worker de Celery**:
```bash
celery -A config worker --loglevel=info --concurrency=1
```

**Terminal 3 — Servidor Django**:
```bash
python manage.py runserver
```

El panel de administración queda disponible en: http://127.0.0.1:8000/admin/

> **Webhooks en desarrollo:** para recibir notificaciones de Twilio y Mercado Pago en local, exponer el servidor con [ngrok](https://ngrok.com/):
> ```bash
> ngrok http 8000
> ```
> Configurar la URL generada en Twilio Console y en Mercado Pago como endpoint de webhook.

### 7. Correr los tests

```bash
python manage.py test tests/
```

---

## Autores

| Nombre | GitHub |
|---|---|
| Damián Larrascq | [@DamianLarrascq](https://github.com/DamianLarrascq) |
| Solange Cruz | [@Solange-Cruz](https://github.com/Solange-Cruz) |
| Federico Piquero | [@FedePiquero](https://github.com/FedePiquero) |
| Giuliana Cristaldo | [@Giuliana222](https://github.com/Giuliana222) |
| Brandon Busche | [@Brandonrbusche](https://github.com/Brandonrbusche) |
| Sebastian Prieto | [@Index2003](https://github.com/Index2003) |
