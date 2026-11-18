"""Tests for recovery from a sentence that fails to generate."""
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tts_unified
from tts_unified import PlaybackController, SessionStore


class FlakyEngine:
    """Fails the first `failures` calls for a sentence, then succeeds."""

    def __init__(self, failures=0, always_fail=False):
        self.failures = failures
        self.always_fail = always_fail
        self.attempts = 0
        self.lock = threading.Lock()

    def generate(self, text, speed, **kwargs):
        with self.lock:
            self.attempts += 1
            n = self.attempts
        if self.always_fail or n <= self.failures:
            raise RuntimeError("network blip")
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        return path

    def is_available(self):
        return True

    def get_name(self):
        return "Flaky"

    def supports_speed(self):
        return True

    def stop(self):
        pass


class InstantPlayer:
    def __init__(self): self.log = []
    def play(self, path): self.log.append(path)
    def is_busy(self): return False
    def stop(self): pass


def make(engine):
    c = PlaybackController(
        engine=engine,
        session_store=SessionStore(base_dir=tempfile.mkdtemp()),
        player=InstantPlayer(),
    )
    c.RETRY_BACKOFF = 0.01
    return c


class TestTransientFailuresRecover:
    def test_a_blip_does_not_end_playback(self):
        engine = FlakyEngine(failures=2)
        c = make(engine)
        c.load_text("One here. Two here. Three here.")
        errors = []
        c.on_error = errors.append
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        deadline = time.monotonic() + 10
        while c.state == PlaybackController.State.PLAYING and time.monotonic() < deadline:
            time.sleep(0.02)
        c.cancel()
        assert not errors, f"a retryable blip surfaced as an error: {errors}"
        assert c.current_index == 2, "playback did not reach the end"

    def test_persistent_failure_reports_once_and_stops(self):
        c = make(FlakyEngine(always_fail=True))
        c.load_text("One here. Two here.")
        errors = []
        c.on_error = errors.append
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        deadline = time.monotonic() + 10
        while c.state == PlaybackController.State.PLAYING and time.monotonic() < deadline:
            time.sleep(0.02)
        c.cancel()
        assert len(errors) == 1, f"expected one report, got {len(errors)}"
        assert c.state == PlaybackController.State.STOPPED

    def test_retries_are_bounded(self):
        engine = FlakyEngine(always_fail=True)
        c = make(engine)
        c.load_text("Only one sentence here.")
        c.on_error = lambda exc: None
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        deadline = time.monotonic() + 10
        while c.state == PlaybackController.State.PLAYING and time.monotonic() < deadline:
            time.sleep(0.02)
        c.cancel()
        assert engine.attempts <= PlaybackController.GENERATE_ATTEMPTS
