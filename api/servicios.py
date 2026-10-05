"""Lógica compartida entre la API (JSON) y las páginas web (templates)."""
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import CodigoRecuperacion, Estudiante, Rubro

log = logging.getLogger(__name__)

VIGENCIA_CODIGO = timedelta(minutes=15)  # tiempo que sirve un código
ESPERA_CODIGO = timedelta(seconds=60)  # mínimo entre un código y el siguiente
INTENTOS_CODIGO = 5  # intentos fallidos permitidos por código

MENSAJE_CODIGO = "Si la cédula está registrada, enviamos un código al correo del estudiante."


def resumen(qs):
    r = qs.aggregate(cantidad=Count("id"), total=Sum("valor"))
    return {"cantidad": r["cantidad"], "total": r["total"] or 0}


def filtrar_estado_pago(qs, estado):
    """Filtra rubros por estado EFECTIVO (igual que el campo `estado_efectivo`):
    un PENDIENTE cuya fecha ya pasó cuenta como VENCIDO."""
    hoy = timezone.localdate()
    P = Rubro.EstadoPago
    if estado == P.VENCIDO:
        return qs.filter(
            Q(estado_pago=P.VENCIDO) | Q(estado_pago=P.PENDIENTE, fecha_vencimiento__lt=hoy)
        )
    if estado == P.PENDIENTE:
        return qs.filter(estado_pago=P.PENDIENTE, fecha_vencimiento__gte=hoy)
    if estado == P.PAGADO:
        return qs.filter(estado_pago=P.PAGADO)
    return qs


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


# ---------- recuperación de credenciales ----------


class CodigoInvalido(Exception):
    """El código no existe, venció, ya se usó o se agotaron los intentos."""


def _hash(user, codigo):
    return salted_hmac("recuperacion", f"{user.pk}:{codigo}").hexdigest()


def _estudiante_con_cuenta(cedula):
    est = Estudiante.objects.select_related("user").filter(cedula=(cedula or "").strip()).first()
    return est if est and est.user else None


def solicitar_codigo(cedula):
    """Envía al correo del estudiante un código de 6 dígitos (y su usuario).

    No dice si la cédula existe: quien llama muestra siempre MENSAJE_CODIGO.
    Si ya se envió uno hace menos de ESPERA_CODIGO, no manda otro.
    """
    est = _estudiante_con_cuenta(cedula)
    if est is None:
        return
    user = est.user
    correo = user.email or est.correo
    if not correo:
        return
    ahora = timezone.now()
    if user.codigos_recuperacion.filter(creado__gt=ahora - ESPERA_CODIGO).exists():
        return
    user.codigos_recuperacion.filter(usado=False).update(usado=True)  # solo vale el último
    codigo = f"{secrets.randbelow(10**6):06d}"
    CodigoRecuperacion.objects.create(user=user, codigo_hash=_hash(user, codigo))
    try:
        send_mail(
            "Recuperación de acceso · Gestión Académica",
            f"Hola {est.nombres},\n\n"
            f"Tu usuario es: {user.username}\n"
            f"Tu código para crear una nueva contraseña es: {codigo}\n\n"
            f"Vale por {int(VIGENCIA_CODIGO.total_seconds() // 60)} minutos. "
            "Si no lo pediste tú, ignora este mensaje.",
            None,  # DEFAULT_FROM_EMAIL
            [correo],
        )
    except Exception:  # un fallo de correo no debe revelar nada ni romper la petición
        log.exception("No se pudo enviar el código de recuperación")


def restablecer_clave(cedula, codigo, password):
    """Valida el código y cambia la contraseña. Lanza CodigoInvalido o ValidationError de Django."""
    error = CodigoInvalido("Código incorrecto o vencido. Pide uno nuevo.")
    est = _estudiante_con_cuenta(cedula)
    if est is None:
        raise error
    user = est.user
    c = (
        user.codigos_recuperacion.filter(usado=False, creado__gt=timezone.now() - VIGENCIA_CODIGO)
        .order_by("-creado")
        .first()
    )
    if c is None or c.intentos >= INTENTOS_CODIGO:
        raise error
    if not constant_time_compare(c.codigo_hash, _hash(user, (codigo or "").strip())):
        c.intentos += 1
        c.save(update_fields=["intentos"])
        raise error
    validate_password(password, user=user)  # si falla, el código sigue valiendo
    user.set_password(password)
    user.save(update_fields=["password"])
    c.usado = True
    c.save(update_fields=["usado"])
    return user
