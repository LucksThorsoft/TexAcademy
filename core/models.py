from django.db import models


# -------------------------
# USUARIOS Y ROLES
# -------------------------

class Usuario(models.Model):
    nombre = models.CharField(max_length=100)
    correo = models.EmailField(unique=True)
    password = models.CharField(max_length=255)  # hacer hash para la contraseña

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
    docente = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('grupo', 'docente', 'materia')


# -------------------------
# PARCIALES Y ACTIVIDADES
# -------------------------

class Parcial(models.Model):
    nombre = models.CharField(max_length=50)
    porcentaje = models.IntegerField()
    grupo_docente_materia = models.ForeignKey(GrupoDocenteMateria, on_delete=models.CASCADE)
    fecha_inicio = models.DateField()
    fecha_cierre = models.DateField()
    cerrado = models.BooleanField(default=False)


class Actividad(models.Model):
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField()
    parcial = models.ForeignKey(Parcial, on_delete=models.CASCADE)
    fecha_entrega = models.DateField()


class Entrega(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    entregado = models.BooleanField(default=False)
    calificacion = models.FloatField(null=True, blank=True)
    comentario = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('actividad', 'alumno')


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
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE)
    motivo = models.TextField()
    nivel_riesgo = models.CharField(max_length=20)
    fecha = models.DateField(auto_now_add=True)
    atendida = models.BooleanField(default=False)


class Notificacion(models.Model):
    alerta = models.ForeignKey(Alerta, on_delete=models.CASCADE)
    medio = models.CharField(max_length=30)  # correo / telegram
    enviado = models.BooleanField(default=False)
    fecha_envio = models.DateField(null=True, blank=True)
