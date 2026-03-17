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
    path('actividades/<int:id>/detalle/', views.detalleActividad, name='detalle_actividad'),
    path('guardar-entregas/', views.guardar_entregas, name='guardar_entregas'),
    path('new-user/', views.new_user, name='new_user'),
    
    # 👇 AGREGAR ESTAS NUEVAS URLs 👇
    path('new-group/', views.new_group, name='new_group'),  # Para crear grupo
    path('new-materia/', views.new_materia, name='new_materia'),  # Para asignar materia a grupo

    # URLs para generación y validación de QR
    path('generar-qr/', views.generar_qr, name='generar_qr'),
    path('api/materias-por-grupo/<int:grupo_id>/', views.api_materias_por_grupo, name='api_materias_por_grupo'),
    path('api/generar-qr/', views.api_generar_qr, name='api_generar_qr'),
    path('api/validar-qr/', views.api_validar_qr, name='api_validar_qr'),
    path('api/registrar-asistencia-qr/', views.api_registrar_asistencia_qr, name='api_registrar_asistencia_qr'),
    path('api/login/', views.api_login, name='api_login'),
    path('api/registro/', views.api_registro_alumno, name='api_registro'),
    path('api/grupos/', views.api_obtener_grupos, name='api_grupos'),
    path('api/verificar-sesion/', views.api_verificar_sesion, name='api_verificar_sesion'),
    path('api/validar-qr-alumno/', views.api_validar_qr_alumno, name='api_validar_qr_alumno'),
    path('obtener-asistencias-por-grupo/', views.obtener_asistencias_por_grupo, name='obtener_asistencias_por_grupo'),
    path('ver_asistencias/', views.ver_asistencias, name='ver_asistencias'),
    path('api/filtrar-asistencias/', views.api_filtrar_asistencias, name='api_filtrar_asistencias'),
    
]