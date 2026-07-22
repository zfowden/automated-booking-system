from datetime import time, timedelta

from tennis_booking import job
from tennis_booking.models import BookingRequest, BookingResult, Slot, london_today


def _creds(monkeypatch):
    monkeypatch.setenv("CLUBSPARK_USERNAME", "u")
    monkeypatch.setenv("CLUBSPARK_PASSWORD", "p")
    monkeypatch.setenv("USE_SECRET_MANAGER", "false")


def test_build_request_days_ahead(monkeypatch):
    monkeypatch.delenv("BOOK_DATE", raising=False)
    monkeypatch.setenv("BOOK_DAYS_AHEAD", "7")
    monkeypatch.setenv("BOOK_TIME", "18:00")
    monkeypatch.setenv("BOOK_DURATION", "90")
    monkeypatch.setenv("BOOK_FALLBACKS", "18:30, 19:00")
    req = job._build_request()
    assert req.date == london_today() + timedelta(days=7)
    assert req.start_time == time(18, 0)
    assert req.duration_minutes == 90
    assert req.fallback_start_times == [time(18, 30), time(19, 0)]


def test_build_request_requires_time(monkeypatch):
    monkeypatch.delenv("BOOK_TIME", raising=False)
    monkeypatch.delenv("BOOK_DATE", raising=False)
    import pytest
    with pytest.raises(ValueError):
        job._build_request()


def test_run_success(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setenv("BOOK_TIME", "18:00")

    req = BookingRequest(date=london_today() + timedelta(days=7), start_time=time(18, 0))
    slot = Slot(court="Court 1", start_time=time(18, 0), end_time=time(19, 0))
    good = BookingResult(success=True, request=req, slot=slot, confirmation="OK")

    sent = {"n": 0}

    class FakeBooker:
        def __init__(self, settings):
            pass

        def book(self, request):
            return good

    class FakeNotifier:
        def send(self, result):
            sent["n"] += 1
            return True

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)
    monkeypatch.setattr("tennis_booking.notifier.make_notifier", lambda s: FakeNotifier())

    assert job.run() == 0
    assert sent["n"] == 1


def test_run_failure_exit_code(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setenv("BOOK_TIME", "18:00")

    class FakeBooker:
        def __init__(self, settings):
            pass

        def book(self, request):
            return BookingResult(success=False, request=request, error="no slot")

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)
    monkeypatch.setattr("tennis_booking.notifier.make_notifier",
                        lambda s: type("N", (), {"send": lambda self, r: True})())

    assert job.run() == 1


def test_run_bad_target_returns_1(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.delenv("BOOK_TIME", raising=False)  # missing required target
    assert job.run() == 1
