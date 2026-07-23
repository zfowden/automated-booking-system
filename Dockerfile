# Playwright's official Python image bundles Chromium + all system libraries.
# The tag MUST match the `playwright` pip version pinned in uv.lock (1.61.0).
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

# Fail fast, no .pyc, unbuffered logs (so Cloud Run captures them live).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    # Cloud-appropriate runtime defaults (override via env / Secret Manager).
    LOGIN_METHOD=lta \
    VENUE_SLUG=ClaphamCommon \
    BASE_URL=https://clubspark.lta.org.uk \
    HEADLESS=true \
    USE_CHROME=false \
    SLOW_MO_MS=10 \
    KEEP_OPEN_ON_ERROR=false \
    EMAIL_PROVIDER=smtp \
    USE_SECRET_MANAGER=true \
    GCP_PROJECT=automated-booker \
    EMAIL_FROM=zack.notifications@gmail.com \
    EMAIL_TO=zack.fowden@gmail.com,valeriarodriguezm.18@gmail.com \
    SMTP_HOST=smtp.gmail.com \
    SMTP_PORT=587 \
    SMTP_USERNAME=zack.notifications@gmail.com \
    BOOK_DAYS_AHEAD=7
    BOOK_TIME=18:00
    BOOK_DURATION=60
    BOOK_COURT=4
    BOOK_FALLBACKS=19:00,20:00
    # Screenshots must go somewhere writable on the ephemeral container FS.
    SCREENSHOT_DIR=/tmp/screenshots

WORKDIR /app

# Install uv (fast, reproducible installs from uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (better layer caching), then the app.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# The image already ships browsers; ensure the pinned Chromium is present.
RUN uv run playwright install chromium

# Cloud Run Jobs run this to completion and then exit.
ENTRYPOINT ["uv", "run", "tennis-book-job"]
