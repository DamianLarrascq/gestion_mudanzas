# notificaciones/tasks.py
"""
Tareas Celery para automatización de mensajes WhatsApp.

Flujos cubiertos:
  1. seguimiento_post_formulario  — ETA de ~4hs tras crear presupuesto
  2. enviar_recordatorio_24h_pendientes — beat cada 15 min, ventana ±15 min a 24hs
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────────

# Ventana de detección para el beat de 24hs:
# Buscamos mudanzas cuya fecha_hora esté entre 23h45 y 24h15 desde ahora.
_VENTANA_MINUTOS = 15


# ── Tarea 1: Seguimiento post-formulario ──────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 min entre reintentos
    name="notificaciones.tasks.enviar_seguimiento_post_formulario",
)
def enviar_seguimiento_post_formulario(self, mudanza_id: int) -> str:
    """
    Enviada con ETA de ~4hs tras la creación del presupuesto.

    Condiciones de envío (todas deben cumplirse):
      - Mudanza existe y está en estado PRESUPUESTADA
      - senia_pagada = False
      - notificacion_seguimiento_enviada = False

    La idempotencia está garantizada por el flag + select_for_update
    dentro del atomic block.
    """
    from gestion.models.mudanzas import Mudanza

    try:
        # select_for_update evita race condition si la tarea se ejecuta en paralelo
        with transaction.atomic():
            try:
                mudanza = (
                    Mudanza.objects
                    .select_related("cliente", "origen", "destino")
                    .select_for_update()
                    .get(pk=mudanza_id)
                )
            except Mudanza.DoesNotExist:
                logger.warning(
                    "[seguimiento] Mudanza #%s no encontrada — abortando.", mudanza_id
                )
                return "SKIP: mudanza no encontrada"

            # ── Verificar condiciones ──────────────────────────────────────
            if mudanza.estado != Mudanza.Estado.PRESUPUESTADA:
                logger.info(
                    "[seguimiento] Mudanza #%s en estado=%s — sin acción.",
                    mudanza_id, mudanza.estado,
                )
                return f"SKIP: estado={mudanza.estado}"

            if mudanza.senia_pagada:
                logger.info(
                    "[seguimiento] Mudanza #%s ya tiene seña pagada — sin acción.", mudanza_id
                )
                return "SKIP: seña pagada"

            if mudanza.notificacion_seguimiento_enviada:
                logger.info(
                    "[seguimiento] Mudanza #%s ya recibió notificación de seguimiento.", mudanza_id
                )
                return "SKIP: ya enviado"

            # ── Armar mensaje ──────────────────────────────────────────────
            origen_label = mudanza.origen.localidad if mudanza.origen else "origen"
            destino_label = mudanza.destino.localidad if mudanza.destino else "destino"

            mensaje = (
                f"¡Hola de nuevo! Notamos que ya tenés tu presupuesto listo "
                f"para la mudanza de {origen_label} a {destino_label}. 📦\n\n"
                f"Recordá que podés congelar el precio y asegurar tu lugar "
                f"reservando con una seña mínima a través de Mercado Pago.\n\n"
                f"¿Tenés alguna duda con el presupuesto? Si preferís hablar "
                f"con un operador, escribí 'operador' y te derivamos."
            )

            # ── Enviar ─────────────────────────────────────────────────────
            _enviar_whatsapp(mudanza.cliente.telefono, mensaje)

            # ── Marcar como enviado (dentro del atomic) ────────────────────
            Mudanza.objects.filter(pk=mudanza_id).update(
                notificacion_seguimiento_enviada=True
            )
            _registrar_notificacion(mudanza, tipo="SEGUIMIENTO", mensaje=mensaje)

    except Exception as exc:
        logger.exception(
            "[seguimiento] Error en mudanza #%s: %s — reintentando.", mudanza_id, exc
        )
        raise self.retry(exc=exc)

    logger.info("[seguimiento] Enviado a Mudanza #%s.", mudanza_id)
    return "OK"


# ── Tarea 2: Recordatorio 24hs antes ─────────────────────────────────────

@shared_task(
    name="notificaciones.tasks.enviar_recordatorio_24h_pendientes",
)
def enviar_recordatorio_24h_pendientes() -> str:
    """
    Ejecutada por celery-beat cada 15 minutos.

    Busca mudanzas CONFIRMADAS cuya fecha_hora esté en la ventana
    [ahora + 23h45, ahora + 24h15] y que no hayan recibido el recordatorio.

    Despacha una subtarea por mudanza para aislar fallos.
    """
    ahora = timezone.now()
    desde = ahora + timedelta(hours=24) - timedelta(minutes=_VENTANA_MINUTOS)
    hasta = ahora + timedelta(hours=24) + timedelta(minutes=_VENTANA_MINUTOS)

    from gestion.models.mudanzas import Mudanza

    pendientes = Mudanza.objects.filter(
        estado=Mudanza.Estado.CONFIRMADA,
        fecha_hora__gte=desde,
        fecha_hora__lte=hasta,
        notificacion_24h_enviada=False,
    ).values_list("pk", flat=True)

    ids = list(pendientes)

    if not ids:
        logger.debug("[recordatorio-24h] Ninguna mudanza en ventana.")
        return "OK: 0 mudanzas"

    logger.info("[recordatorio-24h] Despachando recordatorio para %d mudanza(s): %s", len(ids), ids)

    for mudanza_id in ids:
        enviar_recordatorio_24h.delay(mudanza_id)

    return f"OK: {len(ids)} mudanzas despachadas"


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    name="notificaciones.tasks.enviar_recordatorio_24h",
)
def enviar_recordatorio_24h(self, mudanza_id: int) -> str:
    """
    Envía el recordatorio a una mudanza individual.
    Separado del beat para aislar fallos por mudanza.
    """
    from gestion.models.mudanzas import Mudanza

    try:
        with transaction.atomic():
            try:
                mudanza = (
                    Mudanza.objects
                    .select_related("cliente", "origen")
                    .select_for_update()
                    .get(pk=mudanza_id)
                )
            except Mudanza.DoesNotExist:
                logger.warning("[recordatorio-24h] Mudanza #%s no encontrada.", mudanza_id)
                return "SKIP: no encontrada"

            # Doble check dentro del atomic (otro worker pudo haberla procesado)
            if mudanza.notificacion_24h_enviada:
                return "SKIP: ya enviado"

            if mudanza.estado != Mudanza.Estado.CONFIRMADA:
                logger.info(
                    "[recordatorio-24h] Mudanza #%s ya no está CONFIRMADA (estado=%s).",
                    mudanza_id, mudanza.estado,
                )
                return f"SKIP: estado={mudanza.estado}"

            # ── Armar mensaje ──────────────────────────────────────────────
            nombre = mudanza.cliente.nombre_completo.split()[0]  # primer nombre
            hora_display = timezone.localtime(mudanza.fecha_hora).strftime("%H:%M")
            origen_label = (
                f"{mudanza.origen.calle} {mudanza.origen.numero}, {mudanza.origen.localidad}"
                if mudanza.origen else "el domicilio acordado"
            )

            mensaje = (
                f"¡Hola, {nombre}! Mañana es el gran día de tu mudanza. 🚚\n\n"
                f"Nuestro equipo estará en {origen_label} a las {hora_display}. "
                f"Por favor, asegurate de tener los bultos preparados y acceso "
                f"habilitado para el camión.\n\n"
                f"¡Cualquier eventualidad, escribinos por acá!"
            )

            # ── Enviar ─────────────────────────────────────────────────────
            _enviar_whatsapp(mudanza.cliente.telefono, mensaje)

            # ── Marcar como enviado ────────────────────────────────────────
            Mudanza.objects.filter(pk=mudanza_id).update(
                notificacion_24h_enviada=True
            )
            _registrar_notificacion(mudanza, tipo="RECORDATORIO", mensaje=mensaje)

    except Exception as exc:
        logger.exception("[recordatorio-24h] Error en mudanza #%s: %s", mudanza_id, exc)
        raise self.retry(exc=exc)

    logger.info("[recordatorio-24h] Enviado a Mudanza #%s.", mudanza_id)
    return "OK"


# ── Helpers privados ──────────────────────────────────────────────────────

def _enviar_whatsapp(telefono: str, mensaje: str) -> None:
    """
    Delega al envío real vía Twilio, importando la función ya existente
    en webhook/views.py para no duplicar lógica.

    Si en el futuro se extrae _enviar_mensaje_whatsapp a un módulo
    compartido (ej. notificaciones/senders.py), cambiar el import aquí.
    """
    try:
        from webhook.views import _enviar_mensaje_whatsapp
        _enviar_mensaje_whatsapp(telefono, mensaje)
    except Exception:
        logger.exception("Error enviando WhatsApp a %s.", telefono)
        raise  # propagar para que Celery gestione el reintento


def _registrar_notificacion(mudanza, tipo: str, mensaje: str) -> None:
    """
    Persiste el envío en el log de Notificacion.
    No lanza excepción si falla — el envío ya ocurrió.
    """
    from gestion.models.notificaciones import Notificacion  # ajustar import según estructura real

    _TIPO_MAP = {
        "SEGUIMIENTO": Notificacion.Tipo.RECORDATORIO,  # reutilizar tipo existente
        "RECORDATORIO": Notificacion.Tipo.RECORDATORIO,
    }

    try:
        Notificacion.objects.create(
            mudanza=mudanza,
            tipo=_TIPO_MAP.get(tipo, Notificacion.Tipo.RECORDATORIO),
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=mudanza.cliente.telefono,
            enviada=True,
            enviada_en=timezone.now(),
            error="",
        )
    except Exception:
        logger.exception(
            "No se pudo registrar Notificacion para Mudanza #%s.", mudanza.pk
        )
