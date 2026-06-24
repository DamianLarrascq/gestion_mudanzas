from __future__ import annotations
import mercadopago
import os
from dataclasses import dataclass
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from gestion.models.mudanzas import Mudanza

def _get_sdk() -> mercadopago.SDK:
    token = getattr(settings, "TEST_ACCESS_TOKEN", None)
    if not token:
        raise ImproperlyConfigured(
            "MERCADOPAGO_ACCESS_TOKEN no esta configurado en settings."
        )
    return mercadopago.SDK(token)


@dataclass
class DatoPago:
    """
    Representación genérica de un cobro.
    Desacopla MercadoPagoService de la instancia Mudanza,
    permitiendo usarlo desde cualquier flujo (landing, panel admin, etc).
    """
    uuid: str
    titulo: str
    monto: Decimal
    metadata: dict


class MercadoPagoService:

    @staticmethod
    def generar_preferencia_pago(mudanza: Mudanza) -> str:
        """
        Crea o recrea la preferencia de Checkout Pro para una Mudanza.
        Mantiene la firma original — sin cambios para el resto del sistema.

        Args:
            mudanza: Instancia con monto_senia definido y uuid disponible.

        Returns:
            init_point (URL de pago) listo para el botón del frontend.

        Raises:
            ValueError:            Si monto_senia es None o <= 0.
            ImproperlyConfigured:  Si falta MERCADOPAGO_ACCESS_TOKEN.
            RuntimeError:          Si MercadoPago devuelve un error.
        """
        if not mudanza.monto_senia or mudanza.monto_senia <= 0:
            raise ValueError(
                f"La mudanza #{mudanza.pk} no tiene monto_senia definido."
            )

        dato = DatoPago(
            uuid=str(mudanza.uuid),
            titulo=f"Seña Mudanza #{mudanza.pk}",
            monto=mudanza.monto_senia,
            metadata={
                "mudanza_id": mudanza.pk,
                "mudanza_uuid": str(mudanza.uuid),
            },
        )
        return MercadoPagoService._crear_preferencia(dato, guardar_en=mudanza)

    @staticmethod
    def generar_preferencia_desde_dato(dato: DatoPago, guardar_en=None) -> str:
        """
        Versión genérica: usada por flujos que no tienen una Mudanza todavía
        (ej: landing pública antes de confirmar el pago).

        Args:
            dato:       Datos del cobro.
            guardar_en: Instancia con campo mp_preference_id a actualizar, o None.

        Returns:
            init_point URL.

        Raises:
            ValueError:           Si monto es None o <= 0.
            ImproperlyConfigured: Si falta MERCADOPAGO_ACCESS_TOKEN.
            RuntimeError:         Si MercadoPago devuelve un error.
        """
        return MercadoPagoService._crear_preferencia(dato, guardar_en=guardar_en)

    @staticmethod
    def _crear_preferencia(dato: DatoPago, guardar_en=None) -> str:
        """
        Lógica central de creación de preferencia MP.
        No debe llamarse directamente desde fuera de esta clase.
        """
        if not dato.monto or dato.monto <= 0:
            raise ValueError(f"Monto inválido para preferencia MP: {dato.monto}")

        sdk = _get_sdk()
        base_url = settings.SITE_BASE_URL.rstrip("/")

        preference_data = {
            "items": [
                {
                    "id": dato.uuid,
                    "title": dato.titulo,
                    "quantity": 1,
                    "unit_price": float(dato.monto),
                    "currency_id": "ARS",
                }
            ],
            "external_reference": dato.uuid,
            "back_urls": {
                "success": f"{base_url}/webhook/mp/success/",
                "failure": f"{base_url}/webhook/mp/failure/",
                "pending": f"{base_url}/webhook/mp/pending/",
            },
            "auto_return": "approved",
            "notification_url": f"{base_url}/webhook/mp/notificacion/",
            "metadata": dato.metadata,
        }

        response = sdk.preference().create(preference_data)

        if response["status"] not in (200, 201):
            raise RuntimeError(
                f"MercadoPago error {response['status']}: "
                f"{response.get('response', {})}"
            )

        preference = response["response"]
        preference_id = preference["id"]

        if guardar_en is not None:
            guardar_en.__class__.objects.filter(pk=guardar_en.pk).update(
                mp_preference_id=preference_id
            )
            guardar_en.mp_preference_id = preference_id

        url_key = (
            "sandbox_init_point"
            if getattr(settings, "MERCADOPAGO_SANDBOX", True)
            else "init_point"
        )
        return preference[url_key]
    