from __future__ import annotations
import mercadopago
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from gestion.models.mudanzas import Mudanza

def _get_sdk() -> mercadopago.SDK:
    token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", None)
    if not token:
        raise ImproperlyConfigured(
            'MERCADOPAGO_ACCESS_TOKEN no esta configurado en settings.'
        )
    return mercadopago.SDK(token)

class MercadoPagoService:

    @staticmethod
    def generar_preferencia_pago(mudanza: Mudanza) -> str:
        """
        Crea o recrea la preferencia de Checkout Pro en MercadoPago
        y persiste el 'mp_preference_id' en la mudanza.

        Args:
            mudanza: Instancia con 'monto_senia' ya definido y 'uuid' disponible.

        Returns:
            'init_point' (URL de pago) listo para el boton del frontend.

        Raises:
            ValueError: Si 'monto_senia' es None o <= 0.
            ImproperlyConfigured: Si falta el ACCESS_TOKEN.
            RuntimeError: Si MercadoPago devuelve un error.
        """
        if not mudanza.monto_senia or mudanza.monto_senia <= 0:
            raise ValueError(
                f"La mudanza #{mudanza.pk} no tiene monto_senia definido."
            )

        sdk = _get_sdk()
        base_url = settings.SITE_BASE_URL.rstrip("/")  # ej: "https://tudominio.com"

        preference_data = {
            "items": [
                {
                    "id": str(mudanza.uuid),
                    "title": f"Seña Mudanza #{mudanza.pk}",
                    "quantity": 1,
                    "unit_price": float(mudanza.monto_senia),
                    "currency_id": "ARS",
                }
            ],
            "external_reference": str(mudanza.uuid),
            "back_urls": {
                "success": f"{base_url}/webhook/mp/success/",
                "failure": f"{base_url}/webhook/mp/failure/",
                "pending": f"{base_url}/webhook/mp/pending/",
            },
            "auto_return": "approved",
            "notification_url": f"{base_url}/webhook/mp/notificacion/",
            "metadata": {
                "mudanza_id": mudanza.pk,
                "mudanza_uuid": str(mudanza.uuid),
            },
        }

        response = sdk.preference().create(preference_data)

        if response["status"] not in (200, 201):
            raise RuntimeError(
                f"MercadoPago error {response['status']}: "
                f"{response.get('response', {})}"
            )

        preference = response["response"]
        mp_preference_id = preference["id"]

        # Persiste sin tocar otros campos
        Mudanza.objects.filter(pk=mudanza.pk).update(
            mp_preference_id=mp_preference_id
        )
        mudanza.mp_preference_id = mp_preference_id

        # En sandbox usar sandbox_init_point; en producción init_point
        url_key = (
            "sandbox_init_point"
            if getattr(settings, "MERCADOPAGO_SANDBOX", True)
            else "init_point"
        )
        return preference[url_key]