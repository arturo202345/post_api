from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg, Count
from django.utils import timezone
from rest_framework import filters, generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Estudiante, EstudianteModulo, Modulo, Rubro
from .servicios import (
    MENSAJE_CODIGO,
    CodigoInvalido,
    dashboard_estudiante,
    filtrar_estado_pago,
    restablecer_clave,
    resumen as _resumen,
    solicitar_codigo,
)
from .serializers import (
    EstudianteModuloSerializer,
    EstudianteSerializer,
    LoginSerializer,
    ModuloSerializer,
    PerfilSerializer,
    RecuperarSerializer,
    RegisterSerializer,
    RestablecerSerializer,
    RubroSerializer,
    datos_usuario,
)


# ---------- utilidades ----------


def _dias(request, default):
    """Lee ?dias= de forma segura (si no es un número válido usa el valor por defecto)."""
    try:
        return max(0, min(int(request.query_params.get("dias", default)), 365))
    except (TypeError, ValueError):
        return default


class TieneEstudiante(permissions.IsAuthenticated):
    """Usuario autenticado que tiene una ficha de estudiante asociada."""

    message = "Tu usuario no tiene un estudiante asociado."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and hasattr(request.user, "estudiante")


# ---------- autenticación ----------


class RegisterView(generics.GenericAPIView):
    """Crea el usuario y su ficha de estudiante, y devuelve los tokens (queda con sesión iniciada)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "usuario": datos_usuario(user),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RecuperarView(generics.GenericAPIView):
    """Paso 1: recibe la cédula y envía un código al correo. La respuesta es siempre la misma."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = RecuperarSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        solicitar_codigo(ser.validated_data["cedula"])
        return Response({"detail": MENSAJE_CODIGO})


