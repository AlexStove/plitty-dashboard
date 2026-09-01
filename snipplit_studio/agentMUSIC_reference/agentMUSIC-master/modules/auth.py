"""Machine-to-machine API key auth for the HTTP API.

Two separate credentials exist by design:
  * the machine ``X-API-Key`` (this module) — used by the AF-video-generator
    adapter and any other service-to-service caller;
  * the dashboard/browser access — protected by network policy / reverse-proxy,
    never by the machine key (it must not leak into a browser context).

Posture: fail-closed outside the "local" environment — if no keys are
configured there, every protected route returns 503 instead of silently
serving unauthenticated traffic.
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException

from modules.config import settings

logger = logging.getLogger(__name__)

_warned_fail_open = False


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """FastAPI dependency guarding machine-to-machine routes."""
    global _warned_fail_open

    if not settings.api_keys:
        if settings.environment == "local":
            if not _warned_fail_open:
                logger.warning(
                    "AGENTMUSIC_API_KEYS is not set and APP_ENV=local: "
                    "API auth is DISABLED (fail-open for local dev/tests only)."
                )
                _warned_fail_open = True
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "Machine API key is not configured (AGENTMUSIC_API_KEYS). "
                "The API refuses unauthenticated requests outside the local environment."
            ),
        )

    if not x_api_key or x_api_key not in settings.api_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def log_startup_posture() -> None:
    """Log the effective auth posture once at application startup."""
    if settings.api_keys:
        logger.info("API auth enabled: %d machine key(s) configured", len(settings.api_keys))
    elif settings.environment == "local":
        logger.warning("API auth disabled (local environment, no AGENTMUSIC_API_KEYS)")
    else:
        logger.error(
            "AGENTMUSIC_API_KEYS is empty while APP_ENV=%s: all protected API routes "
            "will return 503 until keys are configured.",
            settings.environment,
        )
