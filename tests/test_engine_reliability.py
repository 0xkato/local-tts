"""Tests for engine probing, subprocess safety, and recovery from a bad sentence."""
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tts_unified
from tts_unified import PiperTTSEngine, PlaybackController, SessionStore


class TestPiperProbeIsCached:
    """is_available() ran 'piper --help' on every play press: ~161ms a time."""

    def setup_method(self):
        self.calls = []
        self.real_run = tts_unified.subprocess.run

        def counting_run(cmd, *a, **kw):
            self.calls.append(cmd)

            class Result:
                returncode = 0
            return Result()

        tts_unified.subprocess.run = counting_run

    def teardown_method(self):
        tts_unified.subprocess.run = self.real_run

    def test_repeated_checks_probe_once(self):
        engine = PiperTTSEngine()
        for _ in range(5):
            engine.check_piper_installed()
        assert len(self.calls) == 1

    def test_invalidate_forces_a_fresh_probe(self):
        """After installing piper or downloading a voice, re-probe."""
        engine = PiperTTSEngine()
        engine.check_piper_installed()
        engine.invalidate_availability()
        engine.check_piper_installed()
        assert len(self.calls) == 2


class TestPiperGenerateCannotHang:
    def test_timeout_kills_the_process_and_reports(self):
        killed = []

        class HungProcess:
            returncode = None

            def communicate(self, input=None, timeout=None):
                raise subprocess.TimeoutExpired(cmd="piper", timeout=timeout)

            def kill(self):
                killed.append(True)

            def wait(self, timeout=None):
                return 0

        engine = PiperTTSEngine()
        engine._piper_installed = True
        real_popen = tts_unified.subprocess.Popen
        real_exists = os.path.exists
        tts_unified.subprocess.Popen = lambda *a, **kw: HungProcess()
        tts_unified.os.path.exists = lambda p: True
        try:
            with pytest.raises(Exception) as excinfo:
                engine.generate("hello", 1.0)
            assert "timed out" in str(excinfo.value).lower()
            assert killed, "a wedged piper process was left running"
        finally:
            tts_unified.subprocess.Popen = real_popen
            tts_unified.os.path.exists = real_exists


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
