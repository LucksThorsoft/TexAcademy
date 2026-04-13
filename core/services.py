from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from twilio.rest import Client


# ──────────────────────────────────────────────
# CLIENTE TWILIO
# ──────────────────────────────────────────────

def get_twilio_client():
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


# ──────────────────────────────────────────────
# SMS
# ──────────────────────────────────────────────

def send_sms(to: str, body: str) -> dict:
    try:
        client = get_twilio_client()
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to,
        )
        return {'success': True, 'sid': message.sid}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ──────────────────────────────────────────────
# EMAIL (HTML + texto plano)
# ──────────────────────────────────────────────

def send_email_html(subject: str, text_body: str, html_body: str, to: list) -> dict:
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
        )
        email.attach_alternative(html_body, 'text/html')
        email.send()
        return {'success': True}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ──────────────────────────────────────────────
# NOTIFICACIÓN DE ALERTA AL TUTOR
# ──────────────────────────────────────────────

def notificar_tutor_alerta(alerta, es_nueva: bool = True):
    """
    Envía correo y SMS al tutor del grupo del alumno cuando se crea o actualiza una alerta.
    Registra el resultado en el modelo Notificacion.

    Args:
        alerta:   Instancia del modelo Alerta (ya guardada en BD)
        es_nueva: True si la alerta se acaba de crear, False si fue actualizada
    """
    # Import aquí para evitar importación circular
    from .models import Notificacion

    alumno = alerta.alumno
    grupo  = alumno.grupo
    tutor  = grupo.tutor

    # Si el grupo no tiene tutor asignado, no hay a quién notificar
    if not tutor:
        print(f"[NOTIFICACION] El grupo {grupo.clave} no tiene tutor asignado.")
        return

    accion     = "generada" if es_nueva else "actualizada"
    nivel      = alerta.nivel_riesgo
    icono_nivel = {"Alto": "🔴", "Medio": "🟡", "Bajo": "🟢"}.get(nivel, "⚪")

    # ── Construir mensajes ──────────────────────────────────────
    asunto = f"{icono_nivel} Alerta {nivel} {accion} – {alumno.nombre} ({grupo.clave})"

    # Texto plano (para SMS y fallback de email)
    motivos_texto = "\n".join(
        f"  • {m.strip()}"
        for m in alerta.motivo.split(" | ")
        if m.strip()
    )
    texto_plano = (
        f"Alerta {accion.upper()} – Nivel {nivel}\n"
        f"Alumno: {alumno.nombre} (Matrícula: {alumno.matricula})\n"
        f"Grupo: {grupo.clave}\n\n"
        f"Motivo(s):\n{motivos_texto}\n\n"
        f"Ingresa al sistema para revisar y atender esta alerta."
    )

    # HTML para email
    motivos_html = "".join(
        f"<li style='margin-bottom:6px'>{m.strip()}</li>"
        for m in alerta.motivo.split(" | ")
        if m.strip()
    )
    colores = {"Alto": "#dc2626", "Medio": "#d97706", "Bajo": "#2563eb"}
    color   = colores.get(nivel, "#6b7280")

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:{color};padding:16px 24px;border-radius:8px 8px 0 0">
        <h2 style="color:#fff;margin:0">{icono_nivel} Alerta de Riesgo Académico</h2>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px">
        <p style="margin:0 0 8px"><strong>Estado:</strong>
          <span style="color:{color};font-weight:700">{nivel} – {accion.capitalize()}</span>
        </p>
        <p style="margin:0 0 4px"><strong>Alumno:</strong> {alumno.nombre}</p>
        <p style="margin:0 0 4px"><strong>Matrícula:</strong> {alumno.matricula}</p>
        <p style="margin:0 0 16px"><strong>Grupo:</strong> {grupo.clave}</p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin-bottom:16px">
        <p style="margin:0 0 8px"><strong>Motivo(s) de la alerta:</strong></p>
        <ul style="margin:0 0 24px;padding-left:20px;color:#374151">
          {motivos_html}
        </ul>
        <p style="color:#6b7280;font-size:13px;margin:0">
          Este es un mensaje automático del Sistema de Seguimiento Académico.<br>
          Por favor ingresa al sistema para atender esta alerta.
        </p>
      </div>
    </div>
    """

    # Texto corto para SMS (máx ~160 chars por segmento)
    sms_body = (
        f"[Sistema] Alerta {nivel} {accion}: {alumno.nombre} ({alumno.matricula}) – "
        f"Grupo {grupo.clave}. Revisa el sistema para más detalles."
    )

    # ── Enviar y registrar CORREO ───────────────────────────────
    if tutor.correo:
        resultado_email = send_email_html(
            subject=asunto,
            text_body=texto_plano,
            html_body=html_body,
            to=[tutor.correo],
        )
        Notificacion.objects.create(
            alerta=alerta,
            destinatario_usuario=tutor,
            medio='correo',
            asunto=asunto,
            mensaje=texto_plano,
            enviado=resultado_email['success'],
            fecha_envio=timezone.now() if resultado_email['success'] else None,
            error=resultado_email.get('error') if not resultado_email['success'] else None,
        )
        estado = "✅ enviado" if resultado_email['success'] else f"❌ error: {resultado_email.get('error')}"
        print(f"[NOTIFICACION EMAIL] Tutor {tutor.nombre} → {estado}")
    else:
        print(f"[NOTIFICACION] Tutor {tutor.nombre} no tiene correo registrado.")

    # ── Enviar y registrar SMS ──────────────────────────────────────
    if tutor.telefono:
        # Normalizar número a formato E.164
        telefono = tutor.telefono.strip().replace(" ", "").replace("-", "")
        if not telefono.startswith("+"):
            telefono = "+52" + telefono  # Agregar código de México si no lo tiene

        resultado_sms = send_sms(to=telefono, body=sms_body)
        Notificacion.objects.create(
            alerta=alerta,
            destinatario_usuario=tutor,
            medio='sms',
            mensaje=sms_body,
            enviado=resultado_sms['success'],
            fecha_envio=timezone.now() if resultado_sms['success'] else None,
            error=resultado_sms.get('error') if not resultado_sms['success'] else None,
        )
        estado = "✅ enviado" if resultado_sms['success'] else f"❌ error: {resultado_sms.get('error')}"
        print(f"[NOTIFICACION SMS]   Tutor {tutor.nombre} → {estado}")
    else:
        print(f"[NOTIFICACION] Tutor {tutor.nombre} no tiene teléfono registrado.")