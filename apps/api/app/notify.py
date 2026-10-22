"""Email notifications (SMTP). Without SMTP_HOST configured messages are only
logged, so development and tests need no mail server. Sending runs from
FastAPI background tasks and never fails the request."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger(__name__)

# Replaced in tests to capture outgoing mail.
outbox: list[EmailMessage] | None = None


def _send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=15) as smtp:
        if s.SMTP_TLS:
            smtp.starttls()
        if s.SMTP_USER:
            smtp.login(s.SMTP_USER, s.SMTP_PASSWORD)
        smtp.send_message(msg)


def send_email(to: list[str], subject: str, body: str) -> None:
    recipients = sorted({t for t in to if t})
    if not recipients:
        return
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    if outbox is not None:
        outbox.append(msg)
        return
    if not s.SMTP_HOST:
        logger.info("Email (SMTP not configured) to %s: %s", recipients, subject)
        return
    try:
        _send(msg)
    except Exception:  # noqa: BLE001
        logger.exception("Email to %s failed", recipients)
