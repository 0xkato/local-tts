"""Tests for real playback-speed control.

Most of the neural voices have no speed control of their own, so speed comes
from time-stretching the generated clip, which preserves pitch.
"""
import math
import os
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
