from django.contrib import admin
from django import forms
from datetime import timedelta
from django.forms import BaseInlineFormSet, ValidationError
from unfold.widgets import UnfoldAdminTextInputWidget, UnfoldAdminPasswordWidget
from unfold.admin import ModelAdmin, TabularInline
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
    AsignacionEmpleado,
    ItemInventario
)

@admin.register(Cliente)
class ClienteAdmin(ModelAdmin):
    list_display = ['nombre_completo', 'dni', 'telefono', 'email', 'creado_en']
    search_fields = ['nombre_completo', 'dni', 'telefono', 'email']

    fieldsets = (
        ('Datos personales', {
            'fields': (
                ('nombre_completo', 'dni'),
                ('fecha_nacimiento',),
            ),
        }),
        ('Contacto', {
            'fields': (
                ('telefono', 'email'),
            ),
        }),
    )


@admin.register(Camion)
class CamionAdmin(ModelAdmin):
    list_display = ['patente', 'modelo', 'categoria', 'activo']
    list_filter = ['categoria', 'activo']

    fieldsets = (
        ('Identificación', {
            'fields': (
                ('patente', 'modelo'),
            ),
        }),
        ('Categoría', {
            'fields': (
                ('categoria', 'activo'),
            ),
        }),
    )


class ItemInventarioInline(TabularInline):
    model = ItemInventario
    extra = 1
    fields = ['tipo', 'descripcion', 'cantidad']


class AsignacionEmpleadoFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        empleados_asignados = []

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue

            empleado = form.cleaned_data.get('empleado')
            if not empleado:
                continue

            if empleado in empleados_asignados:
                raise ValidationError(
                    f'{empleado.nombre} ya fue asignado a esta mudanza.'
                )
            empleados_asignados.append(empleado)

            mudanza = self.instance
            if not mudanza.fecha_hora:
                continue

            fin = mudanza.fecha_hora + timedelta(hours=2)

            conflicto = AsignacionEmpleado.objects.filter(
                empleado = empleado,
                mudanza__fecha_hora__lt = fin,
                mudanza__fecha_hora__gt = mudanza.fecha_hora - timedelta(hours=2),
                mudanza__estado__in = [
                    Mudanza.Estado.CONFIRMADA,
                    Mudanza.Estado.EN_CURSO,
                ],
            ).exclude(mudanza=mudanza)

            if conflicto.exists():
                mudanza_conflicto = conflicto.first().mudanza
                raise ValidationError(
                    f'{empleado.nombre} ya está asignado a la mudanza #{mudanza_conflicto.pk} en ese horario.'
                )


class AsignacionEmpleadoInline(TabularInline):
    model = AsignacionEmpleado
    formset = AsignacionEmpleadoFormSet
    extra = 1
    fields = ['empleado', 'rol']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'empleado':
            kwargs['queryset'] = Empleado.objects.filter(disponible=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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

    add_fieldsets = (
        ('Acceso al sistema', {
            'fields': (
                ('username',),
                ('password1', 'password2'),
            ),
        }),
        ('Datos personales', {
            'fields': (
                ('nombre', 'dni'),
            ),
        }),
        ('Rol y disponibilidad', {
            'fields': (
                ('rol', 'disponible'),
                ('nro_licencia',),
            ),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

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
    inlines = [ItemInventarioInline, AsignacionEmpleadoInline]

    fieldsets = (
        ('Datos generales', {
            'fields': (
                ('cliente', 'estado'),
                ('fecha_hora', 'camion'),
            ),
        }),
        ('Domicilios', {
            'fields': (
                ('domicilio_origen', 'domicilio_destino'),
                ('piso_origen', 'ascensor_origen'),
                ('piso_destino', 'ascensor_destino'),
                ('distancia_km',),
            ),
        }),
        ('Coordenadas', {
            'classes': ('collapse',),
            'fields': (
                ('lat_origen', 'lng_origen'),
                ('lat_destino', 'lng_destino'),
            ),
        }),
        ('Servicio', {
            'fields': (
                ('necesita_ayudantes',),
                ('mp_preference_id',),
            ),
        }),
    )


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
