"""Environment-backed configuration."""

from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoginMethod(str, Enum):
    """How to authenticate against ClubSpark."""

    CLUBSPARK = "clubspark"  # email/password form
    LTA = "lta"  # "Log in with the LTA" button


class EmailProvider(str, Enum):
    """How confirmation emails are sent."""

    SMTP = "smtp"  # raw SMTP (local dev; discouraged on Cloud Run)
    SENDGRID = "sendgrid"  # SendGrid HTTPS API (recommended on GCP)


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

    # --- Email ---
    email_provider: EmailProvider = EmailProvider.SMTP
    email_from: str = ""
    email_to: str = ""
    # SMTP (local dev)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # SendGrid (cloud)
    sendgrid_api_key: str = ""

    # --- Payment ---
    # Card details for paid checkout. On cloud these come from Secret Manager;
    # locally from .env. See the payment caveats in the deploy runbook.
    card_number: str = ""
    card_expiry: str = ""  # MM/YY
    card_cvv: str = ""
    card_name: str = ""
    card_postcode: str = ""
    # HARD SAFETY GATE: real bookings cost money. The card is only submitted when
    # this is explicitly true. Left false, the flow fills the form but stops
    # before paying (dry run) and reports it did not complete payment.
    confirm_payment: bool = False

    # --- Google Cloud ---
    # When true, secrets are pulled from Secret Manager before Settings loads
    # (see secrets.py). Off for local dev.
    use_secret_manager: bool = False
    gcp_project: str = ""

    @property
    def booking_url(self) -> str:
        """Base ClubSpark booking-by-date URL for the configured venue."""
        return f"{self.base_url.rstrip('/')}/{self.venue_slug}/Booking/BookByDate"

    @property
    def email_enabled(self) -> bool:
        """Whether enough settings are present to send email via the chosen provider."""
        if not (self.email_from and self.email_to):
            return False
        if self.email_provider is EmailProvider.SENDGRID:
            return bool(self.sendgrid_api_key)
        return bool(self.smtp_host)

    @property
    def has_card_details(self) -> bool:
        """Whether card fields are populated enough to attempt payment."""
        return bool(self.card_number and self.card_expiry and self.card_cvv)
