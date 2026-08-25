"""Tests for real playback-speed control.

gTTS exposes only 'normal' and 'slow', so every setting from 1.0x up produced
byte-identical audio while the label claimed otherwise. Actual speed comes from
time-stretching the generated clip, which preserves pitch.
"""
import math
import os
import subprocess
import sys
import tempfile
import wave

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_unified import atempo_chain, ffmpeg_available, time_stretch


def make_wav(seconds=2.0, rate=22050):
    """A plain tone file to re-time."""
    path = tempfile.mktemp(suffix=".wav")
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            value = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            frames += value.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return path


def duration(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


class TestAtempoChain:
    """ffmpeg's atempo filter only accepts 0.5-2.0, so wider ratios chain."""

    def test_plain_speed_is_one_filter(self):
        assert atempo_chain(1.5) == "atempo=1.5"

    def test_slow_end_of_slider(self):
        assert atempo_chain(0.5) == "atempo=0.5"

    def test_above_range_chains(self):
        chain = atempo_chain(4.0)
        assert chain.count("atempo") == 2
        product = 1.0
        for part in chain.split(","):
            product *= float(part.split("=")[1])
        assert product == pytest.approx(4.0)

    def test_below_range_chains(self):
        chain = atempo_chain(0.25)
        product = 1.0
        for part in chain.split(","):
            product *= float(part.split("=")[1])
        assert product == pytest.approx(0.25)


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
class TestTimeStretch:
    def test_faster_clip_is_shorter(self):
        src = make_wav(2.0)
        out = time_stretch(src, 2.0)
        assert duration(out) == pytest.approx(1.0, abs=0.1)
        os.unlink(out)

    def test_slower_clip_is_longer(self):
        src = make_wav(1.0)
        out = time_stretch(src, 0.5)
        assert duration(out) == pytest.approx(2.0, abs=0.1)
        os.unlink(out)

    def test_speed_of_one_returns_source_untouched(self):
        src = make_wav(1.0)
        assert time_stretch(src, 1.0) == src
        os.unlink(src)

    def test_source_is_not_leaked(self):
        """The re-timed copy replaces the original, which must not linger."""
        src = make_wav(1.0)
        out = time_stretch(src, 1.5)
        assert out != src
        assert not os.path.exists(src)
        os.unlink(out)

    def test_failure_falls_back_to_source(self):
        """A clip ffmpeg cannot read is still playable at its natural speed."""
        bogus = tempfile.mktemp(suffix=".wav")
        with open(bogus, "wb") as f:
            f.write(b"not audio")
        assert time_stretch(bogus, 1.5) == bogus
        os.unlink(bogus)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


class FakeGTTS:
    """Stands in for gTTS: writes a fixed 2s clip, ignoring speed entirely --
    which is exactly what the real gTTS does above 1.0x."""
    source = None
    calls = []

    def __init__(self, text, lang="en", slow=False):
        FakeGTTS.calls.append({"text": text, "lang": lang, "slow": slow})

    def save(self, path):
        with open(FakeGTTS.source, "rb") as src, open(path, "wb") as dst:
            dst.write(src.read())


class TestEngineSpeedSupport:
    def test_piper_always_supports_speed(self):
        from tts_unified import PiperTTSEngine
        assert PiperTTSEngine().supports_speed() is True

    def test_google_speed_support_tracks_ffmpeg(self):
        from tts_unified import GoogleTTSEngine
        assert GoogleTTSEngine().supports_speed() == ffmpeg_available()


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
class TestGoogleEngineHonoursSpeed:
    def setup_method(self):
        import tts_unified
        self.mod = tts_unified
        self.real_gtts = tts_unified.gTTS
        self.real_flag = tts_unified.GTTS_AVAILABLE
        FakeGTTS.source = make_wav(2.0)
        FakeGTTS.calls = []
        tts_unified.gTTS = FakeGTTS
        tts_unified.GTTS_AVAILABLE = True

    def teardown_method(self):
        self.mod.gTTS = self.real_gtts
        self.mod.GTTS_AVAILABLE = self.real_flag
        if FakeGTTS.source and os.path.exists(FakeGTTS.source):
            os.unlink(FakeGTTS.source)

    def test_faster_setting_produces_shorter_audio(self):
        """The reported defect: 1.0x and 2.0x were byte-identical."""
        engine = self.mod.GoogleTTSEngine()
        normal = engine.generate("hello there", 1.0)
        fast = engine.generate("hello there", 2.0)
        assert probe_duration(fast) < probe_duration(normal) * 0.7
        os.unlink(normal)
        os.unlink(fast)

    def test_slower_setting_produces_longer_audio(self):
        engine = self.mod.GoogleTTSEngine()
        normal = engine.generate("hello there", 1.0)
        slow = engine.generate("hello there", 0.5)
        assert probe_duration(slow) > probe_duration(normal) * 1.5
        os.unlink(normal)
        os.unlink(slow)

    def test_does_not_also_ask_gtts_for_slow(self):
        """Stacking gTTS 'slow' on top of a time-stretch would double-slow it."""
        engine = self.mod.GoogleTTSEngine()
        out = engine.generate("hello there", 0.5)
        assert FakeGTTS.calls[-1]["slow"] is False
        os.unlink(out)
