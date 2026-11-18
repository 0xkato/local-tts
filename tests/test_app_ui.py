"""UI-level tests for the real UnifiedTTSApp.

Driven through a genuine Tk mainloop with a withdrawn window and a silent
player. Skipped where Tk cannot open a display (the project .venv), so the
suite still runs there.
"""
import os
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    TK_OK = True
except Exception:
    TK_OK = False

pytestmark = pytest.mark.skipif(not TK_OK, reason="no usable Tk display")

import tts_unified
from tts_unified import PlaybackController, UnifiedTTSApp, SessionStore


class SilentPlayer:
    """Clips 'play' long enough that nothing advances on its own."""

    def __init__(self, duration=20.0):
        self.duration = duration
        self.log = []
        self._until = 0.0
        self._lock = threading.Lock()

    def play(self, path):
        with self._lock:
            self.log.append(path)
            self._until = time.monotonic() + self.duration

    def is_busy(self):
        with self._lock:
            return time.monotonic() < self._until

    def stop(self):
        with self._lock:
            self._until = 0.0


class StubEngine:
    def __init__(self, fail=False):
        self.fail = fail

    def generate(self, text, speed, **kwargs):
        if self.fail:
            raise RuntimeError("connection reset")
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        return path

    def is_available(self):
        return True

    def get_name(self):
        return "Stub"

    def supports_speed(self):
        return True

    def stop(self):
        pass


class AppHarness:
    """Builds a hidden app and runs a scripted sequence on the Tk main loop.

    The window is withdrawn, so widget visibility is checked with
    winfo_manager() -- winfo_ismapped() reports false for every child of an
    unmapped toplevel and would make such assertions vacuous.
    """

    def __init__(self, text, engine=None, store_dir=None):
        self.root = tk.Tk()
        self.root.withdraw()
        # Injected up front: the app restores the last article during __init__,
        # so swapping the store afterwards is already too late.
        store = SessionStore(base_dir=store_dir or tempfile.mkdtemp())
        self.app = UnifiedTTSApp(self.root, session_store=store)
        self.app.text_area.delete("1.0", "end")
        self.app.current_engine = engine or StubEngine()
        self.app.playback.engine = self.app.current_engine
        self.app.playback.RETRY_BACKOFF = 0.01
        self.player = SilentPlayer()
        self.app.playback._player = self.player
        self.app.text_area.insert("1.0", text)

    WATCHDOG_MS = 25_000

    def run(self, steps):
        """Run (delay_ms, callable) steps in order and collect their results.

        A step that raises records the exception and keeps the chain moving --
        otherwise a single failure would strand mainloop() and hang the suite.
        A watchdog quits regardless, so a wedged step fails instead of hanging.
        """
        results = []
        queue = list(steps)

        def advance():
            if not queue:
                self.root.quit()
                return
            delay, fn = queue.pop(0)

            def step():
                try:
                    results.append(fn())
                except Exception as exc:      # noqa: BLE001 - reported, not swallowed
                    results.append(exc)
                advance()

            self.root.after(delay, step)

        self.root.after(50, advance)
        self.root.after(self.WATCHDOG_MS, self.root.quit)
        self.root.mainloop()
        for item in results:
            if isinstance(item, Exception):
                raise AssertionError(f"step raised: {item!r}") from item
        return results

    def close(self):
        try:
            self.app._on_close()
        except Exception:
            self.root.destroy()


TEXT = " ".join(f"Sentence number {i} of the article." for i in range(1, 13))


