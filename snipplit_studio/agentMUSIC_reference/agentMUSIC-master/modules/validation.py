"""Validation primitives for API-facing commands."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

try:
    from pydantic import field_validator

    def before_validator(field_name: str):
        return field_validator(field_name, mode="before")

except ImportError:
    from pydantic import validator

    def before_validator(field_name: str):
        return validator(field_name, pre=True)




Scenario = Literal["karaoke", "slideshow", "track_promo", "cover_alive", "pov_spotify"]
BgType = Literal["footage", "animated"]
Orientation = Literal["portrait", "landscape"]
DownloadSource = Literal["auto", "deezer", "youtube"]


class MinioImportRequest(BaseModel):
    key: str = Field(min_length=1, max_length=1024)


class MinioBatchImportRequest(BaseModel):
    keys: list[str]

    @before_validator("keys")
    def keys_must_be_non_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("At least one key is required")
        if len(cleaned) > 50:
            raise ValueError("No more than 50 keys are allowed")
        return cleaned


class SpotifyImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    source: DownloadSource = "auto"

    @before_validator("url")
    def spotify_url_only(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("https://open.spotify.com/", "http://open.spotify.com/")):
            raise ValueError("Spotify URL is required")
        return value


class GenerateRequest(BaseModel):
    chorus_id: str | None = Field(default=None, max_length=128)
    scenario: Scenario = "karaoke"
    bg_type: BgType = "footage"
    orientation: Orientation = "portrait"
    videos_per_account: int = Field(default=1, ge=1, le=10)
    topic: str | None = Field(default=None, max_length=4096)


class SubmitVideoRequest(BaseModel):
    """One-shot generation order from the AF platform adapter.

    Contract: one asset per command. Exactly one track source must be given;
    ``count`` other than 1 is rejected — batching lives on legacy /api/generate,
    the platform sends N commands for N videos.
    """

    minio_key: str | None = Field(default=None, min_length=1, max_length=1024)
    spotify_url: str | None = Field(default=None, min_length=1, max_length=2048)
    track_id: str | None = Field(default=None, min_length=1, max_length=128)
    prompt: str | None = Field(default=None, min_length=1, max_length=512)

    command_id: str = Field(min_length=1, max_length=128)
    scenario: Scenario = "karaoke"
    bg_type: BgType = "animated"
    aspect: Orientation = "portrait"
    count: int = Field(default=1)

    # Platform passthrough (informational, echoed back in job metadata)
    project: str | None = Field(default=None, max_length=64)
    content_type: str | None = Field(default=None, max_length=32)
    allowed_platforms: list[str] | None = None
    lang: str | None = Field(default=None, max_length=16)

    @before_validator("spotify_url")
    def submit_spotify_url_only(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value.startswith(("https://open.spotify.com/", "http://open.spotify.com/")):
            raise ValueError("Spotify URL is required")
        return value

    @model_validator(mode="after")
    def check_contract(self) -> "SubmitVideoRequest":
        sources = [
            name
            for name in ("minio_key", "spotify_url", "track_id", "prompt")
            if getattr(self, name)
        ]
        if len(sources) != 1:
            raise ValueError(
                "Exactly one track source is required: minio_key | spotify_url | track_id | prompt"
            )
        if self.count != 1:
            raise ValueError(
                "One asset per command: count must be 1 "
                "(use legacy POST /api/generate videos_per_account for batching)"
            )
        return self

    @property
    def source(self) -> tuple[str, str]:
        """Return (kind, value) of the single track source."""
        for name in ("minio_key", "spotify_url", "track_id", "prompt"):
            value = getattr(self, name)
            if value:
                return name, value
        raise ValueError("no source")  # unreachable after validation
