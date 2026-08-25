"""Tests for playback thread discipline: skipping must never leave a stale
thread driving the index or the audio device.

Regression cover for: pressing next/prev spawned a new playback thread without
retiring the old one, so two threads advanced current_index and fought over the
single pygame music channel -- audible as skipped sentences and garbled audio.
"""
import os
import re
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_unified import PlaybackController, SessionStore


class FakePlayer:
    """Stands in for pygame.mixer.music: one channel, timed playback."""

    def __init__(self, duration=0.15):
        self.duration = duration
        self.play_log = []
        self._busy_until = 0.0
        self._lock = threading.Lock()

    def play(self, path):
        with self._lock:
            self.play_log.append(path)
            self._busy_until = time.monotonic() + self.duration

    def is_busy(self):
        with self._lock:
            return time.monotonic() < self._busy_until

    def stop(self):
        with self._lock:
            self._busy_until = 0.0


class FakeEngine:
    def __init__(self, delay=0.02):
        self.delay = delay
        self.generated = []
        self.text_for_path = {}
        self._lock = threading.Lock()

    def generate(self, text, speed, **kwargs):
        time.sleep(self.delay)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with self._lock:
            self.generated.append(text)
            self.text_for_path[path] = text
        return path

    def is_available(self):
        return True

    def get_name(self):
        return "Fake"

    def stop(self):
        pass


def make_controller(sentences=40, play_duration=0.15, gen_delay=0.02):
    tmpdir = tempfile.mkdtemp()
    engine = FakeEngine(delay=gen_delay)
    player = FakePlayer(duration=play_duration)
    c = PlaybackController(
        engine=engine,
        session_store=SessionStore(base_dir=tmpdir),
        player=player,
    )
    c.load_text(" ".join(f"Sentence number {i} here." for i in range(sentences)))
    return c, engine, player, tmpdir


class TestGenerationToken:
    def test_begin_returns_increasing_tokens(self):
        c, _, _, _ = make_controller(3)
        a = c.begin_generation()
        b = c.begin_generation()
        assert b != a

    def test_only_newest_token_is_current(self):
        c, _, _, _ = make_controller(3)
        old = c.begin_generation()
        new = c.begin_generation()
        assert c.is_current(new)
        assert not c.is_current(old)

    def test_cancel_invalidates_running_token(self):
        c, _, _, _ = make_controller(3)
        gen = c.begin_generation()
        assert c.is_current(gen)
        c.cancel()
        assert not c.is_current(gen)


class TestSkipDoesNotStrandThreads:
    def test_single_skip_advances_exactly_one_sentence(self):
        """The reported bug: one 'next' press ran the index far past +1.

        Sentences 'play' for 5s so nothing advances on its own -- any movement
        beyond +1 within the settle window came from a stranded thread.
        """
        c, _, player, _ = make_controller(sentences=40, play_duration=5.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.25)          # let sentence 0 get going

        before = c.current_index
        c.skip_next()             # user presses next, once
        time.sleep(1.0)           # let any stale thread misbehave

        advanced = c.current_index - before
        c.cancel()
        assert advanced == 1, (
            f"index moved {advanced} sentences after ONE next press "
            f"(sentences sent to the speaker: {len(player.play_log)})"
        )

    def test_mashing_next_advances_once_per_press(self):
        c, _, _, _ = make_controller(sentences=40, play_duration=5.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.25)
        before = c.current_index
        for _ in range(5):
            c.skip_next()
            time.sleep(0.08)
        time.sleep(0.6)
        advanced = c.current_index - before
        c.cancel()
        assert advanced == 5, f"5 next presses moved the index {advanced} sentences"

    def test_only_one_playback_thread_runs_at_a_time(self):
        c, _, _, _ = make_controller(sentences=40, play_duration=5.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.2)
        for _ in range(5):        # user mashes next
            c.skip_next()
            time.sleep(0.05)
        time.sleep(0.5)
        assert c.live_thread_count() <= 1, (
            f"{c.live_thread_count()} playback threads alive simultaneously"
        )
        c.cancel()

    def test_sentences_play_in_order(self):
        """Two threads on one audio channel produced out-of-order playback."""
        c, engine, player, _ = make_controller(sentences=30, play_duration=0.3)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.2)
        c.skip_next()
        time.sleep(1.5)
        c.cancel()

        spoken = [engine.text_for_path[p] for p in player.play_log]
        indices = [int(re.search(r"number (\d+)", t).group(1)) for t in spoken]
        assert indices == sorted(indices), f"played out of order: {indices}"

    def test_cancel_stops_the_thread(self):
        c, _, _, _ = make_controller(sentences=40, play_duration=5.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.2)
        c.cancel()
        time.sleep(0.5)
        assert c.live_thread_count() == 0


class TestGeneratingIsAnnounced:
    """The status bar said 'Speaking...' while it was actually waiting on the
    network. Announce generation, but only when there is a real wait."""

    def test_unbuffered_sentence_announces_generating(self):
        c, _, _, _ = make_controller(sentences=5, play_duration=5.0, gen_delay=0.05)
        announced = []
        c.on_generating = announced.append
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.4)
        c.cancel()
        assert 0 in announced

    def test_buffered_sentence_stays_quiet(self):
        """No flicker when the lookahead already has the clip."""
        c, _, _, _ = make_controller(sentences=5, play_duration=5.0, gen_delay=0.01)
        c.generate_sentence(0, 1.0)          # pre-buffer it
        announced = []
        c.on_generating = announced.append
        c.params_provider = lambda: (1.0, {})
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.3)
        c.cancel()
        assert 0 not in announced

    def test_is_buffered_reports_accurately(self):
        c, _, _, _ = make_controller(sentences=3)
        assert c.is_buffered(0, 1.0) is False
        c.generate_sentence(0, 1.0)
        assert c.is_buffered(0, 1.0) is True
        assert c.is_buffered(0, 2.0) is False, "speed is part of the buffer identity"