class TestResumeDoesNotSwallowPlay:
    """Pressing play with a saved position produced a banner and silence."""

    def test_play_starts_immediately_at_the_saved_sentence(self):
        store_dir = tempfile.mkdtemp()
        SessionStore(base_dir=store_dir).save_position(
            TEXT, sentence_index=5, speed=1.5, engine="Stub"
        )
        h = AppHarness(TEXT, store_dir=store_dir)
        out = h.run([
            (0, h.app.on_play_pause),
            (700, lambda: (h.app.playback.state.value,
                           h.app.playback.current_index,
                           len(h.player.log))),
        ])
        h.close()
        state, index, clips = out[1]
        assert state == "playing", "play press produced no playback"
        assert index == 5, f"did not resume at the saved sentence (got {index})"
        assert clips >= 1, "no audio was sent to the speaker"

    def test_banner_is_shown_so_the_jump_is_explained(self):
        store_dir = tempfile.mkdtemp()
        SessionStore(base_dir=store_dir).save_position(
            TEXT, sentence_index=5, speed=1.5, engine="Stub"
        )
        h = AppHarness(TEXT, store_dir=store_dir)
        out = h.run([
            (0, h.app.on_play_pause),
            (400, lambda: (h.app.resume_frame.winfo_manager() == 'pack',
                           h.app.resume_label.cget("text"))),
        ])
        h.close()
        shown, label = out[1]
        assert shown, "resumed silently with no way to tell why"
        assert "6" in label and "12" in label, f"unhelpful banner text: {label!r}"

    def test_start_over_rewinds_and_keeps_playing(self):
        store_dir = tempfile.mkdtemp()
        SessionStore(base_dir=store_dir).save_position(
            TEXT, sentence_index=5, speed=1.5, engine="Stub"
        )
        h = AppHarness(TEXT, store_dir=store_dir)
        out = h.run([
            (0, h.app.on_play_pause),
            (400, h.app.on_start_over),
            (500, lambda: (h.app.playback.current_index,
                           h.app.playback.state.value,
                           h.app.resume_frame.winfo_manager() == 'pack')),
        ])
        h.close()
        index, state, banner = out[2]
        assert index == 0
        assert state == "playing"
        assert not banner, "banner should clear once it no longer applies"

    def test_no_saved_position_plays_from_the_top(self):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        out = h.run([
            (0, h.app.on_play_pause),
            (600, lambda: (h.app.playback.current_index,
                           h.app.playback.state.value)),
        ])
        h.close()
        assert out[1] == (0, "playing")


class TestErrorsStayOutOfTheWay:
    def test_failure_reports_in_the_status_bar_not_a_modal(self):
        modals = []
        real = tts_unified.messagebox.showerror
        tts_unified.messagebox.showerror = lambda *a, **kw: modals.append(a)
        try:
            h = AppHarness(TEXT, engine=StubEngine(fail=True), store_dir=tempfile.mkdtemp())
            out = h.run([
                (0, h.app.on_play_pause),
                (900, lambda: (h.app.status_label.cget("text"),
                               h.app.playback.state.value)),
            ])
            h.close()
        finally:
            tts_unified.messagebox.showerror = real
        status, state = out[1]
        assert not modals, "a dropped connection popped a modal dialog"
        assert "connection reset" in status.lower() or "error" in status.lower(), status
        assert state == "stopped"


class TestSpeedControlIsHonest:
    """The slider defaulted to 1.5x while Google TTS ignored everything above
    1.0x. If the engine cannot honour it, say so instead of pretending."""

    def _app(self, supports):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        engine = StubEngine()
        engine.supports_speed = lambda: supports
        h.app.current_engine = engine
        h.app._update_speed_availability()
        h.root.update()
        return h

    def test_slider_live_when_the_engine_honours_speed(self):
        h = self._app(True)
        state = str(h.app.speed_slider.cget("state"))
        hint = h.app.speed_hint.winfo_manager()
        h.close()
        assert state == "normal"
        assert hint != "pack", "hint shown even though speed works"

    def test_slider_disabled_and_explained_when_it_would_do_nothing(self):
        h = self._app(False)
        state = str(h.app.speed_slider.cget("state"))
        hint_shown = h.app.speed_hint.winfo_manager() == "pack"
        hint_text = h.app.speed_hint.cget("text")
        h.close()
        assert state == "disabled", "an inert slider was left looking live"
        assert hint_shown, "no explanation for the dead control"
        assert "ffmpeg" in hint_text.lower(), hint_text


class FakeKeyEvent:
    """Tk refuses to dispatch synthetic key events to an unmapped window, and
    parking a real one off-screen crashes macOS Tk -- so the handlers are
    driven directly, and the bindings are asserted separately."""

    def __init__(self, widget):
        self.widget = widget


