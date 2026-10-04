from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Estudiante, EstudianteModulo, Modulo, Rubro

User = get_user_model()
PASS = "Clave-Segura-2026"


def registro(**extra):
    datos = dict(
        username="juan", email="juan@example.com", password=PASS,
        cedula="0912345678", nombres="Juan", apellidos="Pérez",
    )
    datos.update(extra)
    return datos


class BaseTest(APITestCase):
    def setUp(self):
        cache.clear()  # reinicia el límite de intentos entre tests

    def crear_usuario(self, username, cedula, correo=None):
        u = User.objects.create_user(username, correo or f"{username}@example.com", PASS)
        e = Estudiante.objects.create(user=u, cedula=cedula, nombres=username.title(), apellidos="Test",
                                      correo=u.email)
        return u, e

    def login(self, user):
        self.client.force_authenticate(user)


class AuthTests(BaseTest):
    def test_registro_crea_usuario_estudiante_y_tokens(self):
        r = self.client.post("/api/auth/register/", registro(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        u = User.objects.get(username="juan")
        self.assertEqual(u.estudiante.cedula, "0912345678")
        self.assertEqual(r.data["usuario"]["estudiante_id"], u.estudiante.id)

    def test_registro_enlaza_ficha_existente_si_correo_coincide(self):
        ficha = Estudiante.objects.create(cedula="0912345678", nombres="Juan", apellidos="Pérez",
                                          correo="juan@example.com")
        r = self.client.post("/api/auth/register/", registro(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ficha.refresh_from_db()
        self.assertEqual(ficha.user.username, "juan")
        self.assertEqual(Estudiante.objects.count(), 1)

    def test_registro_rechaza_ficha_existente_con_otro_correo(self):
        Estudiante.objects.create(cedula="0912345678", nombres="Juan", apellidos="Pérez",
                                  correo="otro@example.com")
        r = self.client.post("/api/auth/register/", registro(), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cedula", r.data)
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_registro_rechaza_cedula_con_cuenta(self):
        self.crear_usuario("ana", "0912345678")
        r = self.client.post("/api/auth/register/", registro(), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cedula", r.data)

    def test_registro_valida_usuario_correo_y_clave(self):
        self.crear_usuario("juan", "111")
        r = self.client.post("/api/auth/register/", registro(), format="json")
        self.assertIn("username", r.data)
        r = self.client.post("/api/auth/register/",
                             registro(username="otro", email="JUAN@example.com"), format="json")
        self.assertIn("email", r.data)
        r = self.client.post("/api/auth/register/",
                             registro(username="nuevo", email="nuevo@example.com", password="123"),
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)

    def test_login(self):
        self.crear_usuario("juan", "0912345678")
        r = self.client.post("/api/auth/login/", {"username": "juan", "password": PASS}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertEqual(r.data["usuario"]["username"], "juan")
        r = self.client.post("/api/auth/login/", {"username": "juan", "password": "mala"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_token_permite_acceder_a_me(self):
        self.client.post("/api/auth/register/", registro(), format="json")
        r = self.client.post("/api/auth/login/", {"username": "juan", "password": PASS}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        r = self.client.get("/api/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["cedula"], "0912345678")


class MisDatosTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.u1, self.e1 = self.crear_usuario("juan", "111")
        self.u2, self.e2 = self.crear_usuario("ana", "222")
        mod = Modulo.objects.create(nombre="Base de Datos")
        mod2 = Modulo.objects.create(nombre="Redes")
        EstudianteModulo.objects.create(estudiante=self.e1, modulo=mod, estado="EN_CURSO", progreso=60)
        EstudianteModulo.objects.create(estudiante=self.e1, modulo=mod2, estado="FINALIZADO", progreso=100)
        EstudianteModulo.objects.create(estudiante=self.e2, modulo=mod, estado="EN_CURSO", progreso=10)
        hoy = timezone.localdate()
        d = lambda n: hoy + timedelta(days=n)
        Rubro.objects.create(estudiante=self.e1, concepto="Vencido", valor=50, fecha_vencimiento=d(-2))
        Rubro.objects.create(estudiante=self.e1, concepto="En 3 días", valor=80, fecha_vencimiento=d(3))
        Rubro.objects.create(estudiante=self.e1, concepto="Lejano", valor=20, fecha_vencimiento=d(30))
        Rubro.objects.create(estudiante=self.e1, concepto="Pagado", valor=100, fecha_vencimiento=d(1),
                             estado_pago="PAGADO")
        Rubro.objects.create(estudiante=self.e2, concepto="De Ana", valor=999, fecha_vencimiento=d(2))

    def test_me_requiere_login(self):
        self.assertEqual(self.client.get("/api/me/").status_code, 401)

    def test_me_devuelve_solo_mi_ficha_y_progreso(self):
        self.login(self.u1)
        r = self.client.get("/api/me/")
        self.assertEqual(r.data["cedula"], "111")
        self.assertEqual(r.data["progreso_general"], 80.0)

    def test_me_patch_solo_edita_contacto(self):
        self.login(self.u1)
        r = self.client.patch("/api/me/", {"telefono": "0999", "cedula": "HACK", "estado": "INACTIVO"},
                              format="json")
        self.assertEqual(r.status_code, 200)
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.telefono, "0999")
        self.assertEqual(self.e1.cedula, "111")
        self.assertEqual(self.e1.estado, "ACTIVO")

    def test_listados_solo_propios(self):
        self.login(self.u1)
        insc = self.client.get("/api/me/inscripciones/").data
        self.assertEqual(insc["count"], 2)
        rub = self.client.get("/api/me/rubros/").data
        self.assertEqual(rub["count"], 4)
        self.assertNotIn("De Ana", [x["concepto"] for x in rub["results"]])
        solo = self.client.get("/api/me/rubros/?estado_pago=PAGADO").data
        self.assertEqual(solo["count"], 1)

    def test_dashboard_personal_y_alerta(self):
        self.login(self.u1)
        d = self.client.get("/api/me/dashboard/").data
        self.assertTrue(d["hay_pagos_pendientes"])
        self.assertEqual(d["dias_alerta"], 5)
        self.assertEqual(d["modulos"], 2)
        self.assertEqual(d["progreso_promedio"], 80.0)
        self.assertEqual(d["rubros_vencidos"], {"cantidad": 1, "total": 50})
        self.assertEqual(d["rubros_por_vencer"]["cantidad"], 1)
        self.assertEqual(float(d["rubros_por_vencer"]["total"]), 80.0)
        self.assertEqual(d["rubros_pendientes"]["cantidad"], 2)  # 3 días + lejano

    def test_dashboard_sin_deudas_no_alerta(self):
        u3, e3 = self.crear_usuario("luis", "333")
        self.login(u3)
        d = self.client.get("/api/me/dashboard/").data
        self.assertFalse(d["hay_pagos_pendientes"])
        self.assertEqual(d["rubros_vencidos"], {"cantidad": 0, "total": 0})

    def test_usuario_sin_estudiante_recibe_403(self):
        admin = User.objects.create_superuser("admin", "a@example.com", PASS)
        self.login(admin)
        self.assertEqual(self.client.get("/api/me/").status_code, 403)


class AdminTests(BaseTest):
    def test_endpoints_de_administracion_solo_staff(self):
        u, _ = self.crear_usuario("juan", "111")
        self.login(u)
        for ruta in ("estudiantes", "modulos", "inscripciones", "rubros", "rubros/vencidos", "dashboard"):
            self.assertEqual(self.client.get(f"/api/{ruta}/").status_code, 403, ruta)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/estudiantes/").status_code, 401)

    def test_staff_accede_y_por_vencer_tolera_dias_invalidos(self):
        admin = User.objects.create_superuser("admin", "a@example.com", PASS)
        self.login(admin)
        self.assertEqual(self.client.get("/api/estudiantes/").status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard/").status_code, 200)
        self.assertEqual(self.client.get("/api/rubros/por-vencer/?dias=abc").status_code, 200)
