# Tennis Booking Tool — Clapham Common

Automated on-demand tennis court booking for **Clapham Common**, which is managed on
**ClubSpark (LTA)** at <https://clubspark.lta.org.uk/ClaphamCommon>.

The booking grid is a JavaScript app behind a login, so the tool drives a real browser with
[Playwright](https://playwright.dev/python/): it logs in, finds your requested slot, books
it, and emails you the result.

> Personal-use automation. Courts open **7 days in advance**, **max 2 hours/day**. Please
> respect the ClubSpark/LTA terms of service.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync                              # create .venv and install dependencies
uv run playwright install chromium   # download the browser
cp .env.example .env                 # then edit .env with your credentials
```

> First run: the visible window lets you complete login once so the session is captured to
> `storage_state.json`; later runs reuse it and skip login.

## Usage

By default a **Google Chrome window opens** so you can watch each step (login, slot
selection, confirmation) as it happens.

### List available times for a day

```bash
# Show every free slot on a given day (Chrome window opens automatically)
uv run tennis-book slots --date 2026-07-20

# Only a specific court
uv run tennis-book slots --date 2026-07-20 --court "Court 1"
```

Exits non-zero if there are no available slots (matching the filter).

### Book a court

```bash
# Book 6pm for 60 minutes on a given date (Chrome window opens automatically)
uv run tennis-book book --date 2026-07-20 --time 18:00 --duration 60

# Run hidden (no window) and skip the result email
uv run tennis-book book --date 2026-07-20 --time 18:00 --headless --no-email

# Prefer a specific court, with fallback start times if 18:00 is taken
uv run tennis-book book --date 2026-07-20 --time 18:00 \
    --court "Court 1" --fallback 18:30 --fallback 19:00
```

Options for `book`:

| Option | Description |
| --- | --- |
| `--date` | Booking date `YYYY-MM-DD` (today .. +7 days) |
| `--time` | Start time `HH:MM` |
| `--duration` | Minutes: 30/60/90/120 (default 60) |
| `--court` | Preferred court name (optional; any available otherwise) |
| `--fallback` | Fallback start time(s), repeatable |
| `--headless` | Hide the browser window (default: visible so you can watch) |
| `--no-email` | Do not send the result email |

The `book` command exits non-zero if the booking fails, so it works from Task Scheduler / cron.

## Configuration

All configuration is via `.env` (see `.env.example`). Secrets are never committed.
After the first successful login, the browser session is cached in `storage_state.json`
so subsequent runs skip the login step until it expires.

If something goes wrong during a visible run, the Chrome window is **left open so you can
inspect the failure** — press Enter in the terminal to close it (or it auto-closes after
`KEEP_OPEN_SECONDS`, default 300). Set `KEEP_OPEN_ON_ERROR=false` to disable, and note this
only applies when not running `--headless`. A screenshot is also saved to `screenshots/`.

## Development

```bash
uv run pytest          # unit tests (no network)
```

## Project layout

```
src/tennis_booking/
  config.py       # env-backed settings (pydantic-settings)
  models.py       # BookingRequest / Slot / BookingResult
  clubspark.py    # Playwright login + booking flow
  notifier.py     # email results
  logging_config.py
  cli.py          # Typer CLI (`tennis-book`)
```