class TestKeyboardShortcuts:
    """You should be able to drive playback without reaching for the mouse."""

    def _app(self):
        return AppHarness(TEXT, store_dir=tempfile.mkdtemp())

    def test_transport_keys_are_bound(self):
        h = self._app()
        missing = [seq for seq in ("<space>", "<Right>", "<Left>", "<Escape>", "<Up>", "<Down>")
                   if not h.root.bind_all(seq)]
        h.close()
        assert not missing, f"unbound shortcut keys: {missing}"

    def test_space_toggles_playback(self):
        h = self._app()
        key = FakeKeyEvent(h.root)
        out = h.run([
            (0, lambda: h.app._key_play_pause(key)),
            (600, lambda: h.app.playback.state.value),
            (0, lambda: h.app._key_play_pause(key)),
            (300, lambda: h.app.playback.state.value),
        ])
        h.close()
        assert out[1] == "playing"
        assert out[3] == "paused"

    def test_space_while_typing_is_declined(self):
        """The shortcut must not eat spaces in the article you are pasting."""
        h = self._app()
        typing = FakeKeyEvent(h.app.text_area)
        out = h.run([
            (0, lambda: h.app._key_play_pause(typing)),
            (400, lambda: h.app.playback.state.value),
        ])
        h.close()
        assert out[0] is None, "handler swallowed the keypress instead of letting it type"
        assert out[1] == "stopped", "space in the text box started playback"

    def test_arrow_keys_while_typing_are_declined(self):
        h = self._app()
        typing = FakeKeyEvent(h.app.text_area)
        results = [h.app._key_next(typing), h.app._key_prev(typing),
                   h.app._key_stop(typing), h.app._key_faster(typing)]
        h.close()
        assert results == [None, None, None, None], "shortcuts hijacked keys while typing"

    def test_arrows_skip(self):
        h = self._app()
        key = FakeKeyEvent(h.root)
        out = h.run([
            (0, h.app.on_play_pause),
            (700, lambda: h.app._key_next(key)),
            (200, lambda: h.app._key_next(key)),
            (400, lambda: h.app.playback.current_index),
            (0, lambda: h.app._key_prev(key)),
            (300, lambda: h.app.playback.current_index),
        ])
        h.close()
        assert out[3] == 2, f"two Rights should advance two sentences, got {out[3]}"
        assert out[5] == 1

    def test_escape_stops(self):
        h = self._app()
        key = FakeKeyEvent(h.root)
        out = h.run([
            (0, h.app.on_play_pause),
            (600, lambda: h.app._key_stop(key)),
            (300, lambda: (h.app.playback.state.value, h.app.playback.current_index)),
        ])
        h.close()
        assert out[2] == ("stopped", 0)

    def test_up_and_down_change_speed(self):
        h = self._app()
        key = FakeKeyEvent(h.root)
        start = h.app._current_speed
        out = h.run([
            (0, lambda: h.app._key_faster(key)),
            (150, lambda: h.app._current_speed),
            (0, lambda: h.app._key_slower(key)),
            (150, lambda: h.app._current_speed),
        ])
        h.close()
        assert out[1] > start
        assert out[3] == pytest.approx(start, abs=0.001)

    def test_speed_keys_stay_inside_the_slider_range(self):
        h = self._app()
        key = FakeKeyEvent(h.root)
        for _ in range(40):
            h.app._key_faster(key)
        high = h.app._current_speed
        for _ in range(80):
            h.app._key_slower(key)
        low = h.app._current_speed
        h.close()
        assert high == pytest.approx(2.0, abs=0.001)
        assert low == pytest.approx(0.5, abs=0.001)


class TestClickToJump:
    def test_clicking_a_sentence_jumps_to_it(self):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        target = TEXT.index("Sentence number 4")
        out = h.run([
            (0, h.app.on_play_pause),
            (700, lambda: h.app._jump_to_text_index(f"1.{target + 3}")),
            (400, lambda: h.app.playback.current_index),
        ])
        h.close()
        assert out[1] is True, "click was not treated as a jump"
        assert out[2] == 3, f"clicked sentence 4, landed on index {out[2]}"

    def test_click_before_any_text_is_loaded_does_nothing(self):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        out = h.run([(0, lambda: h.app._jump_to_text_index("1.5"))])
        h.close()
        assert out[0] is False

    def test_click_after_editing_does_not_jump_to_the_wrong_place(self):
        """Stale sentence offsets would land the reader somewhere random."""
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        out = h.run([
            (0, h.app.on_play_pause),
            (700, lambda: h.app.text_area.insert("1.0", "Freshly typed words. ")),
            (0, lambda: h.app._jump_to_text_index("1.5")),
        ])
        h.close()
        assert out[2] is False


