"""NeuralTTSEngine and the playback behaviour the neural voices rely on."""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_tts.engine as tts_unified
from local_tts.voices import voice_catalog
from local_tts.engine import NeuralTTSEngine, PlaybackController, SessionStore


class RecordingClient:
    """Stands in for VoiceWorkerClient and remembers what it was asked."""

    def __init__(self):
        self.calls = []

    def synth(self, engine_key, text, voice, speed, out_path):
        self.calls.append({"engine": engine_key, "text": text, "voice": voice, "speed": speed})
        with open(out_path, "wb") as f:
            f.write(b"RIFF")
        return {"path": out_path}


class TestSpeed:
    def setup_method(self):
        self.stretched = []
        self.real_stretch = tts_unified.time_stretch

        def fake_stretch(path, speed):
            self.stretched.append(speed)
            return path

        tts_unified.time_stretch = fake_stretch

    def teardown_method(self):
        tts_unified.time_stretch = self.real_stretch

    def test_native_speed_goes_to_the_model(self):
        client = RecordingClient()
        engine = NeuralTTSEngine(voice_catalog.BY_KEY["kokoro"], client)
        os.unlink(engine.generate("Hi.", 1.5))
        assert client.calls[0]["speed"] == 1.5
        assert self.stretched == [], "a natively timed clip was stretched again"

    def test_other_models_render_at_1x_and_get_retimed(self):
        client = RecordingClient()
        engine = NeuralTTSEngine(voice_catalog.BY_KEY["ming"], client)
        os.unlink(engine.generate("Hi.", 1.5))
        assert client.calls[0]["speed"] == 1.0
        assert self.stretched == [1.5]

    def test_default_voice_is_used_when_none_is_chosen(self):
        client = RecordingClient()
        spec = voice_catalog.BY_KEY["phonon"]
        os.unlink(NeuralTTSEngine(spec, client).generate("Hi.", 1.0))
        assert client.calls[0]["voice"] == spec.default_voice

    def test_failed_generation_leaves_no_temp_file(self):
        class Failing(RecordingClient):
            def synth(self, *a, out_path=None, **kw):
                self.path = out_path
                raise RuntimeError("boom")

        client = Failing()
        engine = NeuralTTSEngine(voice_catalog.BY_KEY["phonon"], client)
        try:
            engine.generate("Hi.", 1.0)
        except RuntimeError:
            pass
        assert not os.path.exists(client.path)


