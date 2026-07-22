"""Google Secret Manager integration.

On Cloud Run the job runs as a service account with Application Default
Credentials, so no keys are needed in code. When ``USE_SECRET_MANAGER=true`` we
resolve a set of secrets and inject them into the environment *before*
:class:`~tennis_booking.config.Settings` is constructed, so the existing
pydantic-settings wiring keeps working unchanged.

Secrets are keyed by the same uppercase names as the env vars they populate
(e.g. ``CLUBSPARK_PASSWORD``). Only secrets that actually exist are injected;
missing ones are skipped so partial configs (e.g. no card on a free venue) work.
"""

from __future__ import annotations

import os

from .logging_config import get_logger

log = get_logger(__name__)

#: Env var names resolved from Secret Manager when enabled. Each maps to a
#: Secret Manager secret of the same name (override the mapping if your secret
#: ids differ from the env var names).
SECRET_ENV_NAMES = (
    "CLUBSPARK_USERNAME",
    "CLUBSPARK_PASSWORD",
    "SENDGRID_API_KEY",
    "CARD_NUMBER",
    "CARD_EXPIRY",
    "CARD_CVV",
    "CARD_NAME",
    "CARD_POSTCODE",
)


def access_secret(project: str, secret_id: str, version: str = "latest") -> str:
    """Return the payload of a Secret Manager secret version as a UTF-8 string."""
    # Imported lazily so unit tests and local runs don't require the GCP SDK.
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def load_secrets_into_env(
    project: str,
    names: tuple[str, ...] = SECRET_ENV_NAMES,
    *,
    overwrite: bool = False,
) -> list[str]:
    """Fetch each secret and set it as an env var. Returns the names loaded.

    A secret that doesn't exist (or can't be read) is skipped with a warning so
    an optional secret never breaks startup. Existing env vars are left alone
    unless ``overwrite`` is true.
    """
    if not project:
        raise ValueError("gcp_project must be set when use_secret_manager is enabled")

    loaded: list[str] = []
    for name in names:
        if not overwrite and os.environ.get(name):
            continue
        try:
            os.environ[name] = access_secret(project, name)
            loaded.append(name)
        except Exception as exc:  # noqa: BLE001 - optional secrets may be absent
            log.warning("Secret %r not loaded from Secret Manager: %s", name, exc)
    log.info("Loaded %d secret(s) from Secret Manager", len(loaded))
    return loaded
