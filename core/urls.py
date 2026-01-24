from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard', views.dashboard),
    path('grupos-alumnos', views.gruposAlumnos),
    path('actividades', views.actividades),
    path('asistencia', views.asistencia),
    path('estadisticas', views.estadisticas),
    path('alertas', views.alertas),

    
]
