from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.views.decorators.http import require_POST
import csv
from io import TextIOWrapper
from .forms import *
from .models import *
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.utils import timezone

# Create your views here.

def dashboard(request):
    return render(request, "dashboard.html")

def gruposAlumnos(request):
    # Verificar si el usuario está autenticado
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    # Obtener el usuario actual desde la sesión
    usuario_id = request.session.get('usuario_id')
    
    try:
        # Obtener el usuario
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener todas las materias que imparte este docente por grupo
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo', 'materia').order_by('grupo__clave', 'materia__nombre')
        
        # Estructura para agrupar materias por grupo
        grupos_dict = {}
        
        for gdm in grupos_docente:
            grupo = gdm.grupo
            materia = gdm.materia
            
            # Si el grupo no está en el diccionario, lo inicializamos
            if grupo.clave not in grupos_dict:
                # Contar alumnos en este grupo
                num_alumnos = Alumno.objects.filter(grupo=grupo).count()
                
                grupos_dict[grupo.clave] = {
                    'clave': grupo.clave,
                    'materias': [],  # Lista de materias que imparte este docente
                    'num_alumnos': num_alumnos,
                    'grupo_id': grupo.id,  # Para posibles enlaces futuros
                }
            
            # Agregar la materia a la lista de materias del grupo
            grupos_dict[grupo.clave]['materias'].append(materia.nombre)
        
        # Convertir el diccionario a lista
        grupos_data = list(grupos_dict.values())
        
        context = {
            'grupos': grupos_data,
            'docente_nombre': usuario.nombre
        }
        
    except Usuario.DoesNotExist:
        # Si el usuario no existe, redirigir al login
        return redirect('login')
    
    return render(request, "gruposAlumnos.html", context)

def asistencia(request):
    # Verificar si el usuario está autenticado
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    # Obtener el usuario actual desde la sesión
    usuario_id = request.session.get('usuario_id')
    
    try:
        # Obtener el usuario
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener todos los grupos donde este docente imparte alguna materia
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo', 'materia').values('grupo').distinct()
        
        # Obtener los IDs de los grupos
        grupo_ids = [g['grupo'] for g in grupos_docente]
        
        # Obtener los grupos completos
        grupos = Grupo.objects.filter(id__in=grupo_ids)
        
        # Preparar datos de grupos para el template
        grupos_data = []
        for grupo in grupos:
            # Obtener los alumnos de este grupo
            alumnos = Alumno.objects.filter(grupo=grupo).order_by('nombre')
            
            # Obtener materias que el docente imparte en este grupo
            materias = GrupoDocenteMateria.objects.filter(
                docente=usuario,
                grupo=grupo
            ).select_related('materia')
            
            materias_list = [{'id': m.materia.id, 'nombre': m.materia.nombre} for m in materias]
            
            grupos_data.append({
                'id': grupo.id,
                'clave': grupo.clave,
                'alumnos': [{'id': a.id, 'nombre': a.nombre, 'matricula': a.matricula} for a in alumnos],
                'materias': materias_list,
                'total_alumnos': alumnos.count()
            })
        
        # También obtener estados de asistencia disponibles
        estados_asistencia = EstadoAsistencia.objects.all()
        estados_data = [{'id': e.id, 'nombre': e.nombre} for e in estados_asistencia]
        
        context = {
            'docente': usuario,
            'grupos': grupos_data,
            'estados_asistencia': estados_data,
            'hoy': timezone.now().date()
        }
        
        return render(request, "asistencia.html", context)

    except Usuario.DoesNotExist:
        return redirect('login')   
          

    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "asistencia.html", context)

def actividades(request):
    return render(request, "actividades.html")

def estadisticas(request):
    return render(request, "estadisticas.html")

def alertas(request):
    return render(request, "alertas.html")

def sidebar(request):
    return render(request, "sidebar.html")

def director(request):
    if not request.session.get('usuario_id'):
        return redirect('login')

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')

    form = DocenteForm()
    grupo_form = GrupoForm()
    materia_form = GrupoDocenteMateriaForm()  # 👈 ESTO FALTABA

    relaciones = GrupoDocenteMateria.objects.select_related(
        'grupo', 'materia', 'docente'
    ).order_by('grupo__clave', 'materia__nombre')

    grupos_data = []

    for rel in relaciones:
        grupo = rel.grupo
        num_alumnos = Alumno.objects.filter(grupo=grupo).count()

        grupos_data.append({
            'clave': grupo.clave,
            'materia': rel.materia.nombre,
            'docente': rel.docente.nombre,
            'num_alumnos': num_alumnos,
            'tutor': grupo.tutor.nombre if grupo.tutor else 'Sin tutor',
        })

    return render(request, "director.html", {
        "form": form,
        "grupo_form": grupo_form,
        "materia_form": materia_form,  # 👈 Y PASARLO
        "grupos": grupos_data
    })



    
@require_POST
def new_user(request):
    if not request.session.get('usuario_id'):
        return redirect('login')

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')

    form = DocenteForm(request.POST)

    if form.is_valid():
        usuario = form.save()

        rol_docente, _ = Rol.objects.get_or_create(nombre="Docente")
        UsuarioRol.objects.create(
            usuario=usuario,
            rol=rol_docente
        )

    return redirect('director')

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
    request.session.flush()
    return redirect('login')