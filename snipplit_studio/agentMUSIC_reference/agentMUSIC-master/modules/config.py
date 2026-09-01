"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(override=False)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "agentmusic"
    environment: str = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "local"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    output_dir: str = os.getenv("OUTPUT_DIR", "output")
    owner_id: int = int(os.getenv("AGENTMUSIC_OWNER_ID", "694509855"))
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))
    api_cors_origins: tuple[str, ...] = tuple(_csv_env("API_CORS_ORIGINS", "*"))
    debug: bool = _bool_env("DEBUG", False)
    # Machine-to-machine API keys (CSV). Empty outside "local" env -> API refuses
    # mutating requests (fail-closed); empty in "local" -> fail-open for dev/tests.
    api_keys: tuple[str, ...] = tuple(_csv_env("AGENTMUSIC_API_KEYS"))
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    pixabay_api_key: str = os.getenv("PIXABAY_API_KEY", "")
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
    spotify_client_id: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    spotify_client_secret: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    yt_dlp_upgrade_url: str = os.getenv(
        "YT_DLP_UPGRADE_URL",
        "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz",
    )

    # Track download: Deezer (streamrip) + hardened yt-dlp
    deezer_arl: str = os.getenv("DEEZER_ARL", "")
    ytm_cookie_file: str = os.getenv("YTM_COOKIE_FILE", "")
    min_track_seconds: float = float(os.getenv("MIN_TRACK_SECONDS", "60"))

    minio_url: str = os.getenv("MINIO_URL", "")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "atome-videos")
    minio_tracks_bucket: str = os.getenv("MINIO_TRACKS_BUCKET", "music-tracks")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", ""))
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", ""))
    minio_tls_verify: bool = _bool_env("MINIO_TLS_VERIFY", True)

    @property
    def minio_configured(self) -> bool:
        return bool(self.minio_url and self.minio_access_key and self.minio_secret_key)


settings = Settings()
