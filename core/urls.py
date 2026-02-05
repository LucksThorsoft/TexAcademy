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
    path('sidebar', views.sidebar),
    path('director', views.director, name='director'),
    path('tutor', views.tutor),
    path('pedagogia', views.pedagogia),
    path('director/new_user', views.new_user, name='new_user'),
    
]
