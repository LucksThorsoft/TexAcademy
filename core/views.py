from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse
from django.core.cache import cache
import csv
import re
import traceback
from io import TextIOWrapper
from .forms import *
from .models import *
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
from django.contrib.auth.hashers import make_password, check_password
from .services import notificar_tutor_alerta, notificar_alumno_cita

# Create your views here.


def home(request):
    return render(request, "home.html")



# En views.py, modificar la función dashboard - Sección de actividades
def determinar_estado_alumno(alumno, docente):
    """
    Determina el estado de un alumno basado ÚNICAMENTE en sus alertas existentes
    Retorna: (estado_texto, estado_clase, en_riesgo_boolean)
    """
    materias_docente = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo,
        docente=docente
    )
    
    if not materias_docente.exists():
        return ("Sin información", "status-info", False)
    
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=materias_docente
    ).values_list('id', flat=True)
    
    alertas = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids
    )
    
    if not alertas.exists():
        return ("Estable", "status-good", False)
    
    if alertas.filter(nivel_riesgo='Alto').exists():
        return ("En Riesgo", "status-danger", True)
    elif alertas.filter(nivel_riesgo='Medio').exists():
        return ("Requiere Atención", "status-warning", False)
    elif alertas.filter(nivel_riesgo='Bajo').exists():
        return ("Precaución", "status-info", False)
    
    return ("Estable", "status-good", False)

def dashboard(request):
    # Verificar si el usuario está autenticado
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    # Obtener el usuario actual desde la sesión
    usuario_id = request.session.get('usuario_id')
    
    try:
        # Obtener el usuario
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener los roles del usuario
        roles = request.session.get('usuario_roles', [])
        
        # Inicializar variables
        grupos_data = []
        total_alumnos = 0
        alumnos_riesgo = 0
        actividades_pendientes = 0
        actividades_data = []
        alertas_data = []
        
        # Si es docente, obtener sus grupos
        if 'Docente' in roles:
            # Obtener todos los grupos donde este docente imparte alguna materia
            grupos_docente = GrupoDocenteMateria.objects.filter(
                docente=usuario
            ).select_related('grupo', 'materia').values('grupo').distinct()
            
            # Obtener los IDs de los grupos
            grupo_ids = [g['grupo'] for g in grupos_docente]
            
            # Obtener los IDs de los GDM del docente para filtrar alertas
            gdm_ids = GrupoDocenteMateria.objects.filter(
                docente=usuario,
                grupo__id__in=grupo_ids
            ).values_list('id', flat=True)
            
            # Obtener los IDs de los parciales de esas materias
            parciales_ids = Parcial.objects.filter(
                grupo_docente_materia__id__in=gdm_ids
            ).values_list('id', flat=True)
            
            # Obtener ALERTAS NO ATENDIDAS de nivel ALTO
            alertas = Alerta.objects.filter(
                parcial__id__in=parciales_ids,
                atendida=False,
                nivel_riesgo='Alto'
            ).select_related(
                'alumno',
                'alumno__grupo',
                'parcial',
                'parcial__grupo_docente_materia__materia'
            ).order_by('-fecha')[:10]
            
            # Procesar alertas para el template
            for alerta in alertas:
                # Obtener nombre del grupo con carrera
                grupo = alerta.alumno.grupo
                if hasattr(grupo, 'carrera') and grupo.carrera:
                    grupo_nombre = f"{grupo.carrera} - {grupo.clave}"
                else:
                    grupo_nombre = f"Grupo {grupo.clave}"
                
                # Obtener materia
                materia_nombre = "General"
                if alerta.parcial and alerta.parcial.grupo_docente_materia:
                    materia_nombre = alerta.parcial.grupo_docente_materia.materia.nombre
                
                # Calcular tiempo relativo
                hoy = timezone.now().date()
                fecha_alerta = alerta.fecha  # ya es un objeto date
                
                if fecha_alerta == hoy:
                    tiempo = "Hoy"
                elif (hoy - fecha_alerta).days == 1:
                    tiempo = "Ayer"
                else:
                    dias = (hoy - fecha_alerta).days
                    tiempo = f"Hace {dias} días"
                
                alertas_data.append({
                    'id': alerta.id,
                    'alumno_nombre': alerta.alumno.nombre,
                    'alumno_matricula': alerta.alumno.matricula,
                    'alumno_id': alerta.alumno.id,
                    'descripcion': alerta.motivo,
                    'tiempo': tiempo,
                    'grupo_clave': grupo.clave,
                    'grupo_nombre': grupo_nombre,
                    'materia': materia_nombre,
                    'nivel_riesgo': alerta.nivel_riesgo
                })
            
            # Obtener los grupos completos con sus relaciones
            grupos = Grupo.objects.filter(id__in=grupo_ids).prefetch_related(
                'alumno_set',
                'grupodocentemateria_set__materia'
            )
            
            # Preparar datos de grupos
            for grupo in grupos:
                # Obtener las materias que el docente imparte en este grupo
                materias = GrupoDocenteMateria.objects.filter(
                    grupo=grupo,
                    docente=usuario
                ).select_related('materia')
                
                # Crear un nombre más descriptivo para el grupo
                if hasattr(grupo, 'carrera') and grupo.carrera:
                    nombre_completo = f"{grupo.carrera} - {grupo.clave}"
                else:
                    nombre_completo = f"Grupo {grupo.clave}"
                
                # Lista de materias que imparte en este grupo
                materias_lista = [m.materia.nombre for m in materias]
                
                # Contar alumnos en este grupo
                num_alumnos = Alumno.objects.filter(grupo=grupo).count()
                total_alumnos += num_alumnos
                
                # Calcular alumnos en riesgo usando la función determinar_estado_alumno
                alumnos_grupo = Alumno.objects.filter(grupo=grupo)
                riesgo_grupo = 0
                
                for alumno in alumnos_grupo:
                    # Usar la función unificada para determinar el estado
                    _, _, en_riesgo = determinar_estado_alumno(alumno, usuario)
                    if en_riesgo:
                        riesgo_grupo += 1
                
                alumnos_riesgo += riesgo_grupo
                
                grupos_data.append({
                    'id': grupo.id,
                    'clave': grupo.clave,
                    'nombre_completo': nombre_completo,
                    'carrera': getattr(grupo, 'carrera', ''),
                    'materias': materias_lista,
                    'num_alumnos': num_alumnos,
                    'alumnos_riesgo': riesgo_grupo
                })
            
            # MODIFICACIÓN: Obtener actividades que NO tengan el 100% de entregas
            hoy = datetime.now().date()
            
            # Obtener todas las actividades del docente (sin filtro de fecha)
            todas_actividades = Actividad.objects.filter(
                parcial__grupo_docente_materia__docente=usuario
            ).select_related(
                'parcial__grupo_docente_materia__grupo'
            ).order_by('fecha_entrega')
            
            # Filtrar actividades que aún tienen entregas pendientes
            actividades_pendientes_lista = []
            for actividad in todas_actividades:
                grupo = actividad.parcial.grupo_docente_materia.grupo
                total_alumnos_act = Alumno.objects.filter(grupo=grupo).count()
                entregadas = Entrega.objects.filter(
                    actividad=actividad,
                    entregado=True
                ).count()
                
                # Solo incluir si NO tiene el 100% de entregas
                if entregadas < total_alumnos_act:
                    actividades_pendientes_lista.append(actividad)
            
            # Contar actividades pendientes (sin el 100% de entregas)
            actividades_pendientes = len(actividades_pendientes_lista)
            
            # Tomar solo las primeras 5 para mostrar
            actividades_mostrar = actividades_pendientes_lista[:5]
            
            # Procesar actividades para el template
            for actividad in actividades_mostrar:
                grupo = actividad.parcial.grupo_docente_materia.grupo
                total_alumnos_act = Alumno.objects.filter(grupo=grupo).count()
                entregadas = Entrega.objects.filter(
                    actividad=actividad,
                    entregado=True
                ).count()
                
                # Calcular días restantes (pueden ser negativos si ya pasó la fecha)
                dias_restantes = (actividad.fecha_entrega - hoy).days
                porcentaje = int((entregadas / total_alumnos_act * 100)) if total_alumnos_act > 0 else 0
                
                # Crear nombre descriptivo para el grupo en actividades
                if hasattr(grupo, 'carrera') and grupo.carrera:
                    grupo_nombre = f"{grupo.carrera} - {grupo.clave}"
                else:
                    grupo_nombre = f"Grupo {grupo.clave}"
                
                actividades_data.append({
                    'id': actividad.id,
                    'titulo': actividad.titulo,
                    'grupo_clave': grupo.clave,
                    'grupo_nombre': grupo_nombre,
                    'entregadas': entregadas,
                    'total_alumnos': total_alumnos_act,
                    'porcentaje_entregas': porcentaje,
                    'dias_restantes': dias_restantes,
                    'fecha_entrega': actividad.fecha_entrega
                })
        
        context = {
            'docente_nombre': usuario.nombre,
            'roles': roles,
            'grupos': grupos_data,
            'total_alumnos': total_alumnos,
            'alumnos_riesgo': alumnos_riesgo,
            'actividades_pendientes': actividades_pendientes,
            'actividades': actividades_data,
            'total_grupos': len(grupos_data),
            'alertas': alertas_data,
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "dashboard.html", context)

def gruposAlumnos(request):
    # Verificar si el usuario está autenticado
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    # Obtener el usuario actual desde la sesión
    usuario_id = request.session.get('usuario_id')
    
    try:
        # Obtener el usuario
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener el cuatrimestre activo
        cuatrimestre_activo = Cuatrimestre.objects.filter(activo=True).first()
        
        # Si no hay cuatrimestre activo, mostrar mensaje
        if not cuatrimestre_activo:
            context = {
                'grupos': [],
                'docente_nombre': usuario.nombre,
                'sin_cuatrimestre': True,
                'mensaje': 'No hay un cuatrimestre activo en el sistema'
            }
            return render(request, "gruposAlumnos.html", context)
        
        # Obtener todas las materias que imparte este docente por grupo
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario,
            grupo__cuatrimestre=cuatrimestre_activo
        ).select_related('grupo', 'materia').order_by('grupo__clave', 'materia__nombre')
        
        # Estructura para agrupar materias por grupo
        grupos_dict = {}
        
        for gdm in grupos_docente:
            grupo = gdm.grupo
            materia = gdm.materia
            
            if grupo.clave not in grupos_dict:
                num_alumnos = Alumno.objects.filter(grupo=grupo).count()
                alumnos_grupo = Alumno.objects.filter(grupo=grupo)
                
                alumnos_list = list(alumnos_grupo)
                
                def extract_matricula_number(matricula):
                    try:
                        numbers = re.findall(r'\d+', matricula)
                        if numbers:
                            return int(numbers[0])
                        return 0
                    except:
                        return 0
                
                alumnos_list.sort(key=lambda x: (
                    extract_matricula_number(x.matricula),
                    x.nombre.lower()
                ))
                
                alumnos_data = []
                for alumno in alumnos_list:
                    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, usuario)
                    
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
                        'estado': estado_texto,
                        'estado_clase': estado_clase,
                        'en_riesgo': en_riesgo,
                        'comentarios': comentarios_data,
                    })
                
                grupos_dict[grupo.clave] = {
                    'clave': grupo.clave,
                    'materias': [],
                    'num_alumnos': num_alumnos,
                    'grupo_id': grupo.id,
                    'alumnos': alumnos_data,
                    'alumnos_json': json.dumps(alumnos_data, ensure_ascii=False),
                    'promedio_grupal': None,
                    'promedio_grupal_valido': False,
                    'alumnos_riesgo': 0,
                }
            
            parciales = Parcial.objects.filter(grupo_docente_materia=gdm).order_by('numero_parcial')
            tiene_parciales = parciales.exists()
            
            parciales_data = []
            if tiene_parciales:
                for parcial in parciales:
                    # Obtener ponderaciones de este parcial
                    ponderaciones = Ponderacion.objects.filter(parcial=parcial)
                    ponderaciones_data = []
                    for pond in ponderaciones:
                        ponderaciones_data.append({
                            'nombre': pond.nombre,
                            'porcentaje': pond.porcentaje,
                        })
                    
                    parciales_data.append({
                        'numero': parcial.numero_parcial,
                        'nombre': parcial.nombre,
                        'porcentaje': parcial.porcentaje,
                        'fecha_inicio': parcial.fecha_inicio.strftime('%d/%m/%Y'),
                        'fecha_fin': parcial.fecha_cierre.strftime('%d/%m/%Y'),
                        'ponderaciones': ponderaciones_data,
                    })
            
            grupos_dict[grupo.clave]['materias'].append({
                'id': gdm.id,
                'nombre': materia.nombre,
                'tiene_parciales': tiene_parciales,
                'parciales_configurados': gdm.parciales_configurados,
                'parciales': parciales_data,
            })
        
        # Calcular promedios grupales y alumnos en riesgo
        for clave, grupo_data in grupos_dict.items():
            grupo_id = grupo_data['grupo_id']
            alumnos_grupo = Alumno.objects.filter(grupo_id=grupo_id)
            
            if alumnos_grupo.exists():
                suma_promedios = 0
                alumnos_con_promedio = 0
                alumnos_en_riesgo = 0
                
                for alumno in alumnos_grupo:
                    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, usuario)
                    
                    alumno_data = next((a for a in grupo_data['alumnos'] if a['id'] == alumno.id), None)
                    if alumno_data:
                        alumno_data['estado'] = estado_texto
                        alumno_data['estado_clase'] = estado_clase
                        alumno_data['en_riesgo'] = en_riesgo
                    
                    if en_riesgo:
                        alumnos_en_riesgo += 1
                    
                    calificaciones = CalificacionParcial.objects.filter(
                        alumno=alumno,
                        parcial__grupo_docente_materia__docente=usuario,
                        parcial__grupo_docente_materia__grupo_id=grupo_id
                    )
                    
                    if calificaciones.exists():
                        suma_califs = sum(c.calificacion for c in calificaciones if c.calificacion is not None)
                        total_califs = calificaciones.count()
                        
                        parciales_totales = Parcial.objects.filter(
                            grupo_docente_materia__docente=usuario,
                            grupo_docente_materia__grupo_id=grupo_id
                        ).count()
                        
                        if total_califs == parciales_totales and total_califs > 0:
                            def redondear(valor):
                                entero = int(valor)
                                ultimo_digito = entero % 10
                                if ultimo_digito == 0:
                                    return entero
                                elif ultimo_digito <= 4:
                                    return entero - ultimo_digito
                                else:
                                    return entero + (10 - ultimo_digito)
                            
                            suma_redondeada = redondear(suma_califs)
                            promedio_final = suma_redondeada / 10
                            suma_promedios += promedio_final
                            alumnos_con_promedio += 1
                
                if alumnos_con_promedio > 0 and alumnos_con_promedio == alumnos_grupo.count():
                    grupo_data['promedio_grupal'] = round(suma_promedios / alumnos_con_promedio, 1)
                    grupo_data['promedio_grupal_valido'] = True
                
                grupo_data['alumnos_riesgo'] = alumnos_en_riesgo
                grupo_data['alumnos_json'] = json.dumps(grupo_data['alumnos'], ensure_ascii=False)
        
        grupos_data = []
        for clave, grupo_data in grupos_dict.items():
            grupo_data['materias_json'] = json.dumps(grupo_data['materias'], ensure_ascii=False)
            grupos_data.append(grupo_data)
        
        context = {
            'grupos': grupos_data,
            'docente_nombre': usuario.nombre,
            'cuatrimestre_activo': cuatrimestre_activo.nombre if cuatrimestre_activo else None,
            'sin_cuatrimestre': False,
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "gruposAlumnos.html", context)

