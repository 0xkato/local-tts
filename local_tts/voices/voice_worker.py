#!/usr/bin/env python3
"""Voice worker: runs the neural TTS models in their own process.

The app's Tk interpreter cannot host these models -- mlx-audio needs Python
3.11+, and a multi-gigabyte model has no business sharing a process with the UI -- so
they live here, in the voices environment, one model at a time.

Protocol: one JSON object per line on stdin, one reply per line on the
original stdout. ML libraries print freely (some of it from C), so file
descriptor 1 is redirected to stderr at startup and replies go to a private
duplicate of it.

    {"id": 1, "op": "load",  "engine": "ming"}
    {"id": 2, "op": "synth", "engine": "ming", "voice": "US_James",
     "text": "...", "speed": 1.0, "out": "/tmp/x.wav"}
    {"id": 3, "op": "quit"}

Replies: {"id": n, "ok": true, ...} or {"id": n, "ok": false, "error": "..."},
each carrying "loaded": the engine now in memory (or null), so the client
never has to guess after a failure. While a request runs, {"id": n,
"heartbeat": true} goes out every few seconds: a first download takes
as long as the connection needs, and only silence means the worker is stuck.
"""
import gc
import json
import os
import sys
import threading
import time
import traceback
import wave

# Claim the reply channel before anything can print into it.
_REPLIES = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
_REPLIES_LOCK = threading.Lock()   # replies and heartbeats share the channel
HEARTBEAT_S = float(os.environ.get("LOCAL_TTS_HEARTBEAT_S", "5"))
os.dup2(2, 1)
sys.stdout = sys.stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import voice_catalog as catalog  # noqa: E402


# ── Audio post-processing ─────────────────────────────────────────────────

def even_pauses(audio: np.ndarray, rate: int, threshold: float = 0.01) -> np.ndarray:
    """Trim a clip's own leading/trailing silence and give it the standard
    pause, so every voice spaces its sentences the same way."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0:
        loud = np.where(np.abs(audio) > threshold * peak)[0]
        lead = int(catalog.LEAD_PAD * rate)
        audio = audio[max(0, loud[0] - lead): loud[-1] + 1]
    tail = np.zeros(int(catalog.TAIL_PAUSE * rate), dtype=np.float32)
    return np.concatenate([audio, tail])


def write_wav(path: str, audio: np.ndarray, rate: int) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def collect(results) -> tuple:
    """Join an mlx-audio generator's chunks into one clip."""
    parts, rate = [], None
    for r in results:
        parts.append(np.array(r.audio, dtype=np.float32).reshape(-1))
        rate = r.sample_rate
    if not parts:
        raise RuntimeError("the model produced no audio")
    return np.concatenate(parts), rate


# ── Engines ───────────────────────────────────────────────────────────────

class PhononEngine:
    def __init__(self, spec):
        import ptts
        self.tts = ptts.TTS("hf://" + spec.repo, lang="en", quant="q8")

    def synth(self, text, voice, speed):
        return self.tts.synth(text, voice=voice), self.tts.sample_rate


def _use_system_espeak():
    """misaki points espeak at a data path from pip's build machine, and
    libespeak calls exit() when it is missing. Point it at Homebrew's."""
    paths = catalog.espeak_paths()
    if paths is None:
        raise RuntimeError("Kokoro needs espeak-ng: brew install espeak-ng")
    import misaki.espeak  # noqa: F401 -- sets the broken paths on import
    import espeak_link
    espeak_link.install()   # started by a browser, a copied library is refused
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    EspeakWrapper.set_library(paths[0])
    EspeakWrapper.set_data_path(paths[1])


class MlxEngine:
    def __init__(self, spec):
        if spec.needs_espeak:
            _use_system_espeak()
        from mlx_audio.tts.utils import load_model
        self.spec = spec
        self.model = load_model(spec.repo)

    def synth(self, text, voice, speed):
        key = self.spec.key
        if key == "kokoro":
            return collect(self.model.generate(text=text, voice=voice, speed=speed, lang_code="a"))
        if key == "ming":
            return collect(self.model.generate(text=text, voice=voice, lang_code="en"))
        raise RuntimeError(f"no recipe for engine {key!r}")

    def unload(self):
        self.model = None
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass


