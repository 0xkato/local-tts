#!/usr/bin/env python3
"""
Unified Text-to-Speech Application
Supports Google TTS and Piper TTS engines
"""

import re
import hashlib
import math
import json
import time
from enum import Enum
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import os
import sys
import tempfile
import subprocess
import shutil
from typing import Optional, Callable
from abc import ABC, abstractmethod

# Required imports
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class SentenceSplitter:
    """Splits text into sentences, respecting abbreviations and ellipses."""

    ABBREVIATIONS = {
        'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'ave', 'blvd',
        'dept', 'est', 'fig', 'ft', 'gen', 'gov', 'inc', 'lt', 'mt', 'no',
        'sgt', 'vs',
    }

    # Abbreviations with internal dots like u.s, e.g, i.e
    DOTTED_ABBREVIATIONS = {'u.s', 'e.g', 'i.e'}

    # Characters that can follow sentence-ending punctuation (closing quotes/parens)
    CLOSING_PUNCTUATION = {'"', "'", '\u201d', '\u2019', ')', ']', '\u00bb'}

    # Markers that start a line item: each such line is one TTS unit
    BULLET_MARKERS = {'-', '*', '+', '\u2022', '\u25cf', '\u25aa'}
    MAX_LIST_NUMBER_DIGITS = 3

    def _at_line_start(self, text: str, pos: int) -> bool:
        """True if only spaces/tabs sit between pos and the start of its line."""
        j = pos - 1
        while j >= 0 and text[j] in ' \t':
            j -= 1
        return j < 0 or text[j] == '\n'

    def _is_numbered_list_dot(self, text: str, dot_pos: int) -> bool:
        """Check if a dot at dot_pos is part of a numbered list marker like '1.' or '12.'

        Requires the number to start its line and the dot to be followed by
        whitespace, so 'He scored 3.' is not a marker, and neither are the
        decimals and years that open a paragraph -- '1.5x is fast.' and
        '2024. What a year.' used to swallow their whole paragraph as one unit.
        """
        # Walk back over digits
        j = dot_pos - 1
        while j >= 0 and text[j].isdigit():
            j -= 1
        digits = dot_pos - 1 - j
        if digits == 0:
            return False  # no digit before the dot
        if digits > self.MAX_LIST_NUMBER_DIGITS:
            return False  # a year or a long figure, not a list index
        # A real marker is followed by a space; "1.5x" and "3.14" are not
        after = dot_pos + 1
        if after >= len(text) or text[after] not in ' \t':
            return False
        return self._at_line_start(text, j + 1)

    def _is_line_item_start(self, text: str, pos: int) -> bool:
        """True if pos opens a bullet or heading line, which reads as one unit."""
        if not self._at_line_start(text, pos):
            return False
        ch = text[pos]
        if ch == '#':
            return True
        if ch in self.BULLET_MARKERS:
            nxt = pos + 1
            return nxt < len(text) and text[nxt] in ' \t'
        return False

    def get_positions(self, text: str) -> list[tuple[int, int]]:
        if not text or not text.strip():
            return []

        positions = []
        n = len(text)
        i = 0
        sentence_start = None
        in_list_item = False

        while i < n:
            # Skip leading whitespace before a sentence
            if sentence_start is None:
                if text[i].isspace():
                    i += 1
                    continue
                sentence_start = i
                # Bullets and headings run to the end of their line: they carry
                # no terminal punctuation, so without this they merge into the
                # paragraph that follows.
                in_list_item = self._is_line_item_start(text, i)

            # Inside a list item, a newline ends the sentence (each line = one item)
            if in_list_item and text[i] == '\n':
                end = i
                while end > sentence_start and text[end - 1].isspace():
                    end -= 1
                if end > sentence_start:
                    positions.append((sentence_start, end))
                sentence_start = None
                in_list_item = False
                i += 1
                continue

            # Check for ellipsis (3+ dots)
            if text[i] == '.' and i + 2 < n and text[i + 1] == '.' and text[i + 2] == '.':
                # Skip all dots in the ellipsis
                while i < n and text[i] == '.':
                    i += 1
                continue

            if text[i] in '.!?':
                # Check if this is an abbreviation
                if text[i] == '.':
                    # Check for numbered list markers like "1.", "23."
                    if self._is_numbered_list_dot(text, i):
                        in_list_item = True
                        i += 1
                        continue

                # Inside a list item: don't split on sentence punctuation —
                # the whole item is one TTS unit, ended only by newline or EOF
                if in_list_item:
                    i += 1
                    continue

                if text[i] == '.':
                    # Check for dotted abbreviations like U.S.
                    # Look back to find the start of a potential dotted abbreviation
                    is_abbrev = False

                    # Check standard abbreviations (word before the dot)
                    # Find the word before the dot
                    j = i - 1
                    while j >= 0 and text[j].isalpha():
                        j -= 1
                    word = text[j + 1:i].lower()
                    if word in self.ABBREVIATIONS:
                        is_abbrev = True

                    # Check dotted abbreviations like U.S.
                    if not is_abbrev:
                        # Look back for pattern like X.X. (e.g., U.S.)
                        # Collect chars backwards
                        j = i
                        dotted = ''
                        while j >= 0:
                            if text[j] == '.':
                                dotted = '.' + dotted
                                j -= 1
                            elif text[j].isalpha():
                                dotted = text[j] + dotted
                                j -= 1
                            else:
                                break
                        # Remove trailing dot for matching
                        dotted_lower = dotted.rstrip('.').lower()
                        if dotted_lower in self.DOTTED_ABBREVIATIONS:
                            is_abbrev = True

                    if is_abbrev:
                        i += 1
                        continue

                # This looks like a sentence-ending punctuation
                # Include any closing punctuation that follows (quotes, parens)
                end_pos = i + 1
                while end_pos < n and text[end_pos] in self.CLOSING_PUNCTUATION:
                    end_pos += 1

                if end_pos >= n or text[end_pos].isspace():
                    # End of sentence found
                    positions.append((sentence_start, end_pos))
                    sentence_start = None
                    i = end_pos
                    continue

            i += 1

        # Handle remaining text (no terminal punctuation)
        if sentence_start is not None:
            # Trim trailing whitespace
            end = n
            while end > sentence_start and text[end - 1].isspace():
                end -= 1
            if end > sentence_start:
                positions.append((sentence_start, end))

        return positions

    def split(self, text: str) -> list[str]:
        positions = self.get_positions(text)
        return [text[start:end] for start, end in positions]


# ── Text normalization ──────────────────────────────────────────────────────
# Both gTTS and Piper (via espeak-ng) already speak numerals, currency, times
# and percentages correctly, so we deliberately leave digits alone: rewriting
# "1,000" or "3.14" into words destroys information the engine would have
# voiced properly. What the engines *cannot* handle is markup -- they read
# "**", "##" and URLs out literally -- so that is what we strip here.

_MD_LINK_RE = re.compile(r'\[([^\]\n]+)\]\([^)\n]*\)')
_BARE_URL_RE = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
_HEADING_RE = re.compile(r'^#{1,6}\s*')
_BULLET_RE = re.compile(r'^[-*+\u2022\u25cf\u25aa]\s+')
_LIST_NUM_RE = re.compile(r'^(\d{1,3})[.)]\s+')
# Emphasis delimiters only count when they sit outside a word, so identifiers
# like generate_sentence and file_name_here survive intact.
_EMPHASIS_RE = re.compile(r'(?<![\w*_])(\*\*\*|___|\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1(?![\w*_])')
# A dash reads as a pause only when it separates two things: spaced out
# ("details -- it's striking") or joining two words ("result--surprisingly").
# "--length_scale" is a command-line flag and is left alone.
_DASH_RE = re.compile(r'\s+(?:--+|[\u2014\u2013])\s+|(?<=\w)(?:--+|[\u2014\u2013])(?=\w)')
# "3.5–4.2%" is a range, and reads as a range
_NUM_RANGE_RE = re.compile(r'(?<=\d)\s*[\u2013\u2014]\s*(?=\d)')
_CHECKBOX_RE = re.compile(r'^\[[ xX]?\]\s*')
_STRAY_MARKUP_RE = re.compile(r'[`*#~|>]')
# Curly quotes are folded to ASCII rather than dropped -- deleting the
# apostrophe in "don’t" would leave the engine saying "dont".
_SMART_QUOTES = {
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2032': "'",
}
_SPEAKABLE_RE = re.compile(r'[^\W_]', re.UNICODE)


