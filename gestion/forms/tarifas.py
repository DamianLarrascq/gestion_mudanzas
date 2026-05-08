"""
ModelForm para crear y editar TarifaBase.

Consumido por:
  - ConfiguracionTarifaView (GET → renderiza; POST → valida y guarda)
  - El frontend recibe `form_schema` (ver TarifaConfigService) para construir
    el formulario dinámicamente sin acoplar HTML al backend.
"""
from __future__ import annotations
from django import forms
from django.core.validators import MinValueValidator
from decimal import Decimal
from gestion.models.presupuestos import TarifaBase

_POSITIVO = MinValueValidator(Decimal("0.01"))
_NO_NEGATIVO = MinValueValidator(Decimal("0.00"))


class TarifaBaseForm(forms.ModelForm):
    """
    Campos y validaciones para la tarifa vigente.

    Grupos lógicos (para el frontend):
      PRECIOS_BASICOS   → precio_por_km, precio_ayudante, recargo_piso
      RECARGOS          → recargo_hora_pico, recargo_fin_de_semana
      COSTOS_OPERATIVOS → seguro_camion, empleado_art, empleado_seguro_riesgo,
                          empleado_seguro_ayudante, salario_conductor, salario_ayudante
      CONFIGURACION     → nombre, vigente_desde, activa, permite_caba_feriados
    """

    class Meta:
        model = TarifaBase
        fields = [
            # CONFIGURACION
            "nombre",
            "vigente_desde",
            "activa",
            "permite_caba_feriados",
            # PRECIOS_BASICOS
            "precio_por_km",
            "precio_ayudante",
            "recargo_piso",
            # RECARGOS
            "recargo_hora_pico",
            "recargo_fin_de_semana",
            # COSTOS_OPERATIVOS
            "seguro_camion",
            "empleado_art",
            "empleado_seguro_riesgo",
            "empleado_seguro_ayudante",
            "salario_conductor",
            "salario_ayudante",
        ]

    # ── Validaciones de campo ──────────────────────────────────────────────

    def clean_precio_por_km(self) -> Decimal:
        v = self.cleaned_data["precio_por_km"]
        if v <= 0:
            raise forms.ValidationError("El precio por km debe ser mayor a 0.")
        return v

    def clean_recargo_hora_pico(self) -> Decimal:
        v = self.cleaned_data["recargo_hora_pico"]
        if v < Decimal("1.00"):
            raise forms.ValidationError(
                "El multiplicador de hora pico debe ser ≥ 1.00 (1.00 = sin recargo)."
            )
        return v

    def clean_recargo_fin_de_semana(self) -> Decimal:
        v = self.cleaned_data["recargo_fin_de_semana"]
        if v < Decimal("1.00"):
            raise forms.ValidationError(
                "El multiplicador fin de semana debe ser ≥ 1.00."
            )
        return v

    def clean(self):
        cleaned = super().clean()
        # Si se activa esta tarifa, asegura que no haya otra activa con fecha >= esta
        # La desactivación de anteriores se delega a la View (con select_for_update).
        return cleaned
