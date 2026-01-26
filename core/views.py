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


from django.shortcuts import render, redirect
from django.contrib import messages
# Asegúrate de importar tus modelos correctamente
from .models import Usuario, UsuarioRol 

def login_view(request):
    if request.session.get('usuario_id'):
        return redirect('/sidebar')

    if request.method == 'POST':
        correo = request.POST.get('correo')
        password = request.POST.get('password')

        if not correo or not password:
            messages.error(request, "Por favor completa todos los campos")
        else:
            try:
                usuario = Usuario.objects.get(correo=correo)
                
                # Validación de contraseña (simple, como la tenías)
                if password == usuario.password:
                    # --- ÉXITO ---
                    request.session['usuario_id'] = usuario.id
                    request.session['usuario_nombre'] = usuario.nombre
                    
                    # --- AQUÍ ESTÁ EL CAMBIO ---
                    # Buscamos en la tabla intermedia UsuarioRol
                    # Usamos .filter().first() para evitar errores si no tiene rol asignado
                    relacion = UsuarioRol.objects.filter(usuario=usuario).first()
                    
                    if relacion:
                        # Si existe relación, guardamos el nombre del rol (ej: "Docente")
                        request.session['usuario_rol'] = relacion.rol.nombre
                    else:
                        # Si no tiene rol asignado en la BD, ponemos un default
                        request.session['usuario_rol'] = "Sin Asignar"

                    return redirect('/sidebar')
                else:
                    messages.error(request, 'Contraseña incorrecta.')
            
            except Usuario.DoesNotExist:
                messages.error(request, 'El correo no está registrado.')

    return render(request, "login.html")

def logout_view(request):
    request.session.flush() # Borra toda la sesión
    return redirect('login')