"""Envoi du digest par SMTP (facultatif : actif uniquement si SMTP_HOST et SMTP_FROM sont définis)."""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from backend.config import Settings


def _send_sync(settings: Settings, recipient: str, subject: str, html: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Ce message est au format HTML. Ouvrez-le dans un client compatible ou consultez le tableau de bord TenderPulse.")
    message.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_html_email(settings: Settings, recipient: str, subject: str, html: str) -> None:
    if not settings.smtp_enabled:
        raise RuntimeError("SMTP non configuré (SMTP_HOST et SMTP_FROM requis)")
    await asyncio.to_thread(_send_sync, settings, recipient, subject, html)
