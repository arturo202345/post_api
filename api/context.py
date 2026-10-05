from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Rubro


def web_contexto(request):
    """Datos de la cabecera web: campana (rubros vencidos o por vencer) e iniciales del avatar."""
    user = getattr(request, "user", None)
    est = getattr(user, "estudiante", None) if user is not None and user.is_authenticated else None
    if est is None:
        return {}
    limite = timezone.localdate() + timedelta(days=settings.DIAS_ALERTA_RUBRO)
    avisos = (
        est.rubros.exclude(estado_pago=Rubro.EstadoPago.PAGADO).filter(fecha_vencimiento__lte=limite).count()
    )
    iniciales = "".join(p[0] for p in est.nombre_completo.split()[:2]).upper() or "?"
    return {"nav_avisos": avisos, "nav_iniciales": iniciales}
