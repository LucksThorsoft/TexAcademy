from django.urls import path
from . import views

urlpatterns = [
    path('home/', views.home),
    path('dashboard', views.dashboard),
    path('grupos-alumnos', views.gruposAlumnos),
    path('actividades', views.actividades),
    path('asistencia', views.asistencia),
    path('estadisticas', views.estadisticas),
    path('alertas', views.alertas),
]