def normalize_for_tts(text: str) -> str:
    """Prepare one sentence for the TTS engine.

    Strips markup that engines would otherwise read aloud, collapses the
    newlines that line-wrapped text leaves mid-sentence, and leaves all
    numbers and words exactly as written. Returns "" when nothing speakable
    is left (a horizontal rule, a stray bullet), so the caller can skip it.
    """
    if not text:
        return ""

    # Links first, so [label](url) keeps its label before bare URLs are dropped
    text = _MD_LINK_RE.sub(r'\1', text)
    text = _BARE_URL_RE.sub('link', text)

    # Leading line markers, on the sentence as the splitter handed it to us
    text = text.strip()
    text = _HEADING_RE.sub('', text)
    text = _BULLET_RE.sub('', text)
    text = _CHECKBOX_RE.sub('', text)
    # "3. Walk the dog" -> "3, Walk the dog": a bare "3." reads as a full stop,
    # which makes the engine pause as if the item had ended.
    text = _LIST_NUM_RE.sub(r'\1, ', text)

    for curly, plain in _SMART_QUOTES.items():
        text = text.replace(curly, plain)
    text = text.replace('`', '')
    text = _EMPHASIS_RE.sub(r'\2', text)
    text = _NUM_RANGE_RE.sub(' to ', text)
    text = _DASH_RE.sub(', ', text)
    text = re.sub(r'\s*&\s*', ' and ', text)

    # Anything left is decoration the engine would pronounce
    text = _STRAY_MARKUP_RE.sub('', text)

    # Collapse the newlines line-wrapped text leaves mid-sentence
    text = ' '.join(text.split())
    # Tidy spacing the substitutions above may have left behind
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    text = re.sub(r'^[,.;:]\s*', '', text)

    if not _SPEAKABLE_RE.search(text):
        return ""
    return text


