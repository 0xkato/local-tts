import sys
import os
import json
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_tts.engine import SessionStore


class TestSessionStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = SessionStore(base_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        text = "Hello world. This is a test."
        self.store.save_position(text, sentence_index=1, speed=1.5, engine="google")
        result = self.store.load_position(text)
        assert result is not None
        assert result["sentence_index"] == 1
        assert result["speed"] == 1.5
        assert result["engine"] == "google"

    def test_load_nonexistent(self):
        result = self.store.load_position("never seen this text")
        assert result is None

    def test_overwrite_position(self):
        text = "Same text here."
        self.store.save_position(text, sentence_index=5, speed=1.0, engine="piper")
        self.store.save_position(text, sentence_index=10, speed=1.5, engine="google")
        result = self.store.load_position(text)
        assert result["sentence_index"] == 10

    def test_text_hash_uses_first_500_chars(self):
        base = "A" * 500
        text1 = base + " extra stuff"
        text2 = base + " different stuff"
        self.store.save_position(text1, sentence_index=3, speed=1.0, engine="google")
        result = self.store.load_position(text2)
        assert result is not None
        assert result["sentence_index"] == 3

    def test_prune_old_sessions(self):
        text = "Old session text."
        self.store.save_position(text, sentence_index=1, speed=1.0, engine="google")
        text_hash = self.store._text_hash(text)
        sessions = self.store._load_sessions()
        sessions[text_hash]["timestamp"] = time.time() - (31 * 86400)
        self.store._save_sessions(sessions)
        self.store.prune_old()
        result = self.store.load_position(text)
        assert result is None

    def test_max_50_sessions(self):
        for i in range(55):
            self.store.save_position(f"Text number {i}.", sentence_index=i, speed=1.0, engine="google")
        self.store.prune_old()
        sessions = self.store._load_sessions()
        assert len(sessions) <= 50

    def test_delete_position(self):
        text = "Delete me."
        self.store.save_position(text, sentence_index=1, speed=1.0, engine="google")
        self.store.delete_position(text)
        result = self.store.load_position(text)
        assert result is None
