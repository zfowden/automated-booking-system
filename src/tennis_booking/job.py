"""Scheduled booking entrypoint for Cloud Run Jobs.

Run on a timer (Cloud Scheduler → Cloud Run Job). Reads the target booking from
environment variables, pulls secrets from Secret Manager when enabled, attempts
the booking, emails the result, and exits 0 on success / 1 on failure so the
Cloud Run Job reflects the outcome.

Booking-target env vars:
    BOOK_DAYS_AHEAD   int, default 7  -- book this many days from today (London).
    BOOK_DATE         optional YYYY-MM-DD; overrides BOOK_DAYS_AHEAD if set.
    BOOK_TIME         HH:MM, required  -- preferred start time.
    BOOK_DURATION     int minutes, default 60.
    BOOK_COURT        optional preferred court name.
    BOOK_FALLBACKS    optional comma-separated HH:MM fallback start times.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta

from .logging_config import configure_logging, get_logger
from .models import BookingRequest, london_today

log = get_logger(__name__)


def _parse_time(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def _build_request() -> BookingRequest:
    """Build the BookingRequest from environment variables."""
    date_env = os.environ.get("BOOK_DATE", "").strip()
    if date_env:
        target_date = datetime.strptime(date_env, "%Y-%m-%d").date()
    else:
        days_ahead = int(os.environ.get("BOOK_DAYS_AHEAD", "7"))
        target_date = london_today() + timedelta(days=days_ahead)

    time_env = os.environ.get("BOOK_TIME", "").strip()
    if not time_env:
        raise ValueError("BOOK_TIME (HH:MM) is required")

    fallbacks = [
        _parse_time(t) for t in os.environ.get("BOOK_FALLBACKS", "").split(",") if t.strip()
    ]

    return BookingRequest(
        date=target_date,
        start_time=_parse_time(time_env),
        duration_minutes=int(os.environ.get("BOOK_DURATION", "60")),
        court=os.environ.get("BOOK_COURT") or None,
        fallback_start_times=fallbacks,
    )


def run() -> int:
    """Do the scheduled booking. Returns a process exit code (0 ok, 1 fail)."""
    configure_logging()

    # Pull secrets into the environment before Settings() reads them.
    from .config import Settings

    project = os.environ.get("GCP_PROJECT", "")
    if os.environ.get("USE_SECRET_MANAGER", "").lower() in ("1", "true", "yes"):
        from .secrets import load_secrets_into_env

        load_secrets_into_env(project)

    try:
        settings = Settings()
        request = _build_request()
    except Exception as exc:  # noqa: BLE001 - config/target errors should exit non-zero
        log.error("Configuration/target error: %s", exc)
        return 1

    # Imported here so config/target errors above don't require Playwright.
    from .clubspark import ClubSparkBooker
    from .notifier import make_notifier

    log.info(
        "Scheduled booking: %s at %s for %d min (court=%s, confirm_payment=%s)",
        request.date, f"{request.start_time:%H:%M}", request.duration_minutes,
        request.court or "any", settings.confirm_payment,
    )

    result = ClubSparkBooker(settings).book(request)
    make_notifier(settings).send(result)

    log.info("Result: %s", result.summary())
    return 0 if result.success else 1


def main() -> None:
    """Console-script entrypoint: run and exit with the proper code."""
    sys.exit(run())


if __name__ == "__main__":
    main()
