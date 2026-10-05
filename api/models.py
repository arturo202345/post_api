from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Estudiante(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    # Cuenta de acceso del estudiante (login). Null = ficha creada por el administrador sin cuenta aún.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estudiante",
    )
    cedula = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)

    class Meta:
        ordering = ["apellidos", "nombres"]

    def __str__(self):
        return f"{self.apellidos} {self.nombres}"

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"


class Modulo(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class EstudianteModulo(models.Model):
    """Matrícula de un estudiante en un módulo, con su progreso particular."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_CURSO = "EN_CURSO", "En curso"
        FINALIZADO = "FINALIZADO", "Finalizado"

    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name="inscripciones")
    modulo = models.ForeignKey(Modulo, on_delete=models.CASCADE, related_name="inscripciones")
    progreso = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_finalizacion = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Estudiante-Módulo"
        verbose_name_plural = "Estudiantes-Módulos"
        constraints = [
            models.UniqueConstraint(fields=["estudiante", "modulo"], name="unique_estudiante_modulo")
        ]

    def __str__(self):
        return f"{self.estudiante} - {self.modulo} ({self.progreso}%)"


class Rubro(models.Model):
    class EstadoPago(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        PAGADO = "PAGADO", "Pagado"
        VENCIDO = "VENCIDO", "Vencido"

    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name="rubros")
    concepto = models.CharField(max_length=150)
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    fecha_emision = models.DateField(default=timezone.localdate)
    fecha_vencimiento = models.DateField()
    estado_pago = models.CharField(max_length=10, choices=EstadoPago.choices, default=EstadoPago.PENDIENTE)

    class Meta:
        ordering = ["fecha_vencimiento"]

    def __str__(self):
        return f"{self.concepto} - {self.estudiante} (${self.valor})"

    @property
    def estado_efectivo(self):
        """Un rubro PENDIENTE cuya fecha ya pasó se considera VENCIDO."""
        if (
            self.estado_pago == self.EstadoPago.PENDIENTE
            and self.fecha_vencimiento < timezone.localdate()
        ):
            return self.EstadoPago.VENCIDO
        return self.estado_pago

class CodigoRecuperacion(models.Model):
    """Código de un solo uso (enviado por correo) para recuperar usuario/contraseña."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="codigos_recuperacion"
    )
    codigo_hash = models.CharField(max_length=64)  # nunca se guarda el código en claro
    creado = models.DateTimeField(auto_now_add=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    usado = models.BooleanField(default=False)