class RestablecerView(generics.GenericAPIView):
    """Paso 2: cédula + código del correo + nueva contraseña."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = RestablecerSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            restablecer_clave(d["cedula"], d["codigo"], d["password"])
        except CodigoInvalido as e:
            raise serializers.ValidationError({"codigo": [str(e)]})
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})
        return Response({"detail": "Contraseña actualizada. Ya puedes iniciar sesión."})


# ---------- "mis datos" (el estudiante autenticado) ----------


class MeView(APIView):
    permission_classes = [TieneEstudiante]

    def get(self, request):
        return Response(EstudianteSerializer(request.user.estudiante).data)

    def patch(self, request):
        est = request.user.estudiante
        ser = PerfilSerializer(est, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(EstudianteSerializer(est).data)


class MisInscripcionesView(generics.ListAPIView):
    permission_classes = [TieneEstudiante]
    serializer_class = EstudianteModuloSerializer

    def get_queryset(self):
        qs = EstudianteModulo.objects.filter(estudiante=self.request.user.estudiante).select_related(
            "estudiante", "modulo"
        )
        estado = self.request.query_params.get("estado")
        return (qs.filter(estado=estado) if estado else qs).order_by("modulo__nombre")


class MisRubrosView(generics.ListAPIView):
    """Rubros del estudiante. Filtro opcional: ?estado_pago=PENDIENTE|PAGADO|VENCIDO."""

    permission_classes = [TieneEstudiante]
    serializer_class = RubroSerializer

    def get_queryset(self):
        qs = Rubro.objects.filter(estudiante=self.request.user.estudiante).select_related("estudiante")
        return filtrar_estado_pago(qs, self.request.query_params.get("estado_pago"))


class MiDashboardView(APIView):
    """Resumen personal: progreso, módulos y estado de los pagos (con alerta de pendientes)."""

    permission_classes = [TieneEstudiante]

    def get(self, request):
        return Response(dashboard_estudiante(request.user.estudiante))


# ---------- administración (solo staff) ----------


class EstudianteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = Estudiante.objects.annotate(progreso_promedio=Avg("inscripciones__progreso")).order_by(
        "apellidos", "nombres"
    )
    serializer_class = EstudianteSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["cedula", "nombres", "apellidos", "correo"]
    ordering_fields = ["apellidos", "nombres", "progreso_promedio"]

    def get_queryset(self):
        qs = super().get_queryset()
        estado = self.request.query_params.get("estado")
        return qs.filter(estado=estado) if estado else qs

    @action(detail=True, methods=["get"])
    def progreso(self, request, pk=None):
        """Reporte de progreso: módulos del estudiante + porcentaje general."""
        est = self.get_object()
        inscripciones = est.inscripciones.select_related("modulo", "estudiante")
        return Response(
            {
                "estudiante": est.nombre_completo,
                "progreso_general": EstudianteSerializer(est).data["progreso_general"],
                "modulos": EstudianteModuloSerializer(inscripciones, many=True).data,
            }
        )

    @action(detail=True, methods=["get"])
    def rubros(self, request, pk=None):
        est = self.get_object()
        qs = est.rubros.select_related("estudiante")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(RubroSerializer(page, many=True).data)


class ModuloViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = Modulo.objects.all()
    serializer_class = ModuloSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre", "descripcion"]
    ordering_fields = ["nombre", "fecha_inicio"]


class EstudianteModuloViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = EstudianteModulo.objects.select_related("estudiante", "modulo")
    serializer_class = EstudianteModuloSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["progreso", "fecha_inicio"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        for campo in ("estudiante", "modulo", "estado"):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        return qs


class RubroViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = Rubro.objects.select_related("estudiante")
    serializer_class = RubroSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["concepto", "estudiante__nombres", "estudiante__apellidos"]
    ordering_fields = ["fecha_vencimiento", "valor"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("estudiante"):
            qs = qs.filter(estudiante=p["estudiante"])
        return filtrar_estado_pago(qs, p.get("estado_pago"))

    @action(detail=False, methods=["get"], url_path="por-vencer")
    def por_vencer(self, request):
        """Rubros pendientes que vencen en los próximos N días (?dias=5)."""
        dias = _dias(request, settings.DIAS_ALERTA_RUBRO)
        hoy = timezone.localdate()
        qs = self.get_queryset().filter(
            estado_pago=Rubro.EstadoPago.PENDIENTE,
            fecha_vencimiento__range=(hoy, hoy + timedelta(days=dias)),
        )
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def vencidos(self, request):
        """Rubros no pagados cuya fecha de vencimiento ya pasó."""
        qs = self.get_queryset().exclude(estado_pago=Rubro.EstadoPago.PAGADO).filter(
            fecha_vencimiento__lt=timezone.localdate()
        )
        return Response(self.get_serializer(qs, many=True).data)


class DashboardView(APIView):
    """Resumen global (solo administradores)."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        hoy = timezone.localdate()
        dias = settings.DIAS_ALERTA_RUBRO
        no_pagados = Rubro.objects.exclude(estado_pago=Rubro.EstadoPago.PAGADO)
        return Response(
            {
                "estudiantes_activos": Estudiante.objects.filter(estado=Estudiante.Estado.ACTIVO).count(),
                "modulos": Modulo.objects.count(),
                "progreso_promedio": round(
                    EstudianteModulo.objects.aggregate(a=Avg("progreso"))["a"] or 0, 1
                ),
                "inscripciones_por_estado": {
                    r["estado"]: r["n"]
                    for r in EstudianteModulo.objects.values("estado").annotate(n=Count("id"))
                },
                "rubros_pendientes": _resumen(no_pagados.filter(fecha_vencimiento__gte=hoy)),
                "rubros_por_vencer": _resumen(
                    no_pagados.filter(fecha_vencimiento__range=(hoy, hoy + timedelta(days=dias)))
                ),
                "rubros_vencidos": _resumen(no_pagados.filter(fecha_vencimiento__lt=hoy)),
            }
        )
