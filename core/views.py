from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import csv
import json
import re
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
        # FILTRADAS por el cuatrimestre activo
        grupos_docente = GrupoDocenteMateria.objects.filter(
            docente=usuario,
            grupo__cuatrimestre=cuatrimestre_activo  # Filtro por cuatrimestre activo
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
                    # Obtener el estado del alumno usando la función unificada
                    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, usuario)
                    
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
                        'fecha_inicio': parcial.fecha_inicio.strftime('%d/%m/%Y'),
                        'fecha_fin': parcial.fecha_cierre.strftime('%d/%m/%Y'),
                    })
            
            # Agregar la materia con su información de parciales
            grupos_dict[grupo.clave]['materias'].append({
                'id': gdm.id,
                'nombre': materia.nombre,
                'tiene_parciales': tiene_parciales,
                'parciales_configurados': gdm.parciales_configurados,
                'parciales': parciales_data,
            })
        
        # Calcular promedios grupales y alumnos en riesgo para cada grupo
        for clave, grupo_data in grupos_dict.items():
            grupo_id = grupo_data['grupo_id']
            alumnos_grupo = Alumno.objects.filter(grupo_id=grupo_id)
            
            if alumnos_grupo.exists():
                suma_promedios = 0
                alumnos_con_promedio = 0
                alumnos_en_riesgo = 0
                
                for alumno in alumnos_grupo:
                    # Obtener el estado actualizado del alumno
                    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, usuario)
                    
                    # Actualizar los datos del alumno
                    alumno_data = next((a for a in grupo_data['alumnos'] if a['id'] == alumno.id), None)
                    if alumno_data:
                        alumno_data['estado'] = estado_texto
                        alumno_data['estado_clase'] = estado_clase
                        alumno_data['en_riesgo'] = en_riesgo
                    
                    if en_riesgo:
                        alumnos_en_riesgo += 1
                    
                    # Obtener calificaciones para el promedio grupal
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
                
                # Calcular promedio grupal
                if alumnos_con_promedio > 0 and alumnos_con_promedio == alumnos_grupo.count():
                    grupo_data['promedio_grupal'] = round(suma_promedios / alumnos_con_promedio, 1)
                    grupo_data['promedio_grupal_valido'] = True
                
                # Guardar alumnos en riesgo
                grupo_data['alumnos_riesgo'] = alumnos_en_riesgo
                # Actualizar el JSON de alumnos con los estados actualizados
                grupo_data['alumnos_json'] = json.dumps(grupo_data['alumnos'], ensure_ascii=False)
        
        # Convertir el diccionario a lista y agregar materias_json a cada grupo
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
                # Usar la función auxiliar para determinar si está en riesgo
                _, _, en_riesgo = determinar_estado_alumno(alumno, docente)
                
                if en_riesgo:
                    alumnos_en_riesgo += 1
                
                # Calcular promedio para el promedio grupal (igual que antes)
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

