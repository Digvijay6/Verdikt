"""Sending mail, with a fallback.

Resend is the right long-term choice, but until a sending domain is verified it
will only deliver to the account owner's own address. That is fine for
development and useless for a demo, where someone types their own email and
expects the invite to arrive.

So: two providers behind one function, and a fallback if the primary refuses.
Resend stays the default so the production path is the one normally exercised;
SMTP exists so an unverified domain does not mean nothing arrives.

Delete the SMTP path once the domain is verified — it is scaffolding, not
architecture.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from enum import StrEnum

import resend

from shared.config import get_settings

log = logging.getLogger(__name__)


class Provider(StrEnum):
    RESEND = "resend"
    SMTP = "smtp"


class EmailNotSent(Exception):
    """Every configured provider refused."""


def _send_resend(to: str, subject: str, body: str) -> str:
    cfg = get_settings()
    if not cfg.resend_api_key or "PLACEHOLDER" in cfg.resend_api_key:
        raise EmailNotSent("Resend is not configured")
    resend.api_key = cfg.resend_api_key
    sent = resend.Emails.send(
        {"from": cfg.from_email, "to": [to], "subject": subject, "text": body}
    )
    return sent.get("id", "")


def _send_smtp(to: str, subject: str, body: str) -> str:
    """Plain SMTP, normally Gmail with an app password.

    Gmail requires 2FA enabled and an app-specific password; your account
    password will not authenticate here.
    """
    cfg = get_settings()
    if not (cfg.smtp_host and cfg.smtp_user and cfg.smtp_password):
        raise EmailNotSent("SMTP is not configured")

    msg = EmailMessage()
    msg["From"] = cfg.smtp_from or cfg.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as s:
        s.starttls()
        s.login(cfg.smtp_user, cfg.smtp_password)
        s.send_message(msg)
    return "smtp"


_SENDERS = {Provider.RESEND: _send_resend, Provider.SMTP: _send_smtp}


def send(to: str, subject: str, body: str) -> str:
    """Send via the configured provider, falling back to the other one.

    The fallback exists for one specific failure: Resend refusing an address
    because the domain is unverified. Discovering that mid-demo, with no
    invite arriving and no visible reason, is exactly the situation worth
    engineering around.

    Raises EmailNotSent only if every provider fails, and logs which and why —
    silent email failure is worse than a loud one.
    """
    cfg = get_settings()
    primary = Provider(cfg.email_provider)
    order = [primary] + [p for p in Provider if p != primary]

    failures = []
    for provider in order:
        try:
            message_id = _SENDERS[provider](to, subject, body)
            if provider is not primary:
                log.warning(
                    "sent via fallback %s after %s failed: %s",
                    provider.value,
                    primary.value,
                    failures[-1] if failures else "unknown",
                )
            return message_id
        except Exception as exc:
            failures.append(f"{provider.value}: {str(exc)[:200]}")
            continue

    raise EmailNotSent("; ".join(failures))
