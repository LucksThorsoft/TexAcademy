from django.db import models
from django.utils import timezone


# -------------------------
# USUARIOS Y ROLES
# -------------------------

class Usuario(models.Model):
    nombre = models.CharField(max_length=100)
    correo = models.EmailField(unique=True)
    password = models.CharField(max_length=255)  # hacer hash para la contraseña
    telefono = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        return self.nombre


class Rol(models.Model):
    nombre = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre


class UsuarioRol(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('usuario', 'rol')


# -------------------------
# CUATRIMESTRES Y GRUPOS
# -------------------------

class Cuatrimestre(models.Model):
    nombre = models.CharField(max_length=50)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activo = models.BooleanField(default=False)

    def __str__(self):
        return self.nombre


class Grupo(models.Model):
    clave = models.CharField(max_length=50)
    cuatrimestre = models.ForeignKey(Cuatrimestre, on_delete=models.CASCADE)
    tutor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.clave


class Alumno(models.Model):
    nombre = models.CharField(max_length=100)
    matricula = models.CharField(max_length=20, unique=True)
    grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE)
    correo = models.EmailField(null=True, blank=True)         # correo del alumno
    telefono = models.CharField(max_length=20, null=True, blank=True)  # SMS alumno/tutor

    def __str__(self):
        return self.nombre


# -------------------------
# MATERIAS Y DOCENTES
# -------------------------

class Materia(models.Model):
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre


class GrupoDocenteMateria(models.Model):
    grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE)
    docente = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    parciales_configurados = models.BooleanField(default=False)   # <-- NUEVO

    class Meta:
        unique_together = ('grupo', 'materia')

    def __str__(self):
        return f"{self.materia} - {self.grupo} ({self.docente})"



# -------------------------
# PARCIALES Y ACTIVIDADES
# -------------------------

class Parcial(models.Model):
    numero_parcial = models.IntegerField(default=1)         # <-- NUEVO
    nombre = models.CharField(max_length=50)
    porcentaje = models.IntegerField()
    grupo_docente_materia = models.ForeignKey(GrupoDocenteMateria, on_delete=models.CASCADE)
    fecha_inicio = models.DateField()
    fecha_cierre = models.DateField()
    cerrado = models.BooleanField(default=False)

    class Meta:
        unique_together = ('grupo_docente_materia', 'numero_parcial')  # No duplicar número por materia

class Actividad(models.Model):
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField()
    parcial = models.ForeignKey(Parcial, on_delete=models.CASCADE)
    fecha_entrega = models.DateField()
    hora_entrega = models.TimeField(default=timezone.now)


class Entrega(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    entregado = models.BooleanField(default=False)
    calificacion = models.FloatField(null=True, blank=True)
    comentario = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('actividad', 'alumno')

# -------------------------
# CALIFICACIONES POR PARCIAL
# -------------------------

class CalificacionParcial(models.Model):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    parcial = models.ForeignKey(Parcial, on_delete=models.CASCADE)
    calificacion = models.FloatField(null=True, blank=True)  # null = aún no capturada
    comentario = models.TextField(null=True, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

# -------------------------
# ASISTENCIAS
# -------------------------

class EstadoAsistencia(models.Model):
    nombre = models.CharField(max_length=30) # Asistió / Retardo / No asistió

    def __str__(self):
        return self.nombre


class Asistencia(models.Model):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    grupo_docente_materia = models.ForeignKey(GrupoDocenteMateria, on_delete=models.CASCADE)
    fecha = models.DateField()
    estado = models.ForeignKey(EstadoAsistencia, on_delete=models.CASCADE)
    comentario = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('alumno', 'grupo_docente_materia', 'fecha')


# -------------------------
# COMENTARIOS, ALERTAS, NOTIFICACIONES
# -------------------------

class Comentario(models.Model):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    docente = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=50)
    texto = models.TextField()
    fecha = models.DateField(auto_now_add=True)


class Alerta(models.Model):
    alumno       = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    parcial      = models.ForeignKey('Parcial', on_delete=models.CASCADE, null=True, blank=True)
    motivo       = models.TextField()
    nivel_riesgo = models.CharField(max_length=20)
    fecha        = models.DateField(auto_now_add=True)
    atendida     = models.BooleanField(default=False)
    derivada     = models.BooleanField(default=False)      # NUEVO
    derivada_a   = models.CharField(max_length=20, null=True, blank=True)  # NUEVO


class SeguimientoAlerta(models.Model):
    ACCIONES = [
        ('cerrada',             'Cerrada'),
        ('derivada_tutor',      'Derivada al Tutor'),
        ('derivada_pedagogia',  'Derivada a Pedagogía'),
        ('derivada_psicologia', 'Derivada a Psicología'),
        ('derivada_direccion',  'Derivada a Dirección'),
        ('comentario',          'Comentario'),
    ]

    alerta     = models.ForeignKey('Alerta', on_delete=models.CASCADE, related_name='seguimientos')
    usuario    = models.ForeignKey('Usuario', on_delete=models.CASCADE)
    accion     = models.CharField(max_length=30, choices=ACCIONES)  # ya tiene 30, suficiente
    comentario = models.TextField()
    fecha      = models.DateTimeField(auto_now_add=True)

class Notificacion(models.Model):
    MEDIOS = [
        ('correo', 'Correo electrónico'),
        ('sms',    'SMS'),
    ]

    alerta               = models.ForeignKey(Alerta, on_delete=models.CASCADE)
    destinatario_usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)
    destinatario_alumno  = models.ForeignKey(Alumno, on_delete=models.SET_NULL, null=True, blank=True)
    medio                = models.CharField(max_length=20, choices=MEDIOS)
    asunto               = models.CharField(max_length=200, null=True, blank=True)  # solo para correo
    mensaje              = models.TextField(null=True, blank=True)
    enviado              = models.BooleanField(default=False)
    fecha_envio          = models.DateTimeField(null=True, blank=True)  # DateTimeField, no DateField
    error                = models.TextField(null=True, blank=True)  # si falla, guardar por qué

class Cita(models.Model):
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('realizada', 'Realizada'),
        ('cancelada', 'Cancelada'),
    ]

    CREADO_POR_ROL = [
        ('Tutor',      'Tutor'),
        ('Pedagogia',  'Pedagogía'),
        ('Psicologia', 'Psicología'),
        ('Director',   'Director'),
    ]

    alerta         = models.ForeignKey(Alerta, on_delete=models.CASCADE, related_name='citas')
    alumno         = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    creado_por     = models.ForeignKey(Usuario, on_delete=models.CASCADE)  # quien agenda (tutor/psico/pedagogo/director)
    rol_creador    = models.CharField(max_length=20, choices=CREADO_POR_ROL)  # su rol en ese momento
    fecha          = models.DateField()
    hora           = models.TimeField()
    comentario     = models.TextField()
    estado         = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cita {self.alumno} – {self.fecha} {self.hora} ({self.rol_creador})"