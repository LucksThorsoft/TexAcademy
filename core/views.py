from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import csv
import re
from io import TextIOWrapper
from .forms import *
from .models import *
import json
from .models import Grupo, Actividad, Entrega, Alumno, GrupoDocenteMateria, Parcial
from django.db.models.functions import Coalesce
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import datetime



def home(request):
    return render(request, "home.html")


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
                    # Obtener comentarios del alumno
                    comentarios_alumno = Comentario.objects.filter(
                        alumno=alumno
                    ).select_related('docente').order_by('-fecha')
                    
                    comentarios_data = []
                    for comentario in comentarios_alumno:
                        comentarios_data.append({
                            'id': comentario.id,
                            'tipo': comentario.tipo,
                            'texto': comentario.texto,
                            'fecha': comentario.fecha.strftime('%d/%m/%Y'),
                            'docente': comentario.docente.nombre
                        })
                    
                    alumnos_data.append({
                        'id': alumno.id,
                        'nombre': alumno.nombre,
                        'matricula': alumno.matricula,
                        'grupo': grupo.clave,
                        'promedio': None,
                        'asistencia': None,
                        'estado': None,
                        'comentarios': comentarios_data,
                    })
                
                # Inicializar el grupo con una lista vacía de materias
                grupos_dict[grupo.clave] = {
                    'clave': grupo.clave,
                    'materias': [],  # Lista vacía que se llenará después
                    'num_alumnos': num_alumnos,
                    'grupo_id': grupo.id,
                    'alumnos': alumnos_data,
                    'alumnos_json': json.dumps(alumnos_data, ensure_ascii=False),
                }
            
            # Verificar si esta materia ya tiene parciales configurados
            parciales = Parcial.objects.filter(grupo_docente_materia=gdm).order_by('numero_parcial')
            tiene_parciales = parciales.exists()
            
            # Obtener datos de parciales si existen
            parciales_data = []
            if tiene_parciales:
                for parcial in parciales:
                    parciales_data.append({
                        'numero': parcial.numero_parcial,
                        'nombre': parcial.nombre,
                        'porcentaje': parcial.porcentaje,
                        'fecha_inicio': parcial.fecha_inicio.strftime('%Y-%m-%d'),
                        'fecha_fin': parcial.fecha_cierre.strftime('%Y-%m-%d'),
                    })
            
            # Agregar la materia con su información de parciales
            grupos_dict[grupo.clave]['materias'].append({
                'id': gdm.id,
                'nombre': materia.nombre,
                'tiene_parciales': tiene_parciales,
                'parciales_configurados': gdm.parciales_configurados,
                'parciales': parciales_data,
            })
        
        # Convertir el diccionario a lista y agregar materias_json a cada grupo
        grupos_data = []
        for clave, grupo_data in grupos_dict.items():
            grupo_data['materias_json'] = json.dumps(grupo_data['materias'], ensure_ascii=False)
            grupos_data.append(grupo_data)
        
        context = {
            'grupos': grupos_data,
            'docente_nombre': usuario.nombre
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "gruposAlumnos.html", context)

