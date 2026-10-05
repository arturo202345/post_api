from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import Estudiante, EstudianteModulo, Modulo, Rubro

User = get_user_model()
PASS = "Clave-Segura-2026"


def datos_registro(**extra):
    d = dict(
        username="juan", email="juan@example.com", password=PASS, password2=PASS,
        cedula="0912345678", nombres="Juan", apellidos="Pérez", telefono="",
    )
    d.update(extra)
    return d


class WebBase(TestCase):
    def setUp(self):
        cache.clear()

    def crear_usuario(self, username, cedula):
        u = User.objects.create_user(username, f"{username}@example.com", PASS)
        e = Estudiante.objects.create(user=u, cedula=cedula, nombres=username.title(), apellidos="Test",
                                      correo=u.email)
        return u, e


class AccesoTests(WebBase):
    def test_paginas_publicas_y_redireccion(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)
        self.assertEqual(self.client.get("/registro/").status_code, 200)
        r = self.client.get("/resumen/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith("/login/?next=/resumen/"))
        self.assertRedirects(self.client.get("/"), "/login/", fetch_redirect_response=False)

    def test_login_correcto_e_incorrecto(self):
        self.crear_usuario("juan", "111")
        r = self.client.post("/login/", {"username": "juan", "password": "mala"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuario o contraseña incorrectos.")
        r = self.client.post("/login/", {"username": "juan", "password": PASS})
        self.assertRedirects(r, "/resumen/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/resumen/").status_code, 200)

    def test_next_no_permite_redirigir_a_otro_sitio(self):
        self.crear_usuario("juan", "111")
        r = self.client.post("/login/", {"username": "juan", "password": PASS, "next": "https://malo.com/"})
        self.assertEqual(r.url, "/resumen/")
        self.client.logout()
        r = self.client.post("/login/", {"username": "juan", "password": PASS, "next": "/rubros/"})
        self.assertEqual(r.url, "/rubros/")

    def test_admin_sin_estudiante_va_al_admin_y_usuario_sin_ficha_no_entra(self):
        User.objects.create_superuser("admin", "a@example.com", PASS)
        r = self.client.post("/login/", {"username": "admin", "password": PASS})
        self.assertEqual(r.url, "/admin/")
        self.client.logout()
        User.objects.create_user("sinficha", "s@example.com", PASS)
        r = self.client.post("/login/", {"username": "sinficha", "password": PASS})
        self.assertContains(r, "no tiene un estudiante asociado")

    def test_bloqueo_tras_muchos_intentos(self):
        self.crear_usuario("juan", "111")
        for _ in range(10):
            self.client.post("/login/", {"username": "juan", "password": "mala"})
        r = self.client.post("/login/", {"username": "juan", "password": PASS})
        self.assertContains(r, "Demasiados intentos")

    def test_salir_solo_por_post(self):
        u, _ = self.crear_usuario("juan", "111")
        self.client.force_login(u)
        self.assertEqual(self.client.get("/salir/").status_code, 405)
        self.assertEqual(self.client.get("/resumen/").status_code, 200)
        r = self.client.post("/salir/")
        self.assertRedirects(r, "/login/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/resumen/").status_code, 302)


class RegistroWebTests(WebBase):
    def test_registro_web_crea_cuenta_y_funciona_en_la_api_de_la_app(self):
        r = self.client.post("/registro/", datos_registro())
        self.assertRedirects(r, "/resumen/", fetch_redirect_response=False)
        self.assertEqual(User.objects.get(username="juan").estudiante.cedula, "0912345678")
        self.assertContains(self.client.get("/resumen/"), "también puedes entrar a la app")

        # El mismo usuario y contraseña sirven para iniciar sesión en la app (JWT).
        app = self.client_class()
        r = app.post("/api/auth/login/", {"username": "juan", "password": PASS},
                     content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()["usuario"]["estudiante_id"])

    def test_registro_en_la_app_funciona_en_la_web(self):
        r = self.client.post("/api/auth/register/",
                             {k: v for k, v in datos_registro().items() if k != "password2"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        web = self.client_class()
        r = web.post("/login/", {"username": "juan", "password": PASS})
        self.assertRedirects(r, "/resumen/", fetch_redirect_response=False)

    def test_registro_enlaza_ficha_existente_si_correo_coincide(self):
        ficha = Estudiante.objects.create(cedula="0912345678", nombres="Juan", apellidos="Pérez",
                                          correo="juan@example.com")
        r = self.client.post("/registro/", datos_registro())
        self.assertRedirects(r, "/resumen/", fetch_redirect_response=False)
        ficha.refresh_from_db()
        self.assertEqual(ficha.user.username, "juan")
        self.assertEqual(Estudiante.objects.count(), 1)

    def test_registro_rechaza_correo_distinto_y_claves_distintas(self):
        Estudiante.objects.create(cedula="0912345678", nombres="Juan", apellidos="Pérez",
                                  correo="otro@example.com")
        r = self.client.post("/registro/", datos_registro())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ya está registrada en el sistema")
        self.assertFalse(User.objects.filter(username="juan").exists())

        r = self.client.post("/registro/", datos_registro(cedula="999", password2="otra"))
        self.assertContains(r, "Las contraseñas no coinciden.")
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_registro_muestra_errores_y_conserva_datos(self):
        self.crear_usuario("juan", "111")
        r = self.client.post("/registro/", datos_registro(nombres="Pedro"))
        self.assertContains(r, "Este nombre de usuario ya está en uso.")
        self.assertContains(r, 'value="Pedro"')
        self.assertNotContains(r, PASS)


class PaginasTests(WebBase):
    def setUp(self):
        super().setUp()
        self.u1, self.e1 = self.crear_usuario("juan", "111")
        self.u2, self.e2 = self.crear_usuario("ana", "222")
        mod, mod2 = Modulo.objects.create(nombre="Base de Datos"), Modulo.objects.create(nombre="Redes")
        EstudianteModulo.objects.create(estudiante=self.e1, modulo=mod, estado="EN_CURSO", progreso=60)
        EstudianteModulo.objects.create(estudiante=self.e1, modulo=mod2, estado="FINALIZADO", progreso=100)
        EstudianteModulo.objects.create(estudiante=self.e2, modulo=mod, estado="EN_CURSO", progreso=10)
        hoy = timezone.localdate()
        d = lambda n: hoy + timedelta(days=n)
        Rubro.objects.create(estudiante=self.e1, concepto="Matrícula vencida", valor=50, fecha_vencimiento=d(-2))
        Rubro.objects.create(estudiante=self.e1, concepto="Cuota en tres días", valor=80, fecha_vencimiento=d(3))
        Rubro.objects.create(estudiante=self.e1, concepto="Pagada", valor=100, fecha_vencimiento=d(1),
                             estado_pago="PAGADO")
        Rubro.objects.create(estudiante=self.e2, concepto="Rubro de Ana", valor=999, fecha_vencimiento=d(2))
        self.client.force_login(self.u1)

    def test_resumen_con_alerta_roja_y_barras(self):
        r = self.client.get("/resumen/")
        self.assertContains(r, "Hola, Juan")
        self.assertContains(r, "1 rubro(s) vencido(s)")
        self.assertContains(r, "alerta rojo")
        self.assertContains(r, "width:80%")  # progreso promedio (60 y 100)
        self.assertContains(r, "$50.00")

    def test_resumen_alerta_naranja_si_no_hay_vencidos(self):
        self.e1.rubros.filter(concepto="Matrícula vencida").delete()
        self.assertContains(self.client.get("/resumen/"), "alerta naranja")

    def test_resumen_sin_deudas_no_muestra_alerta(self):
        self.e1.rubros.exclude(estado_pago="PAGADO").delete()
        self.assertNotContains(self.client.get("/resumen/"), 'class="alerta')

    def test_progreso_muestra_solo_mis_modulos(self):
        r = self.client.get("/progreso/")
        self.assertContains(r, "Base de Datos")
        self.assertContains(r, "Redes")
        self.assertContains(r, "width:100%")
        self.assertContains(r, "En curso")

    def test_rubros_filtra_y_no_mezcla_estudiantes(self):
        r = self.client.get("/rubros/")
        self.assertContains(r, "Matrícula vencida")
        self.assertContains(r, "Cuota en tres días")
        self.assertContains(r, "en 3 día(s)")
        self.assertNotContains(r, "Rubro de Ana")
        r = self.client.get("/rubros/?estado=PAGADO")
        self.assertContains(r, "Pagada")
        self.assertNotContains(r, "Matrícula vencida")
        r = self.client.get("/rubros/?estado=VENCIDO")
        self.assertContains(r, "Matrícula vencida")
        self.assertContains(r, "hace 2 día(s)")
        self.assertEqual(self.client.get("/rubros/?estado=XXX").status_code, 200)

    def test_perfil(self):
        r = self.client.get("/perfil/")
        self.assertContains(r, "Juan Test")
        self.assertContains(r, "@juan")
        self.assertContains(r, "111")