class TestRemembersArticleAndShowsTimeLeft:
    def test_article_is_restored_on_launch(self):
        store_dir = tempfile.mkdtemp()
        SessionStore(base_dir=store_dir).save_last_text("Remembered article text.")
        root = tk.Tk(); root.withdraw()
        try:
            app = UnifiedTTSApp(root, session_store=SessionStore(base_dir=store_dir))
            restored = app.text_area.get("1.0", "end-1c")
        finally:
            root.destroy()
        assert restored.strip() == "Remembered article text."

    def test_closing_remembers_the_article(self):
        store_dir = tempfile.mkdtemp()
        h = AppHarness("An article worth keeping. It has two sentences.", store_dir=store_dir)
        h.close()
        assert SessionStore(base_dir=store_dir).load_last_text().strip() \
            == "An article worth keeping. It has two sentences."

    def test_progress_shows_time_remaining_not_just_a_percentage(self):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        out = h.run([
            (0, h.app.on_play_pause),
            (700, lambda: h.app.progress_label.cget("text")),
        ])
        h.close()
        label = out[1]
        assert "%" in label, f"lost the percentage: {label!r}"
        assert "sec" in label or "min" in label, f"no time estimate: {label!r}"


# ── Neural voices in the engine dropdown ────────────────────────────────────

import voice_catalog
from tts_unified import NeuralTTSEngine


class FakeVoiceClient:
    """Stands in for the voice worker; records who asked for what."""

    def __init__(self):
        self.active = None
        self.synths = []
        self.loads = []
        self.closed = 0

    def set_active(self, key):
        self.active = key

    def load(self, key):
        self.loads.append(key)
        return 0.0

    def synth(self, engine_key, text, voice, speed, out_path):
        self.synths.append((engine_key, voice, text))
        with open(out_path, "wb") as f:
            f.write(b"RIFF")
        return {"path": out_path}

    def close(self):
        self.active = None
        self.closed += 1


class NeuralHarness(AppHarness):
    """The real app, with the neural engines wired to a fake worker and
    treated as installed."""

    def __init__(self, text, monkeypatch):
        monkeypatch.setattr(voice_catalog, "unavailable_reason", lambda spec: "")
        monkeypatch.setattr(voice_catalog, "is_downloaded", lambda repo: True)
        super().__init__(text, store_dir=tempfile.mkdtemp())
        self.client = FakeVoiceClient()
        self.app.voice_client = self.client
        for spec in voice_catalog.ENGINES:
            self.app.engines[spec.key] = NeuralTTSEngine(spec, self.client)
        self.app._current_speed = 1.0   # skip ffmpeg re-timing of the fake clips
        self.app.check_engines_and_initialize()

    def select(self, key):
        self.app.engine_combo.current(self.app._engine_keys.index(key))
        self.app.on_engine_change()


