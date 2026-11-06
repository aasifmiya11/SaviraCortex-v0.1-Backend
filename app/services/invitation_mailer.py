from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode

from app.core.config import settings


def send_invitation_email(
    *,
    to_email: str,
    candidate_name: str,
    organization_name: str,
    inviter_name: str,
    token: str,
) -> None:
    required = {
        "SMTP_HOST": settings.SMTP_HOST,
        "SMTP_USERNAME": settings.SMTP_USERNAME,
        "SMTP_PASSWORD": settings.SMTP_PASSWORD,
        "SMTP_FROM": settings.SMTP_FROM,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("SMTP configuration is incomplete: " + ", ".join(missing))
    if settings.SMTP_USE_SSL and settings.SMTP_STARTTLS:
        raise RuntimeError("Choose SMTP SSL or STARTTLS, not both.")

    link = (
        settings.FRONTEND_BASE_URL.rstrip("/")
        + "/invitations/accept?"
        + urlencode({"token": token})
    )
    subject = f"Invitation for {candidate_name} to join {organization_name}"
    safe_candidate = escape(candidate_name)
    safe_org = escape(organization_name)
    safe_inviter = escape(inviter_name or "Your organization administrator")
    safe_link = escape(link, quote=True)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM
    message["To"] = to_email
    message.set_content(
        f"Hello {candidate_name},\n\n"
        f"{inviter_name or 'Your organization administrator'} invited you to join "
        f"{organization_name} on SaviraCortex.\n\n"
        f"Accept your invitation: {link}\n\n"
        f"This single-use link expires in {settings.INVITATION_EXPIRY_DAYS} days."
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="en"><body style="margin:0;padding:32px;background:#f4f7fb;font-family:Arial,sans-serif;color:#172033">
<div style="max-width:560px;margin:auto;padding:36px;background:#fff;border:1px solid #e5eaf2;border-radius:16px">
<p style="color:#0891b2;font-weight:700;letter-spacing:2px">SAVIRACORTEX</p>
<h1 style="font-size:26px">Hello {safe_candidate},</h1>
<p style="line-height:1.7">{safe_inviter} invited you to join <strong>{safe_org}</strong> on SaviraCortex.</p>
<p style="margin:32px 0"><a href="{safe_link}" style="display:inline-block;padding:14px 24px;background:#0891b2;color:#fff;text-decoration:none;border-radius:8px;font-weight:700">Accept invitation</a></p>
<p style="color:#64748b;font-size:14px;line-height:1.6">This single-use invitation link expires in {settings.INVITATION_EXPIRY_DAYS} days. If you were not expecting this email, ignore it.</p>
<p style="color:#94a3b8;font-size:12px">Automated message from SaviraCortex.</p>
</div></body></html>""",
        subtype="html",
    )

    tls_context = ssl.create_default_context()
    try:
        if settings.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, context=tls_context, timeout=20
            ) as server:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
                server.ehlo()
                if settings.SMTP_STARTTLS:
                    server.starttls(context=tls_context)
                    server.ehlo()
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("The invitation email could not be delivered.") from exc
