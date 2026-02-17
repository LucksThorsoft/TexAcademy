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
    path('detalle-actividad/<int:id>/', views.detalleActividad, name='detalle_actividad'),
    path('guardar-entregas/', views.guardar_entregas, name='guardar_entregas'),
    path('new-user/', views.new_user, name='new_user'),
    
    # 👇 AGREGAR ESTAS NUEVAS URLs 👇
    path('new-group/', views.new_group, name='new_group'),  # Para crear grupo
    path('new-materia/', views.new_materia, name='new_materia'),  # Para asignar materia a grupo
]