import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_unified import SentenceSplitter


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
