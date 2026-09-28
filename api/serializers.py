from django.db.models import Avg
from django.utils import timezone
from rest_framework import serializers

from .models import Estudiante, EstudianteModulo, Modulo, Rubro


class EstudianteSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.CharField(read_only=True)
    progreso_general = serializers.SerializerMethodField()

    class Meta:
        model = Estudiante
        fields = "__all__"

    def get_progreso_general(self, obj):
        avg = getattr(obj, "progreso_promedio", None)
        if avg is None:
            avg = obj.inscripciones.aggregate(a=Avg("progreso"))["a"]
        return round(avg or 0, 1)


class ModuloSerializer(serializers.ModelSerializer):
    class Meta:
        model = Modulo
        fields = "__all__"

    def validate(self, attrs):
        inicio = attrs.get("fecha_inicio", getattr(self.instance, "fecha_inicio", None))
        fin = attrs.get("fecha_fin", getattr(self.instance, "fecha_fin", None))
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError("fecha_fin no puede ser anterior a fecha_inicio.")
        return attrs


class EstudianteModuloSerializer(serializers.ModelSerializer):
    estudiante_nombre = serializers.CharField(source="estudiante.nombre_completo", read_only=True)
    modulo_nombre = serializers.CharField(source="modulo.nombre", read_only=True)

    class Meta:
        model = EstudianteModulo
        fields = "__all__"
        validators = []  # el UniqueConstraint se valida abajo con mensaje propio

    def validate(self, attrs):
        get = lambda k, d=None: attrs.get(k, getattr(self.instance, k, d))
        estado, progreso = get("estado", EstudianteModulo.Estado.PENDIENTE), get("progreso", 0)
        inicio, fin = get("fecha_inicio"), get("fecha_finalizacion")

        if estado == EstudianteModulo.Estado.FINALIZADO and progreso != 100:
            raise serializers.ValidationError({"progreso": "Un módulo FINALIZADO debe tener progreso 100."})
        if estado == EstudianteModulo.Estado.PENDIENTE and progreso != 0:
            raise serializers.ValidationError({"progreso": "Un módulo PENDIENTE debe tener progreso 0."})
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError("fecha_finalizacion no puede ser anterior a fecha_inicio.")

        estudiante, modulo = get("estudiante"), get("modulo")
        duplicado = EstudianteModulo.objects.filter(estudiante=estudiante, modulo=modulo)
        if self.instance:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError("El estudiante ya está matriculado en este módulo.")
        return attrs


class RubroSerializer(serializers.ModelSerializer):
    estudiante_nombre = serializers.CharField(source="estudiante.nombre_completo", read_only=True)
    estado_efectivo = serializers.CharField(read_only=True)
    dias_para_vencer = serializers.SerializerMethodField()

    class Meta:
        model = Rubro
        fields = "__all__"

    def get_dias_para_vencer(self, obj):
        return (obj.fecha_vencimiento - timezone.localdate()).days

    def validate(self, attrs):
        emision = attrs.get("fecha_emision", getattr(self.instance, "fecha_emision", None))
        venc = attrs.get("fecha_vencimiento", getattr(self.instance, "fecha_vencimiento", None))
        if emision and venc and venc < emision:
            raise serializers.ValidationError("fecha_vencimiento no puede ser anterior a fecha_emision.")
        return attrs