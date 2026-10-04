from django.contrib import admin

from .models import Estudiante, EstudianteModulo, Modulo, Rubro


@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ("cedula", "apellidos", "nombres", "correo", "user", "estado")
    search_fields = ("cedula", "nombres", "apellidos", "correo", "user__username")
    list_filter = ("estado",)


@admin.register(Modulo)
class ModuloAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha_inicio", "fecha_fin", "estado")
    search_fields = ("nombre",)


@admin.register(EstudianteModulo)
class EstudianteModuloAdmin(admin.ModelAdmin):
    list_display = ("estudiante", "modulo", "estado", "progreso")
    list_filter = ("estado",)


@admin.register(Rubro)
class RubroAdmin(admin.ModelAdmin):
    list_display = ("concepto", "estudiante", "valor", "fecha_vencimiento", "estado_pago")
    list_filter = ("estado_pago",)
    search_fields = ("concepto", "estudiante__apellidos", "estudiante__cedula")
