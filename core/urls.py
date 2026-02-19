from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard', views.dashboard),
    path('grupos-alumnos', views.gruposAlumnos),
    path('actividades/', views.actividades),
    path('actividades/<int:id>/detalle', views.detalleActividad),
    path('guardar-entregas/', views.guardar_entregas),
    path('asistencia', views.asistencia),
    path('estadisticas', views.estadisticas),
    path('alertas', views.alertas),
    path('sidebar', views.sidebar),
    path('director', views.director, name='director'),
    path('tutor', views.tutor),
    path('pedagogia', views.pedagogia),
    path('director/new_user', views.new_user, name='new_user'),
    path("grupo/nuevo/", views.new_group, name="new_group"),
    path('materia/nueva/', views.new_materia, name='new_materia'),
    path('obtener-alumnos-por-grupo/', views.obtener_alumnos_por_grupo, name='obtener_alumnos_por_grupo'),
    path('guardar-asistencia/', views.guardar_asistencia, name='guardar_asistencia'),
    path('obtener-historial-asistencia/', views.obtener_historial_asistencia, name='obtener_historial_asistencia'),

    
]
