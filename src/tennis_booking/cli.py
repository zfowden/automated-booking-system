"""Typer CLI: `tennis-book`."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time
from typing import Annotated

import typer
from pydantic import ValidationError

from .config import Settings
from .logging_config import configure_logging, get_logger
from .models import BookingRequest

app = typer.Typer(add_completion=False, help="Automated Clapham Common tennis booking.")
log = get_logger(__name__)


def _parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise typer.BadParameter(f"'{value}' is not a valid HH:MM time") from exc


def _load_settings(headless: bool) -> Settings:
    """Load settings from env/.env, applying the --headless override."""
    try:
        settings = Settings()
    except ValidationError as exc:
        typer.secho(f"Configuration error (check your .env): {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if headless:
        settings.headless = True
    return settings


@app.command()
def book(
    date: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"], help="Booking date YYYY-MM-DD")],
    time_: Annotated[str, typer.Option("--time", help="Start time HH:MM")],
    duration: Annotated[int, typer.Option(help="Duration in minutes (30/60/90/120)")] = 60,
    court: Annotated[str | None, typer.Option(help="Preferred court name")] = None,
    fallback: Annotated[
        list[str] | None,
        typer.Option(help="Fallback start time(s) HH:MM if preferred is taken"),
    ] = None,
    headless: Annotated[
        bool, typer.Option(help="Hide the browser window (default: visible so you can watch)")
    ] = False,
    no_email: Annotated[bool, typer.Option("--no-email", help="Skip the result email")] = False,
) -> None:
    """Book a tennis court on-demand."""
    configure_logging()
    settings = _load_settings(headless)

    fallbacks = [_parse_time(f) for f in (fallback or [])]

    try:
        request = BookingRequest(
            date=date.date() if isinstance(date, datetime) else date,
            start_time=_parse_time(time_),
            duration_minutes=duration,
            court=court,
            fallback_start_times=fallbacks,
        )
    except ValidationError as exc:
        typer.secho(f"Invalid booking request: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    # Import here so unit tests can import the CLI without Playwright installed.
    from .clubspark import ClubSparkBooker
    from .notifier import EmailNotifier

    typer.echo(f"Booking {settings.venue_slug}: {request.date} at {request.start_time:%H:%M} "
               f"for {request.duration_minutes} min...")
    result = ClubSparkBooker(settings).book(request)

    if not no_email:
        EmailNotifier(settings).send(result)

    color = typer.colors.GREEN if result.success else typer.colors.RED
    typer.secho(result.summary(), fg=color)
    raise typer.Exit(code=0 if result.success else 1)


@app.command()
def slots(
    date: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"], help="Day to list YYYY-MM-DD")],
    court: Annotated[str | None, typer.Option(help="Only show this court")] = None,
    headless: Annotated[
        bool, typer.Option(help="Hide the browser window (default: visible so you can watch)")
    ] = False,
) -> None:
    """List all available times for a given day."""
    configure_logging()
    settings = _load_settings(headless)
    day = date.date() if isinstance(date, datetime) else date

    from .clubspark import ClubSparkBooker

    typer.echo(f"Checking availability at {settings.venue_slug} on {day}...")
    available = ClubSparkBooker(settings).list_available_slots(day)

    if court:
        available = [s for s in available if court.lower() in s.court.lower()]

    if not available:
        typer.secho("No available slots found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    typer.secho(f"{len(available)} available slot(s):", fg=typer.colors.GREEN)
    for slot in available:
        line = f"  {slot.start_time:%H:%M}  {slot.court}"
        if slot.price:
            line += f"  ({slot.price})"
        typer.echo(line)


if __name__ == "__main__":
    app()
