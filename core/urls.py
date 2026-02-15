from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard', views.dashboard),
    path('grupos-alumnos', views.gruposAlumnos),
    path('actividades', views.actividades),
    path('asistencia', views.asistencia, name='asistencia'),
    path('estadisticas', views.estadisticas),
    path('alertas', views.alertas),
    path('sidebar', views.sidebar),
    path('director', views.director),
    path('tutor', views.tutor),
    path('pedagogia', views.pedagogia),
    
    # API endpoints para AJAX
    path('obtener-alumnos-por-grupo/', views.obtener_alumnos_por_grupo, name='obtener_alumnos_por_grupo'),
    path('guardar-asistencia/', views.guardar_asistencia, name='guardar_asistencia'),
    path('obtener-historial-asistencia/', views.obtener_historial_asistencia, name='obtener_historial_asistencia'),
]