class TestNeuralVoicesInTheDropdown:
    def test_every_voice_is_listed_and_explained_when_not_set_up(self):
        """Without the voices environment they still show, greyed out with a
        reason, rather than silently missing."""
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        labels = list(h.app.engine_combo["values"])
        h.app.engine_combo.current(h.app._engine_keys.index("phonon"))
        h.app.on_engine_change()
        status = h.app.status_label.cget("text")
        enabled = getattr(h.app.play_pause_button, "_enabled", True)
        h.close()
        for spec in voice_catalog.ENGINES:
            assert any(label.startswith(spec.name) for label in labels), spec.name
        assert "README" in status, status
        assert enabled is False

    def test_kokoro_heart_is_the_default_when_installed(self, monkeypatch):
        h = NeuralHarness(TEXT, monkeypatch)
        key = h.app._selected_engine_key()
        voice = h.app._current_voice
        voice_shown = h.app.voice_frame.winfo_manager() == "pack"
        h.close()
        assert (key, voice) == ("kokoro", "af_heart")
        assert voice_shown, "no voice picker for a neural engine"

    def test_phonon_takes_over_where_kokoro_cannot_run(self, monkeypatch):
        """Kokoro needs an Apple Silicon Mac and espeak-ng; elsewhere the app
        should still open on a neural voice."""
        monkeypatch.setattr(voice_catalog, "is_downloaded", lambda repo: True)
        h = NeuralHarness(TEXT, monkeypatch)
        monkeypatch.setattr(voice_catalog, "unavailable_reason",
                            lambda spec: "needs espeak-ng" if spec.key == "kokoro" else "")
        h.app.check_engines_and_initialize()
        key = h.app._selected_engine_key()
        h.close()
        assert key == "phonon"

    def test_switching_engine_mid_playback_carries_on_in_the_new_one(self, monkeypatch):
        h = NeuralHarness(TEXT, monkeypatch)
        h.select("phonon")
        out = h.run([
            (0, h.app.on_play_pause),
            (400, lambda: h.select("ming")),
            (900, lambda: (h.app.playback.state.value, list(h.client.synths))),
        ])
        h.close()
        state, synths = out[2]
        assert state == "playing"
        assert synths[0][0] == "phonon"
        in_ming = [text for engine, _, text in synths if engine == "ming"]
        assert in_ming, "kept talking in the old engine"
        assert in_ming[0].startswith("Sentence number 1 "), "lost its place on the switch"

    def test_changing_voice_mid_playback_is_heard_at_once(self, monkeypatch):
        h = NeuralHarness(TEXT, monkeypatch)
        h.select("phonon")
        hugh = h.app._voice_ids.index("Hugh")

        def pick_hugh():
            h.app.voice_combo.current(hugh)
            h.app.on_voice_change()

        out = h.run([
            (0, h.app.on_play_pause),
            (400, pick_hugh),
            (900, lambda: list(h.client.synths)),
        ])
        h.close()
        synths = out[2]
        assert synths[0][1] == "Everly"
        in_hugh = [text for _, voice, text in synths if voice == "Hugh"]
        assert in_hugh, "the new voice was never used"
        assert in_hugh[0].startswith("Sentence number 1 "), "the change waited for the buffer"

    def test_picking_a_voice_that_cannot_run_frees_the_loaded_one(self, monkeypatch):
        """Drama 3 loaded, then "Kokoro · unavailable" picked: nothing will
        play, so the 24 GB should not stay in memory either."""
        h = NeuralHarness(TEXT, monkeypatch)
        h.select("drama3")
        before = h.client.closed
        monkeypatch.setattr(voice_catalog, "unavailable_reason",
                            lambda spec: "needs espeak-ng" if spec.key == "kokoro" else "")
        h.select("kokoro")
        closed, active = h.client.closed, h.client.active
        h.close()
        assert closed > before, "the previous model was left loaded"
        assert active is None

    def test_leaving_the_neural_voices_shuts_the_worker_down(self, monkeypatch):
        """A heavy model should not sit in memory once you pick Piper or Google."""
        h = NeuralHarness(TEXT, monkeypatch)
        before = h.client.closed
        target = "piper" if h.app.engines["piper"].is_available() else "google"
        h.select(target)
        closed = h.client.closed
        h.close()
        assert closed > before


class TestPlaybackThreadNeverWaitsOnTheUI:
    """Calling into Tk from the playback thread blocks until something else
    wakes the event loop -- on macOS that could be seconds, and it was:
    after an engine switch the new voice stayed silent until the next timer
    or keypress happened along. UI updates must be posted, never awaited."""

    def test_status_updates_from_the_playback_thread_never_wait_on_tk(self):
        h = AppHarness(TEXT, store_dir=tempfile.mkdtemp())
        h.app._wire_playback_callbacks()
        result = {}

        def from_playback_thread():
            start = time.monotonic()
            try:
                h.app.playback.on_generating(0)
                h.app.playback.on_sentence_start(0)
                result["ok"] = True
            except Exception as exc:  # noqa: BLE001 - reported below
                result["error"] = exc
            result["took"] = time.monotonic() - start

        # The main thread is busy (here: joining), not servicing Tk -- the
        # state that left playback stalled. A posted update must not care.
        t = threading.Thread(target=from_playback_thread, daemon=True)
        t.start()
        t.join(3)
        out = h.run([(300, lambda: h.app.status_label.cget("text"))])
        h.close()
        assert result.get("ok"), f"update from the playback thread failed: {result.get('error')!r}"
        assert result["took"] < 0.2, f"playback thread waited {result['took']:.2f}s on Tk"
        assert out[0] == "Speaking…", "the posted update never reached the UI"
