"""Email notification of booking results.

Two providers share one ``send(result) -> bool`` contract:
- :class:`EmailNotifier` — raw SMTP (local dev; discouraged on Cloud Run).
- :class:`SendGridNotifier` — SendGrid HTTPS API (recommended on GCP, port 443).

Use :func:`make_notifier` to pick the provider from settings.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import EmailProvider, Settings
from .logging_config import get_logger
from .models import BookingResult

log = get_logger(__name__)


def build_subject(result: BookingResult) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    return f"[Tennis Booking] {status}: {result.request.date}"


def build_body(result: BookingResult) -> str:
    """Compose the plain-text email body from a booking result."""
    req = result.request
    lines = [
        result.summary(),
        "",
        f"Requested date:  {req.date}",
        f"Requested time:  {req.start_time:%H:%M}",
        f"Duration:        {req.duration_minutes} min",
        f"Preferred court: {req.court or 'any'}",
    ]
    if result.slot:
        lines += [
            "",
            "Booked slot:",
            f"  Court: {result.slot.court}",
            f"  Time:  {result.slot.start_time:%H:%M}"
            + (f"-{result.slot.end_time:%H:%M}" if result.slot.end_time else ""),
        ]
        if result.slot.price:
            lines.append(f"  Price: {result.slot.price}")
    if result.confirmation:
        lines += ["", f"Confirmation: {result.confirmation}"]
    if result.error:
        lines += ["", f"Error: {result.error}"]
    if result.screenshot_path:
        lines += ["", f"Screenshot: {result.screenshot_path}"]
    return "\n".join(lines)


class Notifier(Protocol):
    def send(self, result: BookingResult) -> bool: ...


class EmailNotifier:
    """Sends a plain-text result email over SMTP (STARTTLS)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, result: BookingResult) -> bool:
        if not self.settings.email_enabled:
            log.warning("Email not configured (SMTP settings missing); skipping notification.")
            return False

        recipients = [addr.strip() for addr in self.settings.email_to.split(",") if addr.strip()]

        msg = EmailMessage()
        msg["Subject"] = build_subject(result)
        msg["From"] = self.settings.email_from
        msg["To"] = recipients
        msg.set_content(build_body(result))

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(msg)
            log.info("Result email sent to %s via SMTP", self.settings.email_to)
            return True
        except Exception as exc:  # noqa: BLE001 - notification failure must not crash the run
            log.error("Failed to send result email via SMTP: %s", exc)
            return False



def make_notifier(settings: Settings) -> Notifier:
    """Return the notifier matching ``settings.email_provider``."""
    return EmailNotifier(settings)
