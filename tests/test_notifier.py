import sys
import types
from datetime import date, time, timedelta

from tennis_booking.config import Settings
from tennis_booking.models import BookingRequest, BookingResult, Slot
from tennis_booking.notifier import (
    EmailNotifier,
    SendGridNotifier,
    build_body,
    make_notifier,
)


def _result() -> BookingResult:
    req = BookingRequest(date=date.today() + timedelta(days=2), start_time=time(18, 0))
    slot = Slot(court="Court 1", start_time=time(18, 0), end_time=time(19, 0), price="£12.50")
    return BookingResult(success=True, request=req, slot=slot, confirmation="OK123")


def _settings(**over) -> Settings:
    base = dict(clubspark_username="u", clubspark_password="p")
    base.update(over)
    return Settings(_env_file=None, **base)


def test_build_body_contains_key_fields():
    body = build_body(_result())
    assert "Court 1" in body
    assert "18:00-19:00" in body
    assert "OK123" in body


def test_make_notifier_picks_provider():
    assert isinstance(make_notifier(_settings(email_provider="smtp")), EmailNotifier)
    assert isinstance(make_notifier(_settings(email_provider="sendgrid")), SendGridNotifier)


def test_sendgrid_skips_when_unconfigured():
    # No api key / from / to -> not enabled -> returns False without calling SDK.
    assert SendGridNotifier(_settings(email_provider="sendgrid")).send(_result()) is False


def _install_fake_sendgrid(monkeypatch, status_code=202, capture=None):
    fake_pkg = types.ModuleType("sendgrid")
    fake_helpers = types.ModuleType("sendgrid.helpers")
    fake_mail = types.ModuleType("sendgrid.helpers.mail")

    class Mail:
        def __init__(self, from_email, to_emails, subject, plain_text_content):
            if capture is not None:
                capture.update(
                    from_email=from_email, to_emails=to_emails,
                    subject=subject, body=plain_text_content,
                )

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    class SendGridAPIClient:
        def __init__(self, key):
            if capture is not None:
                capture["key"] = key

        def send(self, message):
            return _Resp(status_code)

    fake_pkg.SendGridAPIClient = SendGridAPIClient
    fake_mail.Mail = Mail
    fake_helpers.mail = fake_mail
    monkeypatch.setitem(sys.modules, "sendgrid", fake_pkg)
    monkeypatch.setitem(sys.modules, "sendgrid.helpers", fake_helpers)
    monkeypatch.setitem(sys.modules, "sendgrid.helpers.mail", fake_mail)


def test_sendgrid_sends(monkeypatch):
    capture = {}
    _install_fake_sendgrid(monkeypatch, status_code=202, capture=capture)
    s = _settings(
        email_provider="sendgrid", sendgrid_api_key="SG.key",
        email_from="a@example.com", email_to="b@example.com",
    )
    assert SendGridNotifier(s).send(_result()) is True
    assert capture["key"] == "SG.key"
    assert capture["to_emails"] == "b@example.com"
    assert "SUCCESS" in capture["subject"]


def test_sendgrid_non_2xx_is_failure(monkeypatch):
    _install_fake_sendgrid(monkeypatch, status_code=500)
    s = _settings(
        email_provider="sendgrid", sendgrid_api_key="SG.key",
        email_from="a@example.com", email_to="b@example.com",
    )
    assert SendGridNotifier(s).send(_result()) is False
