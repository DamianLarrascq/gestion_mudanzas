from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.core.exceptions import ValidationError
from gestion.models.mudanzas import Mudanza
from gestion.models.presupuestos import Presupuesto, TarifaBase


@dataclass(frozen=True)
class _ResumenInventario:
    volumen_total_m3: Decimal
    peso_total_kg: Decimal
    items: list[dict]
    items_por_categoria: dict[str, list[dict]]


@dataclass(frozen=True)
class _DesgloseCostos:
    costo_distancia: Decimal
    costo_peajes: Decimal
    costo_ayudantes: Decimal
    costo_camion: Decimal
    recargo_pisos: Decimal
    total: Decimal


# Helpers

def _obtener_tarifa_activa() -> TarifaBase:
    tarifa = TarifaBase.objects.filter(activa=True).order_by("-vigente_desde").first()
    if tarifa is None:
        raise ValidationError("No existe ninguna Tarifa Base activa en el sistema.")
    return tarifa


def _calcular_inventario(mudanza: Mudanza) -> _ResumenInventario:
    """
    Requiere prefetch_related('inventario__catalogo_item') en el queryset.
    Agrupa por categoría para facilitar la presentación por secciones.
    """
    from collections import defaultdict

    volumen = Decimal("0")
    peso = Decimal("0")
    items: list[dict] = []
    por_categoria: dict[str, list[dict]] = defaultdict(list)

    for item in mudanza.inventario.all():
        catalogo = item.catalogo_item

        if catalogo is None:
            fila = {
                "nombre":             item.descripcion or "Ítem sin catálogo",
                "cantidad":           item.cantidad,
                "volumen_unitario_m3": None,
                "peso_unitario_kg":   None,
                "subtotal_m3":        Decimal("0"),
                "categoria":          "VARIOS",
                "categoria_label":    "Varios",
            }
            items.append(fila)
            por_categoria["VARIOS"].append(fila)
            continue

        subtotal_vol  = (catalogo.volumen_m3       * item.cantidad).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        subtotal_peso = (catalogo.peso_estimado_kg * item.cantidad).quantize(Decimal("0.01"),  rounding=ROUND_HALF_UP)

        volumen += subtotal_vol
        peso    += subtotal_peso

        fila = {
            "nombre":              catalogo.nombre,
            "cantidad":            item.cantidad,
            "volumen_unitario_m3": catalogo.volumen_m3,
            "peso_unitario_kg":    catalogo.peso_estimado_kg,
            "subtotal_m3":         subtotal_vol,
            "categoria":           catalogo.categoria,
            "categoria_label":     catalogo.get_categoria_display(),
        }
        items.append(fila)
        por_categoria[catalogo.categoria].append(fila)

    return _ResumenInventario(
        volumen_total_m3=volumen,
        peso_total_kg=peso,
        items=items,
        items_por_categoria=dict(por_categoria),
    )

def _calcular_piso_sin_ascensor(direccion) -> int:
    """
    Devuelve el numero de piso entero si no tiene ascensor; 0 en caso contrario.
    'PB' se trata como piso 0
    """
    if direccion is None or direccion.tiene_ascensor:
        return 0
    piso_raw = getattr(direccion, 'piso', 'PB') or 'PB'
    try:
        return max(0, int(piso_raw))
    except (ValueError, TypeError):
        return 0


