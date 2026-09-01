"""Unit-тесты ручного выбора фрагмента (segment_select)."""

from modules.segment_select import (
    match_text_to_segment,
    parse_time_range,
    parse_timestamp,
)


# --- parse_timestamp -------------------------------------------------------
def test_parse_timestamp_plain_seconds():
    assert parse_timestamp("90") == 90.0
    assert parse_timestamp("12.5") == 12.5
    assert parse_timestamp("12,5") == 12.5


def test_parse_timestamp_mmss_and_hhmmss():
    assert parse_timestamp("1:30") == 90.0
    assert parse_timestamp("01:02:03") == 3723.0


def test_parse_timestamp_invalid():
    assert parse_timestamp("abc") is None
    assert parse_timestamp("") is None
    assert parse_timestamp("1:2:3:4") is None


# --- parse_time_range ------------------------------------------------------
def test_parse_time_range_hyphen():
    assert parse_time_range("45-72") == (45.0, 72.0)


def test_parse_time_range_timecodes_with_spaces():
    assert parse_time_range("1:05 - 1:30") == (65.0, 90.0)


def test_parse_time_range_dash_unicode():
    assert parse_time_range("0:45–1:30") == (45.0, 90.0)


def test_parse_time_range_two_numbers_space():
    assert parse_time_range("90 120") == (90.0, 120.0)


def test_parse_time_range_rejects_reversed_and_garbage():
    assert parse_time_range("72-45") is None
    assert parse_time_range("hello") is None
    assert parse_time_range("1-2-3") is None
    assert parse_time_range("") is None


# --- match_text_to_segment -------------------------------------------------
def _segments():
    """Два сегмента с пословными таймингами."""
    return [
        {
            "text": "we will rock you tonight",
            "start": 10.0,
            "end": 13.0,
            "words": [
                {"word": "we", "start": 10.0, "end": 10.5},
                {"word": "will", "start": 10.5, "end": 11.0},
                {"word": "rock", "start": 11.0, "end": 11.7},
                {"word": "you", "start": 11.7, "end": 12.2},
                {"word": "tonight", "start": 12.2, "end": 13.0},
            ],
        },
        {
            "text": "dancing in the moonlight again",
            "start": 30.0,
            "end": 34.0,
            "words": [
                {"word": "dancing", "start": 30.0, "end": 30.8},
                {"word": "in", "start": 30.8, "end": 31.0},
                {"word": "the", "start": 31.0, "end": 31.3},
                {"word": "moonlight", "start": 31.3, "end": 32.4},
                {"word": "again", "start": 32.4, "end": 34.0},
            ],
        },
    ]


def test_match_exact_fragment():
    res = match_text_to_segment(_segments(), "rock you tonight", pad=0.0)
    assert res is not None
    assert res["start"] == 11.0
    assert res["end"] == 13.0
    assert res["score"] > 0.9


def test_match_second_segment_with_typos():
    # с опечаткой и разным регистром — fuzzy всё равно находит
    res = match_text_to_segment(_segments(), "Dancing in the moonlite", pad=0.0)
    assert res is not None
    assert res["start"] == 30.0
    assert 32.0 <= res["end"] <= 34.0


def test_match_applies_padding():
    res = match_text_to_segment(_segments(), "rock you", pad=0.5)
    assert res is not None
    assert res["start"] == 10.5  # 11.0 - 0.5
    assert res["end"] == 12.7    # 12.2 + 0.5


def test_match_unknown_text_returns_none():
    assert match_text_to_segment(_segments(), "completely different lyrics here") is None


def test_match_empty_inputs():
    assert match_text_to_segment([], "rock you") is None
    assert match_text_to_segment(_segments(), "") is None


def test_match_falls_back_to_even_split_without_words():
    seg = [{"text": "alpha beta gamma delta", "start": 0.0, "end": 4.0}]
    res = match_text_to_segment(seg, "beta gamma", pad=0.0)
    assert res is not None
    assert 0.9 <= res["start"] <= 1.1   # ~1.0
    assert 2.9 <= res["end"] <= 3.1     # ~3.0
