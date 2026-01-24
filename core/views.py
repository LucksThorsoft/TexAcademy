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


def login_view(request):
    # Si el usuario ya está logueado, lo mandamos directo al dashboard
    if request.session.get('usuario_id'):
        return redirect('/dashboard')

    if request.method == 'POST':
        # Capturamos los datos directamente de los inputs HTML por su 'name'
        correo = request.POST.get('correo')
        password = request.POST.get('password')

        if not correo or not password:
            messages.error(request, "Por favor completa todos los campos")
        else:
            try:
                usuario = Usuario.objects.get(correo=correo)
                
                # Verificar contraseña (asegúrate de que en la BD estén hasheadas)
                # Si en tu BD las tienes como texto plano (mal práctica pero posible),
                # cambia esta línea por: if password == usuario.password:
                # if check_password(password, usuario.password):
                if password == usuario.password:
                    # --- ÉXITO ---
                    request.session['usuario_id'] = usuario.id
                    request.session['usuario_nombre'] = usuario.nombre
                    # Opcional: Guardar rol si lo necesitas
                    # request.session['usuario_rol'] = ... 
                    return redirect('/dashboard')
                else:
                    messages.error(request, 'Contraseña incorrecta.')
            
            except Usuario.DoesNotExist:
                messages.error(request, 'El correo no está registrado.')

    return render(request, "login.html")

def logout_view(request):
    request.session.flush() # Borra toda la sesión
    return redirect('login')