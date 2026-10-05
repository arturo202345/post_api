"""Lógica compartida entre la API (JSON) y las páginas web (templates)."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import Rubro


def resumen(qs):
    r = qs.aggregate(cantidad=Count("id"), total=Sum("valor"))
    return {"cantidad": r["cantidad"], "total": r["total"] or 0}


def dashboard_estudiante(est):
    """Resumen personal: progreso, módulos y estado de los pagos."""
    hoy = timezone.localdate()
    dias = settings.DIAS_ALERTA_RUBRO
    no_pagados = est.rubros.exclude(estado_pago=Rubro.EstadoPago.PAGADO)
    insc = est.inscripciones
    return {
        "estudiante": est.nombre_completo,
        "modulos": insc.count(),
        "progreso_promedio": round(insc.aggregate(a=Avg("progreso"))["a"] or 0, 1),
        "inscripciones_por_estado": {
            r["estado"]: r["n"] for r in insc.values("estado").annotate(n=Count("id"))
        },
        "hay_pagos_pendientes": no_pagados.exists(),
        "dias_alerta": dias,
        # vencidos: fecha pasada | por_vencer: vencen en los próximos `dias_alerta` días
        # pendientes: no pagados que aún no vencen (incluye a los por_vencer)
        "rubros_vencidos": resumen(no_pagados.filter(fecha_vencimiento__lt=hoy)),
        "rubros_por_vencer": resumen(
            no_pagados.filter(fecha_vencimiento__range=(hoy, hoy + timedelta(days=dias)))
        ),
        "rubros_pendientes": resumen(no_pagados.filter(fecha_vencimiento__gte=hoy)),
    }