@csrf_exempt
def guardar_parciales(request):
    """Endpoint para guardar la configuración de parciales"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            gdm_id = data.get('gdm_id')
            unidades = data.get('unidades', [])
            
            # Validar datos
            if not gdm_id:
                return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
            
            if not unidades:
                return JsonResponse({'error': 'No se recibieron unidades'}, status=400)
            
            # Obtener la relación GrupoDocenteMateria
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            # Validar que el docente sea el mismo que está en sesión
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para modificar esta materia'}, status=403)
            
            # Validar que el total de porcentajes sea 100
            total_porcentaje = sum(u['porcentaje'] for u in unidades)
            if total_porcentaje != 100:
                return JsonResponse({'error': 'El total de porcentajes debe ser 100%'}, status=400)
            
            # Validar fechas consecutivas
            fechas_validas = validar_fechas_consecutivas(unidades)
            if not fechas_validas:
                return JsonResponse({'error': 'Las fechas no son consecutivas correctamente'}, status=400)
            
            # Eliminar parciales existentes
            Parcial.objects.filter(grupo_docente_materia=gdm).delete()
            
            # Crear los nuevos parciales
            parciales_creados = []
            for unidad in unidades:
                parcial = Parcial.objects.create(
                    numero_parcial=unidad['numero'],
                    nombre=unidad['nombre'],
                    porcentaje=unidad['porcentaje'],
                    grupo_docente_materia=gdm,
                    fecha_inicio=datetime.strptime(unidad['fecha_inicio'], '%Y-%m-%d').date(),
                    fecha_cierre=datetime.strptime(unidad['fecha_fin'], '%Y-%m-%d').date(),
                    cerrado=False
                )
                parciales_creados.append({
                    'numero': parcial.numero_parcial,
                    'nombre': parcial.nombre,
                    'porcentaje': parcial.porcentaje,
                    'fecha_inicio': parcial.fecha_inicio.strftime('%Y-%m-%d'),
                    'fecha_fin': parcial.fecha_cierre.strftime('%Y-%m-%d'),
                })
            
            # Marcar como configurado
            gdm.parciales_configurados = True
            gdm.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Parciales guardados correctamente',
                'parciales': parciales_creados
            })
            
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def validar_fechas_consecutivas(unidades):
    """Valida que las fechas sean consecutivas independientemente del orden"""
    if len(unidades) <= 1:
        return True
    
    # Ordenar por fecha de inicio
    unidades_ordenadas = sorted(unidades, key=lambda x: x['fecha_inicio'])
    
    # Verificar que los números de parcial correspondan al orden de fechas
    for i in range(len(unidades_ordenadas) - 1):
        fecha_fin_actual = datetime.strptime(unidades_ordenadas[i]['fecha_fin'], '%Y-%m-%d').date()
        fecha_inicio_siguiente = datetime.strptime(unidades_ordenadas[i + 1]['fecha_inicio'], '%Y-%m-%d').date()
        
        # La fecha de inicio siguiente debe ser al menos 1 día después de la fecha fin actual
        if fecha_inicio_siguiente <= fecha_fin_actual:
            return False
    
    return True

@csrf_exempt
def guardar_calificaciones(request):
    """Endpoint para guardar las calificaciones de los alumnos por parcial"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            gdm_id = data.get('gdm_id')
            calificaciones = data.get('calificaciones', [])
 
            if not gdm_id:
                return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
 
            if not calificaciones:
                return JsonResponse({'error': 'No se recibieron calificaciones'}, status=400)
 
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
 
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para modificar esta materia'}, status=403)
 
            parciales = Parcial.objects.filter(grupo_docente_materia=gdm)
            parciales_dict = {p.numero_parcial: p for p in parciales}
 
            calificaciones_guardadas = 0
 
            for item in calificaciones:
                alumno_id        = item.get('alumno_id')
                parcial_numero   = item.get('parcial')
                calificacion_valor = item.get('calificacion')
 
                try:
                    alumno = Alumno.objects.get(id=alumno_id)
                except Alumno.DoesNotExist:
                    continue
 
                if parcial_numero not in parciales_dict:
                    continue
 
                parcial = parciales_dict[parcial_numero]
 
                if calificacion_valor is not None and str(calificacion_valor).strip() != '':
                    try:
                        calif_float = float(calificacion_valor)
                        if calif_float < 0 or calif_float > 100:
                            continue
                    except ValueError:
                        continue
                else:
                    calif_float = None
 
                CalificacionParcial.objects.update_or_create(
                    alumno=alumno,
                    parcial=parcial,
                    defaults={
                        'calificacion': calif_float,
                        'comentario': ''
                    }
                )

                calificaciones_guardadas += 1

                # ── GENERAR/LIMPIAR ALERTAS ──────────────────────────────
                if calif_float is not None:
                    # Calificación capturada → evaluar si genera alerta
                    _generar_alertas_alumno(alumno, parcial, gdm, calif_float)
                else:
                    # Calificación borrada → eliminar alerta si existía
                    Alerta.objects.filter(alumno=alumno, parcial=parcial).delete()
 
            return JsonResponse({
                'success': True,
                'message': f'Calificaciones guardadas correctamente ({calificaciones_guardadas} actualizadas)',
                'guardadas': calificaciones_guardadas
            })
 
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada'}, status=404)
        except Exception as e:
            print(f"Error guardando calificaciones: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 
 

def obtener_calificaciones(request):
    """Endpoint para obtener las calificaciones de una materia"""
    if request.method == 'GET':
        gdm_id = request.GET.get('gdm_id')
        
        if not gdm_id:
            return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
        
        try:
            # Obtener la relación GrupoDocenteMateria
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            # Validar que el docente sea el mismo que está en sesión
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para ver esta materia'}, status=403)
            
            # Obtener todas las calificaciones de esta materia
            calificaciones = CalificacionParcial.objects.filter(
                parcial__grupo_docente_materia=gdm
            ).select_related('alumno', 'parcial')
            
            calificaciones_data = []
            for cal in calificaciones:
                calificaciones_data.append({
                    'alumno_id': cal.alumno.id,
                    'parcial': cal.parcial.numero_parcial,
                    'calificacion': cal.calificacion
                })
            
            return JsonResponse({
                'success': True,
                'calificaciones': calificaciones_data
            })
            
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def perfil_alumno(request, alumno_id):
    # Verificar si el usuario está autenticado
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    # Obtener el alumno
    alumno = get_object_or_404(Alumno, id=alumno_id)
    
    # Obtener el docente actual
    docente_id = request.session.get('usuario_id')
    docente = get_object_or_404(Usuario, id=docente_id)
    
    # Obtener comentarios del alumno
    comentarios = Comentario.objects.filter(
        alumno=alumno
    ).select_related('docente').order_by('-fecha')
    
    # Obtener las materias que este docente imparte en el grupo del alumno
    materias_docente = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo,
        docente=docente
    ).select_related('materia')
    
    # Obtener las actividades relacionadas con estas materias
    actividades_data = []
    for gdm in materias_docente:
        # Obtener los parciales de esta materia
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm,
            cerrado=False
        )
        
        for parcial in parciales:
            # Obtener actividades de este parcial
            actividades = Actividad.objects.filter(
                parcial=parcial
            ).order_by('fecha_entrega')
            
            for actividad in actividades:
                # Verificar si el alumno entregó esta actividad
                entrega = Entrega.objects.filter(
                    actividad=actividad,
                    alumno=alumno
                ).first()
                
                # Determinar estado de entrega
                if entrega:
                    estado_entrega = "Entregado" if entrega.entregado else "Pendiente"
                    calificacion = entrega.calificacion if entrega.calificacion else None
                else:
                    estado_entrega = "No asignado"
                    calificacion = None
                
                actividades_data.append({
                    'id': actividad.id,
                    'nombre': actividad.titulo,
                    'materia': gdm.materia.nombre,
                    'fecha_entrega': actividad.fecha_entrega.strftime('%d/%m/%Y'),
                    'estado': estado_entrega,
                    'calificacion': calificacion,
                    'entregado': entrega.entregado if entrega else False,
                })
    
    # Obtener historial de asistencia del alumno
    asistencias = Asistencia.objects.filter(
        alumno=alumno,
        grupo_docente_materia__docente=docente  # Solo asistencias registradas por este docente
    ).select_related('grupo_docente_materia__materia', 'estado').order_by('-fecha')
    
    # Procesar datos de asistencia
    asistencia_data = []
    total_asistencias = 0
    total_retardos = 0
    total_faltas = 0
    
    for asistencia in asistencias:
        materia_nombre = asistencia.grupo_docente_materia.materia.nombre
        estado_nombre = asistencia.estado.nombre
        
        # Contar para estadísticas
        if estado_nombre == 'Asistió':
            total_asistencias += 1
        elif estado_nombre == 'Retardo':
            total_retardos += 1
        elif estado_nombre == 'No asistió':
            total_faltas += 1
        
        asistencia_data.append({
            'fecha': asistencia.fecha.strftime('%d/%m/%Y'),
            'materia': materia_nombre,
            'estado': estado_nombre,
            'comentario': asistencia.comentario,
        })
    
    # Calcular porcentaje de asistencia (considerando retardos como 0.5)
    total_clases = len(asistencia_data)
    if total_clases > 0:
        porcentaje_asistencia = int(((total_asistencias + total_retardos * 0.5) / total_clases) * 100)
    else:
        porcentaje_asistencia = 0
    
    context = {
        'alumno': alumno,
        'comentarios': comentarios,
        'actividades': actividades_data,
        'asistencia_historial': asistencia_data,
        'estadisticas_asistencia': {
            'asistencias': total_asistencias,
            'retardos': total_retardos,
            'faltas': total_faltas,
            'total_clases': total_clases,
            'porcentaje': porcentaje_asistencia,
        }
    }
    
    return render(request, "perfilAlumno.html", context)

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



