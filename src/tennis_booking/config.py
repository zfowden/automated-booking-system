"""Environment-backed configuration."""

from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoginMethod(str, Enum):
    """How to authenticate against ClubSpark."""

    CLUBSPARK = "clubspark"  # email/password form
    LTA = "lta"  # "Log in with the LTA" button


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- ClubSpark / LTA login ---
    # NB: for the LTA method these are your LTA username (not necessarily an
    # email) and LTA password.
    clubspark_username: str = Field(..., min_length=1)
    clubspark_password: str = Field(..., min_length=1)
    login_method: LoginMethod = LoginMethod.LTA

    # --- Venue ---
    venue_slug: str = "ClaphamCommon"
    base_url: str = "https://clubspark.lta.org.uk"

    # --- Browser ---
    # Default to a visible window so you can follow along. Set HEADLESS=true to hide it.
    headless: bool = False
    # Use your installed Google Chrome rather than Playwright's bundled Chromium.
    use_chrome: bool = True
    # Milliseconds to pause between each Playwright action so steps are followable.
    slow_mo_ms: int = 400
    slot_timeout_seconds: int = 30
    storage_state_path: str = "storage_state.json"
    # On error, keep the (visible) browser window open so you can inspect the
    # failure. Waits up to keep_open_seconds, or until you press Enter. Only
    # applies when headless is False.
    keep_open_on_error: bool = True
    keep_open_seconds: int = 300

    # --- Email (optional) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    @property
    def booking_url(self) -> str:
        """Base ClubSpark booking-by-date URL for the configured venue."""
        return f"{self.base_url.rstrip('/')}/{self.venue_slug}/Booking/BookByDate"

    @property
    def email_enabled(self) -> bool:
        """Whether enough SMTP settings are present to send email."""
        return bool(self.smtp_host and self.email_from and self.email_to)
