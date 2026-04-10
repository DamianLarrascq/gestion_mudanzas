from django.contrib import admin
from django import forms
from unfold.widgets import UnfoldAdminTextInputWidget, UnfoldAdminPasswordWidget
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    Cliente,
    Camion,
    Empleado,
    Mudanza,
    TarifaBase,
    Presupuesto,
    Notificacion,
)

@admin.register(Cliente)
class ClienteAdmin(ModelAdmin):
    list_display = ['nombre_completo', 'telefono', 'email', 'creado_en']
    search_fields = ['nombre_completo', 'telefono', 'email']


@admin.register(Camion)
class CamionAdmin(ModelAdmin):
    list_display = ['patente', 'modelo', 'categoria', 'activo']
    list_filter = ['categoria', 'activo']


class EmpleadoCreationForm(forms.ModelForm):
    username = forms.CharField(label="Nombre de usuario", widget=UnfoldAdminTextInputWidget)
    password1 = forms.CharField(label='Contraseña', widget=UnfoldAdminPasswordWidget)
    password2 = forms.CharField(label='Confirmar contraseña', widget=UnfoldAdminPasswordWidget)

    class Meta:
        model = Empleado
        fields = ['nombre', 'dni', 'rol', 'nro_licencia', 'disponible']

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password1')
        p2 = cleaned_data.get('password2')
        rol = cleaned_data.get('rol')
        nro = cleaned_data.get('nro_licencia')

        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Las contraseñas no coinciden.')

        if rol == Empleado.Rol.CONDUCTOR and not nro:
            self.add_error('nro_licencia', 'El número de licencia es obligatorio para conductores.')

        return cleaned_data

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password1'],
        )

        empleado = super().save(commit=False)
        empleado.user = user
        if commit:
            empleado.save()
        return empleado


class EmpleadoChangeForm(forms.ModelForm):
    class Meta:
        model = Empleado
        fields = ['nombre', 'dni', 'rol', 'nro_licencia', 'disponible']

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get("rol")
        nro = cleaned_data.get("nro_licencia")

        if rol == Empleado.Rol.CONDUCTOR and not nro:
            self.add_error("nro_licencia", "El número de licencia es obligatorio para conductores.")

        return cleaned_data


@admin.register(Empleado)
class EmpleadoAdmin(ModelAdmin):
    list_display = ['nombre', 'rol', 'disponible']
    list_filter = ['rol', 'disponible']
    search_fields = ['nombre', 'dni']

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = EmpleadoCreationForm
        else:
            kwargs['form'] = EmpleadoChangeForm
        return super().get_form(request, obj, **kwargs)


class EmpleadoInline(admin.StackedInline):
    model = Empleado
    can_delete = False
    verbose_name_plural = 'Datos de empleado'
    fields = ['rol', 'nro_licencia', 'disponible']

admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Mudanza)
class MudanzaAdmin(ModelAdmin):
    list_display = ['__str__', 'cliente', 'fecha_hora', 'estado', 'camion']
    list_filter = ['estado']
    search_fields = ['cliente__nombre_completo', 'domicilio_origen', 'domicilio_destino']


@admin.register(TarifaBase)
class TarifaBaseAdmin(ModelAdmin):
    list_display = ['nombre', 'precio_por_km', 'precio_ayudante', 'activa', 'vigente_desde']


@admin.register(Presupuesto)
class PresupuestoAdmin(ModelAdmin):
    list_display = ['mudanza', 'total', 'calculado_en']


@admin.register(Notificacion)
class NotificacionAdmin(ModelAdmin):
    list_display = ['mudanza', 'tipo', 'canal', 'enviada', 'enviada_en']
    list_filter = ['tipo', 'canal', 'enviada']