def obtener_alumnos_por_grupo(request):
    """Endpoint AJAX para obtener los alumnos de un grupo específico"""
    if request.method == 'GET':
        grupo_id = request.GET.get('grupo_id')
        
        if not grupo_id:
            return JsonResponse({'error': 'ID de grupo no proporcionado'}, status=400)
        
        try:
            # Obtener los alumnos del grupo
            alumnos = Alumno.objects.filter(grupo_id=grupo_id).order_by('nombre')
            
            # Preparar datos para JSON
            alumnos_data = []
            for alumno in alumnos:
                alumnos_data.append({
                    'id': alumno.id,
                    'nombre': alumno.nombre,
                    'matricula': alumno.matricula,
                    'grupo_id': alumno.grupo_id
                })
            
            return JsonResponse({
                'success': True,
                'alumnos': alumnos_data,
                'total': len(alumnos_data)
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def guardar_asistencia(request):
    """Endpoint AJAX para guardar la asistencia"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            fecha = data.get('fecha')
            grupo_id = data.get('grupo_id')
            asistencias = data.get('asistencias', {})
            
            print(f"Guardando asistencia - Fecha: {fecha}, Grupo ID: {grupo_id}")
            print(f"Asistencias recibidas: {asistencias}")
            
            # Validar datos requeridos
            if not all([fecha, grupo_id]):
                return JsonResponse({'error': 'Faltan datos requeridos'}, status=400)
            
            # Obtener el grupo y el docente
            grupo = Grupo.objects.get(id=grupo_id)
            docente = Usuario.objects.get(id=request.session.get('usuario_id'))
            
            # Verificar que el docente tenga al menos una materia en este grupo
            gdm = GrupoDocenteMateria.objects.filter(
                grupo=grupo,
                docente=docente
            ).first()
            
            if not gdm:
                return JsonResponse({'error': 'No tienes materias asignadas en este grupo'}, status=400)
            
            # Guardar cada asistencia
            asistencias_guardadas = 0
            for alumno_id, estado_nombre in asistencias.items():
                try:
                    alumno = Alumno.objects.get(id=alumno_id)
                    estado = EstadoAsistencia.objects.get(nombre=estado_nombre)
                    
                    # Crear o actualizar la asistencia
                    asistencia, created = Asistencia.objects.update_or_create(
                        alumno=alumno,
                        grupo_docente_materia=gdm,
                        fecha=fecha,
                        defaults={
                            'estado': estado,
                            'comentario': ''
                        }
                    )
                    
                    asistencias_guardadas += 1
                    print(f"Asistencia {'creada' if created else 'actualizada'} para {alumno.nombre}: {estado_nombre}")
                    
                except Alumno.DoesNotExist:
                    print(f"Error: Alumno con ID {alumno_id} no encontrado")
                except EstadoAsistencia.DoesNotExist:
                    print(f"Error: Estado '{estado_nombre}' no encontrado")
            
            return JsonResponse({
                'success': True, 
                'message': f'Asistencia guardada correctamente para {asistencias_guardadas} alumnos',
                'guardadas': asistencias_guardadas
            })
            
        except Grupo.DoesNotExist:
            return JsonResponse({'error': 'Grupo no encontrado'}, status=404)
        except Usuario.DoesNotExist:
            return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
        except Exception as e:
            print(f"Error inesperado: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def obtener_historial_asistencia(request):
    if request.method == 'GET':
        gdm_id     = request.GET.get('gdm_id')
        docente_id = request.session.get('usuario_id')

        if not gdm_id:
            return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)

        if not docente_id:
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)

        try:
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id, docente_id=docente_id)
            alumnos = Alumno.objects.filter(grupo=gdm.grupo).order_by('nombre')

            if not alumnos.exists():
                return JsonResponse({'historial': [], 'message': 'No hay alumnos en este grupo'})

            historial = []
            for alumno in alumnos:
                asistencias  = Asistencia.objects.filter(alumno=alumno, grupo_docente_materia=gdm)
                total_clases = asistencias.count()

                if total_clases > 0:
                    total_asistencias = asistencias.filter(estado__nombre='Asistió').count()
                    total_retardos    = asistencias.filter(estado__nombre='Retardo').count()
                    total_faltas      = asistencias.filter(estado__nombre='No asistió').count()
                    porcentaje        = int(((total_asistencias + total_retardos * 0.5) / total_clases) * 100)

                    if porcentaje >= 80:   estado_alumno = "Bueno"
                    elif porcentaje >= 60: estado_alumno = "Regular"
                    else:                  estado_alumno = "Crítico"
                else:
                    total_asistencias = total_retardos = total_faltas = porcentaje = 0
                    estado_alumno = "Sin datos"

                historial.append({
                    'alumno_id':    alumno.id,
                    'nombre':       alumno.nombre,
                    'matricula':    alumno.matricula,
                    'asistencias':  total_asistencias,
                    'retardos':     total_retardos,
                    'faltas':       total_faltas,
                    'total_clases': total_clases,
                    'porcentaje':   porcentaje,
                    'estado':       estado_alumno
                })

            return JsonResponse({'historial': historial})

        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido'}, status=405)

def asistencia(request):
    if not request.session.get('usuario_id'):
        return redirect('login')

    usuario_id = request.session.get('usuario_id')

    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return redirect('login')

    # Selector: todos los GDM del docente
    gdms = GrupoDocenteMateria.objects.filter(
        docente=usuario
    ).select_related('grupo', 'materia').order_by('grupo__clave', 'materia__nombre')

    grupos_materia = [
        {'gdm_id': gdm.id, 'label': f"{gdm.grupo.clave} — {gdm.materia.nombre}"}
        for gdm in gdms
    ]

    alumnos_con_estado = []
    gdm_id_sel = request.GET.get('gdm_id') or request.POST.get('gdm_id')
    fecha_sel  = request.GET.get('fecha')  or request.POST.get('fecha')

    # ── GET: cargar lista de alumnos ──────────────────────────────────────
    if request.method == 'GET' and gdm_id_sel and fecha_sel:
        gdm = get_object_or_404(GrupoDocenteMateria, id=gdm_id_sel, docente=usuario)
        alumnos = Alumno.objects.filter(grupo=gdm.grupo).order_by('nombre')

        for alumno in alumnos:
            previa = Asistencia.objects.filter(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_sel
            ).first()

            alumnos_con_estado.append({
                'alumno':      alumno,
                'estado':      previa.estado.nombre if previa else 'Asistió',
                'comentario':  previa.comentario    if previa else '',
            })

    # ── POST: guardar asistencia ──────────────────────────────────────────
    elif request.method == 'POST':
        gdm = get_object_or_404(GrupoDocenteMateria, id=gdm_id_sel, docente=usuario)
        alumnos = Alumno.objects.filter(grupo=gdm.grupo).order_by('nombre')
        estados_validos = {'Asistió', 'Retardo', 'No asistió'}

        for alumno in alumnos:
            estado_nombre = request.POST.get(f'estado_{alumno.id}', 'Asistió')
            if estado_nombre not in estados_validos:
                estado_nombre = 'Asistió'

            estado_obj = EstadoAsistencia.objects.get(nombre=estado_nombre)

            Asistencia.objects.update_or_create(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_sel,
                defaults={
                    'estado':     estado_obj,
                    'comentario': request.POST.get(f'comentario_{alumno.id}', '')
                }
            )

        messages.success(request, f'Asistencia guardada para {alumnos.count()} alumnos.')
        return redirect(f'/asistencia/?gdm_id={gdm_id_sel}&fecha={fecha_sel}')

    context = {
        'docente':            usuario,
        'grupos_materia':     grupos_materia,
        'gdm_id_sel':         str(gdm_id_sel) if gdm_id_sel else '',
        'fecha_sel':          fecha_sel or timezone.now().date().isoformat(),
        'alumnos_con_estado': alumnos_con_estado,
    }
    return render(request, "asistencia.html", context)

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
    materia_form = GrupoDocenteMateriaForm()

    cuatrimestre_activo = Cuatrimestre.objects.filter(activo=True).first()

    # Cuatrimestres para el histórico
    cuatrimestres_data = []
    for c in Cuatrimestre.objects.order_by('-fecha_inicio'):
        grupos_c = Grupo.objects.filter(cuatrimestre=c)
        cuatrimestres_data.append({
            'id': c.id,
            'nombre': c.nombre,
            'activo': c.activo,
            'fecha_inicio': c.fecha_inicio,
            'fecha_fin': c.fecha_fin,
            'total_grupos': grupos_c.count(),
            'total_alumnos': Alumno.objects.filter(grupo__in=grupos_c).count(),
        })

    # Solo grupos del cuatrimestre activo 👇
    grupos_data = []
    if cuatrimestre_activo:
        relaciones = GrupoDocenteMateria.objects.filter(
            grupo__cuatrimestre=cuatrimestre_activo
        ).select_related('grupo', 'materia', 'docente').order_by('grupo__clave', 'materia__nombre')

        for rel in relaciones:
            grupo = rel.grupo
            grupos_data.append({
                'clave': grupo.clave,
                'materia': rel.materia.nombre,
                'docente': rel.docente.nombre,
                'num_alumnos': Alumno.objects.filter(grupo=grupo).count(),
                'tutor': grupo.tutor.nombre if grupo.tutor else 'Sin tutor',
            })

    # Docentes
    rol_docente = Rol.objects.filter(nombre="Docente").first()
    docentes_data = []
    if rol_docente:
        relaciones_docentes = UsuarioRol.objects.filter(rol=rol_docente).select_related('usuario')
        for rel in relaciones_docentes:
            u = rel.usuario
            gdms = GrupoDocenteMateria.objects.filter(
                docente=u
            ).select_related('grupo', 'materia')
            materias_grupos = [f"{g.materia.nombre} / {g.grupo.clave}" for g in gdms]
            docentes_data.append({
                'id': u.id,
                'nombre': u.nombre,
                'correo': u.correo,
                'materias_grupos': materias_grupos,
                'total_grupos': gdms.count(),
            })

    return render(request, "director.html", {
        "form": form,
        "grupo_form": grupo_form,
        "materia_form": materia_form,
        "grupos": grupos_data,
        "sin_cuatrimestre": cuatrimestre_activo is None,
        "cuatrimestres_data": cuatrimestres_data,
        "docentes_data": docentes_data,
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
    if not request.session.get('usuario_id'):
        return redirect('login')
 
    usuario_id = request.session.get('usuario_id')
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return redirect('login')
 
    grupo = Grupo.objects.filter(tutor=usuario).first()
 
    alertas_data = []
    grupo_info   = None
    stats        = {'total': 0, 'alto': 0, 'medio': 0, 'bajo': 0, 'derivadas': 0}
 
    if grupo:
        grupo_info = {'clave': grupo.clave, 'id': grupo.id}
        alumnos    = Alumno.objects.filter(grupo=grupo)
 
        alertas = Alerta.objects.filter(
            alumno__in=alumnos,
            atendida=False
        ).select_related('alumno', 'parcial').order_by('-fecha', '-id')
 
        for alerta in alertas:
            alertas_data.append({
                'id':               alerta.id,
                'alumno_nombre':    alerta.alumno.nombre,
                'alumno_matricula': alerta.alumno.matricula,
                'alumno_id':        alerta.alumno.id,
                'motivo':           alerta.motivo,
                'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],  # NUEVO
                'nivel_riesgo':     alerta.nivel_riesgo,
                'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
                'derivada':         alerta.derivada,
                'derivada_a':       alerta.derivada_a or '',
            })
 
        stats['total']     = len(alertas_data)
        stats['alto']      = sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto')
        stats['medio']     = sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio')
        stats['bajo']      = sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo')
        stats['derivadas'] = sum(1 for a in alertas_data if a['derivada'])
 
    return render(request, 'tutor.html', {
        'usuario':      usuario,
        'grupo':        grupo_info,
        'alertas':      alertas_data,
        'alertas_json': json.dumps(alertas_data, ensure_ascii=False),
        'stats':        stats,
    })

def pedagogia(request):
    if not request.session.get('usuario_id'):
        return redirect('login')
 
    usuario_id = request.session.get('usuario_id')
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return redirect('login')
 
    # Alertas derivadas a Pedagogía que no están cerradas
    alertas_qs = Alerta.objects.filter(
        derivada_a='Pedagogia',
        atendida=False
    ).select_related('alumno', 'alumno__grupo', 'parcial').order_by('-fecha', '-id')
 
    alertas_data = []
    for alerta in alertas_qs:
        # Historial de seguimiento (comentarios previos)
        seguimientos = SeguimientoAlerta.objects.filter(
            alerta=alerta
        ).select_related('usuario').order_by('fecha')
 
        seguimientos_data = []
        for s in seguimientos:
            seguimientos_data.append({
                'usuario':    s.usuario.nombre,
                'accion':     s.accion,
                'comentario': s.comentario,
                'fecha':      s.fecha.strftime('%d/%m/%Y %H:%M'),
            })
 
        alertas_data.append({
            'id':               alerta.id,
            'alumno_nombre':    alerta.alumno.nombre,
            'alumno_matricula': alerta.alumno.matricula,
            'alumno_id':        alerta.alumno.id,
            'grupo':            alerta.alumno.grupo.clave,
            'motivo':           alerta.motivo,
            'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo':     alerta.nivel_riesgo,
            'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
            'derivada_a':       alerta.derivada_a or '',
            'seguimientos':     seguimientos_data,
        })
 
    stats = {
        'total':  len(alertas_data),
        'alto':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'medio':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'bajo':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
    }
 
    return render(request, 'pedagogia.html', {
        'usuario':      usuario,
        'alertas':      alertas_data,
        'alertas_json': json.dumps(alertas_data, ensure_ascii=False),
        'stats':        stats,
    })

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
        elif 'Psicologia' in roles:
            return redirect('/psicologia')
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



def guardar_comentario(request):
    """Endpoint AJAX para guardar comentarios de alumnos"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            alumno_id = data.get('alumno_id')
            texto = data.get('texto')
            docente_id = request.session.get('usuario_id')
            
            print(f"Guardando comentario - Alumno ID: {alumno_id}")
            
            # Validar datos requeridos
            if not all([alumno_id, texto, docente_id]):
                return JsonResponse({'error': 'Faltan datos requeridos'}, status=400)
            
            # Verificar que el alumno existe
            try:
                alumno = Alumno.objects.get(id=alumno_id)
            except Alumno.DoesNotExist:
                return JsonResponse({'error': 'Alumno no encontrado'}, status=404)
            
            # Verificar que el docente existe
            try:
                docente = Usuario.objects.get(id=docente_id)
            except Usuario.DoesNotExist:
                return JsonResponse({'error': 'Docente no encontrado'}, status=404)
            
            # Crear el comentario (tipo por defecto "General")
            comentario = Comentario.objects.create(
                alumno=alumno,
                docente=docente,
                tipo="General",  # Valor por defecto ya que no lo usas
                texto=texto
            )
            
            print(f"Comentario guardado con ID: {comentario.id}")
            
            return JsonResponse({
                'success': True,
                'message': 'Comentario guardado correctamente'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Datos JSON inválidos'}, status=400)
        except Exception as e:
            print(f"Error inesperado: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def new_cuatrimestre(request):
    if request.method == "POST":
        fecha_inicio = request.POST.get("fecha_inicio")
        fecha_fin = request.POST.get("fecha_fin")

        # Generar nombre automático según el mes actual
        hoy = date.today()
        mes = hoy.month
        anio = hoy.year

        if 1 <= mes <= 4:
            nombre = f"Enero-Abril {anio}"
        elif 5 <= mes <= 8:
            nombre = f"Mayo-Agosto {anio}"
        else:
            nombre = f"Septiembre-Diciembre {anio}"

        # Desactivar cualquier cuatrimestre activo previo
        Cuatrimestre.objects.filter(activo=True).update(activo=False)

        Cuatrimestre.objects.create(
            nombre=nombre,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            activo=True
        )
        messages.success(request, f"Cuatrimestre '{nombre}' creado correctamente")

    return redirect("director")

def editar_docente(request, docente_id):
    if not request.session.get('usuario_id'):
        return redirect('login')

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            docente = Usuario.objects.get(id=docente_id)
            docente.nombre = request.POST.get('nombre')
            docente.correo = request.POST.get('correo')

            nueva_password = request.POST.get('password')
            if nueva_password:
                docente.password = nueva_password

            docente.save()
            messages.success(request, 'Docente actualizado correctamente')
        except Usuario.DoesNotExist:
            messages.error(request, 'Docente no encontrado')

    return redirect('director')

def obtener_materias_por_grupo(request):
    """Retorna las materias que el docente imparte en un grupo específico"""
    if request.method == 'GET':
        grupo_id = request.GET.get('grupo_id')
        docente_id = request.session.get('usuario_id')

        if not grupo_id:
            return JsonResponse({'error': 'ID de grupo no proporcionado'}, status=400)

        try:
            gdms = GrupoDocenteMateria.objects.filter(
                grupo_id=grupo_id,
                docente_id=docente_id
            ).select_related('materia')

            materias = [{'id': gdm.id, 'nombre': gdm.materia.nombre} for gdm in gdms]

            return JsonResponse({'success': True, 'materias': materias})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido'}, status=405)

def _generar_alertas_alumno(alumno, parcial, gdm, calificacion):
    motivos    = []
    calif_baja = False
    asist_baja = False

    # 1. CALIFICACIÓN BAJA
    umbral_calif = parcial.porcentaje * 0.60
    calif_baja   = calificacion < umbral_calif

    if calif_baja:
        motivos.append(
            f"Calificación baja en {parcial.nombre}: "
            f"{calificacion:.1f} / {parcial.porcentaje} "
            f"(mínimo esperado: {umbral_calif:.1f})"
        )

    # 2. ASISTENCIA BAJA (solo dentro del rango de fechas del parcial)
    asistencias_parcial = Asistencia.objects.filter(
        alumno=alumno,
        grupo_docente_materia=gdm,
        fecha__gte=parcial.fecha_inicio,
        fecha__lte=parcial.fecha_cierre
    )
    total_clases = asistencias_parcial.count()

    if total_clases > 0:
        total_asistio    = asistencias_parcial.filter(estado__nombre='Asistió').count()
        total_retardo    = asistencias_parcial.filter(estado__nombre='Retardo').count()
        porcentaje_asist = ((total_asistio + total_retardo * 0.5) / total_clases) * 100
        asist_baja       = porcentaje_asist < 70

        if asist_baja:
            motivos.append(
                f"Asistencia baja en {parcial.nombre}: "
                f"{porcentaje_asist:.1f}% "
                f"({total_asistio} asistencias, {total_retardo} retardos de {total_clases} clases)"
            )

    # 3. NIVEL DE RIESGO
    if   calif_baja and asist_baja: nivel_riesgo = 'Alto'
    elif calif_baja:                nivel_riesgo = 'Medio'
    else:                           nivel_riesgo = 'Bajo'

    # 4. BUSCAR ALERTA EXISTENTE para este alumno + parcial
    alerta_existente = Alerta.objects.filter(
        alumno=alumno,
        parcial=parcial
    ).first()

    if not motivos:
        # Sin problemas → eliminar alerta si existía
        if alerta_existente:
            alerta_existente.delete()
            print(f"[ALERTA ELIMINADA] {alumno.nombre} — {parcial.nombre} ya no tiene problemas")
        return

    motivo_completo = ' | '.join(motivos)

    if alerta_existente:
        # Actualizar — y reactivar si ya estaba atendida
        alerta_existente.motivo       = motivo_completo
        alerta_existente.nivel_riesgo = nivel_riesgo
        alerta_existente.atendida     = False
        alerta_existente.save()
        print(f"[ALERTA ACTUALIZADA] {alumno.nombre} — {nivel_riesgo}: {motivo_completo}")
    else:
        Alerta.objects.create(
            alumno=alumno,
            parcial=parcial,
            motivo=motivo_completo,
            nivel_riesgo=nivel_riesgo
        )
        print(f"[ALERTA CREADA] {alumno.nombre} — {nivel_riesgo}: {motivo_completo}")
 
 
def obtener_alertas_grupo(request):
    """Retorna las alertas no atendidas de todos los alumnos de un grupo/materia"""
    if request.method == 'GET':
        gdm_id     = request.GET.get('gdm_id')
        docente_id = request.session.get('usuario_id')
 
        if not gdm_id:
            return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
        if not docente_id:
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
 
        try:
            gdm     = GrupoDocenteMateria.objects.get(id=gdm_id, docente_id=docente_id)
            alumnos = Alumno.objects.filter(grupo=gdm.grupo)
 
            alertas_data = []
            # Solo parciales de esta materia específica
            parciales_gdm = Parcial.objects.filter(grupo_docente_materia=gdm)

            for alumno in alumnos:
                alertas_alumno = Alerta.objects.filter(
                    alumno=alumno,
                    parcial__in=parciales_gdm,
                    atendida=False
                ).order_by('-fecha', '-id')
 
                for alerta in alertas_alumno:
                    alertas_data.append({
                        'alerta_id':        alerta.id,
                        'alumno_id':        alumno.id,
                        'alumno_nombre':    alumno.nombre,
                        'alumno_matricula': alumno.matricula,
                        'motivo':           alerta.motivo,
                        'nivel_riesgo':     alerta.nivel_riesgo,
                        'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
                        'atendida':         alerta.atendida,
                    })
 
            # Ordenar: Alto → Medio → Bajo
            orden_riesgo = {'Alto': 0, 'Medio': 1, 'Bajo': 2}
            alertas_data.sort(key=lambda x: orden_riesgo.get(x['nivel_riesgo'], 99))
 
            return JsonResponse({'success': True, 'alertas': alertas_data})
 
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 
 
@csrf_exempt
def marcar_alerta_atendida(request):
    """Marca una alerta como atendida"""
    if request.method == 'POST':
        try:
            data      = json.loads(request.body)
            alerta_id = data.get('alerta_id')
 
            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
 
            alerta          = Alerta.objects.get(id=alerta_id)
            alerta.atendida = True
            alerta.save()
 
            return JsonResponse({'success': True, 'message': 'Alerta marcada como atendida'})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 

@csrf_exempt
def cerrar_alerta_tutor(request):
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            comentario = data.get('comentario', '').strip()
 
            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)
 
            usuario_id = request.session.get('usuario_id')
            alerta     = Alerta.objects.select_related('alumno__grupo').get(id=alerta_id)
 
            if alerta.alumno.grupo.tutor_id != usuario_id:
                return JsonResponse({'error': 'Sin permiso para esta alerta'}, status=403)
 
            alerta.atendida = True
            alerta.save()
 
            usuario = Usuario.objects.get(id=usuario_id)
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion='cerrada',
                comentario=comentario
            )
 
            return JsonResponse({'success': True})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 
 
@csrf_exempt
def derivar_alerta(request):
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            destino    = data.get('destino')
            comentario = data.get('comentario', '').strip()
 
            if not alerta_id or not destino:
                return JsonResponse({'error': 'Faltan datos'}, status=400)
            if destino not in ('Pedagogia', 'Direccion', 'Psicologia'):
                return JsonResponse({'error': 'Destino inválido'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)
 
            usuario_id = request.session.get('usuario_id')
            alerta     = Alerta.objects.select_related('alumno__grupo').get(id=alerta_id)
 
            if alerta.alumno.grupo.tutor_id != usuario_id:
                return JsonResponse({'error': 'Sin permiso para esta alerta'}, status=403)
 
            alerta.derivada   = True
            alerta.derivada_a = destino
            alerta.save()
 
            usuario = Usuario.objects.get(id=usuario_id)
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion=f'derivada_{destino.lower()}',
                comentario=comentario
            )
 
            return JsonResponse({'success': True, 'derivada_a': destino})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def cerrar_alerta_pedagogia(request):
    """Pedagogía cierra una alerta con comentario"""
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            comentario = data.get('comentario', '').strip()
 
            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)
 
            alerta = Alerta.objects.get(id=alerta_id, derivada_a='Pedagogia')
 
            alerta.atendida = True
            alerta.save()
 
            usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion='cerrada',
                comentario=comentario
            )
 
            return JsonResponse({'success': True})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 
 
@csrf_exempt
@csrf_exempt
def derivar_alerta_pedagogia(request):
    """Pedagogía deriva una alerta a otro departamento"""
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            destino    = data.get('destino')
            comentario = data.get('comentario', '').strip()

            DESTINOS_VALIDOS = ('Direccion', 'Psicologia', 'Tutor')

            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
            if not destino or destino not in DESTINOS_VALIDOS:
                return JsonResponse({'error': 'Destino inválido'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

            alerta = Alerta.objects.get(id=alerta_id, derivada_a='Pedagogia')

            alerta.derivada_a = destino
            alerta.save()

            usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion=f'derivada_{destino.lower()}',
                comentario=comentario
            )

            return JsonResponse({'success': True, 'derivada_a': destino})

        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido'}, status=405)

def psicologia(request):
    if not request.session.get('usuario_id'):
        return redirect('login')
 
    usuario_id = request.session.get('usuario_id')
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return redirect('login')
 
    # Alertas derivadas a Psicología que no están cerradas
    alertas_qs = Alerta.objects.filter(
        derivada_a='Psicologia',
        atendida=False
    ).select_related('alumno', 'alumno__grupo', 'parcial').order_by('-fecha', '-id')
 
    alertas_data = []
    for alerta in alertas_qs:
        seguimientos = SeguimientoAlerta.objects.filter(
            alerta=alerta
        ).select_related('usuario').order_by('fecha')
 
        seguimientos_data = []
        for s in seguimientos:
            seguimientos_data.append({
                'usuario':    s.usuario.nombre,
                'accion':     s.accion,
                'comentario': s.comentario,
                'fecha':      s.fecha.strftime('%d/%m/%Y %H:%M'),
            })
 
        alertas_data.append({
            'id':               alerta.id,
            'alumno_nombre':    alerta.alumno.nombre,
            'alumno_matricula': alerta.alumno.matricula,
            'alumno_id':        alerta.alumno.id,
            'grupo':            alerta.alumno.grupo.clave,
            'motivo':           alerta.motivo,
            'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo':     alerta.nivel_riesgo,
            'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
            'seguimientos':     seguimientos_data,
        })
 
    stats = {
        'total': len(alertas_data),
        'alto':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'medio': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'bajo':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
    }
 
    return render(request, 'psicologia.html', {
        'usuario':      usuario,
        'alertas':      alertas_data,
        'alertas_json': json.dumps(alertas_data, ensure_ascii=False),
        'stats':        stats,
    })
 
 
@csrf_exempt
def cerrar_alerta_psicologia(request):
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            comentario = data.get('comentario', '').strip()
 
            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)
 
            alerta = Alerta.objects.get(id=alerta_id, derivada_a='Psicologia')
 
            alerta.atendida = True
            alerta.save()
 
            usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion='cerrada',
                comentario=comentario
            )
 
            return JsonResponse({'success': True})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)
 
 
@csrf_exempt
def derivar_alerta_psicologia(request):
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            destino    = data.get('destino')
            comentario = data.get('comentario', '').strip()
 
            DESTINOS_VALIDOS = ('Tutor', 'Pedagogia', 'Direccion')
 
            if not alerta_id or not destino:
                return JsonResponse({'error': 'Faltan datos'}, status=400)
            if destino not in DESTINOS_VALIDOS:
                return JsonResponse({'error': 'Destino inválido'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)
 
            alerta = Alerta.objects.get(id=alerta_id, derivada_a='Psicologia')
 
            alerta.derivada_a = destino
            alerta.save()
 
            usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion=f'derivada_{destino.lower()}',
                comentario=comentario
            )
 
            return JsonResponse({'success': True, 'derivada_a': destino})
 
        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
 
    return JsonResponse({'error': 'Método no permitido'}, status=405)