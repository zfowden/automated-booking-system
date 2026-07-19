"""Email notification of booking results."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings
from .logging_config import get_logger
from .models import BookingResult

log = get_logger(__name__)


class EmailNotifier:
    """Sends a plain-text email describing a booking result."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, result: BookingResult) -> bool:
        """Send the result email. Returns True if sent, False if skipped/failed."""
        if not self.settings.email_enabled:
            log.warning("Email not configured (SMTP settings missing); skipping notification.")
            return False

        msg = EmailMessage()
        status = "SUCCESS" if result.success else "FAILED"
        msg["Subject"] = f"[Tennis Booking] {status}: {result.request.date}"
        msg["From"] = self.settings.email_from
        msg["To"] = self.settings.email_to
        msg.set_content(self._body(result))

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(msg)
            log.info("Result email sent to %s", self.settings.email_to)
            return True
        except Exception as exc:  # noqa: BLE001 - notification failure must not crash the run
            log.error("Failed to send result email: %s", exc)
            return False

    @staticmethod
    def _body(result: BookingResult) -> str:
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
                f"  Time:  {result.slot.start_time:%H:%M}-{result.slot.end_time:%H:%M}",
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
