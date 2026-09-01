"""Patch spotdl song.py to handle missing Spotify API fields.

Only patches fields that Spotify actually removed from their API.
Does NOT touch critical fields like 'name', 'id', 'uri', etc.
"""
import pathlib
import sys

candidates = list(pathlib.Path("/usr/local/lib").rglob("spotdl/types/song.py"))
if not candidates:
    print("spotdl/types/song.py not found, skipping patch")
    sys.exit(0)

# Only patch specific fields that Spotify removed
PATCHES = {
    # field access -> safe replacement
    'raw_album_meta["genres"]': 'raw_album_meta.get("genres", [])',
    'raw_artist_meta["genres"]': 'raw_artist_meta.get("genres", [])',
    'raw_album_meta["label"]': 'raw_album_meta.get("label", "")',
    'raw_track_meta["popularity"]': 'raw_track_meta.get("popularity", 0)',
    'raw_album_meta["popularity"]': 'raw_album_meta.get("popularity", 0)',
    'raw_artist_meta["popularity"]': 'raw_artist_meta.get("popularity", 0)',
    'raw_album_meta["copyrights"]': 'raw_album_meta.get("copyrights", [])',
}

for p in candidates:
    t = p.read_text()
    original = t

    for old, new in PATCHES.items():
        t = t.replace(old, new)

    if t != original:
        p.write_text(t)
        count = sum(1 for old in PATCHES if old in original)
        print(f"Patched {p}: {count} targeted fixes applied")
    else:
        print(f"No changes needed in {p}")
