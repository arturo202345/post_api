"""Páginas web (templates) equivalentes a las pantallas de la app Flutter.

Usan la sesión de Django, pero la misma tabla de usuarios que la API: quien se registra
en la web puede iniciar sesión en la app con el mismo usuario y contraseña (y viceversa).
"""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db.models import Avg
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .serializers import RegisterSerializer
from .servicios import dashboard_estudiante

INTENTOS_MAX = 10  # intentos fallidos de login permitidos...
VENTANA = 300  # ...cada 5 minutos por IP


# ---------- utilidades ----------


def estudiante_requerido(vista):
    """Exige sesión iniciada y una ficha de estudiante asociada."""

    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        est = getattr(request.user, "estudiante", None)
        if est is None:
            logout(request)
            return redirect(settings.LOGIN_URL)
        request.estudiante = est
        return vista(request, *args, **kwargs)

    return envoltura


def _clave_intentos(request):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
        "REMOTE_ADDR", ""
    )
    return f"login-fallos:{ip}"


def _bloqueado(request):
    return cache.get(_clave_intentos(request), 0) >= INTENTOS_MAX


def _registrar_fallo(request):
    clave = _clave_intentos(request)
    cache.add(clave, 0, VENTANA)
    try:
        cache.incr(clave)
    except ValueError:
        cache.set(clave, 1, VENTANA)


def _destino_seguro(request, por_defecto="web:resumen"):
    destino = request.POST.get("next") or request.GET.get("next")
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return por_defecto


# ---------- autenticación ----------


def inicio(request):
    return redirect("web:resumen" if request.user.is_authenticated else "web:login")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("web:resumen")
    error = None
    if request.method == "POST":
        if _bloqueado(request):
            error = "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo."
        else:
            user = authenticate(
                request,
                username=request.POST.get("username", "").strip(),
                password=request.POST.get("password", ""),
            )
            if user is None:
                _registrar_fallo(request)
                error = "Usuario o contraseña incorrectos."
            elif getattr(user, "estudiante", None) is None:
                if user.is_staff:
                    login(request, user)
                    return redirect("/admin/")
                error = "Esta cuenta no tiene un estudiante asociado."
            else:
                cache.delete(_clave_intentos(request))
                login(request, user)
                return redirect(_destino_seguro(request))
    return render(
        request,
        "web/login.html",
        {"error": error, "usuario": request.POST.get("username", ""), "next": request.GET.get("next", "")},
    )


CAMPOS_REGISTRO = [
    # (nombre, etiqueta, tipo, autocompletar)
    ("nombres", "Nombres", "text", "given-name"),
    ("apellidos", "Apellidos", "text", "family-name"),
    ("cedula", "Cédula", "text", "off"),
    ("email", "Correo", "email", "email"),
    ("telefono", "Teléfono (opcional)", "tel", "tel"),
    ("username", "Usuario", "text", "username"),
    ("password", "Contraseña", "password", "new-password"),
    ("password2", "Repite la contraseña", "password", "new-password"),
]


def registro_view(request):
    if request.user.is_authenticated:
        return redirect("web:resumen")
    datos, errores = {}, {}
    if request.method == "POST":
        datos = request.POST
        # Mismas reglas que el registro de la app: se reutiliza el serializer de la API.
        ser = RegisterSerializer(data=datos)
        valido = ser.is_valid()
        errores = {campo: [str(e) for e in lista] for campo, lista in ser.errors.items()}
        if datos.get("password") != datos.get("password2"):
            errores["password2"] = ["Las contraseñas no coinciden."]
        if valido and not errores:
            user = ser.save()
            login(request, user)
            messages.success(
                request,
                "Cuenta creada. Con este mismo usuario y contraseña también puedes entrar a la app.",
            )
            return redirect("web:resumen")
    campos = [
        {
            "name": n,
            "label": etiqueta,
            "type": tipo,
            "auto": auto,
            "value": "" if tipo == "password" else datos.get(n, ""),
            "errores": errores.get(n, []),
        }
        for n, etiqueta, tipo, auto in CAMPOS_REGISTRO
    ]
    conocidos = {c[0] for c in CAMPOS_REGISTRO}
    otros = [m for campo, lista in errores.items() if campo not in conocidos for m in lista]
    return render(request, "web/registro.html", {"campos": campos, "otros_errores": otros})


@require_POST
def salir(request):
    logout(request)
    return redirect("web:login")


# ---------- páginas del estudiante ----------


@estudiante_requerido
def resumen(request):
    d = dashboard_estudiante(request.estudiante)
    v, pv, pe = d["rubros_vencidos"], d["rubros_por_vencer"], d["rubros_pendientes"]
    alerta = None
    if d["hay_pagos_pendientes"]:
        if v["cantidad"] > 0:
            alerta = {
                "clase": "rojo",
                "titulo": f"{v['cantidad']} rubro(s) vencido(s)",
                "detalle": f"Debes ${float(v['total']):.2f}. Regulariza tu pago.",
            }
        elif pv["cantidad"] > 0:
            alerta = {
                "clase": "naranja",
                "titulo": f"{pv['cantidad']} rubro(s) por vencer",
                "detalle": f"Vencen en los próximos {d['dias_alerta']} días · ${float(pv['total']):.2f}",
            }
        else:
            alerta = {
                "clase": "gris",
                "titulo": "Tienes pagos pendientes",
                "detalle": f"{pe['cantidad']} rubro(s) · ${float(pe['total']):.2f}",
            }
    return render(
        request,
        "web/resumen.html",
        {
            "pagina": "resumen",
            "d": d,
            "alerta": alerta,
            "primer_nombre": request.estudiante.nombres.split()[0] if request.estudiante.nombres else "",
            "modulos": request.estudiante.inscripciones.select_related("modulo").order_by("modulo__nombre"),
        },
    )


@estudiante_requerido
def progreso(request):
    inscripciones = request.estudiante.inscripciones.select_related("modulo").order_by("modulo__nombre")
    general = round(inscripciones.aggregate(a=Avg("progreso"))["a"] or 0, 1)
    return render(
        request,
        "web/progreso.html",
        {"pagina": "progreso", "inscripciones": inscripciones, "general": general},
    )


FILTROS_RUBRO = ["TODOS", "PENDIENTE", "PAGADO", "VENCIDO"]


@estudiante_requerido
def rubros(request):
    filtro = request.GET.get("estado", "TODOS")
    if filtro not in FILTROS_RUBRO:
        filtro = "TODOS"
    hoy = timezone.localdate()
    lista = []
    for r in request.estudiante.rubros.all():
        r.estado_ef = r.estado_efectivo
        if filtro != "TODOS" and r.estado_ef != filtro:
            continue
        d = (r.fecha_vencimiento - hoy).days
        if r.estado_ef == "PAGADO":
            r.cuando = ""
        elif d == 0:
            r.cuando = "vence hoy"
        elif d > 0:
            r.cuando = f"en {d} día(s)"
        else:
            r.cuando = f"hace {-d} día(s)"
        lista.append(r)
    return render(
        request,
        "web/rubros.html",
        {"pagina": "rubros", "rubros": lista, "filtro": filtro, "filtros": FILTROS_RUBRO},
    )


@estudiante_requerido
def perfil(request):
    return render(request, "web/perfil.html", {"pagina": "perfil", "est": request.estudiante})
