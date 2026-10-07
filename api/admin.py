from django.contrib import admin
from django.utils.html import format_html

from .models import Estudiante, EstudianteModulo, Modulo, Rubro

admin.site.site_header = "gestión académica"
admin.site.site_title = "Gestión Académica"
admin.site.index_title = "Panel de administración"

# (texto, fondo) de cada estado; mismos colores que la web y la app.
_COLORES = {
    "PAGADO": ("#16a34a", "rgba(22,163,74,.12)"),
    "FINALIZADO": ("#16a34a", "rgba(22,163,74,.12)"),
    "VENCIDO": ("#dc2626", "rgba(220,38,38,.12)"),
    "PENDIENTE": ("#B45309", "rgba(194,98,10,.12)"),
    "EN_CURSO": ("#2563eb", "rgba(37,99,235,.12)"),
}


def _pill(valor, etiqueta):
    texto, fondo = _COLORES.get(valor, ("#555", "#eee"))
    return format_html(
        '<span class="pill-estado" style="color:{};background:{}">{}</span>', texto, fondo, etiqueta
    )


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
    list_display = ("estudiante", "modulo", "estado_", "progreso")
    list_filter = ("estado",)

    @admin.display(description="Estado", ordering="estado")
    def estado_(self, obj):
        return _pill(obj.estado, obj.get_estado_display())


@admin.register(Rubro)
class RubroAdmin(admin.ModelAdmin):
    list_display = ("concepto", "estudiante", "valor", "fecha_vencimiento", "estado_")
    list_filter = ("estado_pago",)
    search_fields = ("concepto", "estudiante__apellidos", "estudiante__cedula")

    @admin.display(description="Estado de pago", ordering="estado_pago")
    def estado_(self, obj):
        # estado efectivo: un pendiente con fecha pasada se ve como vencido
        estado = Rubro.EstadoPago(obj.estado_efectivo)  # puede llegar como str o como enum
        return _pill(estado.value, estado.label)
