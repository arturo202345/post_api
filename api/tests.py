from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
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

    def test_filtro_estado_pago_usa_estado_efectivo(self):
        """Un PENDIENTE con fecha pasada se lista como VENCIDO (igual que la web y la app)."""
        self.login(self.u1)
        venc = self.client.get("/api/me/rubros/?estado_pago=VENCIDO").data
        self.assertEqual([x["concepto"] for x in venc["results"]], ["Vencido"])
        pend = self.client.get("/api/me/rubros/?estado_pago=PENDIENTE").data
        self.assertEqual(sorted(x["concepto"] for x in pend["results"]), ["En 3 días", "Lejano"])

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


class RecuperacionTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.user, self.est = self.crear_usuario("juan", "0912345678")
        mail.outbox = []

    def pedir(self, cedula="0912345678"):
        return self.client.post("/api/auth/recuperar/", {"cedula": cedula}, format="json")

    def codigo_enviado(self):
        import re
        return re.search(r"contraseña es: (\d{6})", mail.outbox[-1].body).group(1)

    def confirmar(self, codigo, password="Nueva-Clave-2027", cedula="0912345678"):
        return self.client.post(
            "/api/auth/recuperar/confirmar/",
            {"cedula": cedula, "codigo": codigo, "password": password},
            format="json",
        )

    def test_envia_codigo_y_usuario_al_correo(self):
        r = self.pedir()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["juan@example.com"])
        self.assertIn("juan", mail.outbox[0].body)  # el usuario también se recupera

    def test_cedula_inexistente_responde_igual_y_no_envia(self):
        a, b = self.pedir(), self.pedir("999")
        self.assertEqual(a.data, b.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_no_reenvia_antes_de_un_minuto(self):
        self.pedir()
        self.pedir()
        self.assertEqual(len(mail.outbox), 1)

    def test_cambia_la_clave_con_el_codigo_y_no_se_reutiliza(self):
        self.pedir()
        codigo = self.codigo_enviado()
        self.assertEqual(self.confirmar(codigo).status_code, 200)
        r = self.client.post("/api/auth/login/", {"username": "juan", "password": "Nueva-Clave-2027"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.confirmar(codigo, "Otra-Clave-2028").status_code, 400)

    def test_codigo_incorrecto_y_limite_de_intentos(self):
        self.pedir()
        codigo = self.codigo_enviado()
        mala = "000000" if codigo != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.confirmar(mala).status_code, 400)
        self.assertEqual(self.confirmar(codigo).status_code, 400)  # ya se agotaron los intentos
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASS))

    def test_codigo_vencido(self):
        from .models import CodigoRecuperacion
        self.pedir()
        codigo = self.codigo_enviado()
        CodigoRecuperacion.objects.update(creado=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.confirmar(codigo).status_code, 400)

    def test_clave_debil_no_gasta_el_codigo(self):
        self.pedir()
        codigo = self.codigo_enviado()
        r = self.confirmar(codigo, password="123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)
        self.assertEqual(self.confirmar(codigo).status_code, 200)

    def test_codigo_de_otra_cedula_no_sirve(self):
        self.crear_usuario("ana", "222")
        self.pedir()
        codigo = self.codigo_enviado()
        self.assertEqual(self.confirmar(codigo, cedula="222").status_code, 400)


class CorreoBrevoTests(BaseTest):
    def test_envia_por_https_con_remitente_y_destinatario(self):
        import json
        from unittest import mock

        from django.core.mail import EmailMessage

        from .correo import BrevoEmailBackend

        with mock.patch("api.correo.urllib.request.urlopen") as uo, mock.patch.dict(
            "os.environ", {"BREVO_API_KEY": "clave"}
        ):
            n = BrevoEmailBackend().send_messages(
                [EmailMessage("Asunto", "Hola", "Gestión <no-reply@example.com>", ["a@example.com"])]
            )
        self.assertEqual(n, 1)
        req = uo.call_args[0][0]
        self.assertEqual(req.get_header("Api-key"), "clave")
        cuerpo = json.loads(req.data)
        self.assertEqual(cuerpo["sender"], {"email": "no-reply@example.com", "name": "Gestión"})
        self.assertEqual(cuerpo["to"], [{"email": "a@example.com"}])
        self.assertEqual(cuerpo["textContent"], "Hola")

    def test_error_de_brevo_incluye_el_motivo(self):
        import io
        import urllib.error
        from unittest import mock

        from django.core.mail import EmailMessage

        from .correo import BrevoEmailBackend

        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"message":"sender invalido"}'))
        with mock.patch("api.correo.urllib.request.urlopen", side_effect=err):
            with self.assertRaisesRegex(RuntimeError, "400.*sender invalido"):
                BrevoEmailBackend().send_messages([EmailMessage("A", "B", "x@example.com", ["a@example.com"])])


class InsigniasTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.u, self.est = self.crear_usuario("juan", "111")
        self.py = Modulo.objects.create(nombre="Introducción a Python")
        self.web = Modulo.objects.create(nombre="Desarrollo Web")
        EstudianteModulo.objects.create(
            estudiante=self.est, modulo=self.py, progreso=100,
            estado=EstudianteModulo.Estado.FINALIZADO, fecha_finalizacion=date(2026, 9, 1),
        )
        EstudianteModulo.objects.create(
            estudiante=self.est, modulo=self.web, progreso=40, estado=EstudianteModulo.Estado.EN_CURSO
        )

    def test_modulo_aprobado_da_insignia_y_los_demas_quedan_bloqueados(self):
        self.login(self.u)
        r = self.client.get("/api/me/insignias/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["modulo"] for x in r.data], ["Introducción a Python", "Desarrollo Web"])
        py, web = r.data
        self.assertTrue(py["obtenida"])
        self.assertEqual(py["iniciales"], "IP")  # ignora palabras cortas como "a"
        self.assertEqual(py["fecha"], date(2026, 9, 1))
        self.assertFalse(web["obtenida"])
        self.assertEqual(web["progreso"], 40)
        self.assertTrue(py["color"].startswith("#"))

    def test_solo_ve_las_suyas_y_exige_estudiante(self):
        otro, _ = self.crear_usuario("ana", "222")
        self.login(otro)
        self.assertEqual(self.client.get("/api/me/insignias/").data, [])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/me/insignias/").status_code, 401)