class TestAvailability:
    def test_missing_voices_environment_is_explained(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCAL_TTS_VOICES_PYTHON", str(tmp_path / "missing" / "python"))
        engine = NeuralTTSEngine(voice_catalog.BY_KEY["phonon"], RecordingClient())
        if tts_unified.PYGAME_AVAILABLE:
            assert not engine.is_available()
            assert "README" in engine.unavailable_reason()


class TestCatalog:
    def test_every_engine_offers_its_default_voice(self):
        for spec in voice_catalog.ENGINES:
            assert spec.default_voice in dict(spec.voices), spec.key

    def test_keys_are_unique(self):
        keys = [spec.key for spec in voice_catalog.ENGINES]
        assert len(keys) == len(set(keys))

    def test_download_check_reads_the_hub_cache(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
        assert not voice_catalog.is_downloaded("org/model")
        snap = tmp_path / "models--org--model" / "snapshots" / "abc"
        snap.mkdir(parents=True)
        assert not voice_catalog.is_downloaded("org/model"), "an empty snapshot counted"
        (snap / "config.json").write_text("{}")
        assert voice_catalog.is_downloaded("org/model")


# ── Lookahead ────────────────────────────────────────────────────────────

class FakePlayer:
    def __init__(self, duration):
        self.duration = duration
        self._until = 0.0
        self._lock = threading.Lock()

    def play(self, path):
        with self._lock:
            self._until = time.monotonic() + self.duration

    def is_busy(self):
        with self._lock:
            return time.monotonic() < self._until

    def stop(self):
        with self._lock:
            self._until = 0.0


class SerialEngine:
    """Like the voice worker: one generation at a time, and slow."""

    def __init__(self, delay):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.generated = []
        self._lock = threading.Lock()

    def generate(self, text, speed, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self._lock:
            self.active -= 1
            self.generated.append(text)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        return path

    def is_available(self):
        return True

    def get_name(self):
        return "Serial"

    def stop(self):
        pass


def controller(engine, play_duration):
    c = PlaybackController(engine=engine, session_store=SessionStore(base_dir=tempfile.mkdtemp()),
                           player=FakePlayer(play_duration))
    c.load_text(" ".join(f"Sentence number {i} here." for i in range(30)))
    return c


class TestLookaheadIsSequential:
    def test_lookahead_asks_for_one_sentence_at_a_time(self):
        """Three parallel requests to a one-at-a-time worker just queue, and
        the sentence the listener needs next waits behind them."""
        engine = SerialEngine(delay=0.05)
        c = controller(engine, play_duration=1.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.6)
        c.cancel()
        assert engine.max_active == 1
        assert len(engine.generated) >= 1 + c.LOOKAHEAD

    def test_lookahead_stops_once_playback_moves_on(self):
        """After a skip the old lookahead must not keep the worker busy with
        sentences nobody is going to hear."""
        engine = SerialEngine(delay=0.2)
        c = controller(engine, play_duration=5.0)
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.3)          # first sentence generated, lookahead under way
        c.cancel()
        c.state = PlaybackController.State.STOPPED
        done_at_cancel = len(engine.generated)
        time.sleep(1.0)
        # At most the one request already in flight completes
        assert len(engine.generated) <= done_at_cancel + 1


# ── Engine switches and slow sentences (regression cover from review) ──────

class LogPlayer(FakePlayer):
    def __init__(self, duration):
        super().__init__(duration)
        self.log = []

    def play(self, path):
        self.log.append(os.path.basename(path))
        super().play(path)


class NamedEngine:
    """Names its clips after itself; can hold one sentence until released."""

    def __init__(self, name, hold_index=None, gate=None, delays=None):
        self.name, self.hold_index, self.gate = name, hold_index, gate
        self.delays = delays or {}
        self.paths = []

    def generate(self, text, speed, **kwargs):
        index = int(text.split()[2])
        if self.gate is not None and index == self.hold_index:
            self.gate.wait(10)
        time.sleep(self.delays.get(index, 0.0))
        fd, path = tempfile.mkstemp(prefix=f"{self.name}-s{index}-", suffix=".wav")
        os.close(fd)
        self.paths.append(path)
        return path

    def is_available(self):
        return True

    def get_name(self):
        return self.name

    def stop(self):
        pass


class TestSwitchingNeverReplaysTheOldEngine:
    def _switch_mid_generation(self):
        """The old engine is generating sentence 1 when the user switches. If
        the two engines share a voice id, their cache keys used to match."""
        gate = threading.Event()
        old = NamedEngine("old", hold_index=1, gate=gate)
        player = LogPlayer(0.4)
        c = PlaybackController(engine=old, session_store=SessionStore(base_dir=tempfile.mkdtemp()),
                               player=player)
        c.load_text(" ".join(f"Sentence number {i} here." for i in range(6)))
        c.params_provider = lambda: (1.5, {"voice": "shared"})
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(0.2)
        # what UnifiedTTSApp._engine_switched does
        c.cancel()
        c.cleanup_buffer()
        # The new engine is slower to start than the old one is to finish:
        # the stale clip lands first.
        c.engine = NamedEngine("new", delays={0: 0.2, 1: 0.3})
        c.start_playback_thread()
        gate.set()             # the old engine's clip completes now
        time.sleep(2.0)
        c.state = PlaybackController.State.STOPPED
        c.cancel()
        return player, old

    def test_a_clip_still_generating_in_the_old_engine_is_never_played(self):
        player, _ = self._switch_mid_generation()
        after_switch = player.log[1:]
        assert after_switch, "nothing played after the switch"
        assert not [p for p in after_switch if p.startswith("old")], after_switch

    def test_the_superseded_clip_is_deleted_not_leaked(self):
        _, old = self._switch_mid_generation()
        late = [p for p in old.paths if "-s1-" in os.path.basename(p)]
        assert late and not any(os.path.exists(p) for p in late)


class TestSlowSentences:
    def test_a_sentence_slower_than_the_wait_is_played_not_skipped(self):
        """When playback catches up with a lookahead still generating, it
        waits GENERATE_TIMEOUT -- then used to move on as if the sentence
        had nothing in it. Heavy voices on a busy machine get there."""
        engine = NamedEngine("slow", delays={1: 1.0})
        player = LogPlayer(0.1)
        c = PlaybackController(engine=engine, session_store=SessionStore(base_dir=tempfile.mkdtemp()),
                               player=player)
        c.GENERATE_TIMEOUT = 0.3
        c.RETRY_BACKOFF = 0.2
        c.load_text(" ".join(f"Sentence number {i} here." for i in range(4)))
        c.state = PlaybackController.State.PLAYING
        c.start_playback_thread()
        time.sleep(2.5)
        c.state = PlaybackController.State.STOPPED
        c.cancel()
        played = [int(p.split("-s")[1].split("-")[0]) for p in player.log]
        assert played[:3] == [0, 1, 2], f"sentence 1 was skipped: {played}"


class TestKokoroAccent:
    def test_uk_voices_get_british_pronunciation(self):
        assert voice_catalog.kokoro_lang_code("bf_emma") == "b"
        assert voice_catalog.kokoro_lang_code("bm_george") == "b"

    def test_us_and_unknown_voices_get_american(self):
        assert voice_catalog.kokoro_lang_code("af_heart") == "a"
        assert voice_catalog.kokoro_lang_code("") == "a"
        assert voice_catalog.kokoro_lang_code("zz_new") == "a"


class TestWorkerLog:
    def test_a_big_log_is_set_aside_when_a_worker_starts(self, tmp_path):
        import local_tts.engine as engine
        log = tmp_path / "voices-worker.log"
        log.write_text("x" * 2000)
        client = engine.VoiceWorkerClient(python=str(tmp_path / "no-python"), log_path=str(log))
        client.LOG_MAX_BYTES = 1000
        try:
            client._spawn()
        except RuntimeError:
            pass   # no interpreter there; the log is handled first
        assert (tmp_path / "voices-worker.log.old").read_text() == "x" * 2000
        assert not log.exists() or log.stat().st_size < 1000
