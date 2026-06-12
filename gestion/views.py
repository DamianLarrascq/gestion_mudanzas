from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from gestion.mixins import StaffRequiredMixin, MudanzaOwnerMixin, staff_required
from gestion.models import Empleado, Camion
from gestion.services.dashboard_service import (
    obtener_actividad_reciente,
    obtener_kpis,
    obtener_mudanzas_hoy
)
from gestion.services.empleados_service import FiltrosEmpleado, obtener_empleados_listado, \
    validar_disponibilidad_para_fecha
from gestion.services.flota_service import obtener_estado_flota
from gestion.services.mudanza_create_service import MudanzaCreateService, MudanzaCreateInput, AsignacionInput, \
    ItemInventarioInput, DireccionInput
from gestion.services.mudanzas_list_service import FiltrosMudanza, obtener_mudanzas_filtradas
from gestion.models.clientes import Cliente
from gestion.services.clientes_service import (
    FiltrosCliente, obtener_clientes_filtrados, obtener_detalle_cliente
)
import datetime
from gestion.models.mudanzas import Mudanza
from gestion.services.presupuesto_service import PresupuestoService, construir_contexto_presupuesto
from gestion.services.mercadopago_service import MercadoPagoService
from django.core.exceptions import ValidationError
from django.views.generic.edit import CreateView, UpdateView
from django.contrib import messages
from django.shortcuts import redirect
from gestion.forms.tarifas import TarifaBaseForm
from gestion.models.presupuestos import TarifaBase
from gestion.services.tarifa_config_service import (
    obtener_contexto_config_tarifas
)


@@staff_required
def dashboard(request):
    hoy = timezone.localdate()

    context = {
        'titulo_pagina': 'Dashboard',
        'seccion_activa': 'dashboard',
        'fecha_activa': f"{hoy.day} de {hoy.strftime('%B de %Y')}",

        'kpis': obtener_kpis(hoy),
        'mudanzas_hoy': obtener_mudanzas_hoy(hoy),
        'actividad_reciente': obtener_actividad_reciente(limite=5)
    }

    return render(request, 'gestion/dashboard.html', context)


# Mudanzas

class MudanzaListView(StaffRequiredMixin, TemplateView):
    template_name = 'gestion/mudanzas/lista.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        filtros = FiltrosMudanza(
            q=self.request.GET.get('q', '').strip(),
            estado=self.request.GET.get('estado', '').strip(),
            page=self._parse_page(),
            page_size=20,
        )

        ctx.update(obtener_mudanzas_filtradas(filtros))
        ctx['titulo_pagina'] = 'Mudanzas'
        ctx['seccion_activa'] = 'mudanzas'
        return ctx

    def _parse_page(self) -> int:
        try:
            page = int(self.request.GET.get('page', 1))
            return max(1, page)
        except (ValueError, TypeError):
            return 1


class MudanzaCreateView(StaffRequiredMixin, TemplateView):
    """
    GET /gestion/mudanzas/nueva/
        Renderiza el formulario con los selectores pre-cargados.

    POST /gestion/mudanzas/nueva/
        Crea la mudanza y redirige al detalle.

    Contexto GET:
        Ver _obtener_contexto_formulario()
    """
    template_name = 'gestion/mudanzas/nueva.html'

    def get_context_data(self, **kwargs) -> dict:
        ctx = super().get_context_data(**kwargs)
        fecha = self._parse_fecha_filtro()
        ctx.update(_obtener_contexto_formulario())
        ctx['titulo_pagina'] = 'Nueva Mudanza'
        ctx['seccion_activa'] = 'mudanzas'
        ctx['errors'] = None
        ctx['valores'] = {}
        return ctx

    def _parse_fecha_filtro(self):
        raw = self.request.GET.get('fecha_hora', '').strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw[:10])
        except ValueError:
            return None

    def post(self, request, *args, **kwargs):
        raw = request.POST

        try:
            data = _parsear_input(raw)
            resultado = MudanzaCreateService.crear(data, usuario=request.user)
        except ValidationError as exc:
            ctx = self.get_context_data(**kwargs)
            ctx['errors'] = exc.messages
            ctx['valores'] = raw
            return self.render_to_response(ctx)

        messages.success(
            request,
            f"Mudanza #{resultado['id']} creada correctamente."
        )
        return redirect(resultado['url_detalle'])


