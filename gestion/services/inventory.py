from decimal import Decimal
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from gestion.models import Mudanza

def calcular_volumen_total(mudanza: Mudanza) -> Decimal:
    resultado = (
        mudanza.inventario.filter(catalogo_item__isnull=False).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('cantidad') * F('catalogo_item__volumen_m3'),
                    output_field=DecimalField(),
                )
            )
        )
    )
    return resultado['total'] or Decimal('0')


def calcular_peso_total(mudanza: Mudanza) -> Decimal:
    resultado = (
        mudanza.inventario.filter(catalogo_item__isnull=False).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('cantidad') * F('catalogo_item__peso_estimado_kg'),
                    output_field=DecimalField(),
                )
            )
        )
    )
    return resultado['total'] or Decimal('0')