def _calcular_costos(
        mudanza: Mudanza,
        tarifa: TarifaBase,
        distancia_km: Decimal,
) -> _DesgloseCostos:
    # Distancia
    costo_distancia = (distancia_km * tarifa.precio_por_km).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Peajes: no existe campo en TarifaBase → se recibe como argumento externo.
    # Por ahora se persiste el valor que llegue (default 0); puede extenderse.
    costo_peajes = Decimal("0")

    # Ayudantes
    costo_ayudantes = tarifa.precio_ayudante if mudanza.necesita_ayudantes else Decimal("0")

    # Costo operativo del camión: seguro + ART conductor (costos fijos por servicio)
    costo_camion = (tarifa.seguro_camion + tarifa.empleado_art).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Recargo pisos (origen sin ascensor)
    pisos_origen = _calcular_piso_sin_ascensor(mudanza.origen)
    recargo_pisos = (tarifa.recargo_piso * pisos_origen).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    total = (
            costo_distancia + costo_peajes + costo_ayudantes + costo_camion + recargo_pisos
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return _DesgloseCostos(
        costo_distancia=costo_distancia,
        costo_peajes=costo_peajes,
        costo_ayudantes=costo_ayudantes,
        costo_camion=costo_camion,
        recargo_pisos=recargo_pisos,
        total=total,
    )

# API Publica

class PresupuestoService:

    @staticmethod
    def calcular_y_persistir(
            mudanza_id: int,
            distancia_km: Decimal | float | str,
            costo_peajes: Decimal | float | str = Decimal('0'),
    ) -> dict:
        """
        Calcula y guarda el presupuesto para una mudanza.

        Args:
            mudanza_id: PK de la mudanza.
            distancia_km: Km totales del trayecto (provisto por frontend)
            costo_peajes: Opcional; peajes adicionales informados manualmente.

        Returns:
            Diccionario con contexto listo para renderizar (ver docstring de '_construir_contexto_presupuesto')/

        Raises:
            ValidationError: Distancia invalida, mudanza inexistente, sin tarifa activa
            Mudanza.DoesNotExist
        """

        distancia_km = _validar_distancia(distancia_km)
        costo_peajes = _validar_decimal_positivo(costo_peajes, 'costo_peajes')

        mudanza = (
            Mudanza.objects.select_related(
                'cliente',
                'camion',
                'origen',
                'destino',
            ).prefetch_related('inventario__catalogo_item').get(pk=mudanza_id)
        )

        tarifa = _obtener_tarifa_activa()
        inventario = _calcular_inventario(mudanza)
        costos = _calcular_costos(mudanza, tarifa, distancia_km)

        costos = _DesgloseCostos(
            costo_distancia=costos.costo_distancia,
            costo_peajes=costo_peajes,
            costo_ayudantes=costos.costo_ayudantes,
            costo_camion=costos.costo_camion,
            recargo_pisos=costos.recargo_pisos,
            total = (
                costos.costo_distancia + costo_peajes + costos.costo_ayudantes + costos.costo_camion + costos.recargo_pisos
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        )
        with transaction.atomic():
            Mudanza.objects.filter(pk=mudanza_id).update(distancia_km=distancia_km)
            mudanza.distancia_km = distancia_km

            presupuesto, _ = Presupuesto.objects.update_or_create(
                mudanza=mudanza,
                defaults={
                    'tarifa': tarifa,
                    'costo_distancia': costos.costo_distancia,
                    'costo_peajes': costos.costo_peajes,
                    'costo_ayudantes': costos.costo_ayudantes,
                    'costo_camion': costos.costo_camion,
                    'recargo_pisos': costos.recargo_pisos,
                    'total': costos.total,
                },
            )

        return construir_contexto_presupuesto(mudanza, presupuesto, inventario, costos)

    @staticmethod
    def validar_capacidad_camion(mudanza_id: int) -> dict:
        """
        Valida si el inventario actual cabe en el camión asignado.
        No persiste ni recalcula costos — lectura pura.

        Útil para:
          - API de asignación de camión (antes de confirmar).
          - Validación en tiempo real desde el formulario de inventario.

        Returns:
            {
              "camion_asignado": bool,
              "volumen_total_m3": str,
              "peso_total_kg": str,
              "capacidad_volumen_m3": str | None,
              "capacidad_peso_kg": str | None,
              "sobrecarga_volumen": bool,
              "sobrecarga_peso": bool,
              "puede_transportar": bool,   # True solo si ambos dentro del límite
              "alerta_label": str | None,
            }

        Raises:
            Mudanza.DoesNotExist
        """
        mudanza = (
            Mudanza.objects
            .select_related("camion")
            .prefetch_related("inventario__catalogo_item")
            .get(pk=mudanza_id)
        )

        inventario = _calcular_inventario(mudanza)
        camion = mudanza.camion

        if camion is None:
            return {
                "camion_asignado":     False,
                "volumen_total_m3":    str(inventario.volumen_total_m3),
                "peso_total_kg":       str(inventario.peso_total_kg),
                "capacidad_volumen_m3": None,
                "capacidad_peso_kg":   None,
                "sobrecarga_volumen":  False,
                "sobrecarga_peso":     False,
                "puede_transportar":   True,   # sin camión, no hay límite que validar
                "alerta_label":        None,
            }

        sobrecarga_vol  = inventario.volumen_total_m3 > camion.capacidad_volumen_m3
        sobrecarga_peso = inventario.peso_total_kg    > camion.capacidad_peso_kg

        return {
            "camion_asignado":     True,
            "volumen_total_m3":    str(inventario.volumen_total_m3),
            "peso_total_kg":       str(inventario.peso_total_kg),
            "capacidad_volumen_m3": str(camion.capacidad_volumen_m3),
            "capacidad_peso_kg":   str(camion.capacidad_peso_kg),
            "sobrecarga_volumen":  sobrecarga_vol,
            "sobrecarga_peso":     sobrecarga_peso,
            "puede_transportar":   not sobrecarga_vol and not sobrecarga_peso,
            "alerta_label":        _label_alerta_capacidad(sobrecarga_peso, sobrecarga_vol),
        }

def construir_contexto_presupuesto(
        mudanza: Mudanza,
        presupuesto: Presupuesto,
        inventario: _ResumenInventario,
        costos: _DesgloseCostos,
) -> dict:
    """
    Serializa todo el contexto que necesita ResumenMudanzaView.
    Ningun calculo debe ocurrir fuera de aqui.
    """

    camion = mudanza.camion
    alerta_sobrecarga = (
        camion is not None and inventario.peso_total_kg > camion.capacidad_peso_kg
    )
    alerta_volumen = (camion is not None and inventario.volumen_total_m3 > camion.capacidad_volumen_m3)

    desglose = [
        {'label': 'Costo por distancia', 'valor': _fmt_money(costos.costo_distancia)},
        {'label': 'Peajes estimados', 'valor': _fmt_money(costos.costo_peajes)},
        {'label': 'Ayudantes', 'valor': _fmt_money(costos.costo_ayudantes)},
        {'label': 'Costos operativos camión', 'valor': _fmt_money(costos.costo_camion)},
        {'label': 'Recargo por pisos', 'valor': _fmt_money(costos.recargo_pisos)},
    ]

    monto_senia = mudanza.monto_senia or Decimal("0")

    return {
        # Presupuesto
        "monto_total_formateado": _fmt_money(costos.total),
        "monto_total_raw": costos.total,
        "monto_senia_formateado": _fmt_money(monto_senia),
        "monto_senia_raw": monto_senia,
        "desglose_items": desglose,
        "tarifa_nombre": presupuesto.tarifa.nombre,
        "tarifa_vigente_desde": presupuesto.tarifa.vigente_desde.strftime("%-d/%m/%Y"),

        # Inventario
        "inventario_items": inventario.items,
        "inventario_por_categoria": inventario.items_por_categoria,
        "volumen_total_m3": str(inventario.volumen_total_m3),
        "peso_total_kg": str(inventario.peso_total_kg),

        # Alertas de capacidad
        "alerta_sobrecarga": alerta_sobrecarga,
        "alerta_volumen": alerta_volumen,
        "alerta_capacidad_label": _label_alerta_capacidad(alerta_sobrecarga, alerta_volumen),

        # Distancia
        "distancia_km": str(mudanza.distancia_km or "0"),

        # Pago
        "senia_pagada": mudanza.senia_pagada,
        "mp_preference_id": mudanza.mp_preference_id,
        "pago_url": None,  # lo inyecta la view tras llamar a MercadoPagoService
    }

# Formato y validacion

def _fmt_money(value: Decimal) -> str:
    return f"${value:,.0f}".replace(",", ".")


def _label_alerta_capacidad(sobrepeso: bool, sobrevolumen: bool) -> str | None:
    if sobrepeso and sobrevolumen:
        return "El inventario supera el peso y volumen máximo del camión asignado."
    if sobrepeso:
        return "El inventario supera el peso máximo del camión asignado."
    if sobrevolumen:
        return "El inventario supera el volumen máximo del camión asignado."
    return None


def _validar_distancia(valor) -> Decimal:
    try:
        d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        raise ValidationError("distancia_km debe ser un número válido.")
    if d <= 0:
        raise ValidationError("distancia_km debe ser un valor positivo.")
    return d


def _validar_decimal_positivo(valor, campo: str) -> Decimal:
    try:
        d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        raise ValidationError(f"{campo} debe ser un número válido.")
    if d < 0:
        raise ValidationError(f"{campo} no puede ser negativo.")
    return d