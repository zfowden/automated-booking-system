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

        msg = EmailMessage()
        msg["Subject"] = build_subject(result)
        msg["From"] = self.settings.email_from
        msg["To"] = self.settings.email_to
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


class SendGridNotifier:
    """Sends a plain-text result email via the SendGrid HTTPS API (port 443).

    Preferred on Cloud Run, where outbound SMTP is unreliable/blocked.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, result: BookingResult) -> bool:
        if not self.settings.email_enabled:
            log.warning("Email not configured (SendGrid API key missing); skipping notification.")
            return False

        # Imported lazily so local runs / tests need not install the SDK.
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=self.settings.email_from,
            to_emails=self.settings.email_to,
            subject=build_subject(result),
            plain_text_content=build_body(result),
        )
        try:
            client = SendGridAPIClient(self.settings.sendgrid_api_key)
            response = client.send(message)
            if 200 <= response.status_code < 300:
                log.info("Result email sent to %s via SendGrid (%s)",
                         self.settings.email_to, response.status_code)
                return True
            log.error("SendGrid returned status %s", response.status_code)
            return False
        except Exception as exc:  # noqa: BLE001 - notification failure must not crash the run
            log.error("Failed to send result email via SendGrid: %s", exc)
            return False


def make_notifier(settings: Settings) -> Notifier:
    """Return the notifier matching ``settings.email_provider``."""
    if settings.email_provider is EmailProvider.SENDGRID:
        return SendGridNotifier(settings)
    return EmailNotifier(settings)
