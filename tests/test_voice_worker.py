"""The voice worker: a child process that holds one neural model at a time.

Driven through the real client against the worker's built-in fake engine, so
the protocol, stdout hygiene, crash recovery and voice switching are covered
without any of the ML packages installed.
"""
import os
import sys
import threading
import time
import wave

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("numpy")  # the worker itself needs numpy

from local_tts.voices import voice_catalog
from local_tts.engine import VoiceSwitched, VoiceWorkerClient


def make_client(tmp_path, **env):
    extra = {"LOCAL_TTS_FAKE_VOICES": "1"}
    extra.update(env)
    client = VoiceWorkerClient(
        python=sys.executable, log_path=str(tmp_path / "worker.log"), extra_env=extra,
    )
    # A protocol bug shows up as a lost reply: fail fast instead of hanging
    client.START_TIMEOUT = client.SYNTH_TIMEOUT = 10
    return client


def read_wav(path):
    with wave.open(path) as w:
        frames = w.readframes(w.getnframes())
        rate = w.getframerate()
    import numpy as np
    return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0, rate


def trailing_silence(samples, rate, threshold=0.01):
    import numpy as np
    loud = np.where(np.abs(samples) > threshold)[0]
    return (len(samples) - 1 - loud[-1]) / rate


@pytest.fixture
def client(tmp_path):
    c = make_client(tmp_path)
    c.set_active("fake")
    yield c
    c.close()


class TestSynth:
    def test_writes_a_playable_wav(self, client, tmp_path):
        out = str(tmp_path / "a.wav")
        reply = client.synth("fake", "Hello there.", voice="tone", speed=1.0, out_path=out)
        samples, rate = read_wav(out)
        assert reply["path"] == out
        assert rate == 16000
        assert len(samples) > 0.1 * rate

    def test_every_clip_ends_with_the_same_pause(self, client, tmp_path):
        """Models leave anywhere from no silence to a second of it; sentence
        spacing should not depend on which one is talking."""
        out = str(tmp_path / "a.wav")
        client.synth("fake", "A sentence with a long silent tail.", voice="tone", speed=1.0, out_path=out)
        samples, rate = read_wav(out)
        assert abs(trailing_silence(samples, rate) - voice_catalog.TAIL_PAUSE) < 0.05

    def test_replies_reach_the_caller_that_asked(self, client, tmp_path):
        """Lookahead and playback ask from different threads; each must get
        its own clip back, not a neighbour's."""
        texts = {i: "x" * (20 * (i + 1)) for i in range(4)}
        results, errors = {}, []

        def ask(i):
            try:
                out = str(tmp_path / f"{i}.wav")
                client.synth("fake", texts[i], voice="tone", speed=1.0, out_path=out)
                results[i] = read_wav(out)
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=ask, args=(i,)) for i in texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert not errors, errors
        lengths = [len(results[i][0]) for i in sorted(results)]
        assert lengths == sorted(lengths), "a caller received another caller's clip"


class TestStdoutHygiene:
    def test_library_chatter_does_not_corrupt_replies(self, client, tmp_path):
        """ML libraries print progress to stdout, some of it from C; none of
        that may land in the reply channel."""
        out = str(tmp_path / "a.wav")
        reply = client.synth("fake", "NOISY please", voice="tone", speed=1.0, out_path=out)
        assert reply["path"] == out
        reply = client.synth("fake", "and again", voice="tone", speed=1.0, out_path=out)
        assert reply["path"] == out


class TestFailures:
    def test_engine_error_is_reported_and_the_worker_survives(self, client, tmp_path):
        out = str(tmp_path / "a.wav")
        client.synth("fake", "warm up", voice="tone", speed=1.0, out_path=out)
        pid = client.pid
        with pytest.raises(RuntimeError, match="fake failure"):
            client.synth("fake", "FAIL now", voice="tone", speed=1.0, out_path=out)
        client.synth("fake", "still alive", voice="tone", speed=1.0, out_path=out)
        assert client.pid == pid

    def test_a_crashed_worker_is_replaced_on_the_next_request(self, client, tmp_path):
        out = str(tmp_path / "a.wav")
        client.synth("fake", "warm up", voice="tone", speed=1.0, out_path=out)
        pid = client.pid
        with pytest.raises(RuntimeError):
            client.synth("fake", "CRASH now", voice="tone", speed=1.0, out_path=out)
        client.synth("fake", "back again", voice="tone", speed=1.0, out_path=out)
        assert client.pid != pid

    def test_missing_interpreter_is_a_clear_error(self, tmp_path):
        c = VoiceWorkerClient(python=str(tmp_path / "nope" / "python"), log_path=str(tmp_path / "w.log"))
        c.set_active("fake")
        with pytest.raises(RuntimeError, match="voices environment"):
            c.synth("fake", "hi", voice="tone", speed=1.0, out_path=str(tmp_path / "a.wav"))


