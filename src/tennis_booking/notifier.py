from __future__ import annotations

import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
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
        lines += ["", "Screenshot attached."]
    return "\n".join(lines)


class Notifier(Protocol):
    def send(self, result: BookingResult) -> bool: ...


class EmailNotifier:
    """Sends a plain-text result email over SMTP (STARTTLS), with the failure
    screenshot (if any) attached directly rather than uploaded elsewhere."""

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
        msg["To"] = ", ".join(recipients)
        msg.set_content(build_body(result))

        self._attach_screenshot(msg, result.screenshot_path)

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(msg, to_addrs=recipients)
            log.info("Result email sent to %s via SMTP", recipients)
            return True
        except Exception as exc:  # noqa: BLE001 - notification failure must not crash the run
            log.error("Failed to send result email via SMTP: %s", exc)
            return False

    @staticmethod
    def _attach_screenshot(msg: EmailMessage, screenshot_path: str | None) -> None:
        """Attach the screenshot file to the email, if one was produced.

        Best-effort: a missing or unreadable file logs a warning rather than
        failing the whole notification.
        """
        if not screenshot_path:
            return
        path = Path(screenshot_path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            log.warning("Could not read screenshot %s for attachment: %s", screenshot_path, exc)
            return

        mime_type, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime_type or "image/png").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)


def make_notifier(settings: Settings) -> Notifier:
    """Return the notifier matching ``settings.email_provider``."""
    return EmailNotifier(settings)