# Clientes

class ClienteListView(StaffRequiredMixin, TemplateView):
    template_name = 'gestion/clientes/lista.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        filtros = FiltrosCliente(
            q=self.request.GET.get('q', '').strip(),
            segmento=self.request.GET.get('segmento', '').strip(),
            page=self._parse_page(),
            page_size=25,
        )

        ctx.update(obtener_clientes_filtrados(filtros))
        ctx['titulo_pagina'] = 'Clientes'
        ctx['seccion_activa'] = 'clientes'
        return ctx

    def _parse_page(self) -> int:
        try:
            return max(1, int(self.request.GET.get('page', 1)))
        except (ValueError, TypeError):
            return 1


class ClienteDetailView(StaffRequiredMixin, TemplateView):
    template_name = "gestion/clientes/detalle.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Valida existencia antes de pasar al service
        get_object_or_404(Cliente, pk=self.kwargs["pk"])

        ctx.update(obtener_detalle_cliente(self.kwargs["pk"]))
        ctx["titulo_pagina"] = "Detalle de cliente"
        ctx["seccion_activa"] = "clientes"
        return ctx


# Empleados

class EmpleadoListView(StaffRequiredMixin, TemplateView):
    template_name = "gestion/empleados/lista.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Fecha de consulta: permite evaluar disponibilidad para otro día
        fecha = self._parse_fecha()

        filtros = FiltrosEmpleado(
            q=self.request.GET.get("q", "").strip(),
            rol=self.request.GET.get("rol", "").strip(),
            solo_disponibles=self.request.GET.get("solo_disponibles") == "1",
            page=self._parse_page(),
            page_size=25,
        )

        ctx.update(obtener_empleados_listado(filtros, fecha))
        ctx["titulo_pagina"] = "Empleados"
        ctx["seccion_activa"] = "empleados"
        return ctx

    def _parse_page(self) -> int:
        try:
            return max(1, int(self.request.GET.get("page", 1)))
        except (ValueError, TypeError):
            return 1

    def _parse_fecha(self) -> datetime.date | None:
        raw = self.request.GET.get("fecha", "").strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            return None


