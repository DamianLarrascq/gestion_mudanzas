"""
Carga o actualiza los ítems canónicos del catálogo de muebles.

Uso:
    python manage.py cargar_catalogo          # crea/actualiza
    python manage.py cargar_catalogo --dry-run  # previsualiza sin escribir
"""
from __future__ import annotations
from decimal import Decimal
from django.core.management.base import BaseCommand
from gestion.models.catalogo import CatalogoItem

CATALOGO: list[tuple[str, str, str, str]] = [
    # (nombre, volumen_m3, peso_estimado_kg, categoria)
    # Living
    ("Sillón 3 cuerpos", "2.100", "80.00", "LIVING"),
    ("Sillón 2 cuerpos", "1.400", "55.00", "LIVING"),
    ("Mesa de Comedor Grande", "1.200", "45.00", "LIVING"),
    ("Mesa Ratona", "0.350", "15.00", "LIVING"),
    ("Mueble TV (Modular)", "1.200", "60.00", "LIVING"),
    ("Biblioteca (por cuerpo)", "0.800", "40.00", "LIVING"),
    # Cocina / Lavadero
    ("Heladera Familiar", "1.200", "75.00", "COCINA"),
    ("Heladera Side by Side", "1.800", "110.00", "COCINA"),
    ("Lavarropas", "0.600", "65.00", "COCINA"),
    ("Cocina (4 hornallas)", "0.500", "45.00", "COCINA"),
    ("Lavavajillas", "0.600", "50.00", "COCINA"),
    ("Microondas", "0.120", "15.00", "COCINA"),
    # Dormitorio
    ("Sommier 2 Plazas (Conjunto)", "1.800", "70.00", "DORMITORIO"),
    ("Sommier 1 Plaza (Conjunto)", "0.900", "35.00", "DORMITORIO"),
    ("Placard 2 Cuerpos (Desarmado)", "1.500", "90.00", "DORMITORIO"),
    ("Mesita de Luz", "0.150", "12.00", "DORMITORIO"),
    ("Cómoda / Cajonera", "0.750", "40.00", "DORMITORIO"),
    # Oficina
    ("Escritorio Grande", "1.000", "35.00", "OFICINA"),
    ("Silla de Oficina", "0.400", "15.00", "OFICINA"),
    # Varios
    ("Bicicleta", "0.500", "15.00", "VARIOS"),
    ("Caja Grande", "0.250", "25.00", "VARIOS"),
    ("Caja Mediana", "0.150", "15.00", "VARIOS"),
]


class Command(BaseCommand):
    help = "Carga o actualiza los ítems canónicos del catálogo de muebles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué se haría sin escribir en la base de datos.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        creados = actualizados = 0

        for nombre, volumen, peso, categoria in CATALOGO:
            defaults = {
                "volumen_m3": Decimal(volumen),
                "peso_estimado_kg": Decimal(peso),
                "categoria": categoria,
            }

            if dry_run:
                exists = CatalogoItem.objects.filter(nombre=nombre).exists()
                accion = "ACTUALIZA" if exists else "CREA"
                self.stdout.write(f"  [{accion}] {nombre}")
                continue

            _, created = CatalogoItem.objects.update_or_create(
                nombre=nombre,
                defaults=defaults,
            )
            if created:
                creados += 1
            else:
                actualizados += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: ningún cambio persistido."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Catálogo sincronizado: {creados} creados, {actualizados} actualizados."
                )
            )
