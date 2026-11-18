"""Tests for the text handed to the TTS engine.

The voices already speak numerals, currency and symbols themselves. Our job is to strip *markup* (which engines read aloud literally)
and otherwise leave *content* alone -- rewriting digits destroys information
the engine could have voiced properly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_unified import normalize_for_tts, SentenceSplitter


class TestNumbersReachEngineIntact:
    """Regression: '\\b\\d{1,3}\\b' -> words mangled every compound number."""

    def test_thousands_separator_preserved(self):
        assert "1,000" in normalize_for_tts("About 1,000 people showed up.")

    def test_large_grouped_number_preserved(self):
        assert "250,000" in normalize_for_tts("Revenue hit 250,000 dollars.")

    def test_decimal_preserved(self):
        assert "3.14" in normalize_for_tts("Pi is roughly 3.14 today.")

    def test_currency_decimal_preserved(self):
        assert "$1.5" in normalize_for_tts("It costs $1.5 billion.")

    def test_time_preserved(self):
        assert "10:30" in normalize_for_tts("Meet me at 10:30 sharp.")

    def test_version_preserved(self):
        assert "1.2.3" in normalize_for_tts("Version 1.2.3 shipped.")

    def test_iso_date_preserved(self):
        assert "2025-08-25" in normalize_for_tts("Released on 2025-08-25 finally.")

    def test_phone_number_preserved(self):
        assert "555-0123" in normalize_for_tts("Call 555-0123 now.")

    def test_percentage_preserved(self):
        assert "12%" in normalize_for_tts("Growth was 12% last year.")

    def test_score_preserved(self):
        assert "3-2" in normalize_for_tts("Scores were 3-2 in the end.")

    def test_speed_multiplier_preserved(self):
        assert "1.5x" in normalize_for_tts("The model runs at 1.5x speed.")

    def test_plain_integer_preserved(self):
        assert "5" in normalize_for_tts("There are 5 options")

    def test_year_preserved(self):
        assert "2024" in normalize_for_tts("The year is 2024")

    def test_zero_preserved(self):
        assert "0" in normalize_for_tts("The count is 0")


class TestListPrefixes:
    def test_numbered_prefix_becomes_comma(self):
        """'3.' would otherwise read as a sentence break mid-item."""
        assert normalize_for_tts("3. Walk the dog") == "3, Walk the dog"

    def test_bullet_marker_dropped(self):
        assert normalize_for_tts("- First bullet point") == "First bullet point"
        assert normalize_for_tts("* First bullet point") == "First bullet point"
        assert normalize_for_tts("• First bullet point") == "First bullet point"


class TestMarkupStripped:
    def test_bold_and_italic_markers_removed(self):
        assert normalize_for_tts("The **key insight** is _big_.") == "The key insight is big."

    def test_heading_marks_removed(self):
        assert normalize_for_tts("## Why This Matters") == "Why This Matters"

    def test_link_reduced_to_label(self):
        assert normalize_for_tts("models scale [predictably](https://arxiv.org/abs/2001.08361).") \
            == "models scale predictably."

    def test_bare_url_replaced_with_word(self):
        out = normalize_for_tts("See https://example.com/a/b?c=1 for details.")
        assert "https" not in out and "example.com" not in out
        assert "link" in out

    def test_inline_code_backticks_removed(self):
        assert normalize_for_tts("Call `generate_sentence` now.") == "Call generate_sentence now."

    def test_double_hyphen_becomes_pause(self):
        out = normalize_for_tts("See Figure 1 for details -- it's striking.")
        assert "--" not in out
        assert out == "See Figure 1 for details, it's striking."

    def test_command_line_flag_is_not_a_pause(self):
        """'--length_scale' is a flag, not an em dash."""
        assert normalize_for_tts("Use the `--length_scale` flag.") == "Use the --length_scale flag."

    def test_word_joining_double_hyphen_becomes_pause(self):
        assert normalize_for_tts("the result--surprisingly--held") == "the result, surprisingly, held"

    def test_numeric_en_dash_range_reads_as_to(self):
        assert normalize_for_tts("Rates: 3.5\u20134.2% APR.") == "Rates: 3.5 to 4.2% APR."

    def test_task_list_checkbox_dropped(self):
        assert normalize_for_tts("- [ ] todo item") == "todo item"
        assert normalize_for_tts("- [x] done item") == "done item"

    def test_ampersand_spoken_as_and(self):
        assert normalize_for_tts("GPT-4 & Claude") == "GPT-4 and Claude"


class TestUnspeakableInput:
    def test_whitespace_collapsed(self):
        text = "At\nthe pixel level, the airplane is\ntiny."
        assert normalize_for_tts(text) == "At the pixel level, the airplane is tiny."

    def test_horizontal_rule_yields_nothing(self):
        assert normalize_for_tts("---") == ""
        assert normalize_for_tts("***") == ""

    def test_plain_text_untouched(self):
        assert normalize_for_tts("Hello world") == "Hello world"


class TestSplitterNumberHandling:
    def setup_method(self):
        self.splitter = SentenceSplitter()

    def test_leading_decimal_is_not_a_list_marker(self):
        """'1.5x ...' swallowed the whole paragraph as one unit."""
        text = "1.5x is the default speed. It works well. Third sentence here."
        assert self.splitter.split(text) == [
            "1.5x is the default speed.", "It works well.", "Third sentence here.",
        ]

    def test_leading_year_is_not_a_list_marker(self):
        text = "2024. What a year. It was long."
        assert self.splitter.split(text) == ["2024.", "What a year.", "It was long."]

    def test_leading_price_still_splits(self):
        text = "$4.99 per month. That is cheap."
        assert self.splitter.split(text) == ["$4.99 per month.", "That is cheap."]

    def test_real_numbered_list_still_works(self):
        text = "1. First item\n2. Second item\n3. Third item"
        assert self.splitter.split(text) == ["1. First item", "2. Second item", "3. Third item"]

    def test_bullet_lines_are_separate_units(self):
        text = "* First bullet point\n* Second one here\nCosts fell later."
        assert self.splitter.split(text) == [
            "* First bullet point", "* Second one here", "Costs fell later.",
        ]

    def test_heading_is_its_own_unit(self):
        text = "## Why This Matters\nThe key insight is scale."
        assert self.splitter.split(text) == ["## Why This Matters", "The key insight is scale."]