def determinar_estado_alumno(alumno, docente):
    """
    Determina el estado de un alumno basado ÚNICAMENTE en sus alertas existentes
    Retorna: (estado_texto, estado_clase, en_riesgo_boolean)
    """
    # Obtener las materias que este docente imparte en el grupo del alumno
    materias_docente = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo,
        docente=docente
    )
    
    # Si el docente no tiene materias en este grupo, el alumno no tiene estado relevante
    if not materias_docente.exists():
        return ("Sin información", "status-info", False)
    
    # Obtener los parciales de las materias del docente
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=materias_docente
    ).values_list('id', flat=True)
    
    # Obtener alertas NO ATENDIDAS del alumno en estas materias
    alertas = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids
    )
    
    # Si no hay alertas, el alumno está estable
    if not alertas.exists():
        return ("Estable", "status-good", False)
    
    # Determinar el nivel MÁS ALTO de alerta
    if alertas.filter(nivel_riesgo='Alto').exists():
        return ("En Riesgo", "status-danger", True)
    elif alertas.filter(nivel_riesgo='Medio').exists():
        return ("Requiere Atención", "status-warning", False)
    elif alertas.filter(nivel_riesgo='Bajo').exists():
        return ("Precaución", "status-info", False)
    
    # Fallback (no debería ocurrir)
    return ("Estable", "status-good", False)

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

    # USAR LA FUNCIÓN UNIFICADA PARA DETERMINAR EL ESTADO
    estado_texto, estado_clase, en_riesgo = determinar_estado_alumno(alumno, docente)
    
    # Obtener las materias que este docente imparte en el grupo del alumno
    materias_docente = GrupoDocenteMateria.objects.filter(
        grupo=alumno.grupo,
        docente=docente
    ).select_related('materia')
    
    # Obtener los IDs de los GDM del docente para filtrar
    gdm_ids_docente = [gdm.id for gdm in materias_docente]
    
    # Obtener los parciales de las materias del docente
    parciales_ids = Parcial.objects.filter(
        grupo_docente_materia__in=gdm_ids_docente
    ).values_list('id', flat=True)
    
    # Variables para el promedio de la materia
    promedio_materia = None
    
    # Obtener datos de calificaciones para la tabla
    calificaciones_data = []
    parciales_info = []
    
    for gdm in materias_docente:
        # Obtener los parciales de esta materia
        parciales = Parcial.objects.filter(
            grupo_docente_materia=gdm
        ).order_by('numero_parcial')
        
        # Guardar información de parciales para los encabezados
        for parcial in parciales:
            parciales_info.append({
                'numero': parcial.numero_parcial,
                'nombre': parcial.nombre,
                'porcentaje': parcial.porcentaje,
            })
        
        # Obtener calificaciones del alumno en esta materia
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
    
    # Calcular suma para el promedio (como en el modal)
    suma_calificaciones = sum([
        c['calificacion'] for c in calificaciones_data 
        if c['calificacion'] is not None
    ])
    total_calificaciones = len([c for c in calificaciones_data if c['calificacion'] is not None])
    todas_completas = total_calificaciones == len(parciales_info) and total_calificaciones > 0
    
    if todas_completas and suma_calificaciones > 0:
        # Misma función de redondeo que en el modal
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
    
    # Obtener historial de asistencia del alumno (TODAS las materias)
    asistencias_todas = Asistencia.objects.filter(
        alumno=alumno
    ).select_related(
        'grupo_docente_materia__materia', 
        'grupo_docente_materia__docente',
        'estado'
    ).order_by('-fecha')
    
    # Procesar datos de asistencia (TODAS)
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
    
    # Obtener solo las asistencias de la materia del docente actual
    gdm_ids_docente = [gdm.id for gdm in materias_docente]
    asistencia_esta_materia = [a for a in asistencia_todas_data if a['gdm_id'] in gdm_ids_docente]
    
    # Calcular estadísticas para "Esta Materia"
    total_asistencias_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'Asistió')
    total_retardos_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'Retardo')
    total_faltas_esta = sum(1 for a in asistencia_esta_materia if a['estado'] == 'No asistió')
    total_clases_esta = len(asistencia_esta_materia)
    
    if total_clases_esta > 0:
        porcentaje_esta = int(((total_asistencias_esta + total_retardos_esta * 0.5) / total_clases_esta) * 100)
    else:
        porcentaje_esta = 0
    
    # Calcular estadísticas para "Todas las Materias"
    total_asistencias_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'Asistió')
    total_retardos_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'Retardo')
    total_faltas_todas = sum(1 for a in asistencia_todas_data if a['estado'] == 'No asistió')
    total_clases_todas = len(asistencia_todas_data)
    
    if total_clases_todas > 0:
        porcentaje_todas = int(((total_asistencias_todas + total_retardos_todas * 0.5) / total_clases_todas) * 100)
    else:
        porcentaje_todas = 0
    
    # Comentarios (de asistencia)
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

    # Obtener las alertas del alumno FILTRADAS por las materias del docente
    alertas = Alerta.objects.filter(
        alumno=alumno,
        atendida=False,
        parcial__id__in=parciales_ids  # Solo alertas de parciales del docente
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
    
    # Procesar alertas para el template
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
    
     # Determinar si el alumno está en un cuatrimestre activo
    cuatrimestre_activo = alumno.grupo.cuatrimestre.activo if alumno.grupo.cuatrimestre else False
    
    # También podrías verificar la fecha actual contra el rango del cuatrimestre
    from django.utils import timezone
    hoy = timezone.now().date()
    
    if alumno.grupo.cuatrimestre:
        cuatrimestre_en_rango = (
            alumno.grupo.cuatrimestre.fecha_inicio <= hoy <= alumno.grupo.cuatrimestre.fecha_fin
        )
        # El badge será activo solo si el cuatrimestre está marcado como activo Y la fecha actual está dentro del rango
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
    materia_form = GrupoDocenteMateriaForm()

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
        "materia_form": materia_form,
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
            return redirect('/tutor')
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

                # Obtener TODOS los roles
                relaciones = UsuarioRol.objects.filter(usuario=usuario)
                
                # Crear lista de nombres de roles
                lista_roles = [r.rol.nombre for r in relaciones]
                
                # Guardar la lista en la sesión
                request.session['usuario_roles'] = lista_roles

                # Redirección basada en jerarquía
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
    """Endpoint AJAX para obtener el historial de asistencia de un grupo"""
    if request.method == 'GET':
        grupo_id = request.GET.get('grupo_id')
        docente_id = request.session.get('usuario_id')
        
        print(f"Obteniendo historial - Grupo ID: {grupo_id}, Docente ID: {docente_id}")
        
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
                f"Asistencia baja en {parcial.nombre} "
                f"({gdm.materia.nombre}): "
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
            print(f"Error al obtener historial: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

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
            'estados_asistencia': estados_data
        }
        
    except Usuario.DoesNotExist:
        return redirect('login')
    
    return render(request, "asistencia.html", context)

# Agrega esto en tu views.py

@require_POST
def new_group(request):
    """Vista para crear un nuevo grupo"""
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')
    
    # Aquí procesas la creación del grupo
    # Asumiendo que tienes un formulario para grupos
    form = GrupoForm(request.POST)
    
    if form.is_valid():
        grupo = form.save()
        messages.success(request, f'Grupo {grupo.clave} creado correctamente')
    else:
        messages.error(request, 'Error al crear el grupo')
    
    return redirect('director')

@require_POST
def new_materia(request):
    """Vista para asignar materia a un grupo con docente"""
    if not request.session.get('usuario_id'):
        return redirect('login')
    
    roles = request.session.get('usuario_roles', [])
    if 'Director' not in roles:
        return redirect('dashboard')
    
    # Procesar la asignación de materia
    form = GrupoDocenteMateriaForm(request.POST)
    
    if form.is_valid():
        form.save()
        messages.success(request, 'Materia asignada correctamente')
    else:
        messages.error(request, 'Error al asignar la materia')
    
    return redirect('director')