"""
Де-риск Deezer-ноги: проверяет, что по Spotify-ссылке скачивается ПОЛНЫЙ трек
через Deezer (а не 30-сек превью). Транскрипцию/припевы НЕ запускает — только загрузку.

Запуск из корня проекта (нужны: установленный streamrip+ffmpeg, .env с
SPOTIFY_CLIENT_ID/SECRET и DEEZER_ARL):

    python scripts/check_deezer.py "https://open.spotify.com/track/XXXXXXXXXXXX"
"""

import logging
import sys
import tempfile

from modules.config import settings
from modules.spotify_loader import (
    SpotdlError,
    _streamrip_executable,
    download_artist_tracks,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python scripts/check_deezer.py "<spotify_track_url>"')
        return 2

    url = sys.argv[1]

    print("=== prerequisites ===")
    print("streamrip (rip):", _streamrip_executable() or "NOT FOUND -> pip install streamrip")
    print(
        "SPOTIFY creds:",
        "ok" if (settings.spotify_client_id and settings.spotify_client_secret) else "MISSING",
    )
    print("DEEZER_ARL:", "set" if settings.deezer_arl else "MISSING")
    print("MIN_TRACK_SECONDS:", settings.min_track_seconds)
    print()

    out = tempfile.mkdtemp(prefix="dztest_")
    print(f"downloading (source=deezer) into {out} ...\n")

    try:
        tracks = download_artist_tracks(url, out, max_tracks=1, source="deezer")
    except SpotdlError as e:
        print(f"FAILED: {e}")
        return 1

    print("\n=== result ===")
    if not tracks:
        print("nothing downloaded")
        return 1

    ok = False
    for t in tracks:
        full = (not t.is_preview) and t.duration >= settings.min_track_seconds
        ok = ok or full
        verdict = "FULL OK" if full else "PREVIEW/SHORT (Deezer не сработал)"
        print(f"[{verdict}] source={t.source} duration={round(t.duration, 1)}s "
              f"{t.artist} - {t.title}")
        print(f"  file: {t.path}")

    print()
    print("ИТОГ: Deezer качает полные треки." if ok
          else "ИТОГ: полный трек не получен — смотри INFO-логи streamrip выше.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
