import pytest
from pydantic import ValidationError

from tennis_booking.config import LoginMethod, Settings


def _base_env(monkeypatch):
    monkeypatch.setenv("CLUBSPARK_USERNAME", "user@example.com")
    monkeypatch.setenv("CLUBSPARK_PASSWORD", "secret")


def test_defaults(monkeypatch):
    _base_env(monkeypatch)
    s = Settings(_env_file=None)
    assert s.venue_slug == "ClaphamCommon"
    assert s.login_method is LoginMethod.LTA
    assert s.headless is False  # visible by default so the run can be watched
    assert s.use_chrome is True
    assert s.booking_url == "https://clubspark.lta.org.uk/ClaphamCommon/Booking/BookByDate"


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("CLUBSPARK_USERNAME", raising=False)
    monkeypatch.delenv("CLUBSPARK_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_email_enabled_flag(monkeypatch):
    _base_env(monkeypatch)
    assert Settings(_env_file=None).email_enabled is False

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "a@example.com")
    monkeypatch.setenv("EMAIL_TO", "b@example.com")
    assert Settings(_env_file=None).email_enabled is True


def test_booking_url_respects_slug_and_base(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("VENUE_SLUG", "SomeCourt")
    monkeypatch.setenv("BASE_URL", "https://example.org/")
    s = Settings(_env_file=None)
    assert s.booking_url == "https://example.org/SomeCourt/Booking/BookByDate"
