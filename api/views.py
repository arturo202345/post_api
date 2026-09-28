from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.utils import timezone
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Estudiante, EstudianteModulo, Modulo, Rubro
from .serializers import (
    EstudianteModuloSerializer,
    EstudianteSerializer,
    ModuloSerializer,
    RubroSerializer,
)


class EstudianteViewSet(viewsets.ModelViewSet):
    queryset = Estudiante.objects.annotate(progreso_promedio=Avg("inscripciones__progreso"))
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
        return Response(RubroSerializer(est.rubros.select_related("estudiante"), many=True).data)


class ModuloViewSet(viewsets.ModelViewSet):
    queryset = Modulo.objects.all()
    serializer_class = ModuloSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre", "descripcion"]
    ordering_fields = ["nombre", "fecha_inicio"]


class EstudianteModuloViewSet(viewsets.ModelViewSet):
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
        if p.get("estado_pago"):
            qs = qs.filter(estado_pago=p["estado_pago"])
        return qs

    @action(detail=False, methods=["get"], url_path="por-vencer")
    def por_vencer(self, request):
        """Rubros pendientes que vencen en los próximos N días (?dias=7)."""
        dias = int(request.query_params.get("dias", 7))
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
    """Resumen general para el dashboard de la app."""

    def get(self, request):
        hoy = timezone.localdate()
        no_pagados = Rubro.objects.exclude(estado_pago=Rubro.EstadoPago.PAGADO)
        vencidos = no_pagados.filter(fecha_vencimiento__lt=hoy)
        por_vencer = no_pagados.filter(fecha_vencimiento__range=(hoy, hoy + timedelta(days=7)))
        pendientes = no_pagados.filter(fecha_vencimiento__gte=hoy)

        def resumen(qs):
            return qs.aggregate(cantidad=Count("id"), total=Sum("valor"))

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
                "rubros_pendientes": resumen(pendientes),
                "rubros_por_vencer_7_dias": resumen(por_vencer),
                "rubros_vencidos": resumen(vencidos),
            }
        )