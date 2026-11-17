"""Outgoing e-mail (Ausbau A8/A10).

Every mail is stored as :class:`~models.marketing.OutgoingMail`. With
``MAIL_MODE=mock`` (default) that is all: the mail shows in the dashboard outbox
and never leaves the server. With ``MAIL_MODE=smtp`` it is sent over SMTP with
STARTTLS (port 587) or implicit TLS (port 465); the password stays in ``.env``.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr

from sqlalchemy import delete
from sqlalchemy.orm import Session

from core.config import Settings
from models.marketing import OutgoingMail

log = logging.getLogger(__name__)
KEEP_DAYS = 30


def ready(settings: Settings) -> str | None:
    """Why real sending is not possible; None when SMTP is configured."""
    if settings.mail_mode != "smtp":
        return "Testmodus: Mails bleiben im Postausgang (MAIL_MODE=mock)"
    if not settings.smtp_host or not settings.mail_from:
        return "SMTP_HOST oder MAIL_FROM fehlt"
    return None


def send(
    session: Session,
    settings: Settings,
    to: str,
    subject: str,
    body: str,
    kind: str,
    headers: dict[str, str] | None = None,
) -> OutgoingMail:
    mail = OutgoingMail(
        to_address=to or "(kein Empfänger)", subject=subject[:300], body_text=body, kind=kind
    )
    problem = ready(settings) or (None if "@" in (to or "") else "Kein Empfänger eingetragen")
    if problem is not None:
        mail.status = "mock"
        mail.error = None if settings.mail_mode == "mock" else problem
        session.add(mail)
        session.flush()
        return mail
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(body)
    try:
        context = ssl.create_default_context()
        if settings.smtp_port == 465:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=20, context=context
            )
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            client.starttls(context=context)
        with client:
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            client.send_message(msg, from_addr=parseaddr(settings.mail_from)[1])
        mail.status, mail.sent_at = "sent", datetime.now(UTC)
    except (OSError, smtplib.SMTPException) as exc:
        mail.status, mail.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        log.warning("mail %s to recipient failed: %s", kind, type(exc).__name__)
    session.add(mail)
    session.flush()
    return mail


def cleanup(session: Session, now: datetime | None = None) -> int:
    """Delete mails older than ``KEEP_DAYS`` (they may hold confirmation links)."""
    limit = (now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)
    result = session.execute(delete(OutgoingMail).where(OutgoingMail.created_at < limit))
    return int(getattr(result, "rowcount", 0) or 0)
