from datetime import date, time, timedelta

import pytest
from pydantic import ValidationError

from tennis_booking.models import (
    BOOKING_WINDOW_DAYS,
    BookingRequest,
    BookingResult,
    Slot,
    london_today,
)


def _soon() -> date:
    return london_today() + timedelta(days=2)


def test_valid_request():
    req = BookingRequest(date=_soon(), start_time=time(18, 0), duration_minutes=60)
    assert req.duration_minutes == 60
    assert req.candidate_start_times == [time(18, 0)]


def test_rejects_past_date():
    with pytest.raises(ValidationError):
        BookingRequest(date=london_today() - timedelta(days=1), start_time=time(18, 0))


def test_rejects_beyond_window():
    with pytest.raises(ValidationError):
        BookingRequest(
            date=london_today() + timedelta(days=BOOKING_WINDOW_DAYS + 1),
            start_time=time(18, 0),
        )


def test_accepts_window_edges():
    # today and exactly the last bookable day are both valid.
    BookingRequest(date=london_today(), start_time=time(18, 0))
    BookingRequest(
        date=london_today() + timedelta(days=BOOKING_WINDOW_DAYS),
        start_time=time(18, 0),
    )


def test_rejects_bad_duration():
    with pytest.raises(ValidationError):
        BookingRequest(date=_soon(), start_time=time(18, 0), duration_minutes=45)


def test_candidate_times_dedup_and_order():
    req = BookingRequest(
        date=_soon(),
        start_time=time(18, 0),
        fallback_start_times=[time(18, 30), time(18, 0), time(19, 0)],
    )
    assert req.candidate_start_times == [time(18, 0), time(18, 30), time(19, 0)]


def test_result_summary_success():
    req = BookingRequest(date=_soon(), start_time=time(18, 0))
    slot = Slot(court="Court 1", start_time=time(18, 0), end_time=time(19, 0))
    res = BookingResult(success=True, request=req, slot=slot, confirmation="ABC123")
    s = res.summary()
    assert "Court 1" in s and "18:00-19:00" in s and "ABC123" in s


def test_result_summary_failure():
    req = BookingRequest(date=_soon(), start_time=time(18, 0))
    res = BookingResult(success=False, request=req, error="no slot")
    assert "failed" in res.summary().lower()
