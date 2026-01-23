from django.shortcuts import render

# Create your views here.

from django.shortcuts import render

def home(request):
    return render(request, "home.html")

def dashboard(request):
    return render(request, "dashboard.html")

def gruposAlumnos(request):
    return render(request, "gruposAlumnos.html")

def actividades(request):
    return render(request, "actividades.html")

def asistencia(request):
    return render(request, "asistencia.html")

def estadisticas(request):
    return render(request, "estadisticas.html")

def alertas(request):
    return render(request, "alertas.html")