@login_required
def api_validar_disponibilidad(request, empleado_id: int):
    """
    GET /gestion/empleados/<id>/disponibilidad/?fecha=YYYY-MM-DD
    Retorna JSON con disponibilidad y alertas para usar en modales de asignación.
    """
    raw_fecha = request.GET.get("fecha", "").strip()
    try:
        fecha = datetime.date.fromisoformat(raw_fecha) if raw_fecha else timezone.localdate()
    except ValueError:
        return JsonResponse({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

    try:
        resultado = validar_disponibilidad_para_fecha(empleado_id, fecha)
    except Empleado.DoesNotExist:
        return JsonResponse({"error": "Empleado no encontrado."}, status=404)

    return JsonResponse(resultado)


# Flota

class FlotaMonitorView(StaffRequiredMixin, TemplateView):
    template_name = "gestion/flota/monitor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(obtener_estado_flota())
        ctx["titulo_pagina"] = "Monitoreo de Flota"
        ctx["seccion_activa"] = "flota"
        return ctx


# Resumen mudanza y mp

class ResumenMudanzaView(MudanzaOwnerMixin, TemplateView):
    """
    GET  /gestion/mudanzas/<pk>/resumen/
         Muestra el resumen calculado (si ya existe presupuesto).

    POST /gestion/mudanzas/<pk>/resumen/
         Recalcula el presupuesto con los datos del form y, si corresponde,
         genera la preferencia de pago en MercadoPago.
    """

    template_name = "gestion/mudanzas/resumen.html"

    def get_context_data(self, **kwargs) -> dict:
        ctx = super().get_context_data(**kwargs)
        mudanza = get_object_or_404(
            Mudanza.objects.select_related(
                "cliente", "camion", "origen", "destino"
            ).prefetch_related("inventario__catalogo_item"),
            pk=self.kwargs["pk"],
        )

        presupuesto = getattr(mudanza, "presupuesto", None)
        pago_url = None

        if presupuesto:
            from gestion.services.presupuesto_service import (
                _calcular_inventario,
                _calcular_costos,
                _obtener_tarifa_activa,
            )
            inventario = _calcular_inventario(mudanza)
            tarifa = presupuesto.tarifa
            # Reconstruye _DesgloseCostos desde el presupuesto persistido
            from gestion.services.presupuesto_service import _DesgloseCostos
            costos = _DesgloseCostos(
                costo_distancia=presupuesto.costo_distancia,
                costo_peajes=presupuesto.costo_peajes,
                costo_ayudantes=presupuesto.costo_ayudantes,
                costo_camion=presupuesto.costo_camion,
                recargo_pisos=presupuesto.recargo_pisos,
                total=presupuesto.total,
            )
            ctx_presupuesto = construir_contexto_presupuesto(
                mudanza, presupuesto, inventario, costos
            )

            if mudanza.mp_preference_id and not mudanza.senia_pagada:
                # Regenera URL sin crear nueva preferencia
                sdk_url = _recuperar_init_point(mudanza.mp_preference_id)
                pago_url = sdk_url

            ctx_presupuesto["pago_url"] = pago_url
            ctx.update(ctx_presupuesto)

        ctx.update({
            "mudanza_id": mudanza.pk,
            "cliente_nombre": mudanza.cliente.nombre_completo,
            "titulo_pagina": f"Resumen Mudanza #{mudanza.pk}",
            "seccion_activa": "mudanzas",
            "tiene_presupuesto": presupuesto is not None,
            "senia_pagada": mudanza.senia_pagada,
            "error": None,
        })
        return ctx

    def post(self, request, *args, **kwargs):
        mudanza_pk = self.kwargs["pk"]
        get_object_or_404(Mudanza, pk=mudanza_pk)

        distancia_raw = request.POST.get("distancia_km", "").strip()
        peajes_raw = request.POST.get("costo_peajes", "0").strip() or "0"
        generar_pago = request.POST.get("generar_pago") == "1"

        try:
            ctx_presupuesto = PresupuestoService.calcular_y_persistir(
                mudanza_id=mudanza_pk,
                distancia_km=distancia_raw,
                costo_peajes=peajes_raw,
            )
        except (ValidationError, ValueError) as exc:
            ctx = self.get_context_data(**kwargs)
            ctx["error"] = str(exc)
            return self.render_to_response(ctx)

        pago_url = None
        if generar_pago and not ctx_presupuesto["senia_pagada"]:
            mudanza = Mudanza.objects.get(pk=mudanza_pk)
            try:
                pago_url = MercadoPagoService.generar_preferencia_pago(mudanza)
            except (ValueError, RuntimeError) as exc:
                ctx = self.get_context_data(**kwargs)
                ctx.update(ctx_presupuesto)
                ctx["error"] = f"Error al generar link de pago: {exc}"
                return self.render_to_response(ctx)

        ctx_presupuesto["pago_url"] = pago_url

        ctx = self.get_context_data(**kwargs)
        ctx.update(ctx_presupuesto)
        ctx["tiene_presupuesto"] = True
        return self.render_to_response(ctx)


def _recuperar_init_point(preference_id: str) -> str | None:
    """Consulta la preferencia existente en MP y retorna el init_point."""
    try:
        from gestion.services.mercadopago_service import _get_sdk
        from django.conf import settings
        sdk = _get_sdk()
        response = sdk.preference().get(preference_id)
        if response["status"] == 200:
            key = "sandbox_init_point" if getattr(settings, "MERCADOPAGO_SANDBOX", True) else "init_point"
            return response["response"].get(key)
    except Exception:
        return None
    return None


# Configuracion de tarifas

class ConfiguracionTarifaView(StaffRequiredMixin, TemplateView):
    """
    GET  /gestion/configuracion/tarifas/
        → Contexto con tarifa_activa + historial.

    Contexto entregado al template:
        titulo_pagina       str
        seccion_activa      str  ("configuracion")
        tarifa_activa       dict | None   (ver _serializar_tarifa)
        historial           list[dict]
        puede_crear         bool
    """
    template_name = "gestion/configuracion/tarifas.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(obtener_contexto_config_tarifas())
        ctx["titulo_pagina"] = "Configuración de Tarifas"
        ctx["seccion_activa"] = "configuracion"
        return ctx


class TarifaCreateView(StaffRequiredMixin, CreateView):
    """
    GET  /gestion/configuracion/tarifas/nueva/
        → form_schema en contexto para renderizado dinámico.
    POST /gestion/configuracion/tarifas/nueva/
        → Valida con TarifaBaseForm y redirige.

    Contexto entregado:
        titulo_pagina   str
        seccion_activa  str
        form_schema     list[dict]   – metadatos de cada campo para el frontend
        errors          dict | None  – errores de validación {campo: [mensajes]}
        valores         dict | None  – valores previos para re-renderizado
    """
    model = TarifaBase
    form_class = TarifaBaseForm
    template_name = "gestion/configuracion/tarifa_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo_pagina"] = "Nueva Tarifa"
        ctx["seccion_activa"] = "configuracion"
        ctx["form_schema"] = _build_form_schema(self.get_form())
        ctx["errors"] = None
        ctx["valores"] = None
        return ctx

    def form_invalid(self, form):
        ctx = self.get_context_data(form=form)
        ctx["errors"] = form.errors.get_json_data()
        ctx["valores"] = form.data
        return self.render_to_response(ctx)

    def form_valid(self, form):
        instance = form.save(commit=False)
        if instance.activa:
            TarifaBase.objects.exclude(pk=instance.pk).update(activa=False)
        instance.save()
        messages.success(self.request, f'Tarifa "{instance.nombre}" creada correctamente.')
        return redirect("gestion:config_tarifas")


class TarifaUpdateView(StaffRequiredMixin, UpdateView):
    """
    GET  /gestion/configuracion/tarifas/<pk>/editar/
    POST /gestion/configuracion/tarifas/<pk>/editar/

    Mismo contrato de contexto que TarifaCreateView + `tarifa_id` (int).
    """
    model = TarifaBase
    form_class = TarifaBaseForm
    template_name = "gestion/configuracion/tarifa_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo_pagina"] = "Editar Tarifa"
        ctx["seccion_activa"] = "configuracion"
        ctx["tarifa_id"] = self.object.pk
        ctx["form_schema"] = _build_form_schema(self.get_form())
        ctx["errors"] = None
        ctx["valores"] = None
        return ctx

    def form_invalid(self, form):
        ctx = self.get_context_data(form=form)
        ctx["errors"] = form.errors.get_json_data()
        ctx["valores"] = form.data
        return self.render_to_response(ctx)

    def form_valid(self, form):
        instance = form.save(commit=False)
        if instance.activa:
            TarifaBase.objects.exclude(pk=instance.pk).update(activa=False)
        instance.save()
        messages.success(self.request, f'Tarifa "{instance.nombre}" actualizada.')
        return redirect("gestion:config_tarifas")


