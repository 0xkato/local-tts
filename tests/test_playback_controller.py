import sys
import os
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_tts.engine import PlaybackController, SentenceSplitter, SessionStore
from enum import Enum


class FakeEngine:
    """Mock TTS engine for testing."""
    def __init__(self):
        self.generated = []
        self.available = True

    def generate(self, text, speed, **kwargs):
        self.generated.append(text)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        return tmp.name

    def is_available(self):
        return self.available

    def get_name(self):
        return "Fake"

    def stop(self):
        pass


class TestPlaybackController:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = FakeEngine()
        self.session_store = SessionStore(base_dir=self.tmpdir)
        self.controller = PlaybackController(
            engine=self.engine,
            session_store=self.session_store,
        )

    def teardown_method(self):
        self.controller.cleanup()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_state_is_stopped(self):
        assert self.controller.state == PlaybackController.State.STOPPED

    def test_load_text_splits_sentences(self):
        self.controller.load_text("Hello. World. Foo.")
        assert self.controller.total_sentences == 3
        assert self.controller.current_index == 0

    def test_load_text_empty(self):
        self.controller.load_text("")
        assert self.controller.total_sentences == 0

    def test_next_increments_index(self):
        self.controller.load_text("One. Two. Three.")
        self.controller.current_index = 0
        self.controller.next_sentence()
        assert self.controller.current_index == 1

    def test_next_clamps_at_end(self):
        self.controller.load_text("One. Two.")
        self.controller.current_index = 1
        self.controller.next_sentence()
        assert self.controller.current_index == 1

    def test_prev_decrements_index(self):
        self.controller.load_text("One. Two. Three.")
        self.controller.current_index = 2
        self.controller.prev_sentence()
        assert self.controller.current_index == 1

    def test_prev_clamps_at_zero(self):
        self.controller.load_text("One. Two.")
        self.controller.current_index = 0
        self.controller.prev_sentence()
        assert self.controller.current_index == 0

    def test_seek_to_sentence(self):
        self.controller.load_text("A. B. C. D. E.")
        self.controller.seek_to(3)
        assert self.controller.current_index == 3

    def test_seek_clamps(self):
        self.controller.load_text("A. B.")
        self.controller.seek_to(99)
        assert self.controller.current_index == 1
        self.controller.seek_to(-5)
        assert self.controller.current_index == 0

    def test_generate_current_sentence(self):
        self.controller.load_text("Hello world. Goodbye.")
        audio_path = self.controller.generate_sentence(0, speed=1.5)
        assert audio_path is not None
        assert self.engine.generated == ["Hello world."]

    def test_check_saved_session(self):
        text = "Remember me. Please."
        self.session_store.save_position(text, sentence_index=1, speed=1.5, engine="fake")
        self.controller.load_text(text)
        saved = self.controller.check_saved_position()
        assert saved is not None
        assert saved["sentence_index"] == 1
