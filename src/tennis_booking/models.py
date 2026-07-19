"""Domain models for booking requests and results."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator

#: ClubSpark allows durations in 30-minute increments up to 2 hours.
ALLOWED_DURATIONS = (30, 60, 90, 120)

#: Courts open this many days in advance.
BOOKING_WINDOW_DAYS = 7


class BookingRequest(BaseModel):
    """A user's desired booking."""

    date: date_cls
    start_time: time
    duration_minutes: int = 60
    court: str | None = None
    fallback_start_times: list[time] = Field(default_factory=list)

    @field_validator("duration_minutes")
    @classmethod
    def _valid_duration(cls, v: int) -> int:
        if v not in ALLOWED_DURATIONS:
            raise ValueError(
                f"duration_minutes must be one of {ALLOWED_DURATIONS}, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _valid_date_window(self) -> BookingRequest:
        today = datetime.now().date()
        if self.date < today:
            raise ValueError(f"date {self.date} is in the past")
        latest = today + timedelta(days=BOOKING_WINDOW_DAYS)
        if self.date > latest:
            raise ValueError(
                f"date {self.date} is beyond the {BOOKING_WINDOW_DAYS}-day "
                f"booking window (latest bookable: {latest})"
            )
        return self

    @property
    def candidate_start_times(self) -> list[time]:
        """Preferred start time followed by any fallbacks, de-duplicated in order."""
        ordered = [self.start_time, *self.fallback_start_times]
        seen: set[time] = set()
        result: list[time] = []
        for t in ordered:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result


class Slot(BaseModel):
    """An available slot found on the booking grid."""

    court: str
    start_time: time
    #: End time; unknown when merely listing availability (duration not yet chosen).
    end_time: time | None = None
    price: str | None = None
    #: Playwright selector used to click into this slot.
    selector: str | None = None

    def label(self) -> str:
        """Short human-readable label, e.g. 'Court 1 18:00-19:00' or 'Court 1 18:00'."""
        if self.end_time:
            return f"{self.court} {self.start_time:%H:%M}-{self.end_time:%H:%M}"
        return f"{self.court} {self.start_time:%H:%M}"


class BookingResult(BaseModel):
    """Outcome of an attempted booking."""

    success: bool
    request: BookingRequest
    slot: Slot | None = None
    confirmation: str | None = None
    error: str | None = None
    screenshot_path: str | None = None

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.success and self.slot:
            return (
                f"Booked {self.slot.label()} on {self.request.date}"
                + (f" (ref: {self.confirmation})" if self.confirmation else "")
            )
        return f"Booking failed: {self.error or 'unknown error'}"
