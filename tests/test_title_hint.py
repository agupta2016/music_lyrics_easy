import pytest

from app.transcriber import title_hint


@pytest.mark.parametrize(
    "title, language, expected",
    [
        # Keep the Devanagari part of a Hindi title, drop the English description and hashtags.
        (
            "करूं नित नित तेरा ध्यान | Disciple’s Prayer for Unwavering Devotion | #DJJSBhajan",
            "hi",
            "करूं नित नित तेरा ध्यान",
        ),
        # A Hindi song with only a Latin-letter title gets no hint.
        ("Tum Hi Ho - Aashiqui 2 | Full Song (Official Video)", "hi", None),
        ("Ed Sheeran - Perfect (Official Music Video)", "en", "Ed Sheeran Perfect"),
        ("Ed Sheeran - Perfect (Official Music Video)", None, "Ed Sheeran Perfect"),
        ("kesariya tune.mp3", None, "kesariya tune"),
        ("#shorts", None, None),
        (None, "hi", None),
    ],
)
def test_title_hint(title, language, expected):
    assert title_hint(title, language) == expected
