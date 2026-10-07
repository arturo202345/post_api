from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    DashboardView,
    EstudianteModuloViewSet,
    EstudianteViewSet,
    LoginView,
    MeView,
    MiDashboardView,
    MisInsigniasView,
    MisInscripcionesView,
    MisRubrosView,
    ModuloViewSet,
    RecuperarView,
    RegisterView,
    RestablecerView,
    RubroViewSet,
)

router = DefaultRouter()
router.register("estudiantes", EstudianteViewSet)
router.register("modulos", ModuloViewSet)
router.register("inscripciones", EstudianteModuloViewSet)
router.register("rubros", RubroViewSet)

urlpatterns = [
    # autenticación
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", LoginView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("auth/recuperar/", RecuperarView.as_view()),
    path("auth/recuperar/confirmar/", RestablecerView.as_view()),
    # estudiante autenticado
    path("me/", MeView.as_view()),
    path("me/inscripciones/", MisInscripcionesView.as_view()),
    path("me/insignias/", MisInsigniasView.as_view()),
    path("me/rubros/", MisRubrosView.as_view()),
    path("me/dashboard/", MiDashboardView.as_view()),
    # administración (staff)
    path("dashboard/", DashboardView.as_view()),
    path("", include(router.urls)),
]
