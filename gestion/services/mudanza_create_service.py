from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from gestion.models import Cliente
from gestion.models.auditoria import HistorialEstado
from gestion.models.clientes import Cliente
from gestion.models.direcciones import Direccion
from gestion.models.flota import Camion, Empleado
from gestion.models.mudanzas import AsignacionEmpleado, ItemInventario, Mudanza

# DTOs de entrada - construir desde la request en la vista

@dataclass(frozen=True)
class DireccionInput:
    calle: str
    numero: str
    localidad: str
    provincia: str
    codigo_postal: str
    piso: str = "PB"
    departamento: str = ""
    tiene_ascensor: bool = False
    ascensor_grande: bool = False
    capacidad_ascensor_kg: Optional[int] = None

@dataclass(frozen=True)
class ItemInventarioInput:
    cantidad: int
    catalogo_item_id: Optional[int] = None
    descripcion: str = ""


@dataclass(frozen=True)
class AsignacionInput:
    empleado_id: int
    rol: str


@dataclass(frozen=True)
class MudanzaCreateInput:
    cliente_id: int
    fecha_hora: datetime
    necesita_ayudantes: bool = True
    camion_id: Optional[int] = None
    monto_senia: Optional[Decimal] = None
    origen: Optional[DireccionInput] = None
    asignaciones: list[AsignacionInput] = field(default_factory=list)
    inventario: list[ItemInventarioInput] = field(default_factory=list)

# Validaciones

def _validar_cliente(cliente_id: int) -> Cliente:
    try:
        return Cliente.objects.get(pk=cliente_id)
    except Cliente.DoesNotExist:
        raise ValidationError(f'Cliente con id={cliente_id} no existe')

def _validar_camion(camion_id: int, fecha_hora: datetime) -> Camion:
    try:
        camion = Camion.objects.get(pk=camion_id, activo=True)
    except Camion.DoesNotExist:
        raise ValidationError(f'Camión con id={camion_id} no existe o esta inactivo.')

    # Conflicto de agenda: el camion ya tiene una mudanza confirmada/en curso ese dia
    conflicto = Mudanza.objects.filter(
        camion=camion,
        fecha_hora__date=fecha_hora.date(),
        estado__in=[Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO],
    ).exists()

    if conflicto:
        raise ValidationError(
            f'El camion {camion.patente} ya tiene una mudanza asignada'
            f'para el {fecha_hora.strftime("%d/%m/%Y")}.'
        )

    return camion

def _validar_asignaciones(
        asignaciones: list[AsignacionInput],
        fecha_hora: datetime,) -> list[tuple[Empleado, str]]:
    """
    Valida cada empleado y retorna lista de (Empleado, rol) lista para persistir.
    Raises ValidationError con todos los errores acumulados.
    """
    errores: list[str] = []
    resultado: list[tuple[Empleado, str]] = []
    fecha = fecha_hora.date()

    for a in asignaciones:
        if a.rol not in Empleado.Rol.values:
            errores.append(f"Rol '{a.rol} no es valido.")
            continue

        try:
            empleado = Empleado.objects.get(pk=a.empleado_id)
        except Empleado.DoesNotExist:
            errores.append(f"Empleado con id={a.empleado_id} no existe")
            continue

        if not empleado.disponible:
            errores.append(f'{empleado.nombre} esta marcado como no disponible.')
            continue

        ocupado = AsignacionEmpleado.objects.filter(
            empleado=empleado,
            mudanza__fecha_hora__date=fecha,
            mudanza__estado__in=[Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO],
        ).exists()

        if ocupado:
            errores.append(
                f"{empleado.nombre} ya tiene una mudanza asignada el "
                f"{fecha_hora.strftime('%d/%m/%Y')}."
            )
            continue

        resultado.append((empleado, a.rol))

    if errores:
        raise ValidationError(errores)

    return resultado

def _validar_monto_senia(monto: Optional[Decimal]) -> Optional[Decimal]:
    if monto is None:
        return None
    if monto <= 0:
        raise ValidationError('monto_senia debe ser mayor a cero.')
    return monto.quantize(Decimal('0.01'))

# Creacion de entidades auxiliares

def _crear_direccion(data: DireccionInput) -> Direccion:
    return Direccion.objects.create(
        calle=data.calle.strip(),
        numero=data.numero.strip(),
        localidad=data.localidad.strip(),
        provincia=data.provincia.strip(),
        codigo_postal=data.codigo_postal.strip(),
        piso=data.piso or 'PB',
        departamento=data.departamento or None,
        tiene_ascensor=data.tiene_ascensor,
        ascensor_grande=data.ascensor_grande,
        capacidad_ascensor_kg=data.capacidad_ascensor_kg,
    )