class FakeEngine:
    """A tone generator for the test suite: no ML packages needed. Leaves
    silence on both ends, like real models do, and can misbehave on cue."""

    RATE = 16000

    def __init__(self, spec):
        delay = float(os.environ.get("LOCAL_TTS_FAKE_LOAD_DELAY", "0"))
        if delay:
            time.sleep(delay)

    def synth(self, text, voice, speed):
        if "NOISY" in text:
            # Progress bars write no newline, so unprotected chatter would
            # glue itself to the front of the next reply and corrupt it.
            sys.stdout.write("progress 50%\r")    # Python-level chatter
            sys.stdout.flush()
            os.write(1, b"C-level chatter")       # and from C
        if "FAIL" in text:
            raise RuntimeError("fake failure")
        if "CRASH" in text:
            os._exit(3)
        seconds = 0.01 * len(text) / max(speed, 0.1)
        t = np.arange(int(self.RATE * seconds)) / self.RATE
        tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        lead = np.zeros(int(0.5 * self.RATE), np.float32)
        tail = np.zeros(int(1.0 * self.RATE), np.float32)
        return np.concatenate([lead, tone, tail]), self.RATE


def make_engine(key):
    if key == "fake" and os.environ.get("LOCAL_TTS_FAKE_VOICES"):
        return FakeEngine(None)
    spec = catalog.BY_KEY.get(key)
    if spec is None:
        raise RuntimeError(f"unknown engine {key!r}")
    if spec.backend == "phonon":
        return PhononEngine(spec)
    return MlxEngine(spec)


# ── Request loop ──────────────────────────────────────────────────────────

class Worker:
    def __init__(self):
        self.key = None
        self.engine = None

    def load(self, key):
        if key == self.key:
            return 0.0
        self.unload()
        start = time.monotonic()
        spec = catalog.BY_KEY.get(key)
        engine = make_engine(key)
        # The first generation compiles kernels and builds pipelines -- a
        # second or more of dead air. Pay it here, while the app says
        # "Loading...", instead of after the user presses play.
        engine.synth("Hello there.", spec.default_voice if spec else None, 1.0)
        self.engine, self.key = engine, key
        return time.monotonic() - start

    def unload(self):
        if self.engine is not None and hasattr(self.engine, "unload"):
            self.engine.unload()
        self.engine, self.key = None, None
        gc.collect()

    def handle(self, req):
        op = req.get("op")
        if op == "ping":
            return {"pid": os.getpid()}
        if op == "load":
            return {"load_s": self.load(req["engine"]), "pid": os.getpid()}
        if op == "unload":
            self.unload()
            return {}
        if op == "synth":
            load_s = self.load(req["engine"])
            speed = float(req.get("speed", 1.0))
            start = time.monotonic()
            audio, rate = self.engine.synth(req["text"], req.get("voice"), speed)
            gen_s = time.monotonic() - start
            audio = even_pauses(audio, rate)
            write_wav(req["out"], audio, rate)
            return {"path": req["out"], "audio_s": len(audio) / rate,
                    "gen_s": gen_s, "load_s": load_s, "pid": os.getpid()}
        raise RuntimeError(f"unknown op {op!r}")


def reply(obj):
    line = json.dumps(obj) + "\n"
    with _REPLIES_LOCK:
        _REPLIES.write(line)
        _REPLIES.flush()


class Heartbeat:
    """Says "still working on request n" until the request is answered."""

    def __init__(self, request_id):
        self.request_id = request_id
        self.done = threading.Event()
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self):
        while not self.done.wait(HEARTBEAT_S):
            reply({"id": self.request_id, "heartbeat": True})

    def stop(self):
        self.done.set()


def exit_with_parent():
    """stdin is only read between requests, so a worker in the middle of a
    long load would not notice the app dying. Check the parent instead."""
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(1.0)
            if os.getppid() != parent:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def main():
    exit_with_parent()
    worker = Worker()
    reply({"id": 0, "ok": True, "ready": True, "pid": os.getpid(), "loaded": None})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("op") == "quit":
            reply({"id": req.get("id"), "ok": True, "loaded": worker.key})
            break
        heartbeat = Heartbeat(req.get("id"))
        try:
            result = worker.handle(req)
            result.update({"id": req.get("id"), "ok": True})
        except Exception as exc:
            traceback.print_exc()
            result = {"id": req.get("id"), "ok": False,
                      "error": f"{type(exc).__name__}: {exc}"}
        finally:
            heartbeat.stop()
        result["loaded"] = worker.key
        reply(result)
    worker.unload()


if __name__ == "__main__":
    main()
