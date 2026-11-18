"""The desktop window: paste an article, listen to it sentence by sentence."""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from .engine import (
    PYGAME_AVAILABLE,
    NeuralTTSEngine,
    PlaybackController,
    SessionStore,
    VoiceSwitched,
    VoiceWorkerClient,
    estimate_seconds,
    ffmpeg_available,
    format_duration,
)
from .voices import voice_catalog

if PYGAME_AVAILABLE:
    import pygame


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

        # Initialize engines: the neural voices share one worker process
        self.voice_client = VoiceWorkerClient()
        self.engines = {spec.key: NeuralTTSEngine(spec, self.voice_client)
                        for spec in voice_catalog.ENGINES}
        self._engine_keys = []       # dropdown index -> engine key
        self._voice_ids = []         # voice dropdown index -> voice id
        self._voice_for_engine = {}  # engine key -> voice last picked for it
        self._current_voice = None   # mirror read by the playback thread
        self._preload_token = 0
        # Worker threads hand UI work over through this queue; only the Tk
        # thread ever touches Tk (see _post).
        self._ui_calls = queue.SimpleQueue()
        self._ui_poll_id = None
        self._loading_message = None  # set while a model is loading

        self.current_engine = None
        self.session_store = session_store if session_store is not None else SessionStore()
        self.session_store.prune_old()
        self.playback = PlaybackController(session_store=self.session_store)
        # Mirrors of the Tk variables, safe to read from the playback thread
        self._current_speed = 1.5
        self._restart_after_id = None
        self._suppress_seek = False

        self.create_ui()
        self._drain_ui_calls()
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
            title_frame, text="Local neural voices",
            font=("Helvetica", 12), fg=self.FG_DIM, bg=self.BG,
        ).pack()

        # ── Engine selection row ──
        engine_frame = tk.Frame(main_frame, bg=self.BG)
        self.engine_frame = engine_frame
        engine_frame.pack(pady=8, fill='x')

        tk.Label(
            engine_frame, text="Engine:", font=("Helvetica", 13, "bold"),
            fg=self.FG, bg=self.BG,
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.engine_var = tk.StringVar()
        self.engine_combo = ttk.Combobox(
            engine_frame, textvariable=self.engine_var,
            state="readonly", width=38, font=("Helvetica", 12),
        )
        self.engine_combo.pack(side=tk.LEFT, padx=5)
        self.engine_combo.bind('<<ComboboxSelected>>', self.on_engine_change)

        self.engine_status = tk.Label(
            engine_frame, text="", font=("Helvetica", 11),
            fg=self.FG_DIM, bg=self.BG,
        )
        self.engine_status.pack(side=tk.LEFT, padx=15)

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

        # The voice picker sits on the engine row: a row of its own pushed
        # the controls past the window's height.
        self.voice_frame = tk.Frame(self.engine_frame, bg=self.BG)
        tk.Label(
            self.voice_frame, text="Voice:", font=("Helvetica", 12),
            fg=self.FG, bg=self.BG,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.voice_combo = ttk.Combobox(
            self.voice_frame, state="readonly", width=24, font=("Helvetica", 11),
        )
        self.voice_combo.bind('<<ComboboxSelected>>', self.on_voice_change)
        self.voice_combo.pack(side=tk.LEFT, padx=5)

        # Speed control
        speed_frame = tk.Frame(controls_frame, bg=self.BG)
        speed_frame.pack(pady=8)
        self.speed_frame = speed_frame

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

    # Dropdown order, as listed in voice_catalog; the first usable one is the default
    ENGINE_ORDER = tuple(spec.key for spec in voice_catalog.ENGINES)

    def _engine_entry(self, key):
        """(dropdown label, usable) for one engine."""
        engine = self.engines[key]
        spec = engine.spec
        if engine.unavailable_reason():
            return f"{spec.label} \u00b7 unavailable", False
        if not engine.is_downloaded():
            return f"{spec.label} \u00b7 {spec.download_size} download", True
        return spec.label, True

    UI_POLL_MS = 40

    def _post(self, fn):
        """Run fn on the Tk thread. Safe from any thread.

        Calling into Tk from a worker thread -- even root.after -- waits for
        the Tk thread to service it, and on macOS that can mean waiting until
        some unrelated event (a timer, a keypress) wakes the loop: playback
        sat silent for seconds after an engine switch. A queue drained by
        the Tk thread never makes the caller wait.
        """
        self._ui_calls.put(fn)

    def _drain_ui_calls(self):
        while True:
            try:
                fn = self._ui_calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001 - one bad update must not stop the rest
                import traceback
                traceback.print_exc()
        self._ui_poll_id = self.root.after(self.UI_POLL_MS, self._drain_ui_calls)

    def check_engines_and_initialize(self):
        """List every engine, and select the first one that can run here."""
        entries = [(key,) + self._engine_entry(key) for key in self.ENGINE_ORDER]
        self._engine_keys = [key for key, _, _ in entries]
        self.engine_combo['values'] = [label for _, label, _ in entries]
        usable = [key for key, _, ok in entries if ok]

        # With nothing usable, the first entry still says *why* (not set up,
        # needs espeak-ng, ...), which beats a generic "no engines".
        self.engine_combo.current(self._engine_keys.index(usable[0]) if usable else 0)
        self.on_engine_change()

    def _selected_engine_key(self):
        index = self.engine_combo.current()
        if 0 <= index < len(self._engine_keys):
            return self._engine_keys[index]
        return None
    
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

    def on_engine_change(self, event=None):
        """Switch engine: show its voices, warm up its model, and carry on
        playing in the new voice if something was playing."""
        key = self._selected_engine_key()
        engine = self.engines.get(key)
        if engine is None:
            return
        previous = self.current_engine
        self._preload_token += 1   # a load still running for the old pick is moot
        self._loading_message = None
        self.voice_frame.pack_forget()

        reason = engine.unavailable_reason()
        if reason:
            # Nothing will play, so nothing may stay loaded either
            self.voice_client.close()
            self.current_engine = None
            self._set_play_button_enabled(False)
            self.status_label.config(text=f"{engine.spec.name}: {reason}  \u00b7  {engine.spec.detail}",
                                     fg=self.ACCENT_ORANGE)
        else:
            # Only the selected engine may use the voice worker
            self.voice_client.set_active(key)
            self.current_engine = engine
            self._show_voice_choices(engine.spec)
            self._set_play_button_enabled(True)
            self._update_speed_availability()
            self._preload(engine)

        if self.current_engine is not previous:
            self._engine_switched(previous)

    def _engine_switched(self, previous):
        """Audio cached from the old engine must not be replayed by the new
        one; if it was playing, pick the sentence up again in the new voice."""
        was_playing = self.playback.state == PlaybackController.State.PLAYING
        self.playback.cancel()
        self.playback.cleanup_buffer()
        if not was_playing:
            return
        if self.current_engine is None:
            self.on_stop()
            return
        self.playback.engine = self.current_engine
        self._schedule_restart()

    def _show_voice_choices(self, spec):
        self._voice_ids = [voice for voice, _ in spec.voices]
        self.voice_combo['values'] = [label for _, label in spec.voices]
        voice = self._voice_for_engine.get(spec.key, spec.default_voice)
        self.voice_combo.current(self._voice_ids.index(voice))
        self._current_voice = voice
        self.voice_frame.pack(side=tk.LEFT, padx=(16, 0), before=self.engine_status)

    def on_voice_change(self, event=None):
        index = self.voice_combo.current()
        if not (0 <= index < len(self._voice_ids)) or not isinstance(self.current_engine, NeuralTTSEngine):
            return
        voice = self._voice_ids[index]
        if voice == self._current_voice:
            return
        self._current_voice = voice
        self._voice_for_engine[self.current_engine.spec.key] = voice
        if self.playback.state == PlaybackController.State.PLAYING:
            # Hear the new voice now, not three buffered sentences from now
            self.playback.cancel()
            self._schedule_restart()

    def _preload(self, engine):
        """Load the model in the background as soon as it is picked, so the
        first sentence does not wait on it. A newer pick supersedes this one."""
        self._preload_token += 1
        token = self._preload_token
        name = engine.spec.name
        note = "" if engine.is_downloaded() else f" (downloading {engine.spec.download_size})"
        self._loading_message = f"Loading {name}…{note}"
        self.status_label.config(text=f"{self._loading_message}  ·  {engine.spec.detail}",
                                 fg=self.ACCENT_BLUE)

        def work():
            try:
                seconds = engine.preload()
                message, color = f"Ready - {name}", self.ACCENT_GREEN
                if seconds >= 3:
                    message += f" (loaded in {seconds:.0f}s)"
                message += f"  ·  {engine.spec.detail}"
            except VoiceSwitched:
                return
            except Exception as exc:
                message, color = f"{name} failed to load: {exc}", self.ACCENT_RED
            self._post(lambda: self._preload_done(token, message, color))

        threading.Thread(target=work, daemon=True).start()

    def _preload_done(self, token, message, color):
        if token != self._preload_token:
            return
        self._loading_message = None
        if self.playback.state == PlaybackController.State.PLAYING:
            return  # "Speaking..." is the more useful status while playing
        self.status_label.config(text=message, fg=color)
    
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
        """Speed and voice for the next sentence.

        Read from plain attributes rather than the Tk variables: this is called
        on the playback thread, and Tk variables are not safe to touch there.
        """
        kwargs = {}
        if isinstance(self.current_engine, NeuralTTSEngine):
            kwargs["voice"] = self._current_voice or self.current_engine.spec.default_voice
        return self._current_speed, kwargs

    def _wire_playback_callbacks(self):
        """Point the controller's hooks at the UI, marshalled onto the main
        thread -- they fire from the playback thread."""
        self.playback.params_provider = self._playback_params
        self.playback.engine_name_provider = (
            lambda: self.current_engine.get_name() if self.current_engine else ""
        )
        self.playback.on_sentence_start = lambda index: self._post(self._on_sentence_start)
        self.playback.on_generating = lambda index: self._post(self._on_generating)
        self.playback.on_finished = lambda: self._post(self._on_playback_finished)
        self.playback.on_error = lambda exc: self._post(lambda: self._on_playback_error(exc))

    def _start_playback(self):
        self._cancel_pending_restart()
        if self.current_engine is not None:
            # Resuming after a switch made while paused uses the new engine
            self.playback.engine = self.current_engine
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
        # The first sentence after picking a bigger voice waits on the model
        # loading; say that, rather than imply the sentence itself is slow.
        text = self._loading_message or "Generating audio\u2026"
        self.status_label.config(text=text, fg=self.ACCENT_BLUE)

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
        if self._ui_poll_id is not None:
            self.root.after_cancel(self._ui_poll_id)
            self._ui_poll_id = None
        self.session_store.save_last_text(self.text_area.get("1.0", "end-1c"))
        self.playback.cleanup()
        self.voice_client.close()
        if PYGAME_AVAILABLE:
            pygame.quit()
        self.root.destroy()


def check_dependencies():
    """Print what the app needs and whether each piece is here (--check)."""
    print("Text-to-Speech Application")
    print("=" * 40)
    checks = [
        ("pygame (audio playback)", PYGAME_AVAILABLE, "pip install pygame"),
        ("ffmpeg (speed control)", ffmpeg_available(), "brew install ffmpeg"),
        ("voices environment", os.path.exists(voice_catalog.voices_python()),
         "see Quick Start in the README"),
        ("espeak-ng (Kokoro)", voice_catalog.espeak_paths() is not None,
         "brew install espeak-ng"),
    ]
    for name, ok, fix in checks:
        mark = "\u2713" if ok else "\u2717"
        print(f"{mark} {name}" + ("" if ok else f"  -- {fix}"))
    print()
    for spec in voice_catalog.ENGINES:
        reason = voice_catalog.unavailable_reason(spec)
        mark = "\u2717" if reason else "\u2713"
        print(f"{mark} {spec.name}" + (f"  -- {reason}" if reason else ""))
    return PYGAME_AVAILABLE


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
