from datetime import date

from django.core.management.base import BaseCommand

from api.models import Estudiante, EstudianteModulo, Modulo, Rubro


class Command(BaseCommand):
    help = "Carga los datos de ejemplo del documento (Juan Pérez)."

    def handle(self, *args, **opts):
        juan, _ = Estudiante.objects.get_or_create(
            cedula="0912345678",
            defaults=dict(nombres="Juan", apellidos="Pérez", correo="juan.perez@example.com",
                          telefono="0999999999", direccion="Quevedo"),
        )
        datos = [
            ("Base de Datos", "EN_CURSO", 65),
            ("Programación", "FINALIZADO", 100),
            ("Redes", "PENDIENTE", 0),
        ]
        for nombre, estado, prog in datos:
            mod, _ = Modulo.objects.get_or_create(nombre=nombre)
            EstudianteModulo.objects.get_or_create(
                estudiante=juan, modulo=mod, defaults=dict(estado=estado, progreso=prog)
            )
        Rubro.objects.get_or_create(
            estudiante=juan, concepto="Matrícula",
            defaults=dict(valor=100, fecha_vencimiento=date(2026, 9, 30), estado_pago="PAGADO"),
        )
        Rubro.objects.get_or_create(
            estudiante=juan, concepto="Mensualidad",
            defaults=dict(valor=80, fecha_vencimiento=date(2026, 10, 15), estado_pago="PENDIENTE"),
        )
        self.stdout.write(self.style.SUCCESS("Datos de ejemplo cargados."))
