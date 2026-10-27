from app.transcriber import Segment, remove_overlaps


def test_merges_a_line_repeated_on_top_of_itself():
    out = remove_overlaps([Segment(0, 3, "Tum hi ho"), Segment(2, 4, "tum hi ho")])
    assert [(s.start, s.end, s.text) for s in out] == [(0, 4, "Tum hi ho")]


def test_keeps_a_chorus_line_sung_again_later():
    out = remove_overlaps([Segment(0, 3, "Tum hi ho"), Segment(3, 6, "Tum hi ho")])
    assert len(out) == 2


def test_overlapping_lines_start_after_the_previous_one():
    out = remove_overlaps([Segment(0, 3, "first"), Segment(2.5, 5, "second")])
    assert [(s.start, s.end) for s in out] == [(0, 3), (3, 5)]
