#!/usr/bin/env python3
"""
Unified Text-to-Speech Application
Supports Google TTS and Piper TTS engines
"""

import re
import hashlib
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

    def _is_numbered_list_dot(self, text: str, dot_pos: int) -> bool:
        """Check if a dot at dot_pos is part of a numbered list marker like '1.' or '12.'

        Only matches when the number is at the start of a line (possibly indented),
        so 'He scored 3.' is NOT treated as a list marker.
        """
        # Walk back over digits
        j = dot_pos - 1
        while j >= 0 and text[j].isdigit():
            j -= 1
        if j == dot_pos - 1:
            return False  # no digit before the dot
        # Skip optional indentation (spaces/tabs)
        while j >= 0 and text[j] in ' \t':
            j -= 1
        # Must be at start of string or right after a newline
        return j < 0 or text[j] == '\n'

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
                in_list_item = False

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


# Number-to-words for TTS normalization (0–999)
_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen',
]
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _int_to_words(n: int) -> str:
    if n == 0:
        return 'zero'
    if n < 0:
        return 'minus ' + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ('' if n % 10 == 0 else ' ' + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + ' hundred' + ('' if n % 100 == 0 else ' ' + _int_to_words(n % 100))
    return str(n)  # leave large numbers as digits — TTS handles them fine in context


def normalize_for_tts(text: str) -> str:
    """Normalize text for better TTS pronunciation.

    - Collapses internal whitespace (newlines from line-wrapped text) to single spaces
    - Converts standalone integers (0–999) to words
    - Strips numbered-list prefixes (e.g. '3. ' → 'three, ')
    """
    # Collapse whitespace first — line-wrapped text often has newlines mid-sentence
    # which cause TTS engines to stutter or skip words
    text = ' '.join(text.split())

    # Replace numbered list prefixes at line/sentence start: "3. " → "three, "
    def _replace_list_prefix(m):
        n = int(m.group(1))
        if 0 <= n <= 999:
            return _int_to_words(n) + ',' + m.group(2)
        return m.group(0)
    text = re.sub(r'^(\d{1,3})\.([ \t])', _replace_list_prefix, text, flags=re.MULTILINE)

    # Replace standalone integers surrounded by word boundaries
    def _replace_number(m):
        n = int(m.group(0))
        if 0 <= n <= 999:
            return _int_to_words(n)
        return m.group(0)
    text = re.sub(r'\b\d{1,3}\b', _replace_number, text)

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
        slow = speed < 1.0
        tts = gTTS(text=text, lang=language, slow=slow)
        tts.save(tmp_file.name)
        return tmp_file.name

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


class PiperTTSEngine(TTSEngine):
    """Piper TTS for offline high-quality speech"""
    
    def __init__(self):
        self.is_playing = False
        self.current_audio_file = None
        self.piper_dir = os.path.expanduser("~/.local/share/piper")
        self.voice_model = os.path.join(self.piper_dir, "en_US-norman-medium.onnx")
        self.voice_config = os.path.join(self.piper_dir, "en_US-norman-medium.onnx.json")
    
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
        stdout, stderr = process.communicate(input=text)
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
        """Check if Piper is installed"""
        try:
            # Try to run piper with --help to see if it's installed
            result = subprocess.run(["piper", "--help"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
    
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


class PlaybackController:
    """Manages sentence-by-sentence playback with lookahead buffering."""

    class State(Enum):
        STOPPED = "stopped"
        PLAYING = "playing"
        PAUSED = "paused"

    def __init__(self, engine=None, session_store=None):
        self.engine = engine
        self.session_store = session_store
        self.splitter = SentenceSplitter()

        self.state = self.State.STOPPED
        self.sentences = []
        self.positions = []
        self.current_index = 0
        self.total_sentences = 0
        self.original_text = ""

        self._buffer = {}
        self._buffer_lock = threading.Lock()

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
        self.original_text = text
        self.sentences = self.splitter.split(text)
        self.positions = self.splitter.get_positions(text)
        self.total_sentences = len(self.sentences)
        self.current_index = 0
        self.state = self.State.STOPPED
        self.cleanup_buffer()

    def next_sentence(self):
        if self.current_index < self.total_sentences - 1:
            self.current_index += 1

    def prev_sentence(self):
        if self.current_index > 0:
            self.current_index -= 1

    def seek_to(self, index: int):
        self.current_index = max(0, min(index, self.total_sentences - 1))

    def generate_sentence(self, index: int, speed: float, **kwargs) -> str:
        with self._buffer_lock:
            if index in self._buffer and os.path.exists(self._buffer[index]):
                return self._buffer[index]
        if index < 0 or index >= self.total_sentences:
            return None
        sentence_text = normalize_for_tts(self.sentences[index])
        audio_path = self.engine.generate(sentence_text, speed, **kwargs)
        with self._buffer_lock:
            self._buffer[index] = audio_path
        return audio_path

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

    def cleanup(self):
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

    def __init__(self, root):
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
        self.session_store = SessionStore()
        self.session_store.prune_old()
        self.playback = PlaybackController(session_store=self.session_store)
        self._playback_thread = None
        self._stop_event = threading.Event()

        self.create_ui()
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

        # ── Resume banner (hidden by default) ──
        self.resume_frame = tk.Frame(main_frame, bg=self.BANNER_BG, padx=12, pady=6)
        self.resume_label = tk.Label(
            self.resume_frame, text="", font=("Helvetica", 11, "bold"),
            bg=self.BANNER_BG, fg=self.BANNER_FG,
        )
        self.resume_label.pack(side=tk.LEFT, padx=5)
        self.resume_yes_btn = tk.Button(
            self.resume_frame, text="Resume", command=self.on_resume_yes,
            font=("Helvetica", 10, "bold"), bg=self.ACCENT_GREEN, fg="white",
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
        )
        self.resume_yes_btn.pack(side=tk.LEFT, padx=5)
        self.resume_no_btn = tk.Button(
            self.resume_frame, text="Start Over", command=self.on_resume_no,
            font=("Helvetica", 10), bg=self.BG_LIGHT, fg=self.FG,
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
        )
        self.resume_no_btn.pack(side=tk.LEFT, padx=5)

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

        elif "Piper TTS (Offline)" in selection:
            self.current_engine = self.engines['piper']
            self.lang_frame.pack_forget()
            self._set_play_button_enabled(True)
            self.status_label.config(text="Ready - Piper TTS", fg=self.ACCENT_GREEN)

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
        self.check_engines_and_initialize()
        
        # Select Piper TTS if now available
        engine_items = self.engine_combo['values']
        for i, item in enumerate(engine_items):
            if "Piper TTS (Offline)" in item:
                self.engine_combo.current(i)
                self.on_engine_change()
                break
    
    def update_speed_label(self, value):
        """Update the speed label"""
        speed = float(value)
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
                self._show_resume_banner(saved)
                return
            self._start_playback()
        elif self.playback.state == PlaybackController.State.PLAYING:
            self._pause_playback()
        elif self.playback.state == PlaybackController.State.PAUSED:
            self._start_playback()

    def _show_resume_banner(self, saved):
        idx = saved["sentence_index"]
        total = self.playback.total_sentences
        self.resume_label.config(text=f"Resume from sentence {idx + 1}/{total}?")
        self.resume_frame.pack(fill='x', pady=(5, 0))

    def on_resume_yes(self):
        saved = self.playback.check_saved_position()
        if saved:
            self.playback.seek_to(saved["sentence_index"])
            if "speed" in saved:
                self.speed_var.set(saved["speed"])
                self.speed_label.config(text=f"{saved['speed']:.1f}x")
        self.resume_frame.pack_forget()
        self._start_playback()

    def on_resume_no(self):
        self.resume_frame.pack_forget()
        self.playback.seek_to(0)
        self._start_playback()

    def _start_playback(self):
        self.playback.state = PlaybackController.State.PLAYING
        self._stop_event.clear()
        self._update_play_button("⏸", self.ACCENT_ORANGE)
        self.status_label.config(text="Speaking...", fg=self.ACCENT_BLUE)
        self._update_progress()
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

    def _pause_playback(self):
        self.playback.state = PlaybackController.State.PAUSED
        self._stop_event.set()
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
        self._update_play_button("▶", self.ACCENT_GREEN)
        self.status_label.config(text="Paused", fg=self.ACCENT_ORANGE)
        self.playback.save_current_position(
            speed=self.speed_var.get(),
            engine_name=self.current_engine.get_name() if self.current_engine else "",
        )

    def on_stop(self):
        self.playback.state = PlaybackController.State.STOPPED
        self._stop_event.set()
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
        self.playback.cleanup_buffer()
        self.playback.current_index = 0
        self._update_play_button("▶", self.ACCENT_GREEN)
        self.status_label.config(
            text=f"Ready - {self.current_engine.get_name()}" if self.current_engine else "Ready",
            fg=self.ACCENT_GREEN,
        )
        self._clear_highlight()
        self._update_progress()

    def on_prev(self):
        was_playing = self.playback.state == PlaybackController.State.PLAYING
        if was_playing:
            self._stop_event.set()
            if PYGAME_AVAILABLE:
                pygame.mixer.music.stop()
        self.playback.prev_sentence()
        self._update_progress()
        self._highlight_current()
        if was_playing:
            self._stop_event.clear()
            self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._playback_thread.start()

    def on_next(self):
        was_playing = self.playback.state == PlaybackController.State.PLAYING
        if was_playing:
            self._stop_event.set()
            if PYGAME_AVAILABLE:
                pygame.mixer.music.stop()
        self.playback.next_sentence()
        self._update_progress()
        self._highlight_current()
        if was_playing:
            self._stop_event.clear()
            self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._playback_thread.start()

    def on_progress_seek(self, value):
        if self.playback.total_sentences > 0:
            idx = int(float(value))
            if idx != self.playback.current_index:
                was_playing = self.playback.state == PlaybackController.State.PLAYING
                if was_playing:
                    self._stop_event.set()
                    if PYGAME_AVAILABLE:
                        pygame.mixer.music.stop()
                self.playback.seek_to(idx)
                self._highlight_current()
                self._update_progress_label()
                if was_playing:
                    self._stop_event.clear()
                    self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
                    self._playback_thread.start()

    def _playback_loop(self):
        try:
            while (
                self.playback.state == PlaybackController.State.PLAYING
                and self.playback.current_index < self.playback.total_sentences
                and not self._stop_event.is_set()
            ):
                idx = self.playback.current_index
                speed = self.speed_var.get()

                kwargs = {}
                if isinstance(self.current_engine, GoogleTTSEngine):
                    lang_code = self.lang_combo.get().split("(")[1].split(")")[0]
                    kwargs["language"] = lang_code

                try:
                    audio_path = self.playback.generate_sentence(idx, speed, **kwargs)
                except Exception as e:
                    self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Generation failed: {e}"))
                    break

                if self._stop_event.is_set():
                    break

                # Lookahead: pre-generate next sentence
                if idx + 1 < self.playback.total_sentences:
                    lookahead = threading.Thread(
                        target=self.playback.generate_sentence,
                        args=(idx + 1, speed),
                        kwargs=kwargs,
                        daemon=True,
                    )
                    lookahead.start()

                self.root.after(0, self._highlight_current)
                self.root.after(0, self._update_progress)

                if audio_path and os.path.exists(audio_path) and PYGAME_AVAILABLE:
                    pygame.mixer.music.load(audio_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                        pygame.time.Clock().tick(10)

                if self._stop_event.is_set():
                    break

                self.playback.save_current_position(
                    speed=speed,
                    engine_name=self.current_engine.get_name() if self.current_engine else "",
                )

                if self.playback.current_index < self.playback.total_sentences - 1:
                    self.playback.current_index += 1
                else:
                    break

            if self.playback.state == PlaybackController.State.PLAYING:
                self.playback.state = PlaybackController.State.STOPPED
                self.root.after(0, self._on_playback_finished)
        except Exception as e:
            self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Playback failed: {e}"))
            self.root.after(0, self._on_playback_finished)

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
        if total > 0:
            self.progress_scale.config(to=max(total - 1, 1))
            self.progress_var.set(self.playback.current_index)
        else:
            self.progress_scale.config(to=1)
            self.progress_var.set(0)
        self._update_progress_label()

    def _update_progress_label(self):
        total = self.playback.total_sentences
        if total > 0:
            pct = int(((self.playback.current_index + 1) / total) * 100)
            self.progress_label.config(text=f"{pct}%")
        else:
            self.progress_label.config(text="0%")

    def _on_close(self):
        if self.playback.state != PlaybackController.State.STOPPED:
            self.playback.save_current_position(
                speed=self.speed_var.get(),
                engine_name=self.current_engine.get_name() if self.current_engine else "",
            )
        self._stop_event.set()
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.stop()
            except:
                pass
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