@staff_required
def api_validar_capacidad_camion(request, mudanza_id: int):
    """
    GET /gestion/mudanzas/<id>/validar-capacidad/

    Retorna JSON con el resultado de PresupuestoService.validar_capacidad_camion.
    Sin efectos secundarios — lectura pura.

    Respuesta:
        {
          "camion_asignado": bool,
          "volumen_total_m3": str,
          "peso_total_kg": str,
          "capacidad_volumen_m3": str | null,
          "capacidad_peso_kg": str | null,
          "sobrecarga_volumen": bool,
          "sobrecarga_peso": bool,
          "puede_transportar": bool,
          "alerta_label": str | null
        }
    """
    from gestion.models.mudanzas import Mudanza  # evitar import circular si aplica

    try:
        resultado = PresupuestoService.validar_capacidad_camion(mudanza_id)
    except Mudanza.DoesNotExist:
        return JsonResponse({"error": "Mudanza no encontrada."}, status=404)

    return JsonResponse(resultado)


# Helper privado

def _build_form_schema(form: TarifaBaseForm) -> list[dict]:
    """
    Serializa los metadatos del form para que el frontend construya
    el formulario dinámicamente (útil para React/Alpine/HTMX).

    Cada item:
        {
          "name":       str,   # nombre del campo
          "label":      str,   # label legible
          "type":       str,   # "text" | "number" | "date" | "checkbox"
          "required":   bool,
          "help_text":  str,
          "value":      str | bool | None,   # valor actual (edición) o vacío
          "errors":     list[str],
          "grupo":      str,   # CONFIGURACION | PRECIOS_BASICOS | RECARGOS | COSTOS_OPERATIVOS
        }
    """
    _GRUPOS = {
        "nombre": "CONFIGURACION",
        "vigente_desde": "CONFIGURACION",
        "activa": "CONFIGURACION",
        "permite_caba_feriados": "CONFIGURACION",
        "precio_por_km": "PRECIOS_BASICOS",
        "precio_ayudante": "PRECIOS_BASICOS",
        "recargo_piso": "PRECIOS_BASICOS",
        "recargo_hora_pico": "RECARGOS",
        "recargo_fin_de_semana": "RECARGOS",
        "seguro_camion": "COSTOS_OPERATIVOS",
        "empleado_art": "COSTOS_OPERATIVOS",
        "empleado_seguro_riesgo": "COSTOS_OPERATIVOS",
        "empleado_seguro_ayudante": "COSTOS_OPERATIVOS",
        "salario_conductor": "COSTOS_OPERATIVOS",
        "salario_ayudante": "COSTOS_OPERATIVOS",
    }

    schema = []
    for name, field in form.fields.items():
        widget_type = field.widget.__class__.__name__
        if "Check" in widget_type:
            field_type = "checkbox"
        elif "Date" in widget_type:
            field_type = "date"
        elif "Number" in widget_type or hasattr(field, "decimal_places"):
            field_type = "number"
        else:
            field_type = "text"

        schema.append({
            "name": name,
            "label": str(field.label or name),
            "type": field_type,
            "required": field.required,
            "help_text": str(field.help_text or ""),
            "value": form[name].value(),
            "errors": [str(e) for e in form[name].errors],
            "grupo": _GRUPOS.get(name, "OTROS"),
        })

    return schema


