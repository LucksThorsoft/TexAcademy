from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.views.decorators.http import require_POST
import csv
from io import TextIOWrapper
from .forms import *
from .models import *

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

def new_group(request):
    if request.method == "POST":
        form = GrupoForm(request.POST, request.FILES)

        if form.is_valid():
            grupo = form.save(commit=False)

            cuatrimestre_activo = Cuatrimestre.objects.filter(activo=True).first()
            if not cuatrimestre_activo:
                messages.error(request, "No hay cuatrimestre activo")
                return redirect("director")

            grupo.cuatrimestre = cuatrimestre_activo
            grupo.save()

            archivo = request.FILES.get("archivo_alumnos")

            if archivo:
                archivo_texto = TextIOWrapper(archivo, encoding="utf-8-sig")
                reader = csv.DictReader(archivo_texto)

                for fila in reader:
                    nombre = fila.get("nombre")
                    matricula = fila.get("matricula")

                    if not nombre or not matricula:
                        continue

                    Alumno.objects.get_or_create(
                        matricula=matricula.strip(),
                        defaults={
                            "nombre": nombre.strip(),
                            "grupo": grupo
                        }
                    )

            messages.success(request, "Grupo y alumnos creados correctamente")

    return redirect("director")


def new_materia(request):
    if request.method == "POST":
        form = GrupoDocenteMateriaForm(request.POST)

        if form.is_valid():
            nombre = form.cleaned_data['nombre_materia']
            grupo = form.cleaned_data['grupo']
            docente = form.cleaned_data['docente']

            # Crear o reutilizar materia
            materia, created = Materia.objects.get_or_create(
                nombre=nombre
            )

            # Crear relación grupo-materia-docente
            GrupoDocenteMateria.objects.create(
                grupo=grupo,
                materia=materia,
                docente=docente
            )

    return redirect('director')