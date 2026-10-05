from django.urls import path

from . import web_views as v

app_name = "web"

urlpatterns = [
    path("", v.inicio, name="inicio"),
    path("login/", v.login_view, name="login"),
    path("registro/", v.registro_view, name="registro"),
    path("salir/", v.salir, name="salir"),
    path("resumen/", v.resumen, name="resumen"),
    path("progreso/", v.progreso, name="progreso"),
    path("rubros/", v.rubros, name="rubros"),
    path("perfil/", v.perfil, name="perfil"),
]