# Serializacion de salida

def _serializar_mudanza_creada(mudanza: Mudanza) -> dict:
    """
    Contexto listo para renderizar en la vista post-creacion.
    El frontend NO debe procesar nada de este dict.
    """
    return {
        'id': mudanza.pk,
        'uuid': str(mudanza.uuid),
        'url_detalle': f'/gestion/mudanzas/{mudanza.pk}/',
        'cliente_nombre': mudanza.cliente.nombre_completo,
        'cliente_telefono': mudanza.cliente.telefono,
        'fecha_hora_display': timezone.localtime(mudanza.fecha_hora).strftime('%-d de %B de %Y a las %H:%M'),
        'estado_valor': mudanza.estado,
        'estado_label': mudanza.get_estado_display(),
        'camion_display': mudanza.camion.patente if mudanza.camion else 'Sin asignar',
        'origen_display': (
            f'{mudanza.origen.calle} {mudanza.origen.numero}, {mudanza.origen.localidad}'
            if mudanza.origen else "Sin definir"
        ),
        'destino_display': (
            f'{mudanza.destino.calle} {mudanza.destino.numero}, {mudanza.origen.localidad}'
            if mudanza.origen else "Sin definir"
        ),
        'necesita_ayudantes': mudanza.necesita_ayudantes,
        'monto_senia_display': (
            f'${mudanza.monto_senia:,.0f}'
            if mudanza.monto_senia else "Sin definir"
        ),
        'total_asignaciones': mudanza.asignaciones.count(),
        'total_items_inventario': mudanza.inventario.count(),
    }

# API publica

class MudanzaCreateService:

    @staticmethod
    def crear(data: MudanzaCreateInput, usuario: User) -> dict:
        """
        Crea una Mudanza en estado BORRADOR con todas sus relaciones.

        Flujo:
            1. Validar cliente, camion, empleados y seña.
            2. Crear Direccion origen y destino (si se proveen).
            3. Crear Mudanza.
            4. Crear AsignacionEmpleado por cada empleado validado.
            5. Crear ItemInventario por cada item del inventario.
            6. Registrar HistorialEstado inicial (BORRADOR).
            7. Retornar contexto serializado.

        Args:
            data: DTO con todos los campos de entrada validados por la vista.
            usuario: request.user - necesario para Historialestado.

        Returns:
            dict listo para el template (ver _serializar_mudanza_creada).

        Raises:
            ValidationError: cualquier regla de negocio violada.
            Cliente.DoesNotExist: si cliente_id no existe (wrapped en ValidationError)
        """

        # Validaciones previas (fuera de la transaccion)
        cliente = _validar_cliente(data.cliente_id)
        camion = None

        if data.camion_id is not None:
            camion = _validar_camion(data.camion_id, data.fecha_hora)

        empleados_validados = _validar_asignaciones(data.asignaciones, data.fecha_hora)
        monto_senia = _validar_monto_senia(data.monto_senia)

        with transaction.atomic():
            # Direcciones
            origen = _crear_direccion(data.origen) if data.origen else None
            destino = _crear_direccion(data.destino) if data.destino else None

            # Mudanza principal
            mudanza = Mudanza.objects.create(
                cliente=cliente,
                camion=camion,
                fecha_hora=data.fecha_hora,
                origen=origen,
                destino=destino,
                necesita_ayudantes=data.necesita_ayudantes,
                monto_senia=monto_senia,
                estado=Mudanza.Estado.BORRADOR,
            )

            # Asignaciones
            AsignacionEmpleado.objects.bulk_create([
                AsignacionEmpleado(mudanza=mudanza, empleado=emp, rol=rol)
                for emp, rol in empleados_validados
            ])

            # Inventario
            ItemInventario.objects.bulk_create([
                ItemInventario(
                    mudanza=mudanza,
                    cantidad=item.cantidad,
                    catalogo_item_id=item.catalogo_item_id,
                    descripcion=item.descripcion,
                )
                for item in data.inventario
                if item.cantidad > 0
            ])

            # Audit trail - estado inicial
            HistorialEstado.objects.create(
                mudanza=mudanza,
                estado_anterior=Mudanza.Estado.BORRADOR,
                estado_nuev=Mudanza.Estado.BORRADOR,
                usuario=usuario,
            )

        # select_related para el serializer - fuera de la transaccion
        mudanza = (
            Mudanza.objects.select_related('cliente', 'camion', 'origen', 'destino').prefetch_related('asignaciones', 'inventario').get(pk=mudanza.pk)
        )

        return _serializar_mudanza_creada(mudanza)