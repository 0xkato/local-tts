"""Tests for jumping to a clicked sentence, time-remaining estimates, and
remembering the article between launches."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_unified import PlaybackController, SessionStore, estimate_seconds, format_duration


class NullPlayer:
    def play(self, path): pass
    def is_busy(self): return False
    def stop(self): pass


class TestSentenceAtOffset:
    """Clicking a sentence in the text should jump to it."""

    def setup_method(self):
        self.c = PlaybackController(session_store=None, player=NullPlayer())
        self.text = "First one here. Second one here. Third one here."
        self.c.load_text(self.text)

    def test_offset_inside_first_sentence(self):
        assert self.c.sentence_at_offset(3) == 0

    def test_offset_inside_second_sentence(self):
        assert self.c.sentence_at_offset(self.text.index("Second") + 2) == 1

    def test_offset_inside_third_sentence(self):
        assert self.c.sentence_at_offset(self.text.index("Third") + 2) == 2

    def test_offset_on_the_boundary_picks_the_sentence_it_starts(self):
        assert self.c.sentence_at_offset(self.text.index("Second")) == 1

    def test_offset_in_the_gap_falls_to_the_next_sentence(self):
        gap = self.text.index("First one here.") + len("First one here.")
        assert self.c.sentence_at_offset(gap) == 1

    def test_offset_past_the_end_clamps(self):
        assert self.c.sentence_at_offset(10_000) == 2

    def test_negative_offset_clamps(self):
        assert self.c.sentence_at_offset(-5) == 0

    def test_no_text_loaded(self):
        empty = PlaybackController(session_store=None, player=NullPlayer())
        assert empty.sentence_at_offset(0) is None


class TestTimeEstimates:
    def test_longer_text_takes_longer(self):
        assert estimate_seconds("word " * 200, 1.0) > estimate_seconds("word " * 20, 1.0)

    def test_double_speed_halves_the_estimate(self):
        slow = estimate_seconds("word " * 140, 1.0)
        fast = estimate_seconds("word " * 140, 2.0)
        assert fast == pytest.approx(slow / 2, rel=0.01)

    def test_empty_text_is_zero(self):
        assert estimate_seconds("", 1.5) == 0

    def test_a_minute_of_words_at_normal_speed(self):
        """Calibrated against measured Piper output, so the number means something."""
        assert estimate_seconds("word " * 140, 1.0) == pytest.approx(60, rel=0.25)


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(45) == "45 sec"

    def test_minutes(self):
        assert format_duration(600) == "10 min"

    def test_rounds_up_to_a_minute(self):
        assert format_duration(90) == "2 min"

    def test_hours(self):
        assert format_duration(4500) == "1 hr 15 min"

    def test_zero(self):
        assert format_duration(0) == "0 sec"


class TestRemembersTheArticle:
    """Reopening meant re-pasting the exact text before resume could fire."""

    def setup_method(self):
        self.store = SessionStore(base_dir=tempfile.mkdtemp())

    def test_round_trip(self):
        self.store.save_last_text("An article about scaling laws.")
        assert self.store.load_last_text() == "An article about scaling laws."

    def test_nothing_saved_yet(self):
        assert self.store.load_last_text() is None

    def test_overwrites_previous(self):
        self.store.save_last_text("first")
        self.store.save_last_text("second")
        assert self.store.load_last_text() == "second"

    def test_blank_text_is_not_remembered(self):
        self.store.save_last_text("real text")
        self.store.save_last_text("   \n  ")
        assert self.store.load_last_text() == "real text"

    def test_survives_unicode(self):
        self.store.save_last_text("café — naïve “quotes”")
        assert self.store.load_last_text() == "café — naïve “quotes”"