class TestSwitchingVoices:
    def test_stale_requests_are_refused_without_waking_the_worker(self, tmp_path):
        """A lookahead thread still holding the old engine must not make the
        worker reload a 24 GB model the user just switched away from."""
        c = make_client(tmp_path)
        c.set_active("other")
        with pytest.raises(VoiceSwitched):
            c.synth("fake", "hi", voice="tone", speed=1.0, out_path=str(tmp_path / "a.wav"))
        assert c.pid is None
        c.close()

    def test_switching_away_aborts_a_slow_load(self, tmp_path):
        c = make_client(tmp_path, LOCAL_TTS_FAKE_LOAD_DELAY="30")
        c.set_active("fake")
        outcome = {}

        def preload():
            start = time.monotonic()
            try:
                c.load("fake")
                outcome["result"] = "loaded"
            except Exception as exc:
                outcome["result"] = exc
            outcome["took"] = time.monotonic() - start

        t = threading.Thread(target=preload)
        t.start()
        time.sleep(1.0)  # let the load get going
        c.set_active("something-else")
        t.join(10)
        c.close()
        assert not t.is_alive(), "the load kept the caller waiting"
        assert isinstance(outcome["result"], Exception)
        assert outcome["took"] < 8

    def test_close_stops_the_process(self, client, tmp_path):
        client.synth("fake", "hi", voice="tone", speed=1.0, out_path=str(tmp_path / "a.wav"))
        assert client.pid is not None
        client.close()
        assert client.pid is None


# ── Races around start-up, failed loads and long downloads ─────────────────
# Regression cover from review: each of these let a model the user had
# already walked away from keep loading (up to 24 GB), or killed a download.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_WORKER = os.path.join(REPO, "local_tts", "voices", "voice_worker.py")

SLOW_START = """
import os, runpy, sys, time
time.sleep(float(os.environ["SLOW_START"]))   # python + numpy on a busy machine
sys.argv = [os.environ["REAL_WORKER"]]
runpy.run_path(os.environ["REAL_WORKER"], run_name="__main__")
"""


def slow_start_client(tmp_path, start_s, **env):
    script = tmp_path / "slow_worker.py"
    script.write_text(SLOW_START)
    extra = {"LOCAL_TTS_FAKE_VOICES": "1", "SLOW_START": str(start_s), "REAL_WORKER": REAL_WORKER}
    extra.update(env)
    c = VoiceWorkerClient(python=sys.executable, script=str(script),
                          log_path=str(tmp_path / "worker.log"), extra_env=extra)
    c.START_TIMEOUT = c.SYNTH_TIMEOUT = 10
    return c


def load_in_background(client, key):
    outcome = {}

    def run():
        start = time.monotonic()
        try:
            client.load(key)
            outcome["result"] = "loaded"
        except Exception as exc:
            outcome["result"] = exc
        outcome["took"] = time.monotonic() - start

    t = threading.Thread(target=run)
    t.start()
    return t, outcome


class TestStartupRaces:
    def test_switching_while_the_worker_starts_aborts_the_old_load(self, tmp_path):
        c = slow_start_client(tmp_path, 1.5, LOCAL_TTS_FAKE_LOAD_DELAY="8")
        c.set_active("fake")
        t, outcome = load_in_background(c, "fake")
        time.sleep(0.5)                 # the worker is still starting
        c.set_active("other")
        t.join(20)
        c.close()
        assert isinstance(outcome["result"], Exception), "the abandoned model loaded anyway"
        assert outcome["took"] < 5

    def test_closing_while_the_worker_starts_leaves_nothing_running(self, tmp_path, monkeypatch):
        import local_tts.engine as tts_unified
        real_popen = tts_unified.subprocess.Popen
        spawned = []

        def slow_popen(*a, **kw):
            time.sleep(0.5)             # widen the fork/exec window
            proc = real_popen(*a, **kw)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(tts_unified.subprocess, "Popen", slow_popen)
        c = make_client(tmp_path)
        c.set_active("fake")
        t, outcome = load_in_background(c, "fake")
        time.sleep(0.2)
        c.close()                       # the user closed the app
        t.join(15)
        time.sleep(0.5)
        alive = [p for p in spawned if p.poll() is None]
        for p in alive:
            p.kill()
        assert not alive, "a worker kept running after close()"
        assert isinstance(outcome["result"], Exception)


class TestLoadedStateStaysTrue:
    def test_a_failed_load_does_not_hide_the_next_reload(self, tmp_path):
        """The worker drops its model before loading the next; if that load
        fails it holds nothing, and reloading the old one is a full load the
        user must still be able to abandon."""
        c = make_client(tmp_path, LOCAL_TTS_FAKE_LOAD_DELAY="2")
        c.set_active("fake")
        c.load("fake")
        c.set_active("bogus")
        with pytest.raises(RuntimeError):
            c.load("bogus")
        c.set_active("fake")
        t, outcome = load_in_background(c, "fake")
        time.sleep(0.7)
        c.set_active("ming")
        t.join(10)
        c.close()
        assert isinstance(outcome["result"], Exception), "the reload could not be abandoned"
        assert outcome["took"] < 1.8


class TestLongLoads:
    def test_a_load_longer_than_the_timeout_survives_on_heartbeats(self, tmp_path):
        """A first use downloads up to 24 GB; on an ordinary connection that
        outlasts any fixed timeout. Silence, not duration, means trouble."""
        c = make_client(tmp_path, LOCAL_TTS_FAKE_LOAD_DELAY="2.5", LOCAL_TTS_HEARTBEAT_S="0.3")
        c.LOAD_TIMEOUT = 1.0
        c.set_active("fake")
        try:
            c.load("fake")
        finally:
            c.close()
