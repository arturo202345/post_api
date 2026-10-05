from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Avg
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Estudiante, EstudianteModulo, Modulo, Rubro

User = get_user_model()


def datos_usuario(user):
    """Datos básicos de la sesión que la app guarda tras login/registro."""
    est = getattr(user, "estudiante", None)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "es_admin": user.is_staff,
        "estudiante_id": est.id if est else None,
        "nombre": est.nombre_completo if est else user.get_username(),
    }


# ---------- autenticación ----------


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    cedula = serializers.CharField(max_length=20)
    nombres = serializers.CharField(max_length=100)
    apellidos = serializers.CharField(max_length=100)
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    fecha_nacimiento = serializers.DateField(required=False, allow_null=True)

    def validate_username(self, v):
        v = v.strip()
        if User.objects.filter(username__iexact=v).exists():
            raise serializers.ValidationError("Este nombre de usuario ya está en uso.")
        return v

    def validate_email(self, v):
        v = v.strip().lower()
        if User.objects.filter(email__iexact=v).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return v

    def validate_cedula(self, v):
        return v.strip()

    def validate(self, attrs):
        try:
            validate_password(
                attrs["password"], user=User(username=attrs["username"], email=attrs["email"])
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        # Si el administrador ya cargó la ficha del estudiante, se enlaza (solo si el correo coincide).
        ficha = Estudiante.objects.filter(cedula=attrs["cedula"]).first()
        if ficha:
            if ficha.user_id:
                raise serializers.ValidationError({"cedula": "Esta cédula ya tiene una cuenta registrada."})
            if not ficha.correo or ficha.correo.lower() != attrs["email"]:
                raise serializers.ValidationError(
                    {
                        "cedula": "Esta cédula ya está registrada en el sistema. "
                        "Usa el mismo correo con el que fuiste inscrito o contacta al administrador."
                    }
                )
        attrs["ficha"] = ficha
        return attrs

    @transaction.atomic
    def create(self, vd):
        ficha = vd.pop("ficha")
        user = User.objects.create_user(
            username=vd["username"], email=vd["email"], password=vd["password"]
        )
        if ficha:
            ficha.user = user
            ficha.save(update_fields=["user"])
        else:
            Estudiante.objects.create(
                user=user,
                cedula=vd["cedula"],
                nombres=vd["nombres"],
                apellidos=vd["apellidos"],
                correo=vd["email"],
                telefono=vd.get("telefono", ""),
                fecha_nacimiento=vd.get("fecha_nacimiento"),
            )
        return user


class LoginSerializer(TokenObtainPairSerializer):
    """Login con usuario y contraseña; además de los tokens devuelve los datos del usuario."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data["usuario"] = datos_usuario(self.user)
        return data


# ---------- datos académicos ----------


class EstudianteSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, default=None)
    progreso_general = serializers.SerializerMethodField()

    class Meta:
        model = Estudiante
        fields = "__all__"
        read_only_fields = ["user"]

    def get_progreso_general(self, obj):
        avg = getattr(obj, "progreso_promedio", None)
        if avg is None:
            avg = obj.inscripciones.aggregate(a=Avg("progreso"))["a"]
        return round(avg or 0, 1)


class PerfilSerializer(serializers.ModelSerializer):
    """Lo único que el estudiante puede editar de su propia ficha."""

    class Meta:
        model = Estudiante
        fields = ["telefono", "direccion", "correo"]


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


# ---------- recuperación de credenciales ----------


class RecuperarSerializer(serializers.Serializer):
    cedula = serializers.CharField(max_length=20)


class RestablecerSerializer(serializers.Serializer):
    cedula = serializers.CharField(max_length=20)
    codigo = serializers.CharField(max_length=6)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
