from datetime import date, time, timedelta

from typer.testing import CliRunner

from tennis_booking.cli import app
from tennis_booking.models import BookingRequest, BookingResult, Slot

runner = CliRunner()


def _soon_str() -> str:
    return (date.today() + timedelta(days=2)).isoformat()


def _creds(monkeypatch):
    monkeypatch.setenv("CLUBSPARK_USERNAME", "user@example.com")
    monkeypatch.setenv("CLUBSPARK_PASSWORD", "secret")


def _success_result() -> BookingResult:
    req = BookingRequest(date=date.today() + timedelta(days=2), start_time=time(18, 0))
    slot = Slot(court="Court 1", start_time=time(18, 0), end_time=time(19, 0))
    return BookingResult(success=True, request=req, slot=slot, confirmation="OK123")


def test_book_success_wires_request_and_skips_email(monkeypatch):
    _creds(monkeypatch)
    captured = {}

    class FakeBooker:
        def __init__(self, settings):
            captured["settings"] = settings

        def book(self, request):
            captured["request"] = request
            return _success_result()

    sent = {"called": False}

    class FakeNotifier:
        def __init__(self, settings):
            pass

        def send(self, result):
            sent["called"] = True
            return True

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)
    monkeypatch.setattr("tennis_booking.notifier.make_notifier", lambda s: FakeNotifier(s))

    result = runner.invoke(
        app,
        ["book", "--date", _soon_str(), "--time", "18:00", "--duration", "60", "--no-email"],
    )
    assert result.exit_code == 0, result.output
    assert captured["request"].start_time == time(18, 0)
    assert captured["request"].duration_minutes == 60
    assert sent["called"] is False


def test_book_failure_exit_code_and_email(monkeypatch):
    _creds(monkeypatch)

    class FakeBooker:
        def __init__(self, settings):
            pass

        def book(self, request):
            return BookingResult(success=False, request=request, error="no slot")

    sent = {"called": False}

    class FakeNotifier:
        def __init__(self, settings):
            pass

        def send(self, result):
            sent["called"] = True
            return True

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)
    monkeypatch.setattr("tennis_booking.notifier.make_notifier", lambda s: FakeNotifier(s))

    result = runner.invoke(app, ["book", "--date", _soon_str(), "--time", "18:00"])
    assert result.exit_code == 1
    assert sent["called"] is True


def test_book_rejects_bad_date(monkeypatch):
    _creds(monkeypatch)
    past = (date.today() - timedelta(days=1)).isoformat()
    result = runner.invoke(app, ["book", "--date", past, "--time", "18:00", "--no-email"])
    assert result.exit_code == 2


def test_slots_lists_available_times(monkeypatch):
    _creds(monkeypatch)

    class FakeBooker:
        def __init__(self, settings):
            pass

        def list_available_slots(self, day):
            return [
                Slot(court="Court 1", start_time=time(18, 0)),
                Slot(court="Court 2", start_time=time(18, 30), price="Free"),
            ]

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)

    result = runner.invoke(app, ["slots", "--date", _soon_str()])
    assert result.exit_code == 0, result.output
    assert "18:00" in result.output
    assert "Court 2" in result.output


def test_slots_court_filter_and_empty(monkeypatch):
    _creds(monkeypatch)

    class FakeBooker:
        def __init__(self, settings):
            pass

        def list_available_slots(self, day):
            return [Slot(court="Court 1", start_time=time(18, 0))]

    monkeypatch.setattr("tennis_booking.clubspark.ClubSparkBooker", FakeBooker)

    # Filter that matches nothing -> exit code 1
    result = runner.invoke(app, ["slots", "--date", _soon_str(), "--court", "Court 9"])
    assert result.exit_code == 1
