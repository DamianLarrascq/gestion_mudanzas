from django import forms
import datetime


class SolicitudPresupuestoForm(forms.Form):
    # ── Contacto ──────────────────────────────────────────────────────────────
    nombre   = forms.CharField(max_length=200)
    telefono = forms.CharField(max_length=20)
    email    = forms.EmailField(required=False)

    # ── Origen ────────────────────────────────────────────────────────────────
    origen_calle     = forms.CharField(max_length=200)
    origen_numero    = forms.CharField(max_length=10)
    origen_localidad = forms.CharField(max_length=100)
    origen_piso      = forms.CharField(max_length=10, required=False, initial="PB")
    origen_ascensor  = forms.BooleanField(required=False)
    origen_lat       = forms.FloatField(required=False)
    origen_lng       = forms.FloatField(required=False)

    # ── Destino ───────────────────────────────────────────────────────────────
    destino_calle     = forms.CharField(max_length=200)
    destino_numero    = forms.CharField(max_length=10)
    destino_localidad = forms.CharField(max_length=100)
    destino_piso      = forms.CharField(max_length=10, required=False, initial="PB")
    destino_ascensor  = forms.BooleanField(required=False)
    destino_lat       = forms.FloatField(required=False)
    destino_lng       = forms.FloatField(required=False)

    # ── Logística ─────────────────────────────────────────────────────────────
    fecha_deseada = forms.DateField()
    distancia_km  = forms.DecimalField(max_digits=8, decimal_places=2, min_value=1)

    def clean_fecha_deseada(self):
        fecha = self.cleaned_data["fecha_deseada"]
        if fecha < datetime.date.today():
            raise forms.ValidationError("La fecha de la mudanza no puede ser en el pasado.")
        return fecha

    def clean_origen_piso(self):
        return self.cleaned_data.get("origen_piso") or "PB"

    def clean_destino_piso(self):
        return self.cleaned_data.get("destino_piso") or "PB"