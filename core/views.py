from django.shortcuts import render

# Create your views here.
from django.http import JsonResponse
import json
from .models import Grupo, Actividad, Entrega, Alumno, GrupoDocenteMateria, Parcial


def home(request):
    return render(request, "home.html")


def dashboard(request):
    return render(request, "dashboard.html")


def gruposAlumnos(request):
    return render(request, "gruposAlumnos.html")


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


def asistencia(request):
    return render(request, "asistencia.html")


def estadisticas(request):
    return render(request, "estadisticas.html")


def alertas(request):
    return render(request, "alertas.html")
