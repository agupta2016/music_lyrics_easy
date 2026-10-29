from app.transcriber import Segment, drop_garbled


def _texts(lines):
    segments = [Segment(i, i + 1, text) for i, text in enumerate(lines)]
    return [s.text for s in drop_garbled(segments)]


def test_mixed_script_gibberish_is_dropped_from_a_hindi_song():
    lines = [
        "करूं नित नित तेरा ध्यान यही है प्रार्थना मेरी",
        "कि ज которого बम ऐसे स्व schedश कंग",
        "कि ए dobrा नी करूं नित की उपलन्स",
        "Ha-ha-ha-ha-ha-ha-ha-ha-ha.",
        "मिले भक्ति का मुझे दान",
    ]
    assert _texts(lines) == [
        "करूं नित नित तेरा ध्यान यही है प्रार्थना मेरी",
        "मिले भक्ति का मुझे दान",
    ]


def test_a_hindi_line_with_one_english_word_is_kept():
    lines = ["तुम मेरी जान हो", "तुम मेरी baby हो"]
    assert _texts(lines) == lines


def test_english_songs_are_left_alone():
    lines = ["Let it be, let it be", "Whisper words of wisdom", "नमस्ते"]
    assert _texts(lines) == lines
