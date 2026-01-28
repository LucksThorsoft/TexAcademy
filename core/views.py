from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from .forms import *
from .models import *

# Create your views here.


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

def sidebar(request):
    return render(request, "sidebar.html")

def director(request):
    return render(request, "director.html")

def tutor(request):
    return render(request, "tutor.html")

def pedagogia(request):
    return render(request, "pedagogia.html")

def login_view(request):
    # --- PARTE 1: Redirección si ya está logueado ---
    if request.session.get('usuario_id'):
        # Obtenemos la lista de roles (si no existe, devolvemos lista vacía)
        roles = request.session.get('usuario_roles', [])
        
        # Jerarquía de redirección (Prioridad)
        if 'Director' in roles:
            return redirect('/director')
        elif 'Docente' in roles:
            return redirect('/grupos-alumnos')
        elif 'Tutor' in roles:
            return redirect('/actividades')
        elif 'Pedagogia' in roles:
            return redirect('/pedagogia')
        else:
            return redirect('/dashboard')

    # --- PARTE 2: Login (POST) ---
    if request.method == 'POST':
        correo = request.POST.get('correo')
        password = request.POST.get('password')
        # ... validaciones de campos vacíos ...

        try:
            usuario = Usuario.objects.get(correo=correo)
            if password == usuario.password:
                request.session['usuario_id'] = usuario.id
                request.session['usuario_nombre'] = usuario.nombre

                # --- CAMBIO IMPORTANTE: Obtener TODOS los roles ---
                # Buscamos todas las coincidencias en la tabla intermedia
                relaciones = UsuarioRol.objects.filter(usuario=usuario)
                
                # Creamos una lista de python con los nombres: ['Docente', 'Administrador']
                lista_roles = [r.rol.nombre for r in relaciones]
                
                # Guardamos la lista en la sesión
                request.session['usuario_roles'] = lista_roles

                # --- Redirección basada en jerarquía ---
                # Aunque tenga 3 roles, decidimos a dónde mandarlo por prioridad
                if 'Director' in lista_roles:
                    return redirect('/director')
                elif 'Docente' in lista_roles:
                    return redirect('/grupos-alumnos')
                elif 'Tutor' in lista_roles:
                    return redirect('/tutor')
                elif 'Pedagogia' in lista_roles:
                    return redirect('/pedagogia')
                else:
                    return redirect('/dashboard')
            else:
                 messages.error(request, 'Contraseña incorrecta.')
        except Usuario.DoesNotExist:
             messages.error(request, 'El correo no está registrado.')

    return render(request, "login.html")

def logout_view(request):
    request.session.flush() # Borra toda la sesión
    return redirect('login')