def _parsear_input(raw) -> MudanzaCreateInput:
    """
    Convierte POST crudo en MudanzaCreateInput.
    Lanza ValidationError si los campos obligatorios faltan o tienen formato invalido.
    """
    from decimal import Decimal, InvalidOperation

    errores = []

    # cliente_id
    try:
        cliente_id = int(raw['cliente_id'])
    except (KeyError, ValueError):
        errores.append('cliente_id es obligatorio y debe ser un entero.')
        cliente_id = None

    # fecha_hora
    try:
        fecha_hora = timezone.make_aware(
            datetime.datetime.fromisoformat(raw['fecha_hora'])
        )
    except (KeyError, ValueError):
        errores.append('fecha_hora es obligatoria (formato ISO: YYYY-MM-DDTHH:MM).')
        fecha_hora = None

    if errores:
        raise ValidationError(errores)

    # camion_id (opcional)
    camion_id = None
    if raw.get('camion_id'):
        try:
            camion_id = int(raw['camion_id'])
        except ValueError:
            raise ValidationError('camion_id debe ser un entero valido.')

    # monto_senia (opcional)
    monto_senia = None
    if raw.get('monto_senia'):
        try:
            monto_senia = Decimal(raw['monto_senia'])
        except InvalidOperation:
            raise ValidationError('monto_senia debe ser un numero valido.')

    # Direcciones
    origen = _parsear_direccion(raw, prefijo='origen')
    destino = _parsear_direccion(raw, prefijo='destino')

    # asignaciones: empleados_ids[] + roles[]
    empleado_ids = raw.getlist('empleado_ids[]')
    roles = raw.getlist('roles[]')
    asignaciones = [
        AsignacionInput(empleado_id=int(eid), rol=rol)
        for eid, rol in zip(empleado_ids, roles)
        if eid and rol
    ]

    # inventario: catalogo_item_ids[] + cantidades[] + descripciones[]
    catalogo_ids = raw.getlist('catalogo_item_ids[]')
    cantidades = raw.getlist('cantidades[]')
    descripciones = raw.getlist('descripciones[]')
    inventario = [
        ItemInventarioInput(
            catalogo_item_id=int(cid) if cid else None,
            cantidad=int(cant),
            descripcion=desc,
        )
        for cid, cant, desc in zip(catalogo_ids, cantidades, descripciones)
        if cant and int(cant) > 0
    ]

    return MudanzaCreateInput(
        cliente_id=cliente_id,
        fecha_hora=fecha_hora,
        necesita_ayudantes=raw.get('necesita_ayudantes') == '1',
        camion_id=camion_id,
        monto_senia=monto_senia,
        origen=origen,
        destino=destino,
        asignaciones=asignaciones,
        inventario=inventario,
    )


