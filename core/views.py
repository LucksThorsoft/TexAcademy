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
                
                # Obtener todos los alumnos del grupo y ordenar correctamente
                alumnos_grupo = Alumno.objects.filter(grupo=grupo)
                
                # Convertir a lista para ordenar manualmente
                alumnos_list = list(alumnos_grupo)
                
                # Función para extraer el número de la matrícula
                def extract_matricula_number(matricula):
                    try:
                        # Extraer solo los dígitos de la matrícula
                        import re
                        numbers = re.findall(r'\d+', matricula)
                        if numbers:
                            return int(numbers[0])
                        return 0
                    except:
                        return 0
                
                # Ordenar por: 1) Número de matrícula, 2) Nombre
                alumnos_list.sort(key=lambda x: (
                    extract_matricula_number(x.matricula),
                    x.nombre.lower()
                ))
                
                # Crear lista de alumnos con sus datos
                alumnos_data = []
                for alumno in alumnos_list:
                    alumnos_data.append({
                        'id': alumno.id,
                        'nombre': alumno.nombre,
                        'matricula': alumno.matricula,
                        'promedio': None,
                        'asistencia': None,
                        'estado': None,
                    })
                
                grupos_dict[grupo.clave] = {
                    'clave': grupo.clave,
                    'materias': [],
                    'num_alumnos': num_alumnos,
                    'grupo_id': grupo.id,
                    'alumnos': alumnos_data,
                    'alumnos_json': json.dumps(alumnos_data, ensure_ascii=False),
                }
            
            # Agregar la materia a la lista de materias del grupo
            if materia.nombre not in grupos_dict[grupo.clave]['materias']:
                grupos_dict[grupo.clave]['materias'].append(materia.nombre)
        
        # Convertir el diccionario a lista
        grupos_data = list(grupos_dict.values())
        
        context = {
            'grupos': grupos_data,
            'docente_nombre': usuario.nombre
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "gruposAlumnos.html", context)

def actividades(request):

    if request.method == "POST":
        titulo = request.POST.get("titulo")
        descripcion = request.POST.get("descripcion")
        grupo_id = request.POST.get("grupo")
        fecha_entrega = request.POST.get("fecha_entrega")

        grupo_docente = GrupoDocenteMateria.objects.filter(
            grupo_id=grupo_id
        ).first()

        parcial = Parcial.objects.filter(
            grupo_docente_materia=grupo_docente,
            cerrado=False
        ).first()

        if parcial:
            actividad = Actividad.objects.create(
                titulo=titulo,
                descripcion=descripcion,
                parcial=parcial,
                fecha_entrega=fecha_entrega
            )

            return JsonResponse({
                "id": actividad.id,
                "titulo": actividad.titulo,
                "descripcion": actividad.descripcion,
                "grupo": actividad.parcial.grupo_docente_materia.grupo.clave,
                "fecha": actividad.fecha_entrega,
                "cerrado": actividad.parcial.cerrado
            })

        return JsonResponse({"error": "No hay parcial activo"}, status=400)

    grupos = Grupo.objects.all()
    actividades = Actividad.objects.select_related(
        'parcial',
        'parcial__grupo_docente_materia',
        'parcial__grupo_docente_materia__grupo'
    )

    return render(request, "actividades.html", {
        "grupos": grupos,
        "actividades": actividades
    })


def detalleActividad(request, id):
    actividad = Actividad.objects.select_related(
        'parcial',
        'parcial__grupo_docente_materia',
        'parcial__grupo_docente_materia__grupo'
    ).get(id=id)

    grupo = actividad.parcial.grupo_docente_materia.grupo
    alumnos = grupo.alumno_set.all()

    lista_alumnos = []
    entregadas = 0

    for alumno in alumnos:
        entrega = Entrega.objects.filter(
            actividad=actividad,
            alumno=alumno
        ).first()

        if not entrega:
            entrega = Entrega.objects.create(
                actividad=actividad,
                alumno=alumno,
                entregado=False
            )

        if entrega.entregado:
            entregadas += 1

        lista_alumnos.append({
            "id": entrega.id,
            "nombre": alumno.nombre,
            "matricula": alumno.matricula,
            "entregado": entrega.entregado
        })

    data = {
        "titulo": actividad.titulo,
        "grupo": grupo.clave,
        "fecha_entrega": actividad.fecha_entrega.strftime("%d/%m/%Y"),
        "entregadas": entregadas,
        "total": alumnos.count(),
        "alumnos": lista_alumnos
    }

    return JsonResponse(data)


def guardar_entregas(request):
    if request.method == "POST":
        data = json.loads(request.body)
        entregas = data.get("entregas", [])

        for item in entregas:
            Entrega.objects.filter(id=item["id"]).update(
                entregado=item["entregado"]
            )

        return JsonResponse({"success": True})

    return JsonResponse({"error": "Método no permitido"}, status=405)



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