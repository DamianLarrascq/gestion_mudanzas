from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.core.exceptions import ValidationError
from gestion.models.catalogo import CatalogoItem
from gestion.models.clientes import Cliente
from gestion.models.mudanzas import Mudanza, ItemInventario
from gestion.models.direcciones import Direccion
from gestion.models.presupuestos import Presupuesto
from gestion.services.presupuesto_service import (
    calcular_costos_desde_parametros,
    _obtener_tarifa_activa,
)
from gestion.services.mercadopago_service import MercadoPagoService, DatoPago

# Porcentaje de seña sobre el total
_PORCENTAJE_SENIA = Decimal("0.30")


# ── Validaciones ──────────────────────────────────────────────────────────────

def _validar_inventario(inventario_raw: list) -> list[dict]:
    """
    Valida el array de ítems recibido del frontend.

    Recibe:  [{"catalogo_item_id": 1, "cantidad": 2}, ...]
    Retorna: lista limpia o lanza ValidationError.
    """
    if not isinstance(inventario_raw, list) or len(inventario_raw) == 0:
        raise ValidationError("El inventario no puede estar vacío.")

    ids = [item.get("catalogo_item_id") for item in inventario_raw]
    items_db = {c.pk: c for c in CatalogoItem.objects.filter(pk__in=ids)}

    resultado = []
    for item in inventario_raw:
        item_id = item.get("catalogo_item_id")
        cantidad = item.get("cantidad", 1)

        if item_id not in items_db:
            raise ValidationError(f"Ítem {item_id} no existe en el catálogo.")
        if not isinstance(cantidad, int) or cantidad < 1:
            raise ValidationError(f"Cantidad inválida para ítem {item_id}.")

        resultado.append({"catalogo_item_id": item_id, "cantidad": cantidad})

    return resultado


def _piso_entero(piso_raw: str) -> int:
    """Convierte string de piso a entero. 'PB' o inválido → 0."""
    try:
        return max(0, int(piso_raw))
    except (ValueError, TypeError):
        return 0


# ── API pública ───────────────────────────────────────────────────────────────

def procesar_solicitud_landing(form_data: dict, inventario_raw: list) -> dict:
    """
    Punto de entrada del flujo de solicitud desde la landing pública.

    Orquesta:
        1. Validación de inventario contra DB
        2. Obtención de tarifa activa
        3. Cálculo de costos y seña
        4. get_or_create de Cliente por teléfono
        5. Creación de Direccion origen y destino
        6. Creación de Mudanza en estado PRESUPUESTADA
        7. bulk_create de ItemInventario
        8. Creación de Presupuesto
        9. Generación de preferencia MP (fuera del atomic)

    Args:
        form_data:      cleaned_data del SolicitudPresupuestoForm.
        inventario_raw: lista de dicts [{catalogo_item_id, cantidad}].

    Returns:
        {
            "pago_url":    str,   # URL de Checkout Pro de MercadoPago
            "monto_total": str,   # Total del servicio formateado
            "monto_senia": str,   # Seña a pagar ahora (30% del total)
            "mudanza_id":  int,
        }

    Raises:
        ValidationError: datos inválidos o sin tarifa activa.
        RuntimeError:    error al crear preferencia en MercadoPago.
    """
    inventario = _validar_inventario(inventario_raw)
    tarifa = _obtener_tarifa_activa()

    distancia_km = Decimal(str(form_data["distancia_km"]))
    piso_origen = _piso_entero(form_data.get("origen_piso", "PB"))
    tiene_ascensor = bool(form_data.get("origen_ascensor", False))

    costos = calcular_costos_desde_parametros(
        distancia_km=distancia_km,
        necesita_ayudantes=True,  # default para solicitudes web
        piso_origen=piso_origen,
        tiene_ascensor_origen=tiene_ascensor,
        tarifa=tarifa,
    )

    monto_senia = (costos.total * _PORCENTAJE_SENIA).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    with transaction.atomic():
        # Cliente — reutiliza si ya existe el teléfono
        cliente, _ = Cliente.objects.get_or_create(
            telefono=form_data["telefono"],
            defaults={
                "nombre_completo": form_data["nombre"],
                "email": form_data.get("email") or None,
            },
        )

        origen = Direccion.objects.create(
            calle=form_data["origen_calle"],
            numero=form_data["origen_numero"],
            localidad=form_data["origen_localidad"],
            piso=form_data.get("origen_piso") or "PB",
            tiene_ascensor=tiene_ascensor,
            latitud=form_data.get("origen_lat"),
            longitud=form_data.get("origen_lng"),
        )

        destino = Direccion.objects.create(
            calle=form_data["destino_calle"],
            numero=form_data["destino_numero"],
            localidad=form_data["destino_localidad"],
            piso=form_data.get("destino_piso") or "PB",
            tiene_ascensor=bool(form_data.get("destino_ascensor", False)),
            latitud=form_data.get("destino_lat"),
            longitud=form_data.get("destino_lng"),
        )

        mudanza = Mudanza.objects.create(
            cliente=cliente,
            estado=Mudanza.Estado.PRESUPUESTADA,
            fecha_hora=form_data["fecha_hora"],
            origen=origen,
            destino=destino,
            distancia_km=distancia_km,
            necesita_ayudantes=True,
            monto_senia=monto_senia,
        )

        # Inventario — una sola query al catálogo + bulk insert
        ids_inventario = [i["catalogo_item_id"] for i in inventario]
        items_db = {
            c.pk: c for c in CatalogoItem.objects.filter(pk__in=ids_inventario)
        }
        ItemInventario.objects.bulk_create([
            ItemInventario(
                mudanza=mudanza,
                catalogo_item=items_db[i["catalogo_item_id"]],
                cantidad=i["cantidad"],
            )
            for i in inventario
        ])

        Presupuesto.objects.create(
            mudanza=mudanza,
            tarifa=tarifa,
            costo_distancia=costos.costo_distancia,
            costo_peajes=costos.costo_peajes,
            costo_ayudantes=costos.costo_ayudantes,
            costo_camion=costos.costo_camion,
            recargo_pisos=costos.recargo_pisos,
            total=costos.total,
        )

    # Fuera del atomic: si MP falla, la Mudanza queda en PRESUPUESTADA
    # sin mp_preference_id. El admin puede regenerar el link desde el panel.
    dato = DatoPago(
        uuid=str(mudanza.uuid),
        titulo=f"Seña mudanza — {cliente.nombre_completo}",
        monto=monto_senia,
        metadata={
            "mudanza_id": mudanza.pk,
            "mudanza_uuid": str(mudanza.uuid),
        },
    )
    pago_url = MercadoPagoService.generar_preferencia_desde_dato(dato, guardar_en=mudanza)

    # Disparar seguimiento post-formulario con ETA de 4 horas
    from notificaciones.tasks import enviar_seguimiento_post_formulario

    enviar_seguimiento_post_formulario.apply_async(
        args=[mudanza.pk],
        countdown=4 * 60 * 60,  # 4 horas = 14400 segundos
    )

    return {
        "pago_url": pago_url,
        "monto_total": str(costos.total),
        "monto_senia": str(monto_senia),
        "mudanza_id": mudanza.pk,
    }
