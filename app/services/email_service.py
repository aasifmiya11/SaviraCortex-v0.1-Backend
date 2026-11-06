from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode

from app.core.config import settings


def send_organization_invitation_email(
    *,
    to_email: str,
    organization_name: str,
    inviter_name: str,
    invitation_token: str,
    expires_in_days: int,
) -> None:
    """Send a branded invitation link using the configured SMTP transport."""
    required = {
        "SMTP_HOST": settings.SMTP_HOST,
        "SMTP_USERNAME": settings.SMTP_USERNAME,
        "SMTP_PASSWORD": settings.SMTP_PASSWORD,
        "SMTP_FROM": settings.SMTP_FROM,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError("SMTP is not configured. Missing: " + ", ".join(missing))
    if settings.SMTP_USE_SSL and settings.SMTP_STARTTLS:
        raise RuntimeError("Configure either SMTP_USE_SSL or SMTP_STARTTLS, not both.")

    base_url = settings.FRONTEND_BASE_URL.rstrip("/")
    invite_url = f"{base_url}/invitations/accept?{urlencode({'token': invitation_token})}"
    safe_org = escape(organization_name)
    safe_inviter = escape(inviter_name or "Your organization administrator")
    safe_url = escape(invite_url, quote=True)

    message = EmailMessage()
    message["Subject"] = f"You're invited to join {organization_name} on SaviraCortex"
    message["From"] = settings.SMTP_FROM
    message["To"] = to_email
    message.set_content(
        f"{inviter_name or 'Your organization administrator'} invited you to join "
        f"{organization_name} on SaviraCortex.\n\n"
        f"Accept your invitation: {invite_url}\n\n"
        f"This link expires in {expires_in_days} days. If you were not expecting this, ignore this email."
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="en"><body style="margin:0;padding:32px;background:#f4f7fb;font-family:Arial,sans-serif;color:#172033">
<div style="max-width:560px;margin:auto;padding:36px;background:#fff;border:1px solid #e5eaf2;border-radius:16px">
<p style="color:#0891b2;font-weight:700;letter-spacing:2px">SAVIRACORTEX</p>
<h1 style="font-size:26px">You're invited to join {safe_org}</h1>
<p style="line-height:1.7">{safe_inviter} has invited you to collaborate with their organization on SaviraCortex.</p>
<p style="margin:32px 0"><a href="{safe_url}" style="display:inline-block;padding:14px 24px;background:#0891b2;color:#fff;text-decoration:none;border-radius:8px;font-weight:700">Accept invitation</a></p>
<p style="color:#64748b;font-size:14px;line-height:1.6">This invitation link expires in {expires_in_days} days and can only be used once. If you were not expecting this invitation, you can safely ignore this email.</p>
<hr style="border:0;border-top:1px solid #e5eaf2;margin:28px 0" />
<p style="color:#94a3b8;font-size:12px">Automated message from SaviraCortex. Please do not reply.</p>
</div></body></html>""",
        subtype="html",
    )

    context = ssl.create_default_context()
    try:
        if settings.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=20
            ) as server:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
                server.ehlo()
                if settings.SMTP_STARTTLS:
                    server.starttls(context=context)
                    server.ehlo()
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("Unable to deliver the organization invitation email.") from exc
