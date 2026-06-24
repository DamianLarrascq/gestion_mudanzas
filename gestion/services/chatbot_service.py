"""
Manejador de flujos del chatbot basado en guion estructurado.

Principios:
- Sin IA ni NLP externo: Toda la logica es determinista y basada en el guion.
- Sin dependencias HTTP: se invoca desde cualquier capa (webhook, API REST, Celery).
- Links externos se leen exclusivamente de settings para evitar hardcodeo.
- Toda interaccion queda auditada en MensajeChatbot.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from idlelib.squeezer import count_lines_with_wrapping
from typing import Sequence
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from gestion.models.chatbot import MensajeChatbot, SesionChatbot

# Constantes de deteccion

_TRIGGER_LANDING: str = 'Hola, quiero pedir un presupuesto para una mudanza.'
_TRIGGER_OPERADOR: frozenset[str] = frozenset({'...', 'operador', 'persona', 'humano'})


# DTOs

@dataclass(frozen=True)
class ResultadoChatbot:
    """
    Respuesta que la capa de transporte (webhook, API) debe enviar al usuario.

    Atributos:
        mensajes: Lista ordenada de textos a enviar (uno por burbuja).
        atencion_manual: True si esta interaccion derivo a un operador.
        flujo: Nombre del flujo ejecutado (util para logging externo)
    """

    mensajes: list[str]
    atencion_manual: bool
    flujo: str


# Helpers de acceso a settings

def _url_formulario() -> str:
    url = getattr(settings, 'CHATBOT_URL_FORMULARIO', None)
    if not url:
        raise ImproperlyConfiguredChatbot(
            "CHATBOT_URL_FORMULARIO no esta definida en settings,"
        )
    return url


def _url_web_principal() -> str:
    url = getattr(settings, 'CHATBOT_URL_WEB_PRINCIPAL', None)
    if not url:
        raise ImproperlyConfiguredChatbot(
            'CHATBOT_URL_WEB_PRINCIPAL no esta definida en settings.'
        )
    return url


def _nombre_empresa() -> str:
    return getattr(settings, 'CHATBOT_NOMBRE_EMPRESA', 'Empresa de Mudanzas')


def _nombre_bot() -> str:
    return getattr(settings, 'CHATBOT_NOMBRE_BOT', 'Asistente Virtual')


# Excepcion propia

class ImproperlyConfiguredChatbot(Exception):
    """
    Lanzada cuando falta configuracion obligatoria en settings.
    """


# Constructores de flujos (retornan listas de strings)

def _flujo_landing() -> list[str]:
    empresa = _nombre_empresa()
    bot = _nombre_bot()
    formulario = _url_formulario()

    return [
        f"¡Hola! Bienvenido a {empresa}. 🚚 Soy {bot}, tu asistente virtual. "
        "Te ayudaré a obtener tu presupuesto al instante.",
        "Para darte un precio exacto, necesito que completes un breve formulario "
        "con las direcciones y los muebles a trasladar.",
        f"👉 Comenzar cotización aquí: {formulario}",
        "¡Un detalle importante! Una vez que tengas tu presupuesto, podés reservar "
        "tu fecha con una seña mínima a través de Mercado Pago. Esto nos permite "
        "asegurarte el camión y el equipo de ayudantes solo para vos ese día.",
        "Tené en cuenta que, para poder cumplir con todos nuestros clientes, si el "
        "servicio se cancela o se pospone, la seña se utiliza para cubrir los costos "
        "operativos de la reserva. ¡Así nos organizamos mejor entre todos!",
        "Si preferís charlar con alguien del equipo, solo escribí '...' y te damos "
        "una mano personalmente.",
    ]


def _flujo_general() -> list[str]:
    empresa = _nombre_empresa()
    formulario = _url_formulario()

    return [
        f"¡Hola! Qué bueno que nos contactes. En {empresa} calculamos tu presupuesto "
        "de forma automática y transparente según la distancia y tu inventario."
        "Contamos con una flota preparada y disponibilidad para que reserves tu fecha "
        "con total seguridad."
        "Hacé clic en el siguiente enlace para cargar tus datos y obtener el costo al instante:"
        f"👉 {formulario}",
        "Si preferís charlar con alguien del equipo, solo escribí '...' y te damos "
        "una mano personalmente."
        "¡Un detalle importante! Una vez que tengas tu presupuesto, podés reservar "
        "tu fecha con una seña mínima a través de Mercado Pago. Esto nos permite "
        "asegurarte el camión y el equipo de ayudantes solo para vos ese día."
        "Tené en cuenta que, para poder cumplir con todos nuestros clientes, si el "
        "servicio se cancela o se pospone, la seña se utiliza para cubrir los costos "
        "operativos de la reserva. ¡Así nos organizamos mejor entre todos!",
    ]


def _flujo_operador() -> list[str]:
    return [
        "¡Dale! Ya le aviso a uno de los chicos del equipo para que te escriba. "
        "En un ratito están con vos para despejar cualquier duda."
    ]


# Flujos de notificacion proactiva invocados por Celery

def construir_mensajes_seguimiento_post_formulario(
        origen: str,
        destino: str,
) -> list[str]:
    """
    Mensajes para el seguimiento entre 3 y 6 hs despues de completar el formulario sin haber pagado la seña. Invocado desde una tarea Celery, no desde el handler.

    Args:
        origen: Localidad de origen de la mudanza,
        destino" Localidad de destino de la mudanza.
    """

    return [
        f"¡Hola de nuevo! Notamos que ya tenés tu presupuesto listo para la mudanza "
        f"de {origen} a {destino}. 📦",
        "Recordá que podés congelar el precio y asegurar tu lugar reservando con una "
        "seña mínima a través de Mercado Pago.",
        "¿Tenés alguna duda con el presupuesto? Si preferís hablar con un operador, "
        "escribí '...' y te derivamos.",
    ]


def construir_mensajes_recordatorio_24hs(
        nombre_cliente: str,
        direccion_origen: str,
        hora_mudanza: str,
) -> list[str]:
    """
    Recordatorio automático 24hs antes de la mudanza. Invocado desde Celery.

    Args:
        nombre_cliente:   Nombre completo del cliente.
        direccion_origen: Dirección de origen formateada.
        hora_mudanza:     Hora en formato HH:MM.
    """
    return [
        f"¡Hola, {nombre_cliente}! Mañana es el gran día de tu mudanza. 🚚",
        f"Nuestro equipo estará en {direccion_origen} a las {hora_mudanza}. "
        "Por favor, asegurate de tener los bultos preparados y acceso habilitado "
        "para el camión.",
        "¡Cualquier eventualidad, escribinos por acá!",
    ]

def construir_mensaje_confirmacion_pago(
        cliente_nombre: str,
        mudanza_origen: str,
        mudanza_destino: str
) -> list[str]:
    """
    Mensaje enviado al cliente cuando MercadoPago acredita la seña.
    Invocado desde webhook/views.py::_notificar_confirmacion_pago, inmediatamente
    despues de transicionar la mudanza a CONFIRMADA.

    Args:
        cliente_nombre: Nombre completo del cliente.

    """
    primer_nombre = cliente_nombre.split()[0] if cliente_nombre else "Hola"

    return [
        f"¡Gracias, {primer_nombre}! 🎉 Recibimos tu seña y tu mudanza {mudanza_origen} -> {mudanza_destino}"
        "quedó CONFIRMADA.",
        "Ya reservamos el camión y el equipo de ayudantes para tu fecha. Te vamos a "
        "escribir nuevamente 24hs antes con los detalles finales.",
        "Cualquier consulta, respondé este mensaje y te ayudamos.",
    ]


# Deteccion de flujo

def _detectar_flujo(texto: str) -> SesionChatbot.Flujo:
    """
    Determina el flujo a ejectuar segun el texto recibido.
    La comparacion es case-insensitive y elimina espacios extremos.
    """

    texto_normalizado = texto.strip()

    if texto_normalizado == _TRIGGER_LANDING:
        return SesionChatbot.Flujo.LANDING

    return SesionChatbot.Flujo.GENERAL


def _es_trigger_operador(texto: str) -> bool:
    return texto.strip().lower() in _TRIGGER_OPERADOR


# Persistencia

def _registrar_mensajes(
        sesion: SesionChatbot,
        texto_usuario: str,
        respuestas: list[str],
) -> None:
    """
    Persiste el mensaje del usuario y las respuestas del bot en un bulk_create.
    Operacion de auditoria: no debe lanzar excepciones que interrumpan el flujo.
    """
    logs = [
               MensajeChatbot(
                   sesion=sesion,
                   origen=MensajeChatbot.Origen.USUARIO,
                   texto=texto_usuario,
               )
           ] + [
               MensajeChatbot(
                   sesion=sesion,
                   origen=MensajeChatbot.Origen.BOT,
                   texto=msg,
               )
               for msg in respuestas
           ]
    MensajeChatbot.objects.bulk_create(logs)


# API Publica

class ChatbotHandler:
    """
    Punto de entrada único para procesar un mensaje entrante.

    Uso desde webhook de WhatsApp:
        resultado = ChatbotHandler.procesar(
            canal_id="+5491123456789",
            canal=SesionChatbot.Canal.WHATSAPP,
            texto="Hola, quiero pedir un presupuesto para una mudanza.",
        )

    Uso desde API del pop-up web:
        resultado = ChatbotHandler.procesar(
            canal_id=request.session.session_key,
            canal=SesionChatbot.Canal.WEB,
            texto=texto_del_usuario,
        )
    """

    @staticmethod
    def procesar(
            canal_id: str,
            canal: str,
            texto: str,
    ) -> ResultadoChatbot:
        """
        Identifica el flujo, genera las respuestas y persiste la interacción.

        Args:
            canal_id: Identificador único del interlocutor en su canal.
            canal:    SesionChatbot.Canal.WHATSAPP | SesionChatbot.Canal.WEB
            texto:    Texto recibido del usuario, sin procesar.

        Returns:
            ResultadoChatbot con los mensajes a enviar.

        Raises:
            ImproperlyConfiguredChatbot: si faltan URLs en settings.
        """
        with transaction.atomic():
            sesion, _ = SesionChatbot.objects.get_or_create(
                canal_id=canal_id,
                canal=canal,
            )

            # Si el operador ya tomó el hilo, el bot no responde
            if sesion.atencion_manual:
                return ResultadoChatbot(
                    mensajes=[],
                    atencion_manual=True,
                    flujo="SILENCIADO_POR_OPERADOR",
                )

            # Detección de solicitud de operador (tiene precedencia sobre cualquier flujo)
            if _es_trigger_operador(texto):
                sesion.atencion_manual = True
                sesion.save(update_fields=["atencion_manual", "actualizada_en"])

                respuestas = _flujo_operador()
                _registrar_mensajes(sesion, texto, respuestas)

                return ResultadoChatbot(
                    mensajes=respuestas,
                    atencion_manual=True,
                    flujo="OPERADOR",
                )

            # Detección de flujo estándar
            flujo = _detectar_flujo(texto)

            if sesion.flujo_detectado == SesionChatbot.Flujo.DESCONOCIDO:
                sesion.flujo_detectado = flujo
                sesion.save(update_fields=["flujo_detectado", "actualizada_en"])

            if flujo == SesionChatbot.Flujo.LANDING:
                respuestas = _flujo_landing()
            else:
                respuestas = _flujo_general()

            _registrar_mensajes(sesion, texto, respuestas)

        return ResultadoChatbot(
            mensajes=respuestas,
            atencion_manual=False,
            flujo=flujo,
        )
