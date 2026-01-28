from django.shortcuts import render
from .models import Grupo, GrupoDocenteMateria, Alumno, Materia
from django.db.models import Count

# Create your views here.

from django.shortcuts import render

def home(request):
    return render(request, "home.html")

def dashboard(request):
    return render(request, "dashboard.html")

def gruposAlumnos(request):
    # Obtener todos los grupos
    grupos = Grupo.objects.all()
    
    # Preparar datos para cada grupo
    grupos_data = []
    
    for grupo in grupos:
        # Contar alumnos en este grupo
        num_alumnos = Alumno.objects.filter(grupo=grupo).count()
        
        # Obtener TODAS las materias asociadas a este grupo
        materias_grupo = GrupoDocenteMateria.objects.filter(
            grupo=grupo
        ).select_related('materia').order_by('materia__nombre')
        
        # Obtener lista de nombres de materias
        materias_nombres = [gd.materia.nombre for gd in materias_grupo]
        
        grupos_data.append({
            'clave': grupo.clave,  # "5A", "3B", etc.
            'materias': materias_nombres,  # Lista de nombres de materias
            'num_alumnos': num_alumnos,
        })
    
    context = {
        'grupos': grupos_data
    }
    
    return render(request, "gruposAlumnos.html", context)

def actividades(request):
    return render(request, "actividades.html")

def asistencia(request):
    return render(request, "asistencia.html")

def estadisticas(request):
    return render(request, "estadisticas.html")

def alertas(request):
    return render(request, "alertas.html")


