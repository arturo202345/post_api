from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DashboardView,
    EstudianteModuloViewSet,
    EstudianteViewSet,
    ModuloViewSet,
    RubroViewSet,
)

router = DefaultRouter()
router.register("estudiantes", EstudianteViewSet)
router.register("modulos", ModuloViewSet)
router.register("inscripciones", EstudianteModuloViewSet)
router.register("rubros", RubroViewSet)

urlpatterns = [
    path("dashboard/", DashboardView.as_view()),
    path("", include(router.urls)),
]