def _parsear_direccion(raw, prefijo: str) -> DireccionInput | None:
    calle = raw.get(f"{prefijo}_calle", "").strip()
    if not calle:
        return None
    return DireccionInput(
        calle=calle,
        numero=raw.get(f"{prefijo}_numero", "").strip(),
        localidad=raw.get(f"{prefijo}_localidad", "").strip(),
        provincia=raw.get(f"{prefijo}_provincia", "").strip(),
        codigo_postal=raw.get(f"{prefijo}_codigo_postal", "").strip(),
        piso=raw.get(f"{prefijo}_piso", "").strip(),
        departamento=raw.get(f"{prefijo}_departamento", "").strip(),
        tiene_ascensor=raw.get(f"{prefijo}_tiene_ascensor") == '1',
        ascensor_grande=raw.get(f"{prefijo}_ascensor_grande") == '1',
        capacidad_ascensor_kg=int(raw[f"{prefijo}_capacidad_ascensor_kg"]) if raw.get(
            f"{prefijo}_capacidad_ascensor_kg") else None,
    )


def _obtener_contexto_formulario(fecha=None) -> dict:
    """
    Carga los selectores necesarios para el formulario de nueva mudanza.
    Dos queries simples, sin logica en el template.
    """

    from gestion.models.clientes import Cliente
    from gestion.models.catalogo import CatalogoItem
    from gestion.services.flota_service import obtener_camiones_disponibles_para_fecha

    clientes = list(
        Cliente.objects.order_by("nombre_completo").values('id', 'nombre_completo', 'telefono')
    )
    if fecha is not None:
        camiones = obtener_camiones_disponibles_para_fecha(fecha)
    else:
        camiones = list(
            Camion.objects.filter(activo=True).order_by('patente').values('id', 'patente', 'modelo', 'categoria_label')
        )

    empleados = list(
        Empleado.objects.filter(disponible=True).order_by('nombre').values('id', 'nombre', 'rol')
    )
    catalogo = list(
        CatalogoItem.objects.order_by('nombre').values('id', 'nombre', 'volumen_m3', 'peso_estimado_kg')
    )
    roles = [{'valor': r.value, 'label': r.label} for r in Empleado.Rol]

    return {
        'clientes_disponibles': clientes,
        "camiones_disponibles": camiones,
        'fecha_filtro_camiones': fecha.isoformat() if fecha else None,
        'empleados_disponibles': empleados,
        'catalogo_items': catalogo,
        'opciones_rol': roles,
    }
