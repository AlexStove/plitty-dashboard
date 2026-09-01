import pytest
from pydantic import ValidationError

from modules.validation import GenerateRequest, MinioBatchImportRequest, SpotifyImportRequest


def test_generate_request_rejects_too_many_videos():
    with pytest.raises(ValidationError):
        GenerateRequest(videos_per_account=99)


def test_generate_request_accepts_expected_values():
    request = GenerateRequest(
        scenario="track_promo",
        bg_type="footage",
        orientation="landscape",
        videos_per_account=3,
    )

    assert request.scenario == "track_promo"
    assert request.videos_per_account == 3


def test_spotify_request_rejects_non_spotify_url():
    with pytest.raises(ValidationError):
        SpotifyImportRequest(url="https://example.com/track/123")


def test_minio_batch_strips_empty_keys():
    request = MinioBatchImportRequest(keys=[" artist/song.mp3 ", ""])

    assert request.keys == ["artist/song.mp3"]
