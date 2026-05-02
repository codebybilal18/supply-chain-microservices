"""
Google Secret Manager integration.

In production (Cloud Run), sensitive values like DB passwords are stored in
Secret Manager rather than plain environment variables.  This module provides
a simple helper that:

  1. Detects whether Secret Manager should be used (GOOGLE_CLOUD_PROJECT is set
     and DISABLE_SECRET_MANAGER is not set).
  2. Fetches the secret value once and caches it (no repeated API calls per
     request).
  3. Falls back gracefully to the provided `default` when running locally
     (DISABLE_SECRET_MANAGER=true or Secret Manager is unreachable).

Usage in service config:

    from shared.gcp.secrets import get_secret

    class Settings(BaseSettings):
        DB_PASSWORD: str = ""

        @model_validator(mode="after")
        def load_from_secret_manager(self):
            if not self.DB_PASSWORD:
                self.DB_PASSWORD = get_secret(
                    "scf-inventory-db-password",
                    default=self.DB_PASSWORD,
                )
            return self

Design:
  - Best-effort: if Secret Manager is unreachable (network, IAM), the default
    value is returned and a WARNING is logged.
  - Thread-safe in-process cache: lru_cache keyed by (secret_id, version).
  - Secret version defaults to "latest" — pin to a specific version in prod
    for deterministic deployments.
"""

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

_DISABLE = os.getenv("DISABLE_SECRET_MANAGER", "").lower() in ("1", "true", "yes")


@lru_cache(maxsize=64)
def get_secret(secret_id: str, version: str = "latest", default: str = "") -> str:
    """
    Fetch a secret value from Google Secret Manager.

    Args:
        secret_id:  The secret's resource name (short form, e.g. "scf-db-password")
                    or full form ("projects/.../secrets/.../versions/...").
        version:    Secret version to fetch.  Defaults to "latest".
        default:    Value to return if Secret Manager is disabled or unreachable.

    Returns:
        The secret payload as a string, or `default` on any error.
    """
    if _DISABLE:
        return default

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID", "")
    if not project_id:
        return default

    # Build full resource name if a short ID was supplied
    if not secret_id.startswith("projects/"):
        secret_id = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_id})
        value = response.payload.data.decode("utf-8").strip()
        logger.debug("Loaded secret %s", secret_id)
        return value
    except Exception as exc:
        logger.warning(
            "Secret Manager unavailable for %s, using default: %s", secret_id, exc
        )
        return default
