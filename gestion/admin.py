from django.contrib import admin
from django import forms
from datetime import timedelta
from django.forms import BaseInlineFormSet, ValidationError
from django.utils.html import format_html
from unfold.widgets import UnfoldAdminTextInputWidget, UnfoldAdminPasswordWidget
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.decorators import display, action
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


class AsignacionEmpleadoFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        mudanza = self.instance
        empleados_en_form = []
        conductores = []

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue

            empleado = form.cleaned_data.get('empleado')
            rol = form.cleaned_data.get('rol')
            if not empleado:
                continue

            if empleado in empleados_en_form:
                form.add_error('empleado', 'Este empleado está duplicado en la mudanza.')
            empleados_en_form.append(empleado)

            if rol == Empleado.Rol.CONDUCTOR:
                conductores.append(form)

            from django.utils.dateparse import parse_datetime

            fecha_hora = mudanza.fecha_hora or self.data.get('fecha_hora')

            if isinstance(fecha_hora, str):
                fecha_hora = parse_datetime(fecha_hora)

            if not fecha_hora:
                return

            fin = fecha_hora + timedelta(hours=2)

            for empleado in empleados_en_form:
                conflicto = AsignacionEmpleado.objects.filter(
                    empleado = empleado,
                    mudanza__fecha_hora__lt = fin,
                    mudanza__fecha_hora__gt = mudanza.fecha_hora - timedelta(hours=2),
                    mudanza__estado__in = [
                        Mudanza.Estado.CONFIRMADA,
                        Mudanza.Estado.EN_CURSO,
                        Mudanza.Estado.PRESUPUESTADA,
                    ],
                )

                if mudanza.pk:
                    conflicto = conflicto.exclude(mudanza=mudanza)

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
            qs = Empleado.objects.filter(disponible=True)

            object_id = request.resolver_match.kwargs.get('object_id')

            if object_id:
                try:
                    mudanza = Mudanza.objects.get(pk=object_id)

                    if mudanza.fecha_hora:
                        inicio = mudanza.fecha_hora
                        fin = inicio + timedelta(hours=2)

                        empleados_ocupados = AsignacionEmpleado.objects.filter(
                            mudanza__fecha_hora__lt=fin,
                            mudanza__fecha_hora__gt=inicio - timedelta(hours=2),
                            mudanza__estado__in=[
                                Mudanza.Estado.CONFIRMADA,
                                Mudanza.Estado.EN_CURSO,
                            ],
                        ).values_list('empleado_id', flat=True)

                        qs = qs.exclude(id__in=empleados_ocupados)
                    
                except Mudanza.DoesNotExist:
                    pass
            kwargs['queryset'] = qs
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

    fieldsets = (
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


ESTADO_COLORES = {
    Mudanza.Estado.BORRADOR: ('gray', '⬤'),
    Mudanza.Estado.PRESUPUESTADA: ('blue', '⬤'),
    Mudanza.Estado.CONFIRMADA: ('green', '⬤'),
    Mudanza.Estado.EN_CURSO: ('orange', '⬤'),
    Mudanza.Estado.COMPLETADA: ('teal', '⬤'),
    Mudanza.Estado.CANCELADA: ('red', '⬤'),
    Mudanza.Estado.POSPUESTA: ('purple', '⬤'),
}


@admin.register(Mudanza)
class MudanzaAdmin(ModelAdmin):
    list_display = ['__str__', 'cliente', 'fecha_hora', 'estado_colored', 'camion', 'total_presupuesto']
    list_filter = ['estado']
    search_fields = ['cliente__nombre_completo', 'domicilio_origen', 'domicilio_destino']
    inlines = [AsignacionEmpleadoInline]
    actions = [
        'marcar_confirmada',
        'marcar_en_curso',
        'marcar_completada',
        'marcar_cancelada'
    ]

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

    @display(description='Estado', ordering='estado')
    def estado_colored(self, obj):
        color, icono = ESTADO_COLORES.get(obj.estado, ('gray', "⬤"))
        return format_html(
            '<span style="color: {};">{}</span> {}',
            color, icono, obj.get_estado_display()
        )

    # total presupuesto
    @display(description='Presupuesto', ordering='presupuesto__total')
    def total_presupuesto(self, obj):
        try:
            return f'${obj.presupuesto.total:,.0f}'
        except Mudanza.presupuesto.RelatedObjectDoesNotExist:
            return '-'

    # acciones en masa
    @action(description='Marcar como Confirmada')
    def marcar_confirmada(self, request, queryset):
        actualizadas = queryset.filter(
            estado=Mudanza.Estado.PRESUPUESTADA
        ).update(estado=Mudanza.Estado.CONFIRMADA)
        self.message_user(request, f'{actualizadas} mudanza(s) marcadas como Confirmadas.')


    @action(description='Marcar como En curso')
    def marcar_en_curso(self, request, queryset):
        actualizadas = queryset.filter(
            estado=Mudanza.Estado.CONFIRMADA
        ).update(estado=Mudanza.Estado.EN_CURSO)
        self.message_user(request, f'{actualizadas} mudanza(s) marcadas como En curso')

    @action(description='Marcar como Completada')
    def marcar_completada(self, request, queryset):
        actualizadas = queryset.filter(
            estado = Mudanza.Estado.EN_CURSO
        ).update(estado=Mudanza.Estado.COMPLETADA)
        self.message_user(request, f'{actualizadas} mudanza(s) marcadas como Completadas')

    @action(description='Marcar como Cancelada')
    def marcar_cancelada(self, request, queryset):
        actualizadas = queryset.exclude(
            estado__in=[Mudanza.Estado.COMPLETADA, Mudanza.Estado.CANCELADA]
        ).update(estado=Mudanza.Estado.CANCELADA)
        self.message_user(request, f'{actualizadas} mudanza(s) marcadas como Canceladas')

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
