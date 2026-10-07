"""Backend de correo por HTTPS (Brevo), sin dependencias extra.

Render (plan gratuito) bloquea los puertos SMTP, así que ahí el correo debe salir por una API web.
Se activa solo con variables de entorno (no hay que tocar settings.py):

    EMAIL_BACKEND=api.correo.BrevoEmailBackend
    BREVO_API_KEY=<clave de la API de Brevo>
    DEFAULT_FROM_EMAIL=Gestión Académica <correo-verificado-en-brevo@dominio.com>
"""
import json
import os
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.core.mail.backends.base import BaseEmailBackend

URL = "https://api.brevo.com/v3/smtp/email"


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        enviados = 0
        for m in email_messages:
            nombre, correo = parseaddr(m.from_email)
            sender = {"email": correo}
            if nombre:
                sender["name"] = nombre
            cuerpo = {
                "sender": sender,
                "to": [{"email": a} for a in m.to],
                "subject": m.subject,
                "textContent": m.body,
            }
            req = urllib.request.Request(
                URL,
                data=json.dumps(cuerpo).encode(),
                headers={
                    "api-key": os.environ.get("BREVO_API_KEY", ""),
                    "content-type": "application/json",
                    "accept": "application/json",
                },
            )
            try:
                urllib.request.urlopen(req, timeout=15).close()
                enviados += 1
            except urllib.error.HTTPError as e:
                if not self.fail_silently:  # incluye lo que responde Brevo para poder diagnosticar
                    detalle = e.read().decode(errors="replace")
                    raise RuntimeError(f"Brevo respondió {e.code}: {detalle}") from e
            except Exception:
                if not self.fail_silently:
                    raise
        return enviados