@csrf_exempt
def guardar_parciales(request):
    """Endpoint para guardar la configuración de parciales y sus ponderaciones"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            gdm_id = data.get('gdm_id')
            unidades = data.get('unidades', [])
            ponderaciones = data.get('ponderaciones', {})  # Diccionario: {unidad_numero: [ponderaciones]}
            
            if not gdm_id:
                return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
            
            if not unidades:
                return JsonResponse({'error': 'No se recibieron unidades'}, status=400)
            
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para modificar esta materia'}, status=403)
            
            total_porcentaje = sum(u['porcentaje'] for u in unidades)
            if total_porcentaje != 100:
                return JsonResponse({'error': 'El total de porcentajes debe ser 100%'}, status=400)
            
            fechas_validas = validar_fechas_consecutivas(unidades)
            if not fechas_validas:
                return JsonResponse({'error': 'Las fechas no son consecutivas correctamente'}, status=400)
            
            # Eliminar parciales existentes y sus ponderaciones
            Parcial.objects.filter(grupo_docente_materia=gdm).delete()
            
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
                
                # Guardar ponderaciones de esta unidad
                unidad_numero = str(unidad['numero'])
                if unidad_numero in ponderaciones:
                    for idx, pond in enumerate(ponderaciones[unidad_numero]):
                        Ponderacion.objects.create(
                            parcial=parcial,
                            nombre=pond['nombre'],
                            porcentaje=pond['porcentaje'],
                            orden=idx
                        )
                
                # Obtener ponderaciones guardadas para la respuesta
                ponderaciones_guardadas = []
                for pond in parcial.ponderaciones.all():
                    ponderaciones_guardadas.append({
                        'nombre': pond.nombre,
                        'porcentaje': pond.porcentaje,
                    })
                
                parciales_creados.append({
                    'numero': parcial.numero_parcial,
                    'nombre': parcial.nombre,
                    'porcentaje': parcial.porcentaje,
                    'fecha_inicio': parcial.fecha_inicio.strftime('%Y-%m-%d'),
                    'fecha_fin': parcial.fecha_cierre.strftime('%Y-%m-%d'),
                    'ponderaciones': ponderaciones_guardadas,
                })
            
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
    """Valida que las fechas sean consecutivas"""
    if len(unidades) <= 1:
        return True
    
    unidades_ordenadas = sorted(unidades, key=lambda x: x['fecha_inicio'])
    
    for i in range(len(unidades_ordenadas) - 1):
        fecha_fin_actual = datetime.strptime(unidades_ordenadas[i]['fecha_fin'], '%Y-%m-%d').date()
        fecha_inicio_siguiente = datetime.strptime(unidades_ordenadas[i + 1]['fecha_inicio'], '%Y-%m-%d').date()
        
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
                alumno_id = item.get('alumno_id')
                parcial_numero = item.get('parcial')
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

                if calif_float is not None:
                    _generar_alertas_alumno(alumno, parcial, gdm, calif_float)
                else:
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
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para ver esta materia'}, status=403)
            
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
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    alumno = get_object_or_404(Alumno, id=alumno_id)
    docente_id = request.session.get('usuario_id')
    docente = get_object_or_404(Usuario, id=docente_id)

    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, docente)
    
    materias_docente = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo,
        docente=docente
    ).select_related('materia')
    
    gdm_ids_docente = [gdm.id for gdm in materias_docente]
    
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=gdm_ids_docente
    ).values_list('id', flat=True)
    
    promedio_materia = None
    
    calificaciones_data = []
    parciales_info = []
    
    for gdm in materias_docente:
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm
        ).order_by('numero_parcial')
        
        for parcial in parciales:
            parciales_info.append({
                'numero': parcial.numero_parcial,
                'nombre': parcial.nombre,
                'porcentaje': parcial.porcentaje,
            })
        
        for parcial in parciales:
            calificacion = CalificacionParcial.objects.filter(
                alumno=alumno,
                parcial=parcial
            ).first()
            
            calificaciones_data.append({
                'parcial_numero': parcial.numero_parcial,
                'parcial_nombre': parcial.nombre,
                'parcial_porcentaje': parcial.porcentaje,
                'calificacion': calificacion.calificacion if calificacion and calificacion.calificacion is not None else None
            })
    
    suma_calificaciones = sum([
        c['calificacion'] for c in calificaciones_data 
        if c['calificacion'] is not None
    ])
    total_calificaciones = len([c for c in calificaciones_data if c['calificacion'] is not None])
    todas_completas = total_calificaciones == len(parciales_info) and total_calificaciones > 0
    
    if todas_completas and suma_calificaciones > 0:
        def redondear_calificacion(valor):
            entero = int(valor)
            ultimo_digito = entero % 10
            if ultimo_digito == 0:
                return entero
            elif ultimo_digito <= 4:
                return entero - ultimo_digito
            else:
                return entero + (10 - ultimo_digito)
        
        suma_redondeada = redondear_calificacion(suma_calificaciones)
        promedio_materia = suma_redondeada / 10
    
    actividades_data = []
    for gdm in materias_docente:
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm,
            cerrado=False
        )
        
        for parcial in parciales:
            actividades = Actividad.objects.filter(
                parcial=parcial
            ).order_by('fecha_entrega')
            
            for actividad in actividades:
                entrega = Entrega.objects.filter(
                    actividad=actividad,
                    alumno=alumno
                ).first()
                
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
    
    asistencias_todas = Asistencia.objects.filter(
        alumno=alumno
    ).select_related(
        'grupo_docente_materia__materia', 
        'grupo_docente_materia__docente',
        'estado'
    ).order_by('-fecha')
    
    asistencia_todas_data = []
    
    for asistencia in asistencias_todas:
        materia_nombre = asistencia.grupo_docente_materia.materia.nombre
        docente_nombre = asistencia.grupo_docente_materia.docente.nombre
        estado_nombre = asistencia.estado.nombre
        
        registro = {
            'fecha': asistencia.fecha.strftime('%d/%m/%Y'),
            'materia': materia_nombre,
            'docente': docente_nombre,
            'estado': estado_nombre,
            'comentario': asistencia.comentario,
            'gdm_id': asistencia.grupo_docente_materia.id
        }
        
        asistencia_todas_data.append(registro)
    
    asistencia_esta_materia = [a for a in asistencia_todas_data if a['gdm_id'] in gdm_ids_docente]
    
    total_asistencias_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'Asistió')
    total_retardos_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'Retardo')
    total_faltas_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'No asistió')
    total_clases_esta = len(asistencia_esta_materia)
    
    if total_clases_esta > 0:
        porcentaje_esta = int(((total_asistencias_esta + total_retardos_esta * 0.5) / total_clases_esta) * 100)
    else:
        porcentaje_esta = 0
    
    total_asistencias_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'Asistió')
    total_retardos_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'Retardo')
    total_faltas_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'No asistió')
    total_clases_todas = len(asistencia_todas_data)
    
    if total_clases_todas > 0:
        porcentaje_todas = int(((total_asistencias_todas + total_retardos_todas * 0.5) / total_clases_todas) * 100)
    else:
        porcentaje_todas = 0
    
    comentarios_todas = []
    for a in asistencia_todas_data:
        if a['comentario'] and a['comentario'].strip():
            tipo_comentario = "Observación"
            if a['estado'] == "No asistió":
                tipo_comentario = "Falta"
            elif a['estado'] == "Retardo":
                tipo_comentario = "Retardo"
            
            comentarios_todas.append({
                'tipo': tipo_comentario,
                'fecha': a['fecha'],
                'texto': a['comentario'],
                'docente': a['docente'],
                'materia': a['materia'],
                'estado': a['estado'],
                'gdm_id': a['gdm_id']
            })
    
    comentarios_esta_materia = [c for c in comentarios_todas if c['gdm_id'] in gdm_ids_docente]

    alertas = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids
    ).select_related('parcial__grupo_docente_materia__materia').order_by(
        models.Case(
            models.When(nivel_riesgo='Alto', then=0),
            models.When(nivel_riesgo='Medio', then=1),
            models.When(nivel_riesgo='Bajo', then=2),
            default=3,
            output_field=models.IntegerField(),
        ),
        '-fecha'
    )
    
    alertas_data = []
    for alerta in alertas:
        materia_nombre = "General"
        if alerta.parcial and alerta.parcial.grupo_docente_materia:
            materia_nombre = alerta.parcial.grupo_docente_materia.materia.nombre
        
        alertas_data.append({
            'id': alerta.id,
            'motivo': alerta.motivo,
            'nivel_riesgo': alerta.nivel_riesgo,
            'fecha': alerta.fecha.strftime('%d/%m/%Y'),
            'materia': materia_nombre,
            'parcial': alerta.parcial.nombre if alerta.parcial else None,
        })
    
    cuatrimestre_activo = alumno.grupo.cuatrimestre.activo if alumno.grupo.cuatrimestre else False
    hoy = timezone.now().date()
    
    if alumno.grupo.cuatrimestre:
        cuatrimestre_en_rango = (
            alumno.grupo.cuatrimestre.fecha_inicio <= hoy <= alumno.grupo.cuatrimestre.fecha_fin
        )
        cuatrimestre_valido = alumno.grupo.cuatrimestre.activo and cuatrimestre_en_rango
    else:
        cuatrimestre_valido = False
    
    context = {
        'alumno': alumno,
        'parciales_info': parciales_info,
        'calificaciones_data': calificaciones_data,
        'promedio_materia': promedio_materia,
        'actividades': actividades_data,
        'asistencia_esta_materia': asistencia_esta_materia,
        'asistencia_todas_materias': asistencia_todas_data,
        'stats_esta_materia': {
            'asistencias': total_asistencias_esta,
            'retardos': total_retardos_esta,
            'faltas': total_faltas_esta,
            'total_clases': total_clases_esta,
            'porcentaje': porcentaje_esta,
        },
        'stats_todas_materias': {
            'asistencias': total_asistencias_todas,
            'retardos': total_retardos_todas,
            'faltas': total_faltas_todas,
            'total_clases': total_clases_todas,
            'porcentaje': porcentaje_todas,
        },
        'comentarios_esta_materia': comentarios_esta_materia,
        'comentarios_todas_materias': comentarios_todas,
        'materias_docente': materias_docente,
        'alertas': alertas_data,
        'total_alertas': len(alertas_data),
        'alertas_alto': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'alertas_medio': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'alertas_bajo': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
        'estado_alumno': estado_texto,
        'estado_clase': estado_clase,
        'cuatrimestre_valido': cuatrimestre_valido,
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


#Nuevos endpoints para estadisticas individuales del alumno y editar activisdades

def editar_actividad(request, id):
    """Vista para editar una actividad existente"""
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    if not request.session.get('usuario_id'):
        return JsonResponse({"error": "No autorizado"}, status=401)
    
    try:
        data = json.loads(request.body)
        actividad = Actividad.objects.select_related(
            'parcial__grupo_docente_materia'
        ).get(id=id)
        
        # Verificar permiso
        if actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)
        
        # Actualizar campos
        actividad.titulo = data.get('titulo', actividad.titulo)
        actividad.descripcion = data.get('descripcion', actividad.descripcion)
        
        # Manejar la fecha correctamente
        fecha_entrega = data.get('fecha_entrega')
        if fecha_entrega:
            # Si es string, convertir a date
            if isinstance(fecha_entrega, str):
                actividad.fecha_entrega = datetime.strptime(fecha_entrega, '%Y-%m-%d').date()
            else:
                actividad.fecha_entrega = fecha_entrega
        
        actividad.save()
        
        return JsonResponse({
            "success": True,
            "message": "Actividad actualizada correctamente",
            "actividad": {
                "id": actividad.id,
                "titulo": actividad.titulo,
                "descripcion": actividad.descripcion,
                "fecha_entrega": actividad.fecha_entrega.strftime('%Y-%m-%d')
            }
        })
        
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        print(f"Error en editar_actividad: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def obtener_actividad_para_editar(request, id):
    """Obtener datos de una actividad para editar"""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    if not request.session.get('usuario_id'):
        return JsonResponse({"error": "No autorizado"}, status=401)
    
    try:
        actividad = Actividad.objects.select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'
        ).get(id=id)
        
        # Verificar permiso
        if actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)
        
        return JsonResponse({
            "success": True,
            "actividad": {
                "id": actividad.id,
                "titulo": actividad.titulo,
                "descripcion": actividad.descripcion,
                "fecha_entrega": actividad.fecha_entrega.strftime('%Y-%m-%d'),  # Asegurar formato string
                "grupo_id": actividad.parcial.grupo_docente_materia.grupo.id,
                "materia_id": actividad.parcial.grupo_docente_materia.id,
                "grupo_clave": actividad.parcial.grupo_docente_materia.grupo.clave,
                "materia_nombre": actividad.parcial.grupo_docente_materia.materia.nombre,
                "parcial_nombre": actividad.parcial.nombre
            }
        })
        
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        print(f"Error en obtener_actividad_para_editar: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def estadisticas_actividad_individual(request, id):
    """API para obtener estadísticas detalladas de una actividad específica"""
    if not request.session.get('usuario_id'):
        return JsonResponse({"error": "No autorizado"}, status=401)
    
    try:
        actividad = Actividad.objects.select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'
        ).get(id=id)
        
        # Verificar permiso
        if actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)
        
        grupo = actividad.parcial.grupo_docente_materia.grupo
        alumnos = Alumno.objects.filter(grupo=grupo).order_by('nombre')
        
        # Estadísticas de entregas
        entregas = Entrega.objects.filter(actividad=actividad)
        entregas_completadas = entregas.filter(entregado=True).count()
        total_alumnos = alumnos.count()
        porcentaje_entregas = (entregas_completadas / total_alumnos * 100) if total_alumnos > 0 else 0
        
        # Calificaciones (el campo existe en tu modelo)
        calificaciones = [e.calificacion for e in entregas if e.entregado and e.calificacion is not None]
        promedio_calificacion = sum(calificaciones) / len(calificaciones) if calificaciones else None
        calificacion_max = max(calificaciones) if calificaciones else None
        calificacion_min = min(calificaciones) if calificaciones else None
        
        # Distribución de calificaciones
        rangos = {
            'excelente': 0,   # 90-100
            'bueno': 0,       # 80-89
            'regular': 0,     # 70-79
            'insuficiente': 0, # 60-69
            'reprobado': 0     # 0-59
        }
        
        for e in entregas:
            if e.entregado and e.calificacion is not None:
                if e.calificacion >= 90:
                    rangos['excelente'] += 1
                elif e.calificacion >= 80:
                    rangos['bueno'] += 1
                elif e.calificacion >= 70:
                    rangos['regular'] += 1
                elif e.calificacion >= 60:
                    rangos['insuficiente'] += 1
                else:
                    rangos['reprobado'] += 1
        
        # Datos por alumno para tabla detallada (SIN fecha_entrega porque no existe)
        alumnos_data = []
        for alumno in alumnos:
            entrega = entregas.filter(alumno=alumno).first()
            alumnos_data.append({
                'alumno_id': alumno.id,
                'nombre': alumno.nombre,
                'matricula': alumno.matricula,
                'entregado': entrega.entregado if entrega else False,
                'calificacion': entrega.calificacion if entrega and entrega.entregado and entrega.calificacion is not None else None,
                # 'fecha_entrega' NO existe en tu modelo, así que lo omitimos
            })
        
        # Determinar estado actual
        hoy = timezone.now().date()
        if actividad.parcial.cerrado:
            estado = 'cerrada'
            estado_color = '#6b7280'
        elif actividad.fecha_entrega < hoy:
            estado = 'vencida'
            estado_color = '#dc2626'
        else:
            estado = 'activa'
            estado_color = '#10b981'
        
        return JsonResponse({
            'success': True,
            'actividad': {
                'id': actividad.id,
                'titulo': actividad.titulo,
                'descripcion': actividad.descripcion,
                'materia': actividad.parcial.grupo_docente_materia.materia.nombre,
                'grupo': grupo.clave,
                'parcial': actividad.parcial.nombre,
                'fecha_entrega': actividad.fecha_entrega.strftime('%d/%m/%Y'),
                'estado': estado,
                'estado_color': estado_color
            },
            'estadisticas': {
                'total_alumnos': total_alumnos,
                'entregas_completadas': entregas_completadas,
                'entregas_pendientes': total_alumnos - entregas_completadas,
                'porcentaje_entregas': round(porcentaje_entregas, 1),
                'promedio_calificacion': round(promedio_calificacion, 1) if promedio_calificacion else None,
                'calificacion_max': calificacion_max,
                'calificacion_min': calificacion_min,
                'rangos_calificaciones': rangos
            },
            'alumnos': alumnos_data
        })
        
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        print(f"Error en estadisticas_actividad_individual: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    
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
            # ── Obtener citas de esta alerta ──────────────────
            citas = Cita.objects.filter(
                alerta=alerta
            ).order_by('-fecha_creacion')

            citas_data = []
            for cita in citas:
                citas_data.append({
                    'id':          cita.id,
                    'fecha':       cita.fecha.strftime('%d/%m/%Y'),
                    'hora':        cita.hora.strftime('%H:%M'),
                    'comentario':  cita.comentario,
                    'estado':      cita.estado,
                    'rol_creador': cita.rol_creador,
                    'creado_por':  cita.creado_por.nombre,
                })

            alertas_data.append({
                'id':               alerta.id,
                'alumno_nombre':    alerta.alumno.nombre,
                'alumno_matricula': alerta.alumno.matricula,
                'alumno_id':        alerta.alumno.id,
                'motivo':           alerta.motivo,
                'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
                'nivel_riesgo':     alerta.nivel_riesgo,
                'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
                'derivada':         alerta.derivada,
                'derivada_a':       alerta.derivada_a or '',
                'citas':            citas_data,          # ← nuevo
                'tiene_citas':      len(citas_data) > 0, # ← nuevo
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

def actualizar_calificacion_entrega(request):
    """Actualizar calificación de una entrega individual"""
    if request.method != 'POST':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    if not request.session.get('usuario_id'):
        return JsonResponse({"error": "No autorizado"}, status=401)
    
    try:
        data = json.loads(request.body)
        entrega_id = data.get('entrega_id')
        calificacion = data.get('calificacion')
        
        entrega = Entrega.objects.select_related(
            'actividad__parcial__grupo_docente_materia'
        ).get(id=entrega_id)
        
        # Verificar permiso
        if entrega.actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)
        
        # Validar calificación
        if calificacion is not None:
            try:
                calif_float = float(calificacion)
                if calif_float < 0 or calif_float > 100:
                    return JsonResponse({"error": "La calificación debe estar entre 0 y 100"}, status=400)
                entrega.calificacion = calif_float
            except ValueError:
                return JsonResponse({"error": "Calificación inválida"}, status=400)
        else:
            entrega.calificacion = None
        
        entrega.save()
        
        return JsonResponse({
            "success": True,
            "message": "Calificación actualizada correctamente",
            "calificacion": entrega.calificacion
        })
        
    except Entrega.DoesNotExist:
        return JsonResponse({"error": "Entrega no encontrada"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def estadisticas_alumno_individual(request, alumno_id):
    """API para obtener estadísticas detalladas de un alumno específico"""
    if not request.session.get('usuario_id'):
        return JsonResponse({"error": "No autorizado"}, status=401)
    
    try:
        alumno = Alumno.objects.select_related('grupo').get(id=alumno_id)
        
        # Verificar que el docente tiene acceso a este alumno
        docente_id = request.session.get('usuario_id')
        tiene_acceso = GrupoDocenteMateria.objects.filter(
            grupo=alumno.grupo,
            docente_id=docente_id
        ).exists()
        
        if not tiene_acceso:
            return JsonResponse({"error": "No tienes permiso para ver este alumno"}, status=403)
        
        # Obtener todas las actividades del grupo del alumno
        actividades = Actividad.objects.filter(
            parcial__grupo_docente_materia__grupo=alumno.grupo
        ).select_related(
            'parcial',
            'parcial__grupo_docente_materia__materia'
        ).order_by('-fecha_entrega')
        
        # Estadísticas de actividades
        total_actividades = actividades.count()
        actividades_completadas = 0
        actividades_pendientes = 0
        suma_calificaciones = 0
        calificaciones_count = 0
        
        actividades_detalle = []
        
        for actividad in actividades:
            entrega = Entrega.objects.filter(
                actividad=actividad,
                alumno=alumno
            ).first()
            
            entregado = entrega.entregado if entrega else False
            calificacion = entrega.calificacion if entregado and entrega.calificacion else None
            
            if entregado:
                actividades_completadas += 1
                if calificacion is not None:
                    suma_calificaciones += calificacion
                    calificaciones_count += 1
            else:
                actividades_pendientes += 1
            
            # Determinar estado de la actividad
            hoy = timezone.now().date()
            if actividad.parcial.cerrado:
                estado = 'cerrada'
            elif actividad.fecha_entrega < hoy:
                estado = 'vencida'
            else:
                estado = 'activa'
            
            actividades_detalle.append({
                'id': actividad.id,
                'titulo': actividad.titulo,
                'materia': actividad.parcial.grupo_docente_materia.materia.nombre,
                'parcial': actividad.parcial.nombre,
                'fecha_entrega': actividad.fecha_entrega.strftime('%d/%m/%Y'),
                'entregado': entregado,
                'calificacion': calificacion,
                'estado': estado
            })
        
        # Calcular promedios
        promedio_calificaciones = round(suma_calificaciones / calificaciones_count, 1) if calificaciones_count > 0 else None
        porcentaje_completado = round((actividades_completadas / total_actividades * 100), 1) if total_actividades > 0 else 0
        
        # Estadísticas por materia
        materias_stats = {}
        for act in actividades_detalle:
            materia = act['materia']
            if materia not in materias_stats:
                materias_stats[materia] = {
                    'total': 0,
                    'completadas': 0,
                    'suma_calif': 0,
                    'calif_count': 0
                }
            materias_stats[materia]['total'] += 1
            if act['entregado']:
                materias_stats[materia]['completadas'] += 1
                if act['calificacion']:
                    materias_stats[materia]['suma_calif'] += act['calificacion']
                    materias_stats[materia]['calif_count'] += 1
        
        materias_resumen = []
        for materia, stats in materias_stats.items():
            promedio = round(stats['suma_calif'] / stats['calif_count'], 1) if stats['calif_count'] > 0 else None
            materias_resumen.append({
                'nombre': materia,
                'total_actividades': stats['total'],
                'completadas': stats['completadas'],
                'pendientes': stats['total'] - stats['completadas'],
                'porcentaje': round((stats['completadas'] / stats['total'] * 100), 1),
                'promedio': promedio
            })
        
        # Ordenar por porcentaje descendente
        materias_resumen.sort(key=lambda x: x['porcentaje'], reverse=True)
        
        # Alertas del alumno
        alertas = Alerta.objects.filter(
            alumno=alumno,
            atendida=False
        ).select_related('parcial__grupo_docente_materia__materia').order_by('-fecha')
        
        alertas_data = []
        for alerta in alertas:
            alertas_data.append({
                'id': alerta.id,
                'motivo': alerta.motivo,
                'nivel_riesgo': alerta.nivel_riesgo,
                'fecha': alerta.fecha.strftime('%d/%m/%Y'),
                'materia': alerta.parcial.grupo_docente_materia.materia.nombre if alerta.parcial else 'General',
                'parcial': alerta.parcial.nombre if alerta.parcial else None
            })
        
        return JsonResponse({
            'success': True,
            'alumno': {
                'id': alumno.id,
                'nombre': alumno.nombre,
                'matricula': alumno.matricula,
                'grupo': alumno.grupo.clave
            },
            'estadisticas': {
                'total_actividades': total_actividades,
                'actividades_completadas': actividades_completadas,
                'actividades_pendientes': actividades_pendientes,
                'porcentaje_completado': porcentaje_completado,
                'promedio_calificaciones': promedio_calificaciones,
                'mejor_calificacion': max([a['calificacion'] for a in actividades_detalle if a['calificacion']]) if actividades_completadas > 0 else None,
                'peor_calificacion': min([a['calificacion'] for a in actividades_detalle if a['calificacion']]) if actividades_completadas > 0 else None
            },
            'actividades': actividades_detalle,
            'materias': materias_resumen,
            'alertas': alertas_data,
            'total_alertas': len(alertas_data),
            'alertas_alto': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
            'alertas_medio': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
            'alertas_bajo': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo')
        })
        
    except Alumno.DoesNotExist:
        return JsonResponse({"error": "Alumno no encontrado"}, status=404)
    except Exception as e:
        print(f"Error en estadisticas_alumno_individual: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    

#Aqui terminan ---------------------------


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
                'grupo_id': grupo.id,
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
        usuario = form.save()  # ← el form ya hashea solo, sin cambios extra

        rol_docente, _ = Rol.objects.get_or_create(nombre="Docente")
        UsuarioRol.objects.create(usuario=usuario, rol=rol_docente)

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
            # ── Obtener citas de esta alerta ──────────────────
            citas = Cita.objects.filter(
                alerta=alerta
            ).order_by('-fecha_creacion')

            citas_data = []
            for cita in citas:
                citas_data.append({
                    'id':          cita.id,
                    'fecha':       cita.fecha.strftime('%d/%m/%Y'),
                    'hora':        cita.hora.strftime('%H:%M'),
                    'comentario':  cita.comentario,
                    'estado':      cita.estado,
                    'rol_creador': cita.rol_creador,
                    'creado_por':  cita.creado_por.nombre,
                })

            alertas_data.append({
                'id':               alerta.id,
                'alumno_nombre':    alerta.alumno.nombre,
                'alumno_matricula': alerta.alumno.matricula,
                'alumno_id':        alerta.alumno.id,
                'motivo':           alerta.motivo,
                'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
                'nivel_riesgo':     alerta.nivel_riesgo,
                'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
                'derivada':         alerta.derivada,
                'derivada_a':       alerta.derivada_a or '',
                'citas':            citas_data,          # ← nuevo
                'tiene_citas':      len(citas_data) > 0, # ← nuevo
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
            if check_password(password, usuario.password):
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
                elif 'Psicologia' in lista_roles:
                    return redirect('/psicologia')
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
                    nombre    = fila.get("nombre", "").strip()
                    matricula = fila.get("matricula", "").strip()
                    correo    = fila.get("correo", "").strip() or None
                    telefono  = fila.get("telefono", "").strip() or None

                    if not nombre or not matricula:
                        continue

                    alumno, created = Alumno.objects.get_or_create(
                        matricula=matricula,
                        defaults={
                            "nombre":   nombre,
                            "grupo":    grupo,
                            "correo":   correo,
                            "telefono": telefono,
                        }
                    )

                    # Si el alumno ya existía, actualizar contacto si ahora viene en el CSV
                    if not created:
                        actualizar = False
                        if correo and not alumno.correo:
                            alumno.correo = correo
                            actualizar = True
                        if telefono and not alumno.telefono:
                            alumno.telefono = telefono
                            actualizar = True
                        if actualizar:
                            alumno.save()

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
    docente.telefono = request.POST.get('telefono', '').strip() or None
    if 'Director' not in roles:
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            docente = Usuario.objects.get(id=docente_id)
            docente.nombre = request.POST.get('nombre')
            docente.correo = request.POST.get('correo')

            nueva_password = request.POST.get('password')
            if nueva_password:
                docente.password = make_password(nueva_password)  # ← antes era texto plano

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
            f"Calificación baja en {parcial.nombre} "
            f"({gdm.materia.nombre}): "
            f"{calificacion:.1f} / {parcial.porcentaje} "
            f"(mínimo esperado: {umbral_calif:.1f})"
        )

    # 2. ASISTENCIA BAJA
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
                f"Asistencia baja en {parcial.nombre} "
                f"({gdm.materia.nombre}): "
                f"{porcentaje_asist:.1f}% "
                f"({total_asistio} asistencias, {total_retardo} retardos de {total_clases} clases)"
            )

    # 3. NIVEL DE RIESGO
    if   calif_baja and asist_baja: nivel_riesgo = 'Alto'
    elif calif_baja:                nivel_riesgo = 'Medio'
    else:                           nivel_riesgo = 'Bajo'

    # 4. BUSCAR ALERTA EXISTENTE
    alerta_existente = Alerta.objects.filter(
        alumno=alumno,
        parcial=parcial
    ).first()

    if not motivos:
        if alerta_existente:
            alerta_existente.delete()
            print(f"[ALERTA ELIMINADA] {alumno.nombre} — {parcial.nombre} ya no tiene problemas")
        return

    motivo_completo = ' | '.join(motivos)

    if alerta_existente:
        # Solo notificar si cambió el nivel o el motivo
        cambio_relevante = (
            alerta_existente.motivo       != motivo_completo or
            alerta_existente.nivel_riesgo != nivel_riesgo
        )
        alerta_existente.motivo       = motivo_completo
        alerta_existente.nivel_riesgo = nivel_riesgo
        alerta_existente.atendida     = False
        alerta_existente.save()
        print(f"[ALERTA ACTUALIZADA] {alumno.nombre} — {nivel_riesgo}: {motivo_completo}")

        if cambio_relevante:                                    # ← notificar solo si cambió algo
            notificar_tutor_alerta(alerta_existente, es_nueva=False)

    else:
        nueva_alerta = Alerta.objects.create(
            alumno=alumno,
            parcial=parcial,
            motivo=motivo_completo,
            nivel_riesgo=nivel_riesgo
        )
        print(f"[ALERTA CREADA] {alumno.nombre} — {nivel_riesgo}: {motivo_completo}")
        notificar_tutor_alerta(nueva_alerta, es_nueva=True)    # ← notificar siempre en alertas nuevas
 
 
def obtener_alertas_grupo(request):
    """Endpoint para obtener las alertas de un grupo"""
    if request.method == 'GET':
        gdm_id = request.GET.get('gdm_id')
        
        if not gdm_id:
            return JsonResponse({'error': 'ID de materia no proporcionado'}, status=400)
        
        try:
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            docente_id = request.session.get('usuario_id')
            if gdm.docente.id != docente_id:
                return JsonResponse({'error': 'No tienes permiso para ver estas alertas'}, status=403)
            
            alertas = Alerta.objects.filter(
                parcial__grupo_docente_materia=gdm,
                atendida=False
            ).select_related('alumno', 'parcial')
            
            alertas_data = []
            for alerta in alertas:
                alertas_data.append({
                    'alerta_id': alerta.id,
                    'alumno_nombre': alerta.alumno.nombre,
                    'alumno_matricula': alerta.alumno.matricula,
                    'motivo': alerta.motivo,
                    'nivel_riesgo': alerta.nivel_riesgo,
                    'fecha': alerta.fecha.strftime('%d/%m/%Y'),
                })
            
            return JsonResponse({
                'success': True,
                'alertas': alertas_data
            })
            
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

def director_alertas_view(request):
    """Todas las alertas del sistema (vista general del director)"""
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return JsonResponse({'error': 'Sin permiso'}, status=403)

    # Traer TODAS las alertas no atendidas
    alertas_qs = Alerta.objects.filter(
        atendida=False
    ).select_related('alumno', 'alumno__grupo', 'parcial').order_by('-fecha', '-id')

    alertas_data = _build_alertas_data(alertas_qs)

    stats = {
        'total':  len(alertas_data),
        'alto':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'medio':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'bajo':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
    }
    return JsonResponse({'alertas': alertas_data, 'stats': stats})


def director_alertas_direccion_view(request):
    """Solo las alertas derivadas a Dirección"""
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return JsonResponse({'error': 'Sin permiso'}, status=403)

    alertas_qs = Alerta.objects.filter(
        derivada_a='Direccion',
        atendida=False
    ).select_related('alumno', 'alumno__grupo', 'parcial').order_by('-fecha', '-id')

    alertas_data = _build_alertas_data(alertas_qs)

    stats = {
        'total':  len(alertas_data),
        'alto':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'medio':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'bajo':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
    }
    return JsonResponse({'alertas': alertas_data, 'stats': stats})


def _build_alertas_data(alertas_qs):
    """Helper compartido: convierte queryset de alertas a lista de dicts"""
    result = []
    for alerta in alertas_qs:
        seguimientos = SeguimientoAlerta.objects.filter(
            alerta=alerta
        ).select_related('usuario').order_by('fecha')

        result.append({
            'id':               alerta.id,
            'alumno_nombre':    alerta.alumno.nombre,
            'alumno_matricula': alerta.alumno.matricula,
            'alumno_id':        alerta.alumno.id,
            'grupo':            alerta.alumno.grupo.clave,
            'motivo':           alerta.motivo,
            'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo':     alerta.nivel_riesgo,
            'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
            'derivada':         alerta.derivada,
            'derivada_a':       alerta.derivada_a or '',
            'seguimientos': [{
                'usuario':    s.usuario.nombre,
                'accion':     s.accion,
                'comentario': s.comentario,
                'fecha':      s.fecha.strftime('%d/%m/%Y %H:%M'),
            } for s in seguimientos],
        })
    return result


@csrf_exempt
def cerrar_alerta_direccion(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        data       = json.loads(request.body)
        alerta_id  = data.get('alerta_id')
        comentario = data.get('comentario', '').strip()

        if not alerta_id:
            return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
        if not comentario:
            return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

        # El director puede cerrar cualquier alerta (no solo las de Dirección)
        alerta          = Alerta.objects.get(id=alerta_id)
        alerta.atendida = True
        alerta.save()

        usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
        SeguimientoAlerta.objects.create(
            alerta=alerta, usuario=usuario,
            accion='cerrada', comentario=comentario
        )
        return JsonResponse({'success': True})

    except Alerta.DoesNotExist:
        return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def derivar_alerta_direccion(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        data       = json.loads(request.body)
        alerta_id  = data.get('alerta_id')
        destino    = data.get('destino')
        comentario = data.get('comentario', '').strip()

        DESTINOS_VALIDOS = ('Tutor', 'Pedagogia', 'Psicologia')

        if not alerta_id or not destino:
            return JsonResponse({'error': 'Faltan datos'}, status=400)
        if destino not in DESTINOS_VALIDOS:
            return JsonResponse({'error': 'Destino inválido'}, status=400)
        if not comentario:
            return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

        alerta            = Alerta.objects.get(id=alerta_id)
        alerta.derivada   = True
        alerta.derivada_a = destino
        alerta.save()

        usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
        SeguimientoAlerta.objects.create(
            alerta=alerta, usuario=usuario,
            accion=f'derivada_{destino.lower()}', comentario=comentario
        )
        return JsonResponse({'success': True, 'derivada_a': destino})

    except Alerta.DoesNotExist:
        return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
def perfil_alumno_director(request, alumno_id):
    if not request.session.get('usuario_id'):
        return redirect('login')

    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')

    alumno = get_object_or_404(Alumno, id=alumno_id)

    # Todas las materias del grupo del alumno
    materias_grupo = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo
    ).select_related('materia', 'docente')

    # ── CALIFICACIONES por materia ──────────────────────────────
    materias_data = []
    promedio_general_suma = 0
    promedio_general_count = 0

    for gdm in materias_grupo:
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm
        ).order_by('numero_parcial')

        calificaciones_materia = []
        suma_materia = 0
        total_con_calif = 0

        for parcial in parciales:
            cal = CalificacionParcial.objects.filter(
                alumno=alumno,
                parcial=parcial
            ).first()

            valor = cal.calificacion if cal and cal.calificacion is not None else None

            calificaciones_materia.append({
                'parcial_numero': parcial.numero_parcial,
                'parcial_nombre': parcial.nombre,
                'parcial_porcentaje': parcial.porcentaje,
                'calificacion': valor,
            })

            if valor is not None:
                suma_materia += valor
                total_con_calif += 1

        # Promedio de la materia
        todas_completas = total_con_calif == len(calificaciones_materia) and total_con_calif > 0

        def redondear(valor):
            entero = int(valor)
            ultimo = entero % 10
            if ultimo == 0:
                return entero
            elif ultimo <= 4:
                return entero - ultimo
            else:
                return entero + (10 - ultimo)

        promedio_materia = None
        if todas_completas and suma_materia > 0:
            promedio_materia = redondear(suma_materia) / 10

        if promedio_materia is not None:
            promedio_general_suma += promedio_materia
            promedio_general_count += 1

        materias_data.append({
            'gdm_id': gdm.id,
            'materia_nombre': gdm.materia.nombre,
            'docente_nombre': gdm.docente.nombre,
            'parciales': list(parciales.values('numero_parcial', 'nombre', 'porcentaje')),
            'calificaciones': calificaciones_materia,
            'promedio': promedio_materia,
        })

    promedio_general = round(promedio_general_suma / promedio_general_count, 1) if promedio_general_count > 0 else None

    # ── ASISTENCIA todas las materias ──────────────────────────
    asistencias_qs = Asistencia.objects.filter(
        alumno=alumno
    ).select_related(
        'grupo_docente_materia__materia',
        'grupo_docente_materia__docente',
        'estado'
    ).order_by('-fecha')

    asistencia_data = []
    for a in asistencias_qs:
        asistencia_data.append({
            'fecha': a.fecha.strftime('%d/%m/%Y'),
            'materia': a.grupo_docente_materia.materia.nombre,
            'docente': a.grupo_docente_materia.docente.nombre,
            'estado': a.estado.nombre,
            'comentario': a.comentario or '',
            'gdm_id': a.grupo_docente_materia.id,
        })

    total_clases   = len(asistencia_data)
    total_asistio  = sum(1 for a in asistencia_data if a['estado'] == 'Asistió')
    total_retardos = sum(1 for a in asistencia_data if a['estado'] == 'Retardo')
    total_faltas   = sum(1 for a in asistencia_data if a['estado'] == 'No asistió')
    porcentaje_asistencia = int(((total_asistio + total_retardos * 0.5) / total_clases) * 100) if total_clases > 0 else 0

    # Asistencia por materia (para el desglose)
    asistencia_por_materia = {}
    for a in asistencia_data:
        gdm_id = a['gdm_id']
        if gdm_id not in asistencia_por_materia:
            asistencia_por_materia[gdm_id] = {
                'materia': a['materia'],
                'docente': a['docente'],
                'asistencias': 0, 'retardos': 0, 'faltas': 0, 'total': 0
            }
        asistencia_por_materia[gdm_id]['total'] += 1
        if a['estado'] == 'Asistió':
            asistencia_por_materia[gdm_id]['asistencias'] += 1
        elif a['estado'] == 'Retardo':
            asistencia_por_materia[gdm_id]['retardos'] += 1
        elif a['estado'] == 'No asistió':
            asistencia_por_materia[gdm_id]['faltas'] += 1

    for gdm_id, datos in asistencia_por_materia.items():
        t = datos['total']
        datos['porcentaje'] = int(((datos['asistencias'] + datos['retardos'] * 0.5) / t) * 100) if t > 0 else 0

    asistencia_por_materia_list = list(asistencia_por_materia.values())

    # ── ALERTAS todas las materias ─────────────────────────────
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=materias_grupo
    ).values_list('id', flat=True)

    alertas_qs = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids
    ).select_related('parcial__grupo_docente_materia__materia').order_by(
        models.Case(
            models.When(nivel_riesgo='Alto',  then=0),
            models.When(nivel_riesgo='Medio', then=1),
            models.When(nivel_riesgo='Bajo',  then=2),
            default=3,
            output_field=models.IntegerField(),
        ),
        '-fecha'
    )

    alertas_data = []
    for alerta in alertas_qs:
        materia_nombre = 'General'
        if alerta.parcial and alerta.parcial.grupo_docente_materia:
            materia_nombre = alerta.parcial.grupo_docente_materia.materia.nombre

        alertas_data.append({
            'id': alerta.id,
            'motivo': alerta.motivo,
            'motivos_lista': [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo': alerta.nivel_riesgo,
            'fecha': alerta.fecha.strftime('%d/%m/%Y'),
            'materia': materia_nombre,
            'parcial': alerta.parcial.nombre if alerta.parcial else None,
        })

    # Estado general del alumno
    estado_alumno = 'Estable'
    estado_clase  = 'status-good'
    if any(a['nivel_riesgo'] == 'Alto'  for a in alertas_data):
        estado_alumno = 'En Riesgo'
        estado_clase  = 'status-danger'
    elif any(a['nivel_riesgo'] == 'Medio' for a in alertas_data):
        estado_alumno = 'Requiere Atención'
        estado_clase  = 'status-warning'
    elif any(a['nivel_riesgo'] == 'Bajo'  for a in alertas_data):
        estado_alumno = 'Precaución'
        estado_clase  = 'status-info'

    # ── CUATRIMESTRE activo ────────────────────────────────────
    from django.utils import timezone
    hoy = timezone.now().date()
    cuatrimestre_valido = False
    if alumno.grupo.cuatrimestre:
        cuatrimestre_valido = (
            alumno.grupo.cuatrimestre.activo and
            alumno.grupo.cuatrimestre.fecha_inicio <= hoy <= alumno.grupo.cuatrimestre.fecha_fin
        )

    context = {
        'alumno': alumno,
        'materias_data': materias_data,
        'materias_data_json': json.dumps(materias_data, ensure_ascii=False, default=str),
        'promedio_general': promedio_general,
        'asistencia_data': asistencia_data,
        'asistencia_data_json': json.dumps(asistencia_data, ensure_ascii=False),
        'asistencia_por_materia': asistencia_por_materia_list,
        'asistencia_por_materia_json': json.dumps(asistencia_por_materia_list, ensure_ascii=False),
        'stats_generales': {
            'asistencias': total_asistio,
            'retardos': total_retardos,
            'faltas': total_faltas,
            'total_clases': total_clases,
            'porcentaje': porcentaje_asistencia,
        },
        'alertas': alertas_data,
        'total_alertas': len(alertas_data),
        'alertas_alto':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'alertas_medio': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'alertas_bajo':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
        'estado_alumno': estado_alumno,
        'estado_clase':  estado_clase,
        'cuatrimestre_valido': cuatrimestre_valido,
        'total_materias': len(materias_data),
    }

    return render(request, 'perfilAlumnoDirector.html', context)


@csrf_exempt
def api_login(request):
    """API para login desde la app Flutter (SOLO MATRÍCULA)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            # Ignoramos password completamente
            
            print(f"📱 Intento de login - Matrícula: {matricula}")
            
            if not matricula:
                return JsonResponse({'error': 'Matrícula requerida'}, status=400)
            
            # Buscar alumno por matrícula
            try:
                alumno = Alumno.objects.get(matricula=matricula)
                
                # Login exitoso - NO verificamos contraseña
                grupo_data = {
                    'id': alumno.grupo.id if alumno.grupo else None,
                    'clave': alumno.grupo.clave if alumno.grupo else 'Sin grupo'
                }
                
                response_data = {
                    'id': alumno.id,
                    'nombre': alumno.nombre,
                    'matricula': alumno.matricula,
                    'grupo': grupo_data,
                    'tipo': 'alumno'
                }
                
                print(f"✅ Login exitoso para: {alumno.nombre}")
                return JsonResponse(response_data)
                
            except Alumno.DoesNotExist:
                print(f"❌ Alumno no encontrado: {matricula}")
                return JsonResponse({
                    'error': 'Matrícula no registrada'
                }, status=404)
                
        except Exception as e:
            print(f"🔥 Error en login: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_registro_alumno(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            print("📥 Datos recibidos:", data)  # Debug
            
            # Validar datos requeridos
            if not data.get('nombre'):
                return JsonResponse({'error': 'El nombre es requerido'}, status=400)
            
            if not data.get('matricula'):
                return JsonResponse({'error': 'La matrícula es requerida'}, status=400)
            
            # Verificar si ya existe la matrícula
            if Alumno.objects.filter(matricula=data['matricula']).exists():
                return JsonResponse({'error': 'La matrícula ya está registrada'}, status=400)
            
            # Verificar que el grupo_id existe
            grupo_id = data.get('grupo_id')
            if not grupo_id:
                return JsonResponse({'error': 'El grupo es requerido'}, status=400)
            
            try:
                grupo = Grupo.objects.get(id=grupo_id)
            except Grupo.DoesNotExist:
                return JsonResponse({'error': 'El grupo no existe'}, status=400)
            
            # Crear el alumno
            alumno = Alumno.objects.create(
                nombre=data['nombre'],
                matricula=data['matricula'],
                grupo=grupo
            )
            
            print(f"✅ Alumno creado: {alumno.nombre} - {alumno.matricula}")
            
            return JsonResponse({
                'success': True,
                'id': alumno.id,
                'nombre': alumno.nombre,
                'matricula': alumno.matricula,
                'mensaje': 'Registro exitoso'
            }, status=201)
            
        except Exception as e:
            print(f"🔥 Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_obtener_grupos(request):
    """API para obtener lista de grupos disponibles para registro"""
    if request.method == 'GET':
        try:
            grupos = Grupo.objects.all().order_by('clave')
            grupos_data = [{
                'id': g.id,
                'clave': g.clave,
                'nombre': f"Grupo {g.clave}"
            } for g in grupos]
            
            return JsonResponse({
                'grupos': grupos_data
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_verificar_sesion(request):
    """API para verificar si un alumno tiene sesión activa"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            device_id = data.get('device_id')
            
            try:
                alumno = Alumno.objects.get(matricula=matricula)
                
                # Aquí puedes verificar si el device_id coincide con el último usado
                # Esto requeriría guardar el device_id en el modelo Alumno
                
                return JsonResponse({
                    'valido': True,
                    'alumno': {
                        'id': alumno.id,
                        'nombre': alumno.nombre,
                        'matricula': alumno.matricula,
                        'grupo_id': alumno.grupo.id if alumno.grupo else None
                    }
                })
                
            except Alumno.DoesNotExist:
                return JsonResponse({
                    'valido': False,
                    'error': 'Alumno no encontrado'
                }, status=404)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_validar_qr_alumno(request):
    """API para validar QR escaneado por el alumno y registrar asistencia"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            token = data.get('token')
            
            print(f"📱 Validando QR - Matrícula: {matricula}, Token: {token}")
            
            # Validar token (ej: "A001_123456789")
            token_parts = token.split('_')
            if len(token_parts) != 2:
                return JsonResponse({'error': 'QR inválido'}, status=400)
            
            token_matricula = token_parts[0]
            timestamp = token_parts[1]
            
            if token_matricula != matricula:
                return JsonResponse({'error': 'QR no pertenece al alumno'}, status=400)
            
            # Verificar expiración (10 minutos máximo)
            from django.utils import timezone
            import datetime
            
            timestamp_int = int(timestamp) / 1000
            tiempo_creacion = datetime.datetime.fromtimestamp(timestamp_int)
            tiempo_creacion = timezone.make_aware(tiempo_creacion)
            
            ahora = timezone.now()
            diferencia = (ahora - tiempo_creacion).total_seconds() / 60
            
            print(f"⏱️ Diferencia: {diferencia} minutos")
            
            if diferencia > 10:
                return JsonResponse({'error': 'QR expirado'}, status=400)
            
            # Buscar alumno
            try:
                alumno = Alumno.objects.get(matricula=matricula)
            except Alumno.DoesNotExist:
                return JsonResponse({'error': 'Alumno no encontrado'}, status=404)
            
            # Registrar asistencia
            fecha_hoy = ahora.date()
            
            # Buscar GDM (Grupo-Docente-Materia) para el grupo del alumno
            # NOTA: Debes definir cómo identificar la materia/clase actual
            gdm = GrupoDocenteMateria.objects.filter(
                grupo=alumno.grupo
            ).first()
            
            if not gdm:
                return JsonResponse({'error': 'No hay clase programada'}, status=400)
            
            # Verificar si ya registró
            if Asistencia.objects.filter(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_hoy
            ).exists():
                return JsonResponse({'error': 'Ya registraste asistencia hoy'}, status=400)
            
            # Crear asistencia
            estado_asistio, _ = EstadoAsistencia.objects.get_or_create(nombre='Asistió')
            
            asistencia = Asistencia.objects.create(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_hoy,
                estado=estado_asistio,
                comentario=f'Registrado vía QR a las {ahora.strftime("%H:%M")}'
            )
            
            return JsonResponse({
                'success': True,
                'valido': True,
                'mensaje': 'Asistencia registrada correctamente'
            })
            
        except Exception as e:
            print(f"🔥 Error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_asistencias_por_grupo(request):
    """API para obtener asistencias de un grupo en una fecha específica"""
    if request.method == 'GET':
        try:
            grupo_id = request.GET.get('grupo_id')
            fecha = request.GET.get('fecha')
            
            if not grupo_id or not fecha:
                return JsonResponse({'error': 'Faltan parámetros'}, status=400)
            
            # Buscar GDM para el grupo
            gdms = GrupoDocenteMateria.objects.filter(grupo_id=grupo_id)
            
            asistencias = Asistencia.objects.filter(
                grupo_docente_materia__in=gdms,
                fecha=fecha
            ).values('alumno_id', 'estado__nombre')
            
            return JsonResponse({
                'success': True,
                'asistencias': list(asistencias)
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_actividades_alumno(request):
    """API para obtener actividades pendientes de un alumno"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            
            print(f"📱 Obteniendo actividades para matrícula: {matricula}")
            
            # Buscar alumno
            try:
                alumno = Alumno.objects.get(matricula=matricula)
            except Alumno.DoesNotExist:
                return JsonResponse({'error': 'Alumno no encontrado'}, status=404)
            
            # Obtener el grupo del alumno
            grupo = alumno.grupo
            if not grupo:
                return JsonResponse({'actividades': []})
            
            # Obtener todas las materias que se imparten en el grupo del alumno
            materias_grupo = GrupoDocenteMateria.objects.filter(grupo=grupo)
            
            actividades_pendientes = []
            
            for gdm in materias_grupo:
                # Obtener parciales activos
                parciales = Parcial.objects.filter(
                    grupo_docente_materia=gdm,
                    cerrado=False  # Solo parciales abiertos
                )
                
                for parcial in parciales:
                    # Obtener actividades del parcial
                    actividades = Actividad.objects.filter(
                        parcial=parcial,
                        fecha_entrega__gte=timezone.now().date()  # No vencidas
                    )
                    
                    for actividad in actividades:
                        # Verificar si ya entregó
                        entrega = Entrega.objects.filter(
                            actividad=actividad,
                            alumno=alumno
                        ).first()
                        
                        if not entrega or not entrega.entregado:
                            # Actividad pendiente
                            actividades_pendientes.append({
                                'id': actividad.id,
                                'titulo': actividad.titulo,
                                'descripcion': actividad.descripcion,
                                'materia': gdm.materia.nombre,
                                'grupo': grupo.clave,
                                'fecha_entrega': actividad.fecha_entrega.strftime('%Y-%m-%d'),
                                'fecha_entrega_formateada': actividad.fecha_entrega.strftime('%d/%m/%Y'),
                                'dias_restantes': (actividad.fecha_entrega - timezone.now().date()).days,
                                'parcial': parcial.nombre,
                                'entregada': False
                            })
            
            # Ordenar por fecha de entrega (más próximas primero)
            actividades_pendientes.sort(key=lambda x: x['fecha_entrega'])
            
            print(f"✅ {len(actividades_pendientes)} actividades encontradas")
            
            return JsonResponse({
                'success': True,
                'actividades': actividades_pendientes,
                'total': len(actividades_pendientes)
            })
            
        except Exception as e:
            print(f"🔥 Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def ver_asistencias(request):
    """Vista para ver las asistencias registradas por QR"""
    # Verificar autenticación
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    usuario_id = request.session.get('usuario_id')
    
    try:
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener los grupos del docente
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo', 'materia').values('grupo').distinct()
        
        grupo_ids = [g['grupo'] for g in grupos_docente]
        grupos = Grupo.objects.filter(id__in=grupo_ids)
        
        # Obtener asistencias del día actual (filtradas por grupos del docente)
        hoy = timezone.now().date()
        asistencias_hoy = Asistencia.objects.filter(
            grupo_docente_materia__docente=usuario,
            fecha=hoy
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        ).order_by('-fecha', 'alumno__nombre')
        
        # Calcular totales
        total_asistencias_hoy = asistencias_hoy.count()
        asistencias_por_grupo = {}
        
        for asistencia in asistencias_hoy:
            grupo_clave = asistencia.grupo_docente_materia.grupo.clave
            if grupo_clave not in asistencias_por_grupo:
                asistencias_por_grupo[grupo_clave] = 0
            asistencias_por_grupo[grupo_clave] += 1
        
        # Obtener últimos 10 registros para mostrar en tabla
        ultimas_asistencias = Asistencia.objects.filter(
            grupo_docente_materia__docente=usuario
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        ).order_by('-fecha', '-id')[:20]
        
        context = {
            'grupos': grupos,
            'asistencias_hoy': asistencias_hoy,
            'ultimas_asistencias': ultimas_asistencias,
            'total_asistencias_hoy': total_asistencias_hoy,
            'asistencias_por_grupo': asistencias_por_grupo,
            'hoy': hoy,
            'docente_nombre': usuario.nombre,
        }
        
        return render(request, "ver_asistencias.html", context)
        
    except Usuario.DoesNotExist:
        return redirect('login')
    except Exception as e:
        print(f"Error en ver_asistencias: {e}")
        return redirect('dashboard')

@require_GET
def api_filtrar_asistencias(request):
    """API para filtrar asistencias por grupo y fecha"""
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    try:
        usuario_id = request.session.get('usuario_id')
        grupo_id = request.GET.get('grupo_id')
        fecha = request.GET.get('fecha')
        
        asistencias = Asistencia.objects.filter(
            grupo_docente_materia__docente_id=usuario_id
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        )
        
        if grupo_id and grupo_id != 'todos':
            asistencias = asistencias.filter(
                grupo_docente_materia__grupo_id=grupo_id
            )
        
        if fecha:
            asistencias = asistencias.filter(fecha=fecha)
        
        asistencias = asistencias.order_by('-fecha', 'alumno__nombre')[:50]
        
        data = []
        for a in asistencias:
            data.append({
                'id': a.id,
                'alumno': a.alumno.nombre,
                'matricula': a.alumno.matricula,
                'grupo': a.grupo_docente_materia.grupo.clave,
                'materia': a.grupo_docente_materia.materia.nombre,
                'fecha': a.fecha.strftime('%d/%m/%Y'),
                'hora': a.comentario.split('a las ')[-1] if 'a las' in a.comentario else '-',
                'estado': a.estado.nombre
            })
        
        return JsonResponse({'asistencias': data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# AQUI SE TERMINAN LAS VISTAS RELACIONADAS CON QR Y SE REGRESA A LAS VISTAS PRINCIPALES #


def actividades(request):
    # Verificar autenticación
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    usuario_id = request.session.get('usuario_id')
    
    if request.method == "POST":
        titulo = request.POST.get("titulo")
        descripcion = request.POST.get("descripcion")
        grupo_docente_materia_id = request.POST.get("grupo_docente_materia")
        fecha_entrega = request.POST.get("fecha_entrega")

        try:
            # Primero verificar que la relación existe
            grupo_docente_materia = GrupoDocenteMateria.objects.get(
                id=grupo_docente_materia_id
            )
            
            # VERIFICACIÓN DE SEGURIDAD: Asegurar que el docente tiene acceso a esta materia
            if grupo_docente_materia.docente_id != usuario_id:
                return JsonResponse({
                    "error": "No tienes permiso para crear actividades en esta materia"
                }, status=403)

            # Buscar el parcial MÁS RECIENTE para esta materia (sin importar si está cerrado)
            parcial = Parcial.objects.filter(
                grupo_docente_materia=grupo_docente_materia
            ).order_by('-fecha_inicio').first()

            if parcial:
                actividad = Actividad.objects.create(
                    titulo=titulo,
                    descripcion=descripcion,
                    parcial=parcial,
                    fecha_entrega=fecha_entrega
                )

                return JsonResponse({
                    "success": True,
                    "id": actividad.id,
                    "titulo": actividad.titulo,
                    "descripcion": actividad.descripcion,
                    "grupo": actividad.parcial.grupo_docente_materia.grupo.clave,
                    "fecha": actividad.fecha_entrega,
                    "cerrado": actividad.parcial.cerrado
                })

            return JsonResponse({"error": "No hay parciales para esta materia"}, status=400)
            
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({"error": "La materia seleccionada no existe"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    # GET: Mostrar solo grupos del docente
    try:
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener TODAS las materias del docente
        materias_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo', 'materia').order_by('grupo__clave', 'materia__nombre')
        
        # Estructurar datos para el template
        grupos_con_materias = []
        grupos_dict = {}
        
        for gdm in materias_docente:
            if gdm.grupo.id not in grupos_dict:
                grupos_dict[gdm.grupo.id] = {
                    'id': gdm.grupo.id,
                    'clave': gdm.grupo.clave,
                    'materias': []
                }
            
            # Buscar el parcial más reciente para esta materia (sin importar fechas)
            parcial_reciente = Parcial.objects.filter(
                grupo_docente_materia=gdm
            ).order_by('-fecha_inicio').first()
            
            # Determinar si tiene parcial y obtener info
            tiene_parcial = parcial_reciente is not None
            
            # Preparar información del parcial
            parcial_info = None
            if parcial_reciente:
                parcial_info = {
                    'id': parcial_reciente.id,
                    'nombre': parcial_reciente.nombre,
                    'porcentaje': parcial_reciente.porcentaje,
                    'cerrado': parcial_reciente.cerrado
                }
            
            grupos_dict[gdm.grupo.id]['materias'].append({
                'relacion_id': gdm.id,
                'nombre': gdm.materia.nombre,
                'tiene_parcial': tiene_parcial,
                'parcial_info': parcial_info
            })
        
        grupos_con_materias = list(grupos_dict.values())
        
        # Obtener actividades del docente con sus entregas
        actividades = Actividad.objects.filter(
            parcial__grupo_docente_materia__docente=usuario
        ).select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'
        ).order_by('-fecha_entrega')
        
        # Calcular entregas para cada actividad
        for actividad in actividades:
            total_alumnos = Alumno.objects.filter(
                grupo=actividad.parcial.grupo_docente_materia.grupo
            ).count()
            
            entregadas = Entrega.objects.filter(
                actividad=actividad,
                entregado=True
            ).count()
            
            actividad.total_alumnos = total_alumnos
            actividad.entregadas = entregadas
            actividad.porcentaje = int((entregadas / total_alumnos * 100)) if total_alumnos > 0 else 0
        
        context = {
            'grupos_con_materias': grupos_con_materias,
            'actividades': actividades,
            'hoy': timezone.now().date().strftime('%Y-%m-%d')
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "actividades.html", context)

def detalleActividad(request, id):
    try:
        # Verificar autenticación con sesión manual
        if not request.session.get('usuario_id'):
            return JsonResponse({"error": "No autorizado"}, status=401)
        
        actividad = Actividad.objects.select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'
        ).get(id=id)
        
        # Verificar que la actividad pertenezca al docente de la sesión
        if actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)

        grupo = actividad.parcial.grupo_docente_materia.grupo
        materia = actividad.parcial.grupo_docente_materia.materia
        parcial = actividad.parcial
        
        alumnos = grupo.alumno_set.all().order_by('nombre')

        lista_alumnos = []
        entregadas = 0

        for alumno in alumnos:
            entrega, created = Entrega.objects.get_or_create(
                actividad=actividad,
                alumno=alumno,
                defaults={'entregado': False}
            )

            if entrega.entregado:
                entregadas += 1

            lista_alumnos.append({
                "id": entrega.id,
                "alumno_id": alumno.id,
                "nombre": alumno.nombre,
                "matricula": alumno.matricula,
                "entregado": entrega.entregado
            })

        data = {
            "titulo": actividad.titulo,
            "descripcion": actividad.descripcion,
            "grupo": grupo.clave,
            "materia": materia.nombre,
            "parcial": parcial.nombre,
            "fecha_entrega": actividad.fecha_entrega.strftime('%d/%m/%Y'),
            "entregadas": entregadas,
            "total": alumnos.count(),
            "alumnos": lista_alumnos
        }

        return JsonResponse(data)
    
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    
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

def estadisticas_actividades(request):
    """API para obtener estadísticas de actividades usando sesión manual"""
    
    # Verificar autenticación con sesión manual
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    usuario_id = request.session.get('usuario_id')
    
    # Obtener el usuario
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
    # Verificar si el usuario tiene rol de docente
    tiene_rol_docente = UsuarioRol.objects.filter(usuario=usuario, rol__nombre='Docente').exists()
    if not tiene_rol_docente:
        return JsonResponse({'error': 'No tienes permisos de docente'}, status=403)
    
    hoy = timezone.now().date()
    
    # Obtener actividades del docente usando el ID de sesión
    actividades = Actividad.objects.filter(
        parcial__grupo_docente_materia__docente_id=usuario_id
    ).select_related(
        'parcial', 
        'parcial__grupo_docente_materia', 
        'parcial__grupo_docente_materia__materia', 
        'parcial__grupo_docente_materia__grupo'
    ).distinct()
    
    total_actividades = actividades.count()
    
    if total_actividades == 0:
        return JsonResponse({
            'total_actividades': 0,
            'total_entregas': 0,
            'promedio_entregas': 0,
            'actividades_activas': 0,
            'actividades_vencidas': 0,
            'actividades_cerradas': 0,
            'actividades_detalle': [],
            'charts': {
                'entregas_labels': [],
                'entregas_data': [],
                'estado_activas': 0,
                'estado_vencidas': 0,
                'estado_cerradas': 0,
                'materias_labels': [],
                'materias_data': [],
                'tiempo_data': {'atiempo': 0, 'tarde': 0, 'no_entregadas': 0}
            }
        })
    
    # Procesar estadísticas
    actividades_detalle = []
    entregas_labels = []
    entregas_data = []
    
    actividades_activas = 0
    actividades_vencidas = 0
    actividades_cerradas = 0
    
    total_entregas = 0
    total_alumnos_sum = 0
    
    materias_stats = {}
    entregas_completadas_total = 0
    entregas_pendientes_total = 0
    
    for act in actividades:
        # Obtener total de alumnos en el grupo
        grupo = act.parcial.grupo_docente_materia.grupo
        total_alumnos = Alumno.objects.filter(grupo=grupo).count()
        
        # Contar entregas completadas
        entregas_count = Entrega.objects.filter(actividad=act, entregado=True).count()
        
        # Calcular porcentaje
        porcentaje = (entregas_count / total_alumnos * 100) if total_alumnos > 0 else 0
        
        # Determinar estado de la actividad
        if act.parcial.cerrado:
            estado = 'cerrada'
            actividades_cerradas += 1
        elif act.fecha_entrega < hoy:
            estado = 'vencida'
            actividades_vencidas += 1
        else:
            estado = 'activa'
            actividades_activas += 1
        
        entregas_completadas_total += entregas_count
        entregas_pendientes_total += (total_alumnos - entregas_count)
        
        actividades_detalle.append({
            'id': act.id,
            'titulo': act.titulo,
            'descripcion': act.descripcion,
            'materia': act.parcial.grupo_docente_materia.materia.nombre,
            'grupo': grupo.clave,
            'entregadas': entregas_count,
            'total_alumnos': total_alumnos,
            'porcentaje': round(porcentaje, 1),
            'estado': estado,
            'fecha_entrega': act.fecha_entrega.strftime('%d/%m/%Y')
        })
        
        titulo_corto = act.titulo[:25] + ('...' if len(act.titulo) > 25 else '')
        entregas_labels.append(titulo_corto)
        entregas_data.append(round(porcentaje, 1))
        
        total_entregas += entregas_count
        total_alumnos_sum += total_alumnos
        
        materia_nombre = act.parcial.grupo_docente_materia.materia.nombre
        if materia_nombre not in materias_stats:
            materias_stats[materia_nombre] = {'total_porcentaje': 0, 'count': 0}
        materias_stats[materia_nombre]['total_porcentaje'] += porcentaje
        materias_stats[materia_nombre]['count'] += 1
    
    promedio_entregas = (total_entregas / total_alumnos_sum * 100) if total_alumnos_sum > 0 else 0
    
    materias_labels = list(materias_stats.keys())
    materias_data = [round(stat['total_porcentaje'] / stat['count'], 1) for stat in materias_stats.values()]
    
    if len(materias_labels) > 10:
        combined = list(zip(materias_labels, materias_data))
        combined.sort(key=lambda x: x[1], reverse=True)
        materias_labels = [x[0] for x in combined[:10]]
        materias_data = [x[1] for x in combined[:10]]
    
    if len(entregas_labels) > 15:
        combined = list(zip(entregas_labels, entregas_data))
        combined.sort(key=lambda x: x[1], reverse=True)
        entregas_labels = [x[0] for x in combined[:15]]
        entregas_data = [x[1] for x in combined[:15]]
    
    return JsonResponse({
        'total_actividades': total_actividades,
        'total_entregas': total_entregas,
        'promedio_entregas': round(promedio_entregas, 1),
        'actividades_activas': actividades_activas,
        'actividades_vencidas': actividades_vencidas,
        'actividades_cerradas': actividades_cerradas,
        'actividades_detalle': actividades_detalle,
        'charts': {
            'entregas_labels': entregas_labels,
            'entregas_data': entregas_data,
            'estado_activas': actividades_activas,
            'estado_vencidas': actividades_vencidas,
            'estado_cerradas': actividades_cerradas,
            'materias_labels': materias_labels,
            'materias_data': materias_data,
            'tiempo_data': {
                'atiempo': entregas_completadas_total,
                'tarde': 0,
                'no_entregadas': entregas_pendientes_total
            }
        }
    })

def generar_qr(request):
    """Vista principal para generar códigos QR"""
    print("🔵 Entrando a función generar_qr")
    
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return JsonResponse({'error': 'Sin permiso'}, status=403)

    alertas_qs = Alerta.objects.filter(
        derivada_a='Direccion',
        atendida=False
    ).select_related('alumno', 'alumno__grupo', 'parcial').order_by('-fecha', '-id')

    alertas_data = _build_alertas_data(alertas_qs)

    stats = {
        'total':  len(alertas_data),
        'alto':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'medio':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'bajo':   sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
    }
    return JsonResponse({'alertas': alertas_data, 'stats': stats})


def _build_alertas_data(alertas_qs):
    """Helper compartido: convierte queryset de alertas a lista de dicts"""
    result = []
    for alerta in alertas_qs:
        seguimientos = SeguimientoAlerta.objects.filter(
            alerta=alerta
        ).select_related('usuario').order_by('fecha')

        result.append({
            'id':               alerta.id,
            'alumno_nombre':    alerta.alumno.nombre,
            'alumno_matricula': alerta.alumno.matricula,
            'alumno_id':        alerta.alumno.id,
            'grupo':            alerta.alumno.grupo.clave,
            'motivo':           alerta.motivo,
            'motivos_lista':    [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo':     alerta.nivel_riesgo,
            'fecha':            alerta.fecha.strftime('%d/%m/%Y'),
            'derivada':         alerta.derivada,
            'derivada_a':       alerta.derivada_a or '',
            'seguimientos': [{
                'usuario':    s.usuario.nombre,
                'accion':     s.accion,
                'comentario': s.comentario,
                'fecha':      s.fecha.strftime('%d/%m/%Y %H:%M'),
            } for s in seguimientos],
        })
    return result


@csrf_exempt
def cerrar_alerta_direccion(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        data       = json.loads(request.body)
        alerta_id  = data.get('alerta_id')
        comentario = data.get('comentario', '').strip()

        if not alerta_id:
            return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
        if not comentario:
            return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

        # El director puede cerrar cualquier alerta (no solo las de Dirección)
        alerta          = Alerta.objects.get(id=alerta_id)
        alerta.atendida = True
        alerta.save()

        usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
        SeguimientoAlerta.objects.create(
            alerta=alerta, usuario=usuario,
            accion='cerrada', comentario=comentario
        )
        return JsonResponse({'success': True})

    except Alerta.DoesNotExist:
        return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def derivar_alerta_direccion(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    try:
        data       = json.loads(request.body)
        alerta_id  = data.get('alerta_id')
        destino    = data.get('destino')
        comentario = data.get('comentario', '').strip()

        DESTINOS_VALIDOS = ('Tutor', 'Pedagogia', 'Psicologia')

        if not alerta_id or not destino:
            return JsonResponse({'error': 'Faltan datos'}, status=400)
        if destino not in DESTINOS_VALIDOS:
            return JsonResponse({'error': 'Destino inválido'}, status=400)
        if not comentario:
            return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

        alerta            = Alerta.objects.get(id=alerta_id)
        alerta.derivada   = True
        alerta.derivada_a = destino
        alerta.save()

        usuario = Usuario.objects.get(id=request.session.get('usuario_id'))
        SeguimientoAlerta.objects.create(
            alerta=alerta, usuario=usuario,
            accion=f'derivada_{destino.lower()}', comentario=comentario
        )
        return JsonResponse({'success': True, 'derivada_a': destino})

    except Alerta.DoesNotExist:
        return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
def perfil_alumno_director(request, alumno_id):
    if not request.session.get('usuario_id'):
        return redirect('login')

    roles = request.session.get('usuario_roles', [])
    if 'Docente' not in roles and 'Director' not in roles:
        return redirect('dashboard')

    alumno = get_object_or_404(Alumno, id=alumno_id)

    # Todas las materias del grupo del alumno
    materias_grupo = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo
    ).select_related('materia', 'docente')

    # ── CALIFICACIONES por materia ──────────────────────────────
    materias_data = []
    promedio_general_suma = 0
    promedio_general_count = 0

    for gdm in materias_grupo:
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm
        ).order_by('numero_parcial')

        calificaciones_materia = []
        suma_materia = 0
        total_con_calif = 0

        for parcial in parciales:
            cal = CalificacionParcial.objects.filter(
                alumno=alumno,
                parcial=parcial
            ).first()

            valor = cal.calificacion if cal and cal.calificacion is not None else None

            calificaciones_materia.append({
                'parcial_numero': parcial.numero_parcial,
                'parcial_nombre': parcial.nombre,
                'parcial_porcentaje': parcial.porcentaje,
                'calificacion': valor,
            })

            if valor is not None:
                suma_materia += valor
                total_con_calif += 1

        # Promedio de la materia
        todas_completas = total_con_calif == len(calificaciones_materia) and total_con_calif > 0

        def redondear(valor):
            entero = int(valor)
            ultimo = entero % 10
            if ultimo == 0:
                return entero
            elif ultimo <= 4:
                return entero - ultimo
            else:
                return entero + (10 - ultimo)

        promedio_materia = None
        if todas_completas and suma_materia > 0:
            promedio_materia = redondear(suma_materia) / 10

        if promedio_materia is not None:
            promedio_general_suma += promedio_materia
            promedio_general_count += 1

        materias_data.append({
            'gdm_id': gdm.id,
            'materia_nombre': gdm.materia.nombre,
            'docente_nombre': gdm.docente.nombre,
            'parciales': list(parciales.values('numero_parcial', 'nombre', 'porcentaje')),
            'calificaciones': calificaciones_materia,
            'promedio': promedio_materia,
        })

    promedio_general = round(promedio_general_suma / promedio_general_count, 1) if promedio_general_count > 0 else None

    # ── ASISTENCIA todas las materias ──────────────────────────
    asistencias_qs = Asistencia.objects.filter(
        alumno=alumno
    ).select_related(
        'grupo_docente_materia__materia',
        'grupo_docente_materia__docente',
        'estado'
    ).order_by('-fecha')

    asistencia_data = []
    for a in asistencias_qs:
        asistencia_data.append({
            'fecha': a.fecha.strftime('%d/%m/%Y'),
            'materia': a.grupo_docente_materia.materia.nombre,
            'docente': a.grupo_docente_materia.docente.nombre,
            'estado': a.estado.nombre,
            'comentario': a.comentario or '',
            'gdm_id': a.grupo_docente_materia.id,
        })

    total_clases   = len(asistencia_data)
    total_asistio  = sum(1 for a in asistencia_data if a['estado'] == 'Asistió')
    total_retardos = sum(1 for a in asistencia_data if a['estado'] == 'Retardo')
    total_faltas   = sum(1 for a in asistencia_data if a['estado'] == 'No asistió')
    porcentaje_asistencia = int(((total_asistio + total_retardos * 0.5) / total_clases) * 100) if total_clases > 0 else 0

    # Asistencia por materia (para el desglose)
    asistencia_por_materia = {}
    for a in asistencia_data:
        gdm_id = a['gdm_id']
        if gdm_id not in asistencia_por_materia:
            asistencia_por_materia[gdm_id] = {
                'materia': a['materia'],
                'docente': a['docente'],
                'asistencias': 0, 'retardos': 0, 'faltas': 0, 'total': 0
            }
        asistencia_por_materia[gdm_id]['total'] += 1
        if a['estado'] == 'Asistió':
            asistencia_por_materia[gdm_id]['asistencias'] += 1
        elif a['estado'] == 'Retardo':
            asistencia_por_materia[gdm_id]['retardos'] += 1
        elif a['estado'] == 'No asistió':
            asistencia_por_materia[gdm_id]['faltas'] += 1

    for gdm_id, datos in asistencia_por_materia.items():
        t = datos['total']
        datos['porcentaje'] = int(((datos['asistencias'] + datos['retardos'] * 0.5) / t) * 100) if t > 0 else 0

    asistencia_por_materia_list = list(asistencia_por_materia.values())

    # ── ALERTAS todas las materias ─────────────────────────────
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=materias_grupo
    ).values_list('id', flat=True)

    alertas_qs = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids
    ).select_related('parcial__grupo_docente_materia__materia').order_by(
        models.Case(
            models.When(nivel_riesgo='Alto',  then=0),
            models.When(nivel_riesgo='Medio', then=1),
            models.When(nivel_riesgo='Bajo',  then=2),
            default=3,
            output_field=models.IntegerField(),
        ),
        '-fecha'
    )

    alertas_data = []
    for alerta in alertas_qs:
        materia_nombre = 'General'
        if alerta.parcial and alerta.parcial.grupo_docente_materia:
            materia_nombre = alerta.parcial.grupo_docente_materia.materia.nombre

        alertas_data.append({
            'id': alerta.id,
            'motivo': alerta.motivo,
            'motivos_lista': [m.strip() for m in alerta.motivo.split(' | ') if m.strip()],
            'nivel_riesgo': alerta.nivel_riesgo,
            'fecha': alerta.fecha.strftime('%d/%m/%Y'),
            'materia': materia_nombre,
            'parcial': alerta.parcial.nombre if alerta.parcial else None,
        })

    # Estado general del alumno
    estado_alumno = 'Estable'
    estado_clase  = 'status-good'
    if any(a['nivel_riesgo'] == 'Alto'  for a in alertas_data):
        estado_alumno = 'En Riesgo'
        estado_clase  = 'status-danger'
    elif any(a['nivel_riesgo'] == 'Medio' for a in alertas_data):
        estado_alumno = 'Requiere Atención'
        estado_clase  = 'status-warning'
    elif any(a['nivel_riesgo'] == 'Bajo'  for a in alertas_data):
        estado_alumno = 'Precaución'
        estado_clase  = 'status-info'

    # ── CUATRIMESTRE activo ────────────────────────────────────
    from django.utils import timezone
    hoy = timezone.now().date()
    cuatrimestre_valido = False
    if alumno.grupo.cuatrimestre:
        cuatrimestre_valido = (
            alumno.grupo.cuatrimestre.activo and
            alumno.grupo.cuatrimestre.fecha_inicio <= hoy <= alumno.grupo.cuatrimestre.fecha_fin
        )

    context = {
        'alumno': alumno,
        'materias_data': materias_data,
        'materias_data_json': json.dumps(materias_data, ensure_ascii=False, default=str),
        'promedio_general': promedio_general,
        'asistencia_data': asistencia_data,
        'asistencia_data_json': json.dumps(asistencia_data, ensure_ascii=False),
        'asistencia_por_materia': asistencia_por_materia_list,
        'asistencia_por_materia_json': json.dumps(asistencia_por_materia_list, ensure_ascii=False),
        'stats_generales': {
            'asistencias': total_asistio,
            'retardos': total_retardos,
            'faltas': total_faltas,
            'total_clases': total_clases,
            'porcentaje': porcentaje_asistencia,
        },
        'alertas': alertas_data,
        'total_alertas': len(alertas_data),
        'alertas_alto':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Alto'),
        'alertas_medio': sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Medio'),
        'alertas_bajo':  sum(1 for a in alertas_data if a['nivel_riesgo'] == 'Bajo'),
        'estado_alumno': estado_alumno,
        'estado_clase':  estado_clase,
        'cuatrimestre_valido': cuatrimestre_valido,
        'total_materias': len(materias_data),
    }

    return render(request, 'perfilAlumnoDirector.html', context)


def obtener_estadisticas_desempeno(request):
    if request.method == 'GET':
        gdm_id = request.GET.get('gdm_id')
        docente_id = request.session.get('usuario_id')

        if not gdm_id or not docente_id:
            return JsonResponse({'estadisticas': []})

        try:
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id, docente_id=docente_id)

            alumnos = Alumno.objects.filter(grupo=gdm.grupo)

            data = []

            for alumno in alumnos:
                asistencias = Asistencia.objects.filter(
                    alumno=alumno,
                    grupo_docente_materia=gdm
                )

                total = asistencias.count()

                if total > 0:
                    asistio = asistencias.filter(estado__nombre__iexact='Asistió').count()
                    retardos = asistencias.filter(estado__nombre__iexact='Retardo').count()

                    porcentaje = int(((asistio + retardos * 0.5) / total) * 100)

                    if porcentaje >= 80:
                        estado = "Bueno"
                    elif porcentaje >= 60:
                        estado = "Regular"
                    else:
                        estado = "Crítico"
                else:
                    estado = "Sin datos"

                data.append({
                    'id': alumno.id,
                    'nombre': alumno.nombre,
                    'matricula': alumno.matricula,
                    'estado': estado,
                })

            return JsonResponse({'estadisticas': data})

        except Exception as e:
            print(e)
            return JsonResponse({'estadisticas': []})
        

        
def obtener_datos_graficas_asistencia(request):
    """Endpoint para obtener datos de asistencias y faltas por mes para gráficas"""
    if request.method == 'GET':
        alumno_id = request.GET.get('alumno_id')
        gdm_id = request.GET.get('gdm_id')
        
        if not alumno_id or not gdm_id:
            return JsonResponse({'error': 'Faltan parámetros', 'success': False}, status=400)
        
        try:
            alumno = Alumno.objects.get(id=alumno_id)
            gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
            
            # Obtener el año de la primera asistencia
            primera_asistencia = Asistencia.objects.filter(
                alumno=alumno,
                grupo_docente_materia=gdm
            ).order_by('fecha').first()
            
            año = primera_asistencia.fecha.year if primera_asistencia else 2026
            
            # Meses a mostrar (Enero a Abril)
            meses = [
                {'numero': 1, 'nombre': 'Ene'},
                {'numero': 2, 'nombre': 'Feb'},
                {'numero': 3, 'nombre': 'Mar'},
                {'numero': 4, 'nombre': 'Abr'},
            ]
            
            # Encontrar el máximo valor para escalar las gráficas
            max_asistencias = 0
            datos_por_mes = []
            
            for mes in meses:
                asistencias_mes = Asistencia.objects.filter(
                    alumno=alumno,
                    grupo_docente_materia=gdm,
                    fecha__month=mes['numero'],
                    fecha__year=año
                )
                
                total_asistencias = asistencias_mes.filter(estado__nombre='Asistió').count()
                total_faltas = asistencias_mes.filter(estado__nombre='No asistió').count()
                
                max_asistencias = max(max_asistencias, total_asistencias, total_faltas)
                
                datos_por_mes.append({
                    'mes': mes['nombre'],
                    'asistencias': total_asistencias,
                    'faltas': total_faltas,
                })
            
            # Calcular la escala (máximo redondeado hacia arriba)
            escala = max(max_asistencias, 5)  # Mínimo 5 para que se vea bien
            
            return JsonResponse({
                'success': True,
                'alumno_nombre': alumno.nombre,
                'datos_por_mes': datos_por_mes,
                'escala': escala
            })
            
        except Alumno.DoesNotExist:
            return JsonResponse({'error': 'Alumno no encontrado', 'success': False}, status=404)
        except GrupoDocenteMateria.DoesNotExist:
            return JsonResponse({'error': 'Materia no encontrada', 'success': False}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e), 'success': False}, status=500)
    
    return JsonResponse({'error': 'Método no permitido', 'success': False}, status=405)   

# ========== VISTAS PARA QR (AGREGADAS DESPUÉS DE ACTIVIDADES) ==========

@require_GET
def api_materias_por_grupo(request, grupo_id):
    """API para obtener materias de un grupo para un docente específico"""
    print(f"🔵 api_materias_por_grupo - Grupo ID: {grupo_id}")
    
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    try:
        usuario_id = request.session.get('usuario_id')
        usuario = Usuario.objects.get(id=usuario_id)
        
        materias = GrupoDocenteMateria.objects.filter(
            grupo_id=grupo_id,
            docente=usuario
        ).select_related('materia')
        
        materias_data = [{
            'id': m.materia.id,
            'nombre': m.materia.nombre
        } for m in materias]
        
        print(f"🟢 Materias encontradas: {len(materias_data)}")
        return JsonResponse({'materias': materias_data})
        
    except Exception as e:
        print(f"🔴 Error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
def api_generar_qr(request):
    """API para generar un nuevo código QR"""
    print("🔵 api_generar_qr")
    
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    try:
        data = json.loads(request.body)
        usuario_id = request.session.get('usuario_id')
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Crear token único
        token = secrets.token_urlsafe(16)
        
        # Calcular expiración
        fecha_hora = datetime.strptime(
            f"{data['fecha']} {data['hora']}", 
            "%Y-%m-%d %H:%M"
        )
        fecha_expiracion = (fecha_hora + timedelta(minutes=data['duracion'])).timestamp()
        
        # Obtener nombres
        grupo = Grupo.objects.get(id=data['grupo'])
        materia = Materia.objects.get(id=data['materia'])
        
        # Guardar en cache
        qr_data = {
            'id': token[:8],
            'docente_id': usuario_id,
            'docente_nombre': usuario.nombre,
            'grupo_id': data['grupo'],
            'grupo_nombre': grupo.clave,
            'materia_id': data['materia'],
            'materia_nombre': materia.nombre,
            'token': token,
            'fecha': data['fecha'],
            'hora': data['hora'],
            'duracion': data['duracion'],
            'fecha_generacion': timezone.now().timestamp(),
            'fecha_expiracion': fecha_expiracion,
            'activo': True,
            'escaneos': 0
        }
        
        cache.set(f'qr_{token}', qr_data, timeout=3600)
        
        # Guardar en historial
        cache_key = f'qr_history_{usuario_id}_{timezone.now().date()}'
        historial = cache.get(cache_key, [])
        historial.insert(0, {
            'hora': data['hora'],
            'grupo': grupo.clave,
            'materia': materia.nombre,
            'duracion': data['duracion'],
            'token': token[:8],
            'activo': True
        })
        historial = historial[:10]
        cache.set(cache_key, historial, timeout=86400)
        
        print(f"🟢 QR generado: {token[:8]}")
        return JsonResponse({
            'success': True,
            'token': token,
            'grupo_nombre': grupo.clave,
            'materia_nombre': materia.nombre,
            'fecha': data['fecha'],
            'hora': data['hora'],
            'duracion': data['duracion']
        })
        
    except Exception as e:
        print(f"🔴 Error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

def generar_qr(request):
    """Vista principal para generar códigos QR"""
    print("🔵 Entrando a función generar_qr")
    
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    roles = request.session.get('usuario_roles', [])
    if 'Docente' not in roles and 'Director' not in roles:
        return redirect('dashboard')
    
    try:
        usuario_id = request.session.get('usuario_id')
        usuario = Usuario.objects.get(id=usuario_id)
        
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo').values('grupo').distinct()
        
        grupo_ids = [g['grupo'] for g in grupos_docente]
        grupos = Grupo.objects.filter(id__in=grupo_ids)
        
        cache_key = f'qr_history_{usuario_id}_{timezone.now().date()}'
        historial_qr = cache.get(cache_key, [])
        
        context = {
            'grupos': grupos,
            'historial_qr': historial_qr,
            'today': timezone.now().date(),
            'now': timezone.now(),
            'debug': True,
        }
        
        return render(request, 'generar_qr.html', context)
        
    except Exception as e:
        print(f"🔴 Error: {str(e)}")
        return redirect('dashboard')

@require_POST
def api_validar_qr(request):
    """API para validar QR escaneado por el alumno"""
    print("🔵 api_validar_qr")
    try:
        data = json.loads(request.body)
        token = data.get('token')
        matricula = data.get('matricula')
        device_id = data.get('device_id')
        
        print(f"📱 Validando QR - Token: {token}, Matrícula: {matricula}")
        
        # Validar datos requeridos
        if not all([token, matricula]):
            return JsonResponse({
                'valido': False,
                'error': 'Faltan datos requeridos'
            }, status=400)
        
        # Buscar QR en cache
        qr_data = cache.get(f'qr_{token}')
        
        if not qr_data:
            print(f"❌ QR no encontrado: {token}")
            return JsonResponse({
                'valido': False,
                'error': 'QR no válido o expirado'
            }, status=400)
        
        # Verificar expiración
        ahora = timezone.now().timestamp()
        if ahora > qr_data['fecha_expiracion']:
            cache.delete(f'qr_{token}')
            print(f"❌ QR expirado: {token}")
            return JsonResponse({
                'valido': False,
                'error': 'QR expirado'
            }, status=400)
        
        # Verificar alumno
        try:
            alumno = Alumno.objects.get(matricula=matricula)
            print(f"✅ Alumno encontrado: {alumno.nombre}")
        except Alumno.DoesNotExist:
            print(f"❌ Alumno no encontrado: {matricula}")
            return JsonResponse({
                'valido': False,
                'error': 'Alumno no encontrado'
            }, status=400)
        
        # Verificar que el alumno pertenezca al grupo
        if alumno.grupo_id != qr_data['grupo_id']:
            print(f"❌ Grupo incorrecto. Alumno: {alumno.grupo_id}, QR: {qr_data['grupo_id']}")
            return JsonResponse({
                'valido': False,
                'error': 'No perteneces a este grupo'
            }, status=400)
        
        # Obtener la relación grupo-docente-materia
        gdm = GrupoDocenteMateria.objects.filter(
            grupo_id=qr_data['grupo_id'],
            materia_id=qr_data['materia_id'],
            docente_id=qr_data['docente_id']
        ).first()
        
        if not gdm:
            print(f"❌ Configuración de clase inválida")
            return JsonResponse({
                'valido': False,
                'error': 'Configuración de clase inválida'
            }, status=400)
        
        # Verificar si ya registró asistencia hoy
        fecha_clase = datetime.strptime(qr_data['fecha'], '%Y-%m-%d').date()
        asistencia_existente = Asistencia.objects.filter(
            alumno=alumno,
            grupo_docente_materia=gdm,
            fecha=fecha_clase
        ).exists()
        
        if asistencia_existente:
            print(f"❌ Asistencia ya registrada para {alumno.nombre}")
            return JsonResponse({
                'valido': False,
                'error': 'Ya registraste asistencia para esta clase'
            }, status=400)
        
        # Si todo está bien, incrementar contador de escaneos
        qr_data['escaneos'] += 1
        cache.set(f'qr_{token}', qr_data, timeout=3600)
        
        print(f"✅ QR válido para {alumno.nombre}")
        
        return JsonResponse({
            'valido': True,
            'mensaje': 'QR válido',
            'clase_data': {
                'grupo': qr_data['grupo_nombre'],
                'materia': qr_data['materia_nombre'],
                'fecha': qr_data['fecha'],
                'hora': qr_data['hora'],
                'docente': qr_data['docente_nombre'],
                'gdm_id': gdm.id
            }
        })
        
    except Exception as e:
        print(f"🔥 Error validando QR: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
def api_registrar_asistencia_qr(request):
    """API para registrar la asistencia después de validar QR"""
    print("🔵 api_registrar_asistencia_qr")
    
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    try:
        data = json.loads(request.body)
        matricula = data.get('matricula')
        gdm_id = data.get('gdm_id')
        fecha = data.get('fecha')
        
        alumno = Alumno.objects.get(matricula=matricula)
        gdm = GrupoDocenteMateria.objects.get(id=gdm_id)
        estado_asistio = EstadoAsistencia.objects.get(nombre='Asistió')
        
        asistencia = Asistencia.objects.create(
            alumno=alumno,
            grupo_docente_materia=gdm,
            fecha=fecha,
            estado=estado_asistio,
            comentario='Registrado vía QR'
        )
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Asistencia registrada correctamente',
            'asistencia_id': asistencia.id
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def api_login(request):
    """API para login desde la app Flutter (SOLO MATRÍCULA)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            # Ignoramos password completamente
            
            print(f"📱 Intento de login - Matrícula: {matricula}")
            
            if not matricula:
                return JsonResponse({'error': 'Matrícula requerida'}, status=400)
            
            # Buscar alumno por matrícula
            try:
                alumno = Alumno.objects.get(matricula=matricula)
                
                # Login exitoso - NO verificamos contraseña
                grupo_data = {
                    'id': alumno.grupo.id if alumno.grupo else None,
                    'clave': alumno.grupo.clave if alumno.grupo else 'Sin grupo'
                }
                
                response_data = {
                    'id': alumno.id,
                    'nombre': alumno.nombre,
                    'matricula': alumno.matricula,
                    'grupo': grupo_data,
                    'tipo': 'alumno'
                }
                
                print(f"✅ Login exitoso para: {alumno.nombre}")
                return JsonResponse(response_data)
                
            except Alumno.DoesNotExist:
                print(f"❌ Alumno no encontrado: {matricula}")
                return JsonResponse({
                    'error': 'Matrícula no registrada'
                }, status=404)
                
        except Exception as e:
            print(f"🔥 Error en login: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_registro_alumno(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            print("📥 Datos recibidos:", data)  # Debug
            
            # Validar datos requeridos
            if not data.get('nombre'):
                return JsonResponse({'error': 'El nombre es requerido'}, status=400)
            
            if not data.get('matricula'):
                return JsonResponse({'error': 'La matrícula es requerida'}, status=400)
            
            # Verificar si ya existe la matrícula
            if Alumno.objects.filter(matricula=data['matricula']).exists():
                return JsonResponse({'error': 'La matrícula ya está registrada'}, status=400)
            
            # Verificar que el grupo_id existe
            grupo_id = data.get('grupo_id')
            if not grupo_id:
                return JsonResponse({'error': 'El grupo es requerido'}, status=400)
            
            try:
                grupo = Grupo.objects.get(id=grupo_id)
            except Grupo.DoesNotExist:
                return JsonResponse({'error': 'El grupo no existe'}, status=400)
            
            # Crear el alumno
            alumno = Alumno.objects.create(
                nombre=data['nombre'],
                matricula=data['matricula'],
                grupo=grupo
            )
            
            print(f"✅ Alumno creado: {alumno.nombre} - {alumno.matricula}")
            
            return JsonResponse({
                'success': True,
                'id': alumno.id,
                'nombre': alumno.nombre,
                'matricula': alumno.matricula,
                'mensaje': 'Registro exitoso'
            }, status=201)
            
        except Exception as e:
            print(f"🔥 Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_obtener_grupos(request):
    """API para obtener lista de grupos disponibles para registro"""
    if request.method == 'GET':
        try:
            grupos = Grupo.objects.all().order_by('clave')
            grupos_data = [{
                'id': g.id,
                'clave': g.clave,
                'nombre': f"Grupo {g.clave}"
            } for g in grupos]
            
            return JsonResponse({
                'grupos': grupos_data
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_verificar_sesion(request):
    """API para verificar si un alumno tiene sesión activa"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            device_id = data.get('device_id')
            
            try:
                alumno = Alumno.objects.get(matricula=matricula)
                
                # Aquí puedes verificar si el device_id coincide con el último usado
                # Esto requeriría guardar el device_id en el modelo Alumno
                
                return JsonResponse({
                    'valido': True,
                    'alumno': {
                        'id': alumno.id,
                        'nombre': alumno.nombre,
                        'matricula': alumno.matricula,
                        'grupo_id': alumno.grupo.id if alumno.grupo else None
                    }
                })
                
            except Alumno.DoesNotExist:
                return JsonResponse({
                    'valido': False,
                    'error': 'Alumno no encontrado'
                }, status=404)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_validar_qr_alumno(request):
    """API para validar QR escaneado por el alumno y registrar asistencia"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            token = data.get('token')
            
            print(f"📱 Validando QR - Matrícula: {matricula}, Token: {token}")
            
            # Validar token (ej: "A001_123456789")
            token_parts = token.split('_')
            if len(token_parts) != 2:
                return JsonResponse({'error': 'QR inválido'}, status=400)
            
            token_matricula = token_parts[0]
            timestamp = token_parts[1]
            
            if token_matricula != matricula:
                return JsonResponse({'error': 'QR no pertenece al alumno'}, status=400)
            
            # Verificar expiración (10 minutos máximo)
            from django.utils import timezone
            import datetime
            
            timestamp_int = int(timestamp) / 1000
            tiempo_creacion = datetime.datetime.fromtimestamp(timestamp_int)
            tiempo_creacion = timezone.make_aware(tiempo_creacion)
            
            ahora = timezone.now()
            diferencia = (ahora - tiempo_creacion).total_seconds() / 60
            
            print(f"⏱️ Diferencia: {diferencia} minutos")
            
            if diferencia > 10:
                return JsonResponse({'error': 'QR expirado'}, status=400)
            
            # Buscar alumno
            try:
                alumno = Alumno.objects.get(matricula=matricula)
            except Alumno.DoesNotExist:
                return JsonResponse({'error': 'Alumno no encontrado'}, status=404)
            
            # Registrar asistencia
            fecha_hoy = ahora.date()
            
            # Buscar GDM (Grupo-Docente-Materia) para el grupo del alumno
            # NOTA: Debes definir cómo identificar la materia/clase actual
            gdm = GrupoDocenteMateria.objects.filter(
                grupo=alumno.grupo
            ).first()
            
            if not gdm:
                return JsonResponse({'error': 'No hay clase programada'}, status=400)
            
            # Verificar si ya registró
            if Asistencia.objects.filter(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_hoy
            ).exists():
                return JsonResponse({'error': 'Ya registraste asistencia hoy'}, status=400)
            
            # Crear asistencia
            estado_asistio, _ = EstadoAsistencia.objects.get_or_create(nombre='Asistió')
            
            asistencia = Asistencia.objects.create(
                alumno=alumno,
                grupo_docente_materia=gdm,
                fecha=fecha_hoy,
                estado=estado_asistio,
                comentario=f'Registrado vía QR a las {ahora.strftime("%H:%M")}'
            )
            
            return JsonResponse({
                'success': True,
                'valido': True,
                'mensaje': 'Asistencia registrada correctamente'
            })
            
        except Exception as e:
            print(f"🔥 Error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def obtener_asistencias_por_grupo(request):
    """API para obtener asistencias de un grupo en una fecha específica"""
    if request.method == 'GET':
        try:
            grupo_id = request.GET.get('grupo_id')
            fecha = request.GET.get('fecha')
            
            if not grupo_id or not fecha:
                return JsonResponse({'error': 'Faltan parámetros'}, status=400)
            
            # Buscar GDM para el grupo
            gdms = GrupoDocenteMateria.objects.filter(grupo_id=grupo_id)
            
            asistencias = Asistencia.objects.filter(
                grupo_docente_materia__in=gdms,
                fecha=fecha
            ).values('alumno_id', 'estado__nombre')
            
            return JsonResponse({
                'success': True,
                'asistencias': list(asistencias)
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def api_actividades_alumno(request):
    """API para obtener actividades pendientes de un alumno"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            matricula = data.get('matricula')
            
            print(f"📱 Obteniendo actividades para matrícula: {matricula}")
            
            # Buscar alumno
            try:
                alumno = Alumno.objects.get(matricula=matricula)
            except Alumno.DoesNotExist:
                return JsonResponse({'error': 'Alumno no encontrado'}, status=404)
            
            # Obtener el grupo del alumno
            grupo = alumno.grupo
            if not grupo:
                return JsonResponse({'actividades': []})
            
            # Obtener todas las materias que se imparten en el grupo del alumno
            materias_grupo = GrupoDocenteMateria.objects.filter(grupo=grupo)
            
            actividades_pendientes = []
            
            for gdm in materias_grupo:
                # Obtener parciales activos
                parciales = Parcial.objects.filter(
                    grupo_docente_materia=gdm,
                    cerrado=False  # Solo parciales abiertos
                )
                
                for parcial in parciales:
                    # Obtener actividades del parcial
                    actividades = Actividad.objects.filter(
                        parcial=parcial,
                        fecha_entrega__gte=timezone.now().date()  # No vencidas
                    )
                    
                    for actividad in actividades:
                        # Verificar si ya entregó
                        entrega = Entrega.objects.filter(
                            actividad=actividad,
                            alumno=alumno
                        ).first()
                        
                        if not entrega or not entrega.entregado:
                            # Actividad pendiente
                            actividades_pendientes.append({
                                'id': actividad.id,
                                'titulo': actividad.titulo,
                                'descripcion': actividad.descripcion,
                                'materia': gdm.materia.nombre,
                                'grupo': grupo.clave,
                                'fecha_entrega': actividad.fecha_entrega.strftime('%Y-%m-%d'),
                                'fecha_entrega_formateada': actividad.fecha_entrega.strftime('%d/%m/%Y'),
                                'dias_restantes': (actividad.fecha_entrega - timezone.now().date()).days,
                                'parcial': parcial.nombre,
                                'entregada': False
                            })
            
            # Ordenar por fecha de entrega (más próximas primero)
            actividades_pendientes.sort(key=lambda x: x['fecha_entrega'])
            
            print(f"✅ {len(actividades_pendientes)} actividades encontradas")
            
            return JsonResponse({
                'success': True,
                'actividades': actividades_pendientes,
                'total': len(actividades_pendientes)
            })
            
        except Exception as e:
            print(f"🔥 Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def ver_asistencias(request):
    """Vista para ver las asistencias registradas por QR"""
    # Verificar autenticación
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    usuario_id = request.session.get('usuario_id')
    
    try:
        usuario = Usuario.objects.get(id=usuario_id)
        
        # Obtener los grupos del docente
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario
        ).select_related('grupo', 'materia').values('grupo').distinct()
        
        grupo_ids = [g['grupo'] for g in grupos_docente]
        grupos = Grupo.objects.filter(id__in=grupo_ids)
        
        # Obtener asistencias del día actual (filtradas por grupos del docente)
        hoy = timezone.now().date()
        asistencias_hoy = Asistencia.objects.filter(
            grupo_docente_materia__docente=usuario,
            fecha=hoy
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        ).order_by('-fecha', 'alumno__nombre')
        
        # Calcular totales
        total_asistencias_hoy = asistencias_hoy.count()
        asistencias_por_grupo = {}
        
        for asistencia in asistencias_hoy:
            grupo_clave = asistencia.grupo_docente_materia.grupo.clave
            if grupo_clave not in asistencias_por_grupo:
                asistencias_por_grupo[grupo_clave] = 0
            asistencias_por_grupo[grupo_clave] += 1
        
        # Obtener últimos 10 registros para mostrar en tabla
        ultimas_asistencias = Asistencia.objects.filter(
            grupo_docente_materia__docente=usuario
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        ).order_by('-fecha', '-id')[:20]
        
        context = {
            'grupos': grupos,
            'asistencias_hoy': asistencias_hoy,
            'ultimas_asistencias': ultimas_asistencias,
            'total_asistencias_hoy': total_asistencias_hoy,
            'asistencias_por_grupo': asistencias_por_grupo,
            'hoy': hoy,
            'docente_nombre': usuario.nombre,
        }
        
        return render(request, "ver_asistencias.html", context)
        
    except Usuario.DoesNotExist:
        return redirect('login')
    except Exception as e:
        print(f"Error en ver_asistencias: {e}")
        return redirect('dashboard')

@require_GET
def api_filtrar_asistencias(request):
    """API para filtrar asistencias por grupo y fecha"""
    if not request.session.get('usuario_id'):
        return JsonResponse({'error': 'No autenticado'}, status=401)
    
    try:
        usuario_id = request.session.get('usuario_id')
        grupo_id = request.GET.get('grupo_id')
        fecha = request.GET.get('fecha')
        
        asistencias = Asistencia.objects.filter(
            grupo_docente_materia__docente_id=usuario_id
        ).select_related(
            'alumno',
            'grupo_docente_materia__grupo',
            'grupo_docente_materia__materia',
            'estado'
        )
        
        if grupo_id and grupo_id != 'todos':
            asistencias = asistencias.filter(
                grupo_docente_materia__grupo_id=grupo_id
            )
        
        if fecha:
            asistencias = asistencias.filter(fecha=fecha)
        
        asistencias = asistencias.order_by('-fecha', 'alumno__nombre')[:50]
        
        data = []
        for a in asistencias:
            data.append({
                'id': a.id,
                'alumno': a.alumno.nombre,
                'matricula': a.alumno.matricula,
                'grupo': a.grupo_docente_materia.grupo.clave,
                'materia': a.grupo_docente_materia.materia.nombre,
                'fecha': a.fecha.strftime('%d/%m/%Y'),
                'hora': a.comentario.split('a las ')[-1] if 'a las' in a.comentario else '-',
                'estado': a.estado.nombre
            })
        
        return JsonResponse({'asistencias': data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# AQUI SE TERMINAN LAS VISTAS RELACIONADAS CON QR Y SE REGRESA A LAS VISTAS PRINCIPALES #

def detalleActividad(request, id):
    try:
        # Verificar autenticación con sesión manual
        if not request.session.get('usuario_id'):
            return JsonResponse({"error": "No autorizado"}, status=401)
        
        actividad = Actividad.objects.select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'
        ).get(id=id)
        
        # Verificar que la actividad pertenezca al docente de la sesión
        if actividad.parcial.grupo_docente_materia.docente_id != request.session.get('usuario_id'):
            return JsonResponse({"error": "No tienes permiso"}, status=403)

        grupo = actividad.parcial.grupo_docente_materia.grupo
        materia = actividad.parcial.grupo_docente_materia.materia
        parcial = actividad.parcial
        
        alumnos = grupo.alumno_set.all().order_by('nombre')

        lista_alumnos = []
        entregadas = 0

        for alumno in alumnos:
            entrega, created = Entrega.objects.get_or_create(
                actividad=actividad,
                alumno=alumno,
                defaults={'entregado': False}
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
            "descripcion": actividad.descripcion,
            "grupo": grupo.clave,
            "materia": materia.nombre,
            "parcial": parcial.nombre,
            "fecha_entrega": actividad.fecha_entrega.strftime('%d/%m/%Y'),
            "entregadas": entregadas,
            "total": alumnos.count(),
            "alumnos": lista_alumnos
        }

        return JsonResponse(data)
    
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    
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




def obtener_promedio_grupal(request):
    """Endpoint para obtener el promedio grupal y alumnos en riesgo"""
    if request.method == 'GET':
        grupo_id = request.GET.get('grupo_id')
        docente_id = request.session.get('usuario_id')
        
        if not grupo_id or not docente_id:
            return JsonResponse({'error': 'Faltan parámetros'}, status=400)
        
        try:
            grupo = Grupo.objects.get(id=grupo_id)
            docente = Usuario.objects.get(id=docente_id)
            
            alumnos = Alumno.objects.filter(grupo=grupo)
            
            if not alumnos.exists():
                return JsonResponse({
                    'promedio': None,
                    'valido': False,
                    'alumnos_riesgo': 0,
                    'mensaje': 'No hay alumnos en el grupo'
                })
            
            suma_promedios = 0
            alumnos_con_promedio = 0
            alumnos_en_riesgo = 0
            
            for alumno in alumnos:
                _, _, en_riesgo = determinar_estado_alumno(alumno, docente)
                
                if en_riesgo:
                    alumnos_en_riesgo += 1
                
                calificaciones = CalificacionParcial.objects.filter(
                    alumno=alumno,
                    parcial__grupo_docente_materia__docente=docente,
                    parcial__grupo_docente_materia__grupo=grupo
                )
                
                if calificaciones.exists():
                    suma_califs = sum(c.calificacion for c in calificaciones if c.calificacion is not None)
                    total_califs = calificaciones.count()
                    
                    parciales_totales = Parcial.objects.filter(
                        grupo_docente_materia__docente=docente,
                        grupo_docente_materia__grupo=grupo
                    ).count()
                    
                    if total_califs == parciales_totales and total_califs > 0:
                        def redondear(valor):
                            entero = int(valor)
                            ultimo_digito = entero % 10
                            if ultimo_digito == 0:
                                return entero
                            elif ultimo_digito <= 4:
                                return entero - ultimo_digito
                            else:
                                return entero + (10 - ultimo_digito)
                        
                        suma_redondeada = redondear(suma_califs)
                        promedio_final = suma_redondeada / 10
                        suma_promedios += promedio_final
                        alumnos_con_promedio += 1
            
            if alumnos_con_promedio > 0 and alumnos_con_promedio == alumnos.count():
                promedio_grupal = round(suma_promedios / alumnos_con_promedio, 1)
                return JsonResponse({
                    'promedio': promedio_grupal,
                    'valido': True,
                    'alumnos_riesgo': alumnos_en_riesgo,
                    'mensaje': 'Datos actualizados correctamente'
                })
            else:
                return JsonResponse({
                    'promedio': None,
                    'valido': False,
                    'alumnos_riesgo': alumnos_en_riesgo,
                    'mensaje': 'Faltan calificaciones de algunos alumnos'
                })
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)


@csrf_exempt
def agendar_cita(request): 
    """Endpoint genérico para agendar citas — funciona para Tutor, Pedagogia, Psicologia y Director"""
    if request.method == 'POST':
        try:
            data       = json.loads(request.body)
            alerta_id  = data.get('alerta_id')
            fecha      = data.get('fecha')
            hora       = data.get('hora')
            comentario = data.get('comentario', '').strip()

            if not alerta_id:
                return JsonResponse({'error': 'ID de alerta no proporcionado'}, status=400)
            if not fecha or not hora:
                return JsonResponse({'error': 'Fecha y hora son obligatorias'}, status=400)
            if not comentario:
                return JsonResponse({'error': 'El comentario es obligatorio'}, status=400)

            usuario_id = request.session.get('usuario_id')
            if not usuario_id:
                return JsonResponse({'error': 'No autenticado'}, status=401)

            # Detectar el rol del usuario en sesión
            roles_sesion = request.session.get('usuario_roles', [])
            ROLES_PERMITIDOS = ('Director', 'Tutor', 'Pedagogia', 'Psicologia')
            rol_activo = next((r for r in ROLES_PERMITIDOS if r in roles_sesion), None)

            if not rol_activo:
                return JsonResponse({'error': 'Sin permiso para agendar citas'}, status=403)

            alerta  = Alerta.objects.select_related('alumno__grupo').get(id=alerta_id)
            usuario = Usuario.objects.get(id=usuario_id)

            # Verificar que el usuario tiene relación con esta alerta según su rol
            if rol_activo == 'Tutor':
                if alerta.alumno.grupo.tutor_id != usuario_id:
                    return JsonResponse({'error': 'Esta alerta no pertenece a tu grupo'}, status=403)
            elif rol_activo in ('Pedagogia', 'Psicologia'):
                if alerta.derivada_a != rol_activo:
                    return JsonResponse({'error': f'Esta alerta no está derivada a {rol_activo}'}, status=403)
            # Director puede agendar cita en cualquier alerta

            # ── Convertir strings a objetos date/time ──
            try:
                fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
                hora_obj  = datetime.strptime(hora,  '%H:%M').time()
            except ValueError:
                return JsonResponse({'error': 'Formato de fecha u hora inválido'}, status=400)

            # Crear la cita
            cita = Cita.objects.create(
                alerta=alerta,
                alumno=alerta.alumno,
                creado_por=usuario,
                rol_creador=rol_activo,
                fecha=fecha_obj,    # ← objeto date, no string
                hora=hora_obj,      # ← objeto time, no string
                comentario=comentario,
            )

            # Registrar en el historial de la alerta
            SeguimientoAlerta.objects.create(
                alerta=alerta,
                usuario=usuario,
                accion='comentario',
                comentario=(
                    f"[{rol_activo}] Cita agendada para el "
                    f"{cita.fecha.strftime('%d/%m/%Y')} a las "
                    f"{cita.hora.strftime('%H:%M')}. {comentario}"
                )
            )

            # Notificar al alumno
            notificar_alumno_cita(cita)

            return JsonResponse({
                'success':    True,
                'fecha':      cita.fecha.strftime('%d/%m/%Y'),
                'hora':       cita.hora.strftime('%H:%M'),
                'rol_creador': rol_activo,
            })

        except Alerta.DoesNotExist:
            return JsonResponse({'error': 'Alerta no encontrada'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método no permitido'}, status=405)