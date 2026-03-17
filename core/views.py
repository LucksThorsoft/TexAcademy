from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
import csv
import json
import secrets
from datetime import datetime, timedelta
from django.core.cache import cache 
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
        
        # DEBUG: Imprimir para verificar
        print("="*50)
        print("Datos enviados a la plantilla:")
        import json
        print(json.dumps(grupos_con_materias, indent=2, default=str))
        print("="*50)
        
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


def detalleActividad(request, id):
    try:
        actividad = Actividad.objects.select_related(
            'parcial',
            'parcial__grupo_docente_materia',
            'parcial__grupo_docente_materia__grupo',
            'parcial__grupo_docente_materia__materia'  # <-- IMPORTANTE: agregar materia
        ).get(id=id)

        grupo = actividad.parcial.grupo_docente_materia.grupo
        materia = actividad.parcial.grupo_docente_materia.materia  # <-- Obtener materia
        parcial = actividad.parcial  # <-- Obtener parcial
        
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
            "materia": materia.nombre,  # <-- AGREGADO
            "parcial": parcial.nombre,   # <-- AGREGADO
            "fecha": actividad.fecha_entrega,
            "entregadas": entregadas,
            "total": alumnos.count(),
            "alumnos": lista_alumnos
        }

        return JsonResponse(data)
    
    except Actividad.DoesNotExist:
        return JsonResponse({"error": "Actividad no encontrada"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

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
        
        if not docente_id:
            return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
        
        try:
            # Obtener el grupo y el docente
            grupo = Grupo.objects.get(id=grupo_id)
            docente = Usuario.objects.get(id=docente_id)
            
            # Obtener el GDM (relación grupo-docente-materia)
            gdm = GrupoDocenteMateria.objects.filter(
                grupo=grupo,
                docente=docente
            ).first()
            
            if not gdm:
                return JsonResponse({'error': 'No tienes materias asignadas en este grupo'}, status=400)
            
            # Obtener todos los alumnos del grupo
            alumnos = Alumno.objects.filter(grupo=grupo).order_by('nombre')
            
            if not alumnos.exists():
                return JsonResponse({'historial': [], 'message': 'No hay alumnos en este grupo'})
            
            historial = []
            for alumno in alumnos:
                # Obtener asistencias de este alumno
                asistencias = Asistencia.objects.filter(
                    alumno=alumno,
                    grupo_docente_materia=gdm
                )
                
                total_clases = asistencias.count()
                
                if total_clases > 0:
                    total_asistencias = asistencias.filter(estado__nombre='Asistió').count()
                    total_retardos = asistencias.filter(estado__nombre='Retardo').count()
                    total_faltas = asistencias.filter(estado__nombre='No asistió').count()
                    
                    # Calcular porcentaje (los retardos cuentan como 0.5)
                    porcentaje = int(((total_asistencias + total_retardos * 0.5) / total_clases) * 100)
                    
                    # Determinar estado basado en porcentaje
                    if porcentaje >= 80:
                        estado_alumno = "Bueno"
                    elif porcentaje >= 60:
                        estado_alumno = "Regular"
                    else:
                        estado_alumno = "Crítico"
                else:
                    total_asistencias = 0
                    total_retardos = 0
                    total_faltas = 0
                    porcentaje = 0
                    estado_alumno = "Sin datos"
                
                historial.append({
                    'alumno_id': alumno.id,
                    'nombre': alumno.nombre,
                    'matricula': alumno.matricula,
                    'asistencias': total_asistencias,
                    'retardos': total_retardos,
                    'faltas': total_faltas,
                    'total_clases': total_clases,
                    'porcentaje': porcentaje,
                    'estado': estado_alumno
                })
            
            print(f"Historial generado para {len(historial)} alumnos")
            return JsonResponse({'historial': historial})
                
        except Grupo.DoesNotExist:
            return JsonResponse({'error': 'Grupo no encontrado'}, status=404)
        except Usuario.DoesNotExist:
            return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
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