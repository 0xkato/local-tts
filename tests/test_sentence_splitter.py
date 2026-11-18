import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_tts.engine import SentenceSplitter


class TestSentenceSplitter:
    def setup_method(self):
        self.splitter = SentenceSplitter()

    def test_simple_sentences(self):
        text = "Hello world. How are you? I am fine!"
        result = self.splitter.split(text)
        assert result == ["Hello world.", "How are you?", "I am fine!"]

    def test_single_sentence(self):
        text = "Just one sentence."
        result = self.splitter.split(text)
        assert result == ["Just one sentence."]

    def test_abbreviations_preserved(self):
        text = "Dr. Smith went to Washington. He met Mr. Jones there."
        result = self.splitter.split(text)
        assert result == ["Dr. Smith went to Washington.", "He met Mr. Jones there."]

    def test_us_abbreviation(self):
        text = "The U.S. is a country. It is large."
        result = self.splitter.split(text)
        assert result == ["The U.S. is a country.", "It is large."]

    def test_empty_string(self):
        result = self.splitter.split("")
        assert result == []

    def test_whitespace_only(self):
        result = self.splitter.split("   \n\n  ")
        assert result == []

    def test_no_punctuation(self):
        text = "This has no ending punctuation"
        result = self.splitter.split(text)
        assert result == ["This has no ending punctuation"]

    def test_multiple_spaces_between_sentences(self):
        text = "First sentence.   Second sentence."
        result = self.splitter.split(text)
        assert result == ["First sentence.", "Second sentence."]

    def test_newlines_between_sentences(self):
        text = "First sentence.\nSecond sentence.\n\nThird sentence."
        result = self.splitter.split(text)
        assert result == ["First sentence.", "Second sentence.", "Third sentence."]

    def test_ellipsis_not_split(self):
        text = "Wait for it... And there it is. Done."
        result = self.splitter.split(text)
        assert result == ["Wait for it... And there it is.", "Done."]

    def test_sentence_positions(self):
        text = "Hello world. How are you?"
        sentences = self.splitter.split(text)
        positions = self.splitter.get_positions(text)
        assert len(positions) == 2
        assert text[positions[0][0]:positions[0][1]] == "Hello world."
        assert text[positions[1][0]:positions[1][1]] == "How are you?"

    # ── Numbered list tests ──

    def test_numbered_list_not_split_at_marker(self):
        """Each numbered list item becomes its own sentence."""
        text = "1. First item\n2. Second item\n3. Third item"
        result = self.splitter.split(text)
        assert result == ["1. First item", "2. Second item", "3. Third item"]

    def test_numbered_list_with_sentence_periods(self):
        """List items that end with periods split correctly at the content period."""
        text = "1. Do this thing.\n2. Do that thing.\n3. Done."
        result = self.splitter.split(text)
        assert result == ["1. Do this thing.", "2. Do that thing.", "3. Done."]

    def test_numbered_list_with_internal_periods(self):
        """Periods inside list items don't split the item — whole line is one sentence."""
        text = "1. one. a bunch of text\n2. two. some more text\n3. three. some more text"
        result = self.splitter.split(text)
        assert result == [
            "1. one. a bunch of text",
            "2. two. some more text",
            "3. three. some more text",
        ]

    def test_number_mid_sentence_still_splits(self):
        """Numbers mid-sentence (not at line start) still split normally."""
        text = "He scored 3. She scored 4."
        result = self.splitter.split(text)
        assert result == ["He scored 3.", "She scored 4."]

    def test_decimal_not_split(self):
        text = "The value is 3.14 exactly. Got it."
        result = self.splitter.split(text)
        assert result == ["The value is 3.14 exactly.", "Got it."]

    # ── Closing punctuation tests ──

    def test_closing_quote_after_period(self):
        text = 'She said "hello." Then she left.'
        result = self.splitter.split(text)
        assert result == ['She said "hello."', "Then she left."]

    def test_closing_paren_after_question(self):
        text = "(Is this real?) Yes it is."
        result = self.splitter.split(text)
        assert result == ["(Is this real?)", "Yes it is."]