class SessionStore:
    """Persistent storage for playback positions, keyed by text hash."""

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.expanduser("~/.local/share/local-tts")
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.sessions_file = os.path.join(self.base_dir, "sessions.json")

    def _text_hash(self, text: str) -> str:
        """SHA256 of first 500 chars, truncated to 16 hex chars."""
        return hashlib.sha256(text[:500].encode("utf-8")).hexdigest()[:16]

    def _load_sessions(self) -> dict:
        """Read sessions.json and return dict."""
        if not os.path.exists(self.sessions_file):
            return {}
        try:
            with open(self.sessions_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_sessions(self, sessions: dict) -> None:
        """Write sessions dict to sessions.json."""
        with open(self.sessions_file, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)

    def save_position(self, text: str, sentence_index: int, speed: float, engine: str) -> None:
        """Save playback position with timestamp."""
        sessions = self._load_sessions()
        key = self._text_hash(text)
        sessions[key] = {
            "sentence_index": sentence_index,
            "speed": speed,
            "engine": engine,
            "timestamp": time.time(),
        }
        self._save_sessions(sessions)

    def load_position(self, text: str) -> dict | None:
        """Return saved position dict or None."""
        sessions = self._load_sessions()
        return sessions.get(self._text_hash(text))

    def delete_position(self, text: str) -> None:
        """Remove saved position for the given text."""
        sessions = self._load_sessions()
        key = self._text_hash(text)
        if key in sessions:
            del sessions[key]
            self._save_sessions(sessions)

    def _last_text_path(self) -> str:
        return os.path.join(self.base_dir, "last_text.txt")

    def save_last_text(self, text: str) -> None:
        """Remember the article, so reopening does not mean re-pasting it.

        Blank text is ignored: closing an empty window should not wipe what was
        saved from the previous session.
        """
        if not text or not text.strip():
            return
        try:
            with open(self._last_text_path(), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def load_last_text(self) -> str | None:
        try:
            with open(self._last_text_path(), "r", encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None

    def prune_old(self, max_age_days: int = 30, max_sessions: int = 50) -> None:
        """Remove sessions older than max_age_days and keep at most max_sessions."""
        sessions = self._load_sessions()
        cutoff = time.time() - (max_age_days * 86400)
        # Remove expired sessions
        sessions = {k: v for k, v in sessions.items() if v.get("timestamp", 0) >= cutoff}
        # If still over limit, keep the most recent
        if len(sessions) > max_sessions:
            sorted_keys = sorted(sessions, key=lambda k: sessions[k].get("timestamp", 0), reverse=True)
            sessions = {k: sessions[k] for k in sorted_keys[:max_sessions]}
        self._save_sessions(sessions)


# ── Duration estimates ──────────────────────────────────────────────────────
# Calibrated against measured Piper output: an eight-word sentence took ~3.4s at
# 1.0x, and a fourteen-word one ~5.9s, both landing near 140 words per minute.
WORDS_PER_MINUTE = 140


def estimate_seconds(text: str, speed: float = 1.0) -> float:
    """Roughly how long `text` takes to read aloud at `speed`."""
    words = len(text.split())
    if not words:
        return 0
    return words / WORDS_PER_MINUTE * 60.0 / max(speed, 0.1)


def format_duration(seconds: float) -> str:
    """A short, human duration: '45 sec', '10 min', '1 hr 15 min'."""
    seconds = int(max(0, round(seconds)))
    if seconds < 60:
        return f"{seconds} sec"
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    return f"{hours} hr {remainder} min" if remainder else f"{hours} hr"


# ── Playback speed ──────────────────────────────────────────────────────────
# gTTS offers only "normal" and "slow", so asking it for 1.5x returns exactly
# the same audio as 1.0x. Real speed control means re-timing the clip after the
# fact; ffmpeg's atempo filter does it without the chipmunk pitch shift that
# naive resampling causes. Without ffmpeg we fall back to what gTTS can do and
# say so in the UI rather than showing a slider that does nothing.

_FFMPEG_CHECKED = None


def ffmpeg_available() -> bool:
    """Whether ffmpeg is on PATH. Probed once, then remembered."""
    global _FFMPEG_CHECKED
    if _FFMPEG_CHECKED is None:
        _FFMPEG_CHECKED = shutil.which("ffmpeg") is not None
    return _FFMPEG_CHECKED


def atempo_chain(speed: float) -> str:
    """Build an atempo filter chain for any ratio.

    A single atempo only accepts 0.5-2.0, so ratios outside that are split into
    several passes whose product is the requested speed.
    """
    factors = []
    remaining = float(speed)
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join("atempo={:.6g}".format(f) for f in factors)


def time_stretch(path: str, speed: float) -> str:
    """Re-time an audio file, preserving pitch.

    Returns the path to play. The re-timed copy replaces the original, so the
    source is removed on success. Returns `path` unchanged when there is nothing
    to do or when ffmpeg cannot read the file -- a clip at the wrong speed still
    beats no clip at all.
    """
    if abs(speed - 1.0) < 0.01 or not ffmpeg_available():
        return path
    root, ext = os.path.splitext(path)
    out_path = root + ".speed" + (ext or ".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
             "-i", path, "-filter:a", atempo_chain(speed), out_path],
            capture_output=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return path
    if result.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass
        return path
    try:
        os.unlink(path)
    except OSError:
        pass
    return out_path


class TTSEngine(ABC):
    """Abstract base class for TTS engines"""

    @abstractmethod
    def generate(self, text: str, speed: float, **kwargs) -> str:
        """Generate audio file from text. Returns path to temp audio file."""
        pass

    @abstractmethod
    def speak(self, text: str, speed: float, callback: Optional[Callable] = None) -> None:
        """Generate and play speech from text"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop current speech playback"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available"""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the display name of this engine"""
        pass

    def supports_speed(self) -> bool:
        """Whether this engine can actually honour the speed setting."""
        return True


class GoogleTTSEngine(TTSEngine):
    """Google TTS using gTTS"""

    def __init__(self):
        self.is_playing = False
        self.current_audio_file = None

    def generate(self, text: str, speed: float, language: str = "en") -> str:
        """Generate audio file from text. Returns path to temp audio file."""
        if not GTTS_AVAILABLE:
            raise Exception("gTTS not available")
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_file.close()
        # gTTS has no real speed control, only a "slow" flag. When we can
        # re-time the clip ourselves we ask for normal speed and stretch it;
        # otherwise "slow" is the only slower-than-normal option we have.
        slow = speed < 1.0 and not ffmpeg_available()
        tts = gTTS(text=text, lang=language, slow=slow)
        tts.save(tmp_file.name)
        return time_stretch(tmp_file.name, speed)

    def speak(self, text: str, speed: float, callback: Optional[Callable] = None, language: str = "en") -> None:
        if not GTTS_AVAILABLE or not PYGAME_AVAILABLE:
            raise Exception("gTTS or pygame not available")

        self.is_playing = True
        try:
            self.current_audio_file = self.generate(text, speed, language=language)

            pygame.mixer.music.load(self.current_audio_file)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy() and self.is_playing:
                pygame.time.Clock().tick(10)
        finally:
            self.is_playing = False
            if self.current_audio_file and os.path.exists(self.current_audio_file):
                try:
                    os.unlink(self.current_audio_file)
                except:
                    pass
            if callback:
                callback()
    
    def stop(self) -> None:
        self.is_playing = False
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
    
    def is_available(self) -> bool:
        return GTTS_AVAILABLE and PYGAME_AVAILABLE
    
    def get_name(self) -> str:
        return "Google TTS"

    def supports_speed(self) -> bool:
        # Without ffmpeg the slider can only pick between normal and slow
        return ffmpeg_available()


class PiperTTSEngine(TTSEngine):
    """Piper TTS for offline high-quality speech"""
    
    def __init__(self):
        self.is_playing = False
        self.current_audio_file = None
        self.piper_dir = os.path.expanduser("~/.local/share/piper")
        self.voice_model = os.path.join(self.piper_dir, "en_US-norman-medium.onnx")
        self.voice_config = os.path.join(self.piper_dir, "en_US-norman-medium.onnx.json")
        self._piper_installed = None
    
    GENERATE_TIMEOUT = 60  # seconds before a wedged piper process is killed

    def generate(self, text: str, speed: float, **kwargs) -> str:
        """Generate audio file from text. Returns path to temp audio file."""
        if not self.is_available():
            raise Exception("Piper TTS not available")
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_file.close()
        length_scale = 1.0 / speed
        process = subprocess.Popen(
            ["piper", "--model", self.voice_model, "--output_file", tmp_file.name, "--length_scale", str(length_scale)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            stdout, stderr = process.communicate(input=text, timeout=self.GENERATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Without this a wedged piper holds the sentence forever, and the
            # buffer's own waiters block behind it.
            process.kill()
            process.wait(timeout=5)
            raise Exception(
                f"Piper timed out after {self.GENERATE_TIMEOUT}s generating this sentence"
            )
        if process.returncode != 0:
            raise Exception(f"Piper failed: {stderr}")
        return tmp_file.name

    def speak(self, text: str, speed: float, callback: Optional[Callable] = None) -> None:
        if not self.is_available():
            raise Exception("Piper TTS not available")

        self.is_playing = True
        try:
            self.current_audio_file = self.generate(text, speed)

            pygame.mixer.music.load(self.current_audio_file)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy() and self.is_playing:
                pygame.time.Clock().tick(10)
        finally:
            self.is_playing = False
            if self.current_audio_file and os.path.exists(self.current_audio_file):
                try:
                    os.unlink(self.current_audio_file)
                except:
                    pass
            if callback:
                callback()
    
    def stop(self) -> None:
        self.is_playing = False
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
    
    def is_available(self) -> bool:
        if not PYGAME_AVAILABLE:
            return False
        
        # Check if piper command is available
        if not self.check_piper_installed():
            return False
        
        return os.path.exists(self.voice_model)
    
    def get_name(self) -> str:
        return "Piper TTS"
    
    def check_piper_installed(self) -> bool:
        """Whether the piper command exists, probed once and remembered.

        is_available() runs before every play press, and spawning
        'piper --help' each time cost ~160ms of dead air.
        """
        if self._piper_installed is None:
            try:
                result = subprocess.run(
                    ["piper", "--help"], capture_output=True, text=True, timeout=2
                )
                self._piper_installed = result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                self._piper_installed = False
        return self._piper_installed

    def invalidate_availability(self) -> None:
        """Re-probe on the next check, after an install or a voice download."""
        self._piper_installed = None
    
    def download_model(self, status_callback: Callable[[str], None]) -> bool:
        """Download the Piper voice model"""
        try:
            import urllib.request
            
            os.makedirs(self.piper_dir, exist_ok=True)
            
            model_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx"
            config_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json"
            
            status_callback("Downloading model file (12MB)...")
            urllib.request.urlretrieve(model_url, self.voice_model)
            
            status_callback("Downloading config file...")
            urllib.request.urlretrieve(config_url, self.voice_config)
            
            status_callback("Voice model downloaded successfully!")
            return True
        except Exception as e:
            status_callback(f"Download failed: {str(e)}")
            return False


class AudioPlayer:
    """pygame.mixer.music behind a swappable interface, so playback logic can
    be exercised without an audio device."""

    def play(self, path: str) -> None:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()

    def is_busy(self) -> bool:
        # Tolerant of a mixer that was never started or is already torn down:
        # cancel() runs on load, on close, and before the first play.
        try:
            return pygame.mixer.music.get_busy()
        except pygame.error:
            return False

    def stop(self) -> None:
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass


class PlaybackController:
    """Owns sentence-by-sentence playback: the audio buffer, the worker thread,
    and the generation token that keeps exactly one thread in charge.

    Every playback thread carries the generation token it was born with and
    re-checks it before each step that touches shared state. Skipping bumps the
    generation, which retires the running thread wherever it happens to be --
    no flag to race on, and no thread to wait for.
    """

    class State(Enum):
        STOPPED = "stopped"
        PLAYING = "playing"
        PAUSED = "paused"

    LOOKAHEAD = 3          # sentences pre-generated ahead of the one playing
    KEEP_BEHIND = 2        # sentences of audio kept for a quick 'prev'
    POLL_INTERVAL = 0.05   # seconds between "is the clip still playing?" checks
    GENERATE_TIMEOUT = 60  # seconds a waiter blocks on someone else's generate
    GENERATE_ATTEMPTS = 3  # tries before a sentence is reported as failed
    RETRY_BACKOFF = 0.4    # seconds, multiplied by the attempt number

    def __init__(self, engine=None, session_store=None, player=None):
        self.engine = engine
        self.session_store = session_store
        self.splitter = SentenceSplitter()

        self.state = self.State.STOPPED
        self.sentences = []
        self.positions = []
        self.current_index = 0
        self.total_sentences = 0
        self.original_text = ""

        if player is None and PYGAME_AVAILABLE:
            player = AudioPlayer()
        self._player = player

        self._buffer = {}        # buffer key -> generated audio file path
        self._inflight = {}      # buffer key -> Event, set when generation ends
        self._errors = {}        # buffer key -> exception from a failed generate
        self._buffer_lock = threading.Lock()
        self._active_path = None

        self._generation = 0
        self._gen_lock = threading.RLock()
        self._threads = []
        self._thread_lock = threading.Lock()

        # Hooks the UI fills in; each is called from the playback thread.
        self.on_sentence_start = None
        self.on_generating = None
        self.on_finished = None
        self.on_error = None
        self.params_provider = lambda: (1.0, {})
        self.engine_name_provider = lambda: ""

    @property
    def current_sentence(self) -> str:
        if 0 <= self.current_index < self.total_sentences:
            return self.sentences[self.current_index]
        return ""

    @property
    def current_position(self) -> tuple:
        if 0 <= self.current_index < len(self.positions):
            return self.positions[self.current_index]
        return (0, 0)

    def load_text(self, text: str):
        self.cancel()
        self.original_text = text
        self.sentences = self.splitter.split(text)
        self.positions = self.splitter.get_positions(text)
        self.total_sentences = len(self.sentences)
        self.current_index = 0
        self.state = self.State.STOPPED
        self.cleanup_buffer()

    # ── Generation tokens ───────────────────────────────────────────────

    def begin_generation(self) -> int:
        """Retire any running thread and mint the token for the next one."""
        with self._gen_lock:
            self._generation += 1
            return self._generation

    def is_current(self, gen: int) -> bool:
        with self._gen_lock:
            return gen == self._generation

    def cancel(self) -> None:
        """Stop playback now: invalidate the running thread and cut the audio.

        Returns immediately -- the retired thread notices its stale token at its
        next checkpoint and exits on its own, so the UI never blocks on a
        network call that is already in flight.
        """
        with self._gen_lock:
            self._generation += 1
            if self._player is not None:
                self._player.stop()
            self._active_path = None

    def live_thread_count(self) -> int:
        with self._thread_lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            return len(self._threads)

    # ── Transport ───────────────────────────────────────────────────────

    def next_sentence(self):
        if self.current_index < self.total_sentences - 1:
            self.current_index += 1

    def prev_sentence(self):
        if self.current_index > 0:
            self.current_index -= 1

    def seek_to(self, index: int):
        self.current_index = max(0, min(index, self.total_sentences - 1))

    def sentence_at_offset(self, offset: int) -> Optional[int]:
        """Which sentence covers a character offset, for click-to-jump.

        An offset landing in the whitespace between two sentences belongs to the
        one about to start, which is what a click in that gap means.
        """
        if not self.positions:
            return None
        offset = max(0, offset)
        for index, (_, end) in enumerate(self.positions):
            if offset < end:
                return index
        return len(self.positions) - 1

    def remaining_text(self) -> str:
        """Everything from the current sentence onward."""
        return " ".join(self.sentences[self.current_index:])

    def skip_next(self):
        """Move one sentence forward, resuming playback if it was running."""
        self._skip(self.next_sentence)

    def skip_prev(self):
        self._skip(self.prev_sentence)

    def _skip(self, move):
        was_playing = self.state == self.State.PLAYING
        self.cancel()
        move()
        if was_playing:
            self.start_playback_thread()

    def start_playback_thread(self) -> None:
        """Start the one thread that drives playback from current_index."""
        gen = self.begin_generation()
        thread = threading.Thread(target=self._playback_loop, args=(gen,), daemon=True)
        with self._thread_lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()

    # ── Audio generation and buffering ──────────────────────────────────

    def _buffer_key(self, index: int, speed: float, kwargs: dict) -> tuple:
        """Speed and language are part of the key: audio cached at 1.0x must not
        be replayed after the user drags the speed slider to 2.0x."""
        return (index, round(float(speed), 3), tuple(sorted(kwargs.items())))

    def generate_sentence(self, index: int, speed: float, **kwargs) -> Optional[str]:
        """Return a playable audio file for a sentence, generating it once.

        Concurrent callers for the same sentence (the player catching up to its
        own lookahead) share a single generate instead of each paying for one.
        Returns None when the sentence has nothing speakable in it.
        """
        if index < 0 or index >= self.total_sentences:
            return None
        spoken = normalize_for_tts(self.sentences[index])
        if not spoken:
            return None

        key = self._buffer_key(index, speed, kwargs)
        with self._buffer_lock:
            path = self._buffer.get(key)
            if path and os.path.exists(path):
                return path
            done = self._inflight.get(key)
            owner = done is None
            if owner:
                done = threading.Event()
                self._inflight[key] = done
                self._errors.pop(key, None)

        if not owner:
            done.wait(timeout=self.GENERATE_TIMEOUT)
            with self._buffer_lock:
                error = self._errors.get(key)
                if error is not None:
                    raise error
                return self._buffer.get(key)

        try:
            audio_path = self.engine.generate(spoken, speed, **kwargs)
        except Exception as exc:
            with self._buffer_lock:
                self._errors[key] = exc
                self._inflight.pop(key, None)
            done.set()
            raise
        with self._buffer_lock:
            self._buffer[key] = audio_path
            self._inflight.pop(key, None)
        done.set()
        return audio_path

    def is_buffered(self, index: int, speed: float, **kwargs) -> bool:
        """Whether this sentence's audio is already generated and on disk."""
        key = self._buffer_key(index, speed, kwargs)
        with self._buffer_lock:
            path = self._buffer.get(key)
        return bool(path and os.path.exists(path))

    def _start_lookahead(self, index: int, speed: float, kwargs: dict, gen: int) -> None:
        """Pre-generate the next few sentences while this one plays, so a skip
        forward lands on audio that is already waiting."""
        for offset in range(1, self.LOOKAHEAD + 1):
            ahead = index + offset
            if ahead >= self.total_sentences:
                break
            threading.Thread(
                target=self._lookahead_worker,
                args=(ahead, speed, dict(kwargs), gen),
                daemon=True,
            ).start()

    def _lookahead_worker(self, index: int, speed: float, kwargs: dict, gen: int) -> None:
        if not self.is_current(gen):
            return
        try:
            self.generate_sentence(index, speed, **kwargs)
        except Exception:
            pass  # a failed pre-fetch is retried, and reported, on arrival

    def prune_buffer(self, current_index: int) -> None:
        """Drop cached audio outside the window around the current sentence."""
        low = current_index - self.KEEP_BEHIND
        high = current_index + self.LOOKAHEAD + 1
        with self._buffer_lock:
            for key in list(self._buffer):
                if low <= key[0] <= high:
                    continue
                path = self._buffer.pop(key)
                if path and path != self._active_path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    # ── The playback loop ───────────────────────────────────────────────

    def _playback_loop(self, gen: int) -> None:
        try:
            while self.is_current(gen) and self.state == self.State.PLAYING:
                index = self.current_index
                if index < 0 or index >= self.total_sentences:
                    break
                speed, kwargs = self.params_provider()

                # Only announce when there is an actual wait: the lookahead
                # usually has the clip ready and the label would just flicker.
                if self.on_generating and not self.is_buffered(index, speed, **kwargs):
                    self.on_generating(index)

                audio_path, failure = None, None
                for attempt in range(1, self.GENERATE_ATTEMPTS + 1):
                    if not self.is_current(gen):
                        return
                    try:
                        audio_path = self.generate_sentence(index, speed, **kwargs)
                        failure = None
                        break
                    except Exception as exc:
                        # A dropped connection should cost a pause, not the
                        # rest of the article.
                        failure = exc
                        if attempt < self.GENERATE_ATTEMPTS:
                            time.sleep(self.RETRY_BACKOFF * attempt)
                if failure is not None:
                    self.state = self.State.STOPPED
                    if self.is_current(gen) and self.on_error:
                        self.on_error(failure)
                    return

                if not self.is_current(gen):
                    return

                self._start_lookahead(index, speed, kwargs, gen)
                if self.on_sentence_start:
                    self.on_sentence_start(index)

                if audio_path and os.path.exists(audio_path) and self._player is not None:
                    # Claiming the token and starting the clip under one lock
                    # keeps a thread retired mid-step from ever reaching the
                    # speaker after cancel() has silenced it.
                    with self._gen_lock:
                        if not self.is_current(gen):
                            return
                        self._player.play(audio_path)
                        self._active_path = audio_path
                    while self.is_current(gen) and self._player.is_busy():
                        time.sleep(self.POLL_INTERVAL)

                if not self.is_current(gen):
                    return

                self.save_current_position(speed, self.engine_name_provider())
                self.prune_buffer(index)

                if index >= self.total_sentences - 1:
                    break
                # Assigned, not incremented: a thread can only ever move the
                # index to the sentence after the one it actually played.
                self.current_index = index + 1

            if self.is_current(gen):
                self.state = self.State.STOPPED
                if self.on_finished:
                    self.on_finished()
        except Exception as exc:
            if self.is_current(gen) and self.on_error:
                self.on_error(exc)

    # ── Session persistence ─────────────────────────────────────────────

    def check_saved_position(self) -> dict | None:
        if self.session_store and self.original_text:
            return self.session_store.load_position(self.original_text)
        return None

    def save_current_position(self, speed: float, engine_name: str):
        if self.session_store and self.original_text:
            self.session_store.save_position(
                self.original_text,
                sentence_index=self.current_index,
                speed=speed,
                engine=engine_name,
            )

    def cleanup_buffer(self):
        with self._buffer_lock:
            for path in self._buffer.values():
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            self._buffer.clear()
            self._inflight.clear()
            self._errors.clear()
        self._active_path = None

    def cleanup(self):
        self.cancel()
        self.cleanup_buffer()


class UnifiedTTSApp:
    """Main application window"""
    
    # Color palette
    BG = "#1B2838"
    BG_LIGHT = "#2A3A4A"
    BG_CARD = "#233345"
    FG = "#E8EDF2"
    FG_DIM = "#8899AA"
    ACCENT_BLUE = "#2196F3"
    ACCENT_GREEN = "#4CAF50"
    ACCENT_RED = "#E53935"
    ACCENT_ORANGE = "#FF9800"
    ACCENT_AMBER = "#FF8F00"
    HIGHLIGHT = "#FF8F00"
    BANNER_BG = "#FFF176"
    BANNER_FG = "#333333"

    def __init__(self, root, session_store=None):
        """`session_store` is injectable so tests never touch the real one --
        restoring the last article at startup otherwise reads a user's saved
        text straight into the test fixture.
        """
        self.root = root
        self.root.title("Text to Speech")
        self.root.configure(bg=self.BG)

        # Window size — tall enough to fit all controls without squishing
        width, height = 950, 820
        self.root.geometry(f"{width}x{height}")
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(850, 750)

        self._setup_theme()

        # Initialize pygame mixer once before creating any engines
        if PYGAME_AVAILABLE:
            pygame.mixer.init()

        # Initialize engines
        self.engines = {
            'google': GoogleTTSEngine(),
            'piper': PiperTTSEngine()
        }

        self.current_engine = None
        self.session_store = session_store if session_store is not None else SessionStore()
        self.session_store.prune_old()
        self.playback = PlaybackController(session_store=self.session_store)
        # Mirrors of the Tk variables, safe to read from the playback thread
        self._current_speed = 1.5
        self._current_language = "en"
        self._restart_after_id = None
        self._suppress_seek = False

        self.create_ui()
        self._bind_shortcuts()
        self._restore_last_text()
        self.check_engines_and_initialize()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_theme(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TCombobox",
            fieldbackground=self.BG_LIGHT,
            background=self.BG_LIGHT,
            foreground=self.FG,
            arrowcolor=self.FG,
            borderwidth=1,
            relief="flat",
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", self.BG_LIGHT)],
            foreground=[("readonly", self.FG)],
            selectbackground=[("readonly", self.BG_LIGHT)],
            selectforeground=[("readonly", self.FG)],
        )

        style.configure("Horizontal.TScale",
            background=self.BG,
            troughcolor=self.BG_LIGHT,
            borderwidth=0,
        )

        # Option menu popup styling
        self.root.option_add("*TCombobox*Listbox.background", self.BG_LIGHT)
        self.root.option_add("*TCombobox*Listbox.foreground", self.FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.ACCENT_BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    
    def create_ui(self):
        """Create the user interface"""

        # Main container
        main_frame = tk.Frame(self.root, bg=self.BG, padx=30, pady=20)
        main_frame.pack(expand=True, fill='both')
        self.main_frame = main_frame

        # ── Title ──
        title_frame = tk.Frame(main_frame, bg=self.BG)
        title_frame.pack(pady=(0, 15))

        tk.Label(
            title_frame, text="Text to Speech",
            font=("Helvetica", 30, "bold"), fg=self.FG, bg=self.BG,
        ).pack()
        tk.Label(
            title_frame, text="Powered by Google TTS and Piper TTS",
            font=("Helvetica", 12), fg=self.FG_DIM, bg=self.BG,
        ).pack()

        # ── Engine selection row ──
        engine_frame = tk.Frame(main_frame, bg=self.BG)
        engine_frame.pack(pady=8, fill='x')

        tk.Label(
            engine_frame, text="Engine:", font=("Helvetica", 13, "bold"),
            fg=self.FG, bg=self.BG,
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.engine_var = tk.StringVar()
        self.engine_combo = ttk.Combobox(
            engine_frame, textvariable=self.engine_var,
            state="readonly", width=35, font=("Helvetica", 12),
        )
        self.engine_combo.pack(side=tk.LEFT, padx=5)
        self.engine_combo.bind('<<ComboboxSelected>>', self.on_engine_change)

        self.engine_status = tk.Label(
            engine_frame, text="", font=("Helvetica", 11),
            fg=self.FG_DIM, bg=self.BG,
        )
        self.engine_status.pack(side=tk.LEFT, padx=15)

        self.download_button = tk.Button(
            engine_frame, text="Download Voice Model",
            command=self.download_piper_model,
            font=("Helvetica", 10, "bold"),
            bg=self.ACCENT_BLUE, fg="white",
            activebackground="#1976D2", activeforeground="white",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
        )

        # ── Text area card ──
        tk.Label(
            main_frame, text="Enter text to speak:",
            font=("Helvetica", 13, "bold"), fg=self.FG, bg=self.BG,
        ).pack(pady=(12, 4), anchor='w')

        text_card = tk.Frame(main_frame, bg=self.BG_CARD, padx=3, pady=3)
        text_card.pack(padx=0, pady=2, expand=True, fill='both')

        self.text_area = scrolledtext.ScrolledText(
            text_card, wrap=tk.WORD,
            font=("Menlo" if sys.platform == "darwin" else "Consolas", 12),
            bg=self.BG_LIGHT, fg=self.FG,
            insertbackground=self.FG,
            selectbackground=self.ACCENT_BLUE, selectforeground="white",
            relief=tk.FLAT, borderwidth=0, highlightthickness=0,
            padx=12, pady=10,
        )
        self.text_area.pack(expand=True, fill='both')
        self.text_area.tag_configure("current_sentence", background=self.HIGHLIGHT, foreground="#FFFFFF")

        # ── Controls area (fixed height — text area gets remaining space) ──
        controls_frame = tk.Frame(main_frame, bg=self.BG)
        controls_frame.pack(pady=(12, 0), fill='x', expand=False)

        # Language selection (for Google TTS)
        self.lang_frame = tk.Frame(controls_frame, bg=self.BG)

        tk.Label(
            self.lang_frame, text="Language:", font=("Helvetica", 12),
            fg=self.FG, bg=self.BG,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.lang_var = tk.StringVar(value="en")
        languages = [
            ("English", "en"), ("Spanish", "es"), ("French", "fr"),
            ("German", "de"), ("Italian", "it"), ("Portuguese", "pt"),
            ("Russian", "ru"), ("Japanese", "ja"), ("Korean", "ko"),
            ("Chinese", "zh"),
        ]
        self.lang_combo = ttk.Combobox(
            self.lang_frame, textvariable=self.lang_var,
            values=[f"{name} ({code})" for name, code in languages],
            state="readonly", width=25, font=("Helvetica", 11),
        )
        self.lang_combo.set("English (en)")
        self.lang_combo.bind('<<ComboboxSelected>>', self.on_language_change)
        self.lang_combo.pack(side=tk.LEFT, padx=5)

        # Speed control
        speed_frame = tk.Frame(controls_frame, bg=self.BG)
        speed_frame.pack(pady=8)

        tk.Label(
            speed_frame, text="Speed:", font=("Helvetica", 12),
            fg=self.FG, bg=self.BG,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.speed_var = tk.DoubleVar(value=1.5)
        self.speed_slider = tk.Scale(
            speed_frame, from_=0.5, to=2.0, resolution=0.1,
            orient=tk.HORIZONTAL, variable=self.speed_var,
            length=300, command=self.update_speed_label, showvalue=False,
            bg=self.BG, fg=self.FG, troughcolor=self.BG_LIGHT,
            highlightthickness=0, activebackground=self.ACCENT_BLUE,
        )
        self.speed_slider.pack(side=tk.LEFT, padx=8)

        self.speed_label = tk.Label(
            speed_frame, text="1.5x", font=("Helvetica", 13, "bold"),
            fg=self.ACCENT_BLUE, bg=self.BG, width=5,
        )
        self.speed_label.pack(side=tk.LEFT, padx=5)

        # Shown only when the selected engine cannot actually change speed
        self.speed_hint = tk.Label(
            speed_frame, text="", font=("Helvetica", 10),
            fg=self.ACCENT_ORANGE, bg=self.BG,
        )

        # ── Progress bar ──
        progress_frame = tk.Frame(controls_frame, bg=self.BG)
        progress_frame.pack(fill='x', pady=(8, 2))

        self.progress_var = tk.IntVar(value=0)
        self.progress_scale = tk.Scale(
            progress_frame, from_=0, to=1,
            orient=tk.HORIZONTAL, variable=self.progress_var,
            showvalue=False, command=self.on_progress_seek,
            bg=self.BG, fg=self.FG, troughcolor=self.BG_LIGHT,
            highlightthickness=0, activebackground=self.ACCENT_BLUE,
            sliderlength=20, width=12,
        )
        self.progress_scale.pack(fill='x', expand=True)

        self.progress_label = tk.Label(
            progress_frame, text="0%",
            font=("Helvetica", 10), fg=self.FG_DIM, bg=self.BG,
        )
        self.progress_label.pack()

        # ── Transport controls ──
        # Use Canvas-based buttons so colors work on macOS (tk.Button ignores bg/fg)
        transport_frame = tk.Frame(controls_frame, bg=self.BG)
        transport_frame.pack(pady=10)

        self.prev_button = self._make_transport_btn(
            transport_frame, "⏮", self.ACCENT_BLUE, self.on_prev, size=50,
        )
        self.prev_button.pack(side=tk.LEFT, padx=6)

        self.play_pause_button = self._make_transport_btn(
            transport_frame, "▶", self.ACCENT_GREEN, self.on_play_pause, size=64, font_size=26,
        )
        self.play_pause_button.pack(side=tk.LEFT, padx=8)

        self.stop_button = self._make_transport_btn(
            transport_frame, "⏹", self.ACCENT_RED, self.on_stop, size=50,
        )
        self.stop_button.pack(side=tk.LEFT, padx=6)

        self.next_button = self._make_transport_btn(
            transport_frame, "⏭", self.ACCENT_BLUE, self.on_next, size=50,
        )
        self.next_button.pack(side=tk.LEFT, padx=6)

        tk.Label(
            controls_frame,
            text="space play/pause   \u2190 \u2192 skip   \u2191 \u2193 speed   esc stop   click a sentence to jump",
            font=("Helvetica", 10), fg=self.FG_DIM, bg=self.BG,
        ).pack(pady=(0, 2))

        # ── Resume banner (hidden by default) ──
        self.resume_frame = tk.Frame(main_frame, bg=self.BANNER_BG, padx=12, pady=6)
        self.resume_label = tk.Label(
            self.resume_frame, text="", font=("Helvetica", 11, "bold"),
            bg=self.BANNER_BG, fg=self.BANNER_FG,
        )
        self.resume_label.pack(side=tk.LEFT, padx=5)
        self.start_over_btn = tk.Button(
            self.resume_frame, text="Start Over", command=self.on_start_over,
            font=("Helvetica", 10, "bold"), bg=self.ACCENT_GREEN, fg="white",
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
        )
        self.start_over_btn.pack(side=tk.LEFT, padx=5)

        # ── Status ──
        self.status_label = tk.Label(
            controls_frame, text="Checking engines...",
            fg=self.FG_DIM, bg=self.BG, font=("Helvetica", 11),
        )
        self.status_label.pack(pady=8)
    
    def _make_transport_btn(self, parent, text, color, command, size=50, font_size=18):
        """Create a colored round-rect canvas button that works on all platforms."""
        canvas = tk.Canvas(
            parent, width=size, height=size,
            bg=self.BG, highlightthickness=0, cursor="hand2",
        )
        r = 10  # corner radius
        # Draw rounded rectangle
        rect_id = self._round_rect(canvas, 2, 2, size - 2, size - 2, r, fill=color, outline="")
        text_id = canvas.create_text(
            size // 2, size // 2, text=text, fill="white",
            font=("Helvetica", font_size, "bold"),
        )
        # Store metadata for later updates
        canvas._btn_rect = rect_id
        canvas._btn_text = text_id
        canvas._btn_color = color
        canvas._btn_size = size

        # Hover effects
        def on_enter(e):
            canvas.itemconfig(rect_id, fill=self._lighten(color, 0.15))
        def on_leave(e):
            canvas.itemconfig(rect_id, fill=canvas._btn_color)
        def on_click(e):
            command()

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<ButtonRelease-1>", on_click)

        return canvas

    def _round_rect(self, canvas, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle on a canvas."""
        points = [
            x1 + r, y1,   x2 - r, y1,   x2, y1,   x2, y1 + r,
            x2, y2 - r,   x2, y2,        x2 - r, y2,
            x1 + r, y2,   x1, y2,        x1, y2 - r,
            x1, y1 + r,   x1, y1,        x1 + r, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    @staticmethod
    def _lighten(hex_color, amount):
        """Lighten a hex color by a fraction."""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _update_play_button(self, text, color):
        """Update the play/pause canvas button's icon and color."""
        c = self.play_pause_button
        c._btn_color = color
        c.itemconfig(c._btn_rect, fill=color)
        c.itemconfig(c._btn_text, text=text)

    def _set_play_button_enabled(self, enabled):
        """Enable or dim the play/pause canvas button."""
        c = self.play_pause_button
        if enabled:
            c._btn_color = self.ACCENT_GREEN
            c.itemconfig(c._btn_rect, fill=self.ACCENT_GREEN)
            c.itemconfig(c._btn_text, fill="white")
            c.configure(cursor="hand2")
            c._enabled = True
        else:
            c.itemconfig(c._btn_rect, fill=self.BG_LIGHT)
            c.itemconfig(c._btn_text, fill=self.FG_DIM)
            c.configure(cursor="")
            c._enabled = False

    def check_engines_and_initialize(self):
        """Check available engines and initialize"""
        available_engines = []
        engine_items = []
        
        # Check Piper TTS FIRST (so it appears first in dropdown)
        piper_engine = self.engines['piper']
        if piper_engine.is_available():
            available_engines.append('piper')
            engine_items.append("Piper TTS (Offline)")
        elif piper_engine.check_piper_installed():
            engine_items.append("Piper TTS (Model Not Downloaded)")
        else:
            engine_items.append("Piper TTS (Not Installed - pip install piper-tts)")
        
        # Check Google TTS SECOND
        if self.engines['google'].is_available():
            available_engines.append('google')
            engine_items.append("Google TTS (Online)")
        else:
            engine_items.append("Google TTS (Not Available - Install gtts & pygame)")
        
        self.engine_combo['values'] = engine_items
        
        # Always select first item in list (Piper will be first if available)
        if available_engines:
            # Select the first available engine in the dropdown
            self.engine_combo.current(0)
            
            # Set the current engine based on what's first
            first_item = engine_items[0]
            if "Piper TTS (Offline)" in first_item:
                self.current_engine = self.engines['piper']
            elif "Google TTS (Online)" in first_item:
                self.current_engine = self.engines['google']
            else:
                # Neither is fully available, but set based on what's selected
                for engine_key in available_engines:
                    if engine_key == 'piper' and "Piper" in first_item:
                        self.current_engine = self.engines['piper']
                        break
                    elif engine_key == 'google' and "Google" in first_item:
                        self.current_engine = self.engines['google']
                        break
            
            self.on_engine_change()
            self.status_label.config(text="Ready", fg=self.ACCENT_GREEN)
        else:
            self.engine_combo.current(0)
            self.status_label.config(text="No TTS engines available. Please install dependencies.", fg=self.ACCENT_RED)
            self._set_play_button_enabled(False)
    
    SPEED_STEP = 0.1

    def _bind_shortcuts(self):
        """Transport keys that work anywhere except inside the text box.

        Bound with bind_all and filtered on event.widget, so typing an article
        still inserts spaces and moves the caret with the arrow keys.
        """
        self.root.bind_all("<space>", self._key_play_pause)
        self.root.bind_all("<Right>", self._key_next)
        self.root.bind_all("<Left>", self._key_prev)
        self.root.bind_all("<Escape>", self._key_stop)
        self.root.bind_all("<Up>", self._key_faster)
        self.root.bind_all("<Down>", self._key_slower)
        self.text_area.bind("<Button-1>", self._on_text_click)

    def _typing(self, event):
        return getattr(event, "widget", None) is self.text_area

    def _key_play_pause(self, event):
        if self._typing(event):
            return None
        self.on_play_pause()
        return "break"

    def _key_next(self, event):
        if self._typing(event):
            return None
        self.on_next()
        return "break"

    def _key_prev(self, event):
        if self._typing(event):
            return None
        self.on_prev()
        return "break"

    def _key_stop(self, event):
        if self._typing(event):
            return None
        self.on_stop()
        return "break"

    def _key_faster(self, event):
        return self._nudge_speed(self.SPEED_STEP, event)

    def _key_slower(self, event):
        return self._nudge_speed(-self.SPEED_STEP, event)

    def _nudge_speed(self, delta, event):
        if self._typing(event):
            return None
        speed = round(min(2.0, max(0.5, self._current_speed + delta)), 2)
        self.speed_var.set(speed)
        self.update_speed_label(speed)
        return "break"

    def _on_text_click(self, event):
        """Click a sentence to jump to it, once there is something to jump in."""
        index = self.text_area.index(f"@{event.x},{event.y}")
        self._jump_to_text_index(index)
        return None

    def _jump_to_text_index(self, tk_index) -> bool:
        """Seek to the sentence covering a Tk text index. False if not possible."""
        if self.playback.total_sentences == 0:
            return False
        # Offsets only mean anything while the box still holds the loaded text
        if self.text_area.get("1.0", "end-1c") != self.playback.original_text:
            return False
        offset = len(self.text_area.get("1.0", tk_index))
        target = self.playback.sentence_at_offset(offset)
        if target is None or target == self.playback.current_index:
            return False
        was_playing = self.playback.state == PlaybackController.State.PLAYING
        self.playback.cancel()
        self.playback.seek_to(target)
        self._update_progress()
        self._highlight_current()
        if was_playing:
            self._schedule_restart(delay_ms=120)
        return True

    def _restore_last_text(self):
        """Put the last article back, so reopening does not mean re-pasting."""
        remembered = self.session_store.load_last_text()
        if remembered and not self.text_area.get("1.0", "end-1c").strip():
            self.text_area.insert("1.0", remembered)

    def _update_speed_availability(self):
        """Match the speed control to what the engine can actually deliver."""
        engine = self.current_engine
        supported = engine.supports_speed() if engine else True
        if supported:
            self.speed_slider.config(state=tk.NORMAL)
            self.speed_hint.pack_forget()
        else:
            self.speed_slider.config(state=tk.DISABLED)
            self.speed_hint.config(text="install ffmpeg for speed control")
            self.speed_hint.pack(side=tk.LEFT, padx=8)

    def on_language_change(self, event=None):
        """Cache the language code so the playback thread never reads a Tk var."""
        selection = self.lang_combo.get()
        if "(" in selection and ")" in selection:
            self._current_language = selection.split("(")[1].split(")")[0]

    def on_engine_change(self, event=None):
        """Handle engine selection change"""
        selection = self.engine_combo.get()
        
        # Hide download button by default
        self.download_button.pack_forget()
        
        if "Google TTS (Online)" in selection:
            self.current_engine = self.engines['google']
            self.lang_frame.pack(pady=10)
            self._set_play_button_enabled(True)
            self.status_label.config(text="Ready - Google TTS", fg=self.ACCENT_GREEN)
            self._update_speed_availability()

        elif "Piper TTS (Offline)" in selection:
            self.current_engine = self.engines['piper']
            self.lang_frame.pack_forget()
            self._set_play_button_enabled(True)
            self.status_label.config(text="Ready - Piper TTS", fg=self.ACCENT_GREEN)
            self._update_speed_availability()

        elif "Model Not Downloaded" in selection:
            self.current_engine = None
            self.lang_frame.pack_forget()
            self._set_play_button_enabled(False)
            self.download_button.pack(side=tk.LEFT, padx=20)
            self.status_label.config(text="Download voice model to use Piper TTS", fg=self.ACCENT_ORANGE)

        else:
            self.current_engine = None
            self._set_play_button_enabled(False)
            if "Google" in selection:
                self.status_label.config(text="Install: pip install gtts pygame", fg=self.ACCENT_ORANGE)
            else:
                self.status_label.config(text="Install: pip install piper-tts", fg=self.ACCENT_ORANGE)
    
    def download_piper_model(self):
        """Download Piper voice model"""
        self.download_button.config(state="disabled", text="Downloading...")
        self.status_label.config(text="Downloading voice model...", fg=self.ACCENT_BLUE)

        def download_thread():
            def update_status(msg):
                self.root.after(0, lambda: self.status_label.config(text=msg, fg=self.ACCENT_BLUE))
            
            success = self.engines['piper'].download_model(update_status)
            
            if success:
                self.root.after(0, self.refresh_engines_after_download)
            else:
                self.root.after(0, lambda: self.download_button.config(state="normal", text="Download Voice Model"))
        
        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()
    
    def refresh_engines_after_download(self):
        """Refresh engine list after downloading Piper model"""
        self.download_button.pack_forget()
        self.engines['piper'].invalidate_availability()
        self.check_engines_and_initialize()
        
        # Select Piper TTS if now available
        engine_items = self.engine_combo['values']
        for i, item in enumerate(engine_items):
            if "Piper TTS (Offline)" in item:
                self.engine_combo.current(i)
                self.on_engine_change()
                break
    
    def update_speed_label(self, value):
        """Update the speed label and the thread-safe speed mirror."""
        speed = float(value)
        self._current_speed = speed
        self.speed_label.config(text=f"{speed:.1f}x")
    
    def on_play_pause(self):
        if getattr(self.play_pause_button, '_enabled', True) is False:
            return
        if self.playback.state == PlaybackController.State.STOPPED:
            text = self.text_area.get("1.0", "end-1c")
            if not text.strip():
                messagebox.showwarning("No Text", "Please enter some text to speak")
                return
            if not self.current_engine or not self.current_engine.is_available():
                messagebox.showerror("Error", "Selected TTS engine is not available")
                return
            self.playback.engine = self.current_engine
            self.playback.load_text(text)
            saved = self.playback.check_saved_position()
            if saved and saved["sentence_index"] > 0:
                # Resume straight away and say so. Making play show a banner and
                # fall silent read as a broken play button.
                self.playback.seek_to(saved["sentence_index"])
                if "speed" in saved:
                    self.speed_var.set(saved["speed"])
                    self._current_speed = float(saved["speed"])
                    self.speed_label.config(text=f"{saved['speed']:.1f}x")
                self._show_resume_banner()
            else:
                self.resume_frame.pack_forget()
            self._start_playback()
        elif self.playback.state == PlaybackController.State.PLAYING:
            self._pause_playback()
        elif self.playback.state == PlaybackController.State.PAUSED:
            self._start_playback()

    def _show_resume_banner(self):
        index = self.playback.current_index
        total = self.playback.total_sentences
        self.resume_label.config(
            text=f"Picked up where you left off \u2014 sentence {index + 1} of {total}."
        )
        self.resume_frame.pack(fill='x', pady=(5, 0))

    def on_start_over(self):
        """Rewind to the beginning and keep playing."""
        self.resume_frame.pack_forget()
        self.playback.cancel()
        self.playback.seek_to(0)
        self._start_playback()

    def _playback_params(self):
        """Speed and language for the next sentence.

        Read from plain attributes rather than the Tk variables: this is called
        on the playback thread, and Tk variables are not safe to touch there.
        """
        kwargs = {}
        if isinstance(self.current_engine, GoogleTTSEngine):
            kwargs["language"] = self._current_language
        return self._current_speed, kwargs

    def _wire_playback_callbacks(self):
        """Point the controller's hooks at the UI, marshalled onto the main
        thread -- they fire from the playback thread."""
        self.playback.params_provider = self._playback_params
        self.playback.engine_name_provider = (
            lambda: self.current_engine.get_name() if self.current_engine else ""
        )
        self.playback.on_sentence_start = lambda index: self.root.after(
            0, self._on_sentence_start
        )
        self.playback.on_generating = lambda index: self.root.after(0, self._on_generating)
        self.playback.on_finished = lambda: self.root.after(0, self._on_playback_finished)
        self.playback.on_error = lambda exc: self.root.after(
            0, lambda: self._on_playback_error(exc)
        )

    def _start_playback(self):
        self._cancel_pending_restart()
        self._wire_playback_callbacks()
        self.playback.state = PlaybackController.State.PLAYING
        self._update_play_button("⏸", self.ACCENT_ORANGE)
        self.status_label.config(text="Speaking...", fg=self.ACCENT_BLUE)
        self._update_progress()
        # Take focus off the text box so space and the arrows drive playback
        self.root.focus_set()
        self.playback.start_playback_thread()

    def _pause_playback(self):
        self._cancel_pending_restart()
        self.playback.state = PlaybackController.State.PAUSED
        self.playback.cancel()
        self._update_play_button("▶", self.ACCENT_GREEN)
        self.status_label.config(text="Paused", fg=self.ACCENT_ORANGE)
        self.playback.save_current_position(
            speed=self._current_speed,
            engine_name=self.current_engine.get_name() if self.current_engine else "",
        )

    def on_stop(self):
        self._cancel_pending_restart()
        self.playback.state = PlaybackController.State.STOPPED
        self.playback.cancel()
        self.playback.cleanup_buffer()
        self.playback.current_index = 0
        self._update_play_button("▶", self.ACCENT_GREEN)
        self.status_label.config(
            text=f"Ready - {self.current_engine.get_name()}" if self.current_engine else "Ready",
            fg=self.ACCENT_GREEN,
        )
        self._clear_highlight()
        self.resume_frame.pack_forget()
        self._update_progress()

    def on_prev(self):
        self.playback.skip_prev()
        self._update_progress()
        self._highlight_current()

    def on_next(self):
        self.playback.skip_next()
        self._update_progress()
        self._highlight_current()

    def on_progress_seek(self, value):
        """Fires for every step of a slider drag, so the seek is coalesced:
        the highlight follows the thumb, but playback restarts once, at the end.
        """
        if self._suppress_seek or self.playback.total_sentences == 0:
            return
        index = int(float(value))
        if index == self.playback.current_index:
            return
        self.playback.cancel()          # silence immediately while dragging
        self.playback.seek_to(index)
        self._highlight_current()
        self._update_progress_label()
        self._schedule_restart()

    def _schedule_restart(self, delay_ms=200):
        self._cancel_pending_restart()
        self._restart_after_id = self.root.after(delay_ms, self._commit_restart)

    def _cancel_pending_restart(self):
        if self._restart_after_id is not None:
            self.root.after_cancel(self._restart_after_id)
            self._restart_after_id = None

    def _commit_restart(self):
        self._restart_after_id = None
        if self.playback.state == PlaybackController.State.PLAYING:
            self.playback.start_playback_thread()

    def _on_generating(self):
        self.status_label.config(text="Generating audio\u2026", fg=self.ACCENT_BLUE)

    def _on_sentence_start(self):
        self.status_label.config(text="Speaking\u2026", fg=self.ACCENT_BLUE)
        self._highlight_current()
        self._update_progress()

    def _on_playback_error(self, exc):
        """Report a failed sentence without a modal.

        The controller already retried; playback stops on the sentence that
        failed, so pressing play picks up from exactly there.
        """
        self.playback.state = PlaybackController.State.STOPPED
        self._update_play_button("▶", self.ACCENT_GREEN)
        position = self.playback.current_index + 1
        self.status_label.config(
            text=f"Stopped at sentence {position}: {exc} \u2014 press play to retry",
            fg=self.ACCENT_RED,
        )

    def _on_playback_finished(self):
        self._update_play_button("▶", self.ACCENT_GREEN)
        self._clear_highlight()
        self.playback.cleanup_buffer()
        if self.playback.session_store:
            self.playback.session_store.delete_position(self.playback.original_text)
        self.status_label.config(
            text=f"Ready - {self.current_engine.get_name()}" if self.current_engine else "Ready",
            fg=self.ACCENT_GREEN,
        )

    def _highlight_current(self):
        self._clear_highlight()
        if not self.playback.positions or self.playback.current_index >= len(self.playback.positions):
            return
        start, end = self.playback.positions[self.playback.current_index]
        text_content = self.playback.original_text
        line = text_content[:start].count('\n') + 1
        col = start - text_content[:start].rfind('\n') - 1
        end_line = text_content[:end].count('\n') + 1
        end_col = end - text_content[:end].rfind('\n') - 1
        start_idx = f"{line}.{col}"
        end_idx = f"{end_line}.{end_col}"
        self.text_area.tag_add("current_sentence", start_idx, end_idx)
        self.text_area.see(start_idx)

    def _clear_highlight(self):
        self.text_area.tag_remove("current_sentence", "1.0", tk.END)

    def _update_progress(self):
        total = self.playback.total_sentences
        # Moving the scale fires on_progress_seek; suppress it so our own
        # updates are not mistaken for the user dragging the thumb.
        self._suppress_seek = True
        try:
            if total > 0:
                self.progress_scale.config(to=max(total - 1, 1))
                self.progress_var.set(self.playback.current_index)
            else:
                self.progress_scale.config(to=1)
                self.progress_var.set(0)
        finally:
            self._suppress_seek = False
        self._update_progress_label()

    def _update_progress_label(self):
        total = self.playback.total_sentences
        if total <= 0:
            self.progress_label.config(text="0%")
            return
        pct = int(((self.playback.current_index + 1) / total) * 100)
        left = estimate_seconds(self.playback.remaining_text(), self._current_speed)
        self.progress_label.config(text=f"{pct}%  \u00b7  ~{format_duration(left)} left")

    def _on_close(self):
        if self.playback.state != PlaybackController.State.STOPPED:
            self.playback.save_current_position(
                speed=self._current_speed,
                engine_name=self.current_engine.get_name() if self.current_engine else "",
            )
        self._cancel_pending_restart()
        self.session_store.save_last_text(self.text_area.get("1.0", "end-1c"))
        self.playback.cleanup()
        if PYGAME_AVAILABLE:
            pygame.quit()
        self.root.destroy()


def check_dependencies():
    """Check and display available dependencies"""
    print("Text-to-Speech Application")
    print("=" * 40)
    print("Checking dependencies...")
    print()
    
    deps = {
        'gtts': GTTS_AVAILABLE,
        'pygame': PYGAME_AVAILABLE
    }
    
    available = []
    missing = []
    
    for dep, status in deps.items():
        if status:
            available.append(dep)
            print(f"✓ {dep} - Available")
        else:
            missing.append(dep)
            print(f"✗ {dep} - Not installed")
    
    # Check for Piper (cross-platform)
    piper_available = False
    try:
        result = subprocess.run(["piper", "--help"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            piper_available = True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        piper_available = False
    
    if piper_available:
        print("✓ piper - Available")
        available.append('piper')
    else:
        print("✗ piper - Not installed")
        missing.append('piper')
    
    print()
    
    if missing:
        print("To install missing dependencies:")
        print("-" * 40)
        if 'gtts' in missing or 'pygame' in missing:
            python_deps = [d for d in missing if d in ['gtts', 'pygame']]
            print(f"pip install {' '.join(python_deps)}")
        if 'piper' in missing:
            print("pip install piper-tts")
        print()
    
    if not PYGAME_AVAILABLE:
        print("WARNING: pygame is required for audio playback!")
        print("Install with: pip install pygame")
        return False
    
    return True


def main():
    """Main entry point"""
    # Check dependencies with --check flag
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        check_dependencies()
        return
    
    # Create and run the application
    root = tk.Tk()
    app = UnifiedTTSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()