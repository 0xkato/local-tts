"""The neural voices the app offers, shared by the app and the voice worker.

Pure data and the standard library only: the app (whatever Python runs Tk)
and the worker (its own environment, Python 3.11+ for mlx-audio) both import
this, and neither may drag the other's dependencies in.
"""
from __future__ import annotations

import glob
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

DATA_DIR = os.path.expanduser("~/.local/share/local-tts")
WORKER_LOG = os.path.join(DATA_DIR, "voices-worker.log")
DEFAULT_VOICES_PYTHON = os.path.join(DATA_DIR, "voices-env", "bin", "python")

# Every neural clip gets the same trailing pause, so sentences are spaced
# evenly whatever silence a model happens to leave. Seconds at 1x speed.
TAIL_PAUSE = 0.25
LEAD_PAD = 0.03


@dataclass(frozen=True)
class EngineSpec:
    key: str
    name: str
    weight: str                 # shown in the dropdown: light / medium / heavy
    detail: str                 # shown beside it: size, hardware, licence
    backend: str                # "phonon" (ptts) or "mlx" (mlx-audio)
    repo: str                   # Hugging Face repo holding the weights
    voices: tuple = field(default_factory=tuple)   # (voice id, label) pairs
    default_voice: str = ""
    native_speed: bool = False  # False: the app re-times the clip with ffmpeg
    apple_only: bool = False    # mlx-audio needs Apple Silicon
    needs_espeak: bool = False  # Kokoro's out-of-dictionary fallback
    download_size: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} — {self.weight}"

    def voice_label(self, voice_id: str) -> str:
        return dict(self.voices).get(voice_id, voice_id)


ENGINES = (
    EngineSpec(
        key="kokoro", name="Kokoro", weight="light",
        detail="330 MB · Mac", backend="mlx",
        repo="mlx-community/Kokoro-82M-bf16",
        voices=(
            ("af_heart", "Heart (US)"),
            ("af_bella", "Bella (US)"),
            ("af_nicole", "Nicole (US, hushed)"),
            ("af_sarah", "Sarah (US)"),
            ("am_michael", "Michael (US)"),
            ("am_fenrir", "Fenrir (US)"),
            ("bf_emma", "Emma (UK)"),
            ("bm_george", "George (UK)"),
        ),
        default_voice="af_heart", native_speed=True, apple_only=True,
        needs_espeak=True, download_size="330 MB",
    ),
    EngineSpec(
        key="phonon", name="Phonon", weight="light",
        detail="65 MB · runs on any laptop", backend="phonon",
        repo="gradium/phonon-31m-en",
        voices=(
            ("Everly", "Everly — soft, relaxed"),
            ("Hugh", "Hugh — soft, close"),
            ("Spencer", "Spencer — airy, patient"),
            ("Hadley", "Hadley — even, kind"),
            ("Delia", "Delia — low, grounded"),
            ("Juniper", "Juniper — warm, resonant"),
            ("Preston", "Preston — steady, low"),
            ("Miles", "Miles — resonant"),
            ("Harper", "Harper — friendly"),
            ("Edwin", "Edwin — firm, tidy"),
        ),
        default_voice="Everly", download_size="220 MB",
    ),
    EngineSpec(
        key="ming", name="Ming 3.0", weight="medium",
        detail="3 GB · recent Mac", backend="mlx",
        repo="mlx-community/Ming-3.0-tts-0.5B-bf16",
        voices=(
            ("US_James", "James (US)"),
            ("US_Emma", "Emma (US)"),
            ("US_Stella", "Stella (US)"),
            ("UK_George", "George (UK)"),
            ("UK_Charlotte", "Charlotte (UK)"),
        ),
        default_voice="US_James", apple_only=True, download_size="3 GB",
    ),
)

BY_KEY = {spec.key: spec for spec in ENGINES}


def voices_python() -> str:
    """The interpreter of the voices environment, overridable for tests."""
    return os.environ.get("LOCAL_TTS_VOICES_PYTHON", DEFAULT_VOICES_PYTHON)


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def hf_hub_cache() -> str:
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    return os.path.join(home, "hub")


def is_downloaded(repo: str) -> bool:
    """Whether a Hugging Face repo already sits in the local cache."""
    folder = os.path.join(hf_hub_cache(), "models--" + repo.replace("/", "--"), "snapshots")
    return any(os.listdir(p) for p in glob.glob(os.path.join(folder, "*")) if os.path.isdir(p))


ESPEAK_PREFIXES = ("/opt/homebrew/opt/espeak-ng", "/usr/local/opt/espeak-ng")


def espeak_paths() -> tuple[str, str] | None:
    """(library, data dir) of a system espeak-ng.

    The espeak that pip ships for Kokoro has its data path baked in from the
    build machine and exits the whole process on first use, so a Homebrew one
    is required instead.
    """
    for prefix in ESPEAK_PREFIXES:
        for lib in ("libespeak-ng.dylib", "libespeak-ng.so", "libespeak-ng.so.1"):
            path = os.path.join(prefix, "lib", lib)
            data = os.path.join(prefix, "share", "espeak-ng-data")
            if os.path.exists(path) and os.path.isdir(data):
                return path, data
    found = shutil.which("espeak-ng")
    if found:
        prefix = os.path.dirname(os.path.dirname(os.path.realpath(found)))
        for lib in ("libespeak-ng.dylib", "libespeak-ng.so", "libespeak-ng.so.1"):
            path = os.path.join(prefix, "lib", lib)
            data = os.path.join(prefix, "share", "espeak-ng-data")
            if os.path.exists(path) and os.path.isdir(data):
                return path, data
    return None


def unavailable_reason(spec: EngineSpec) -> str:
    """Why an engine cannot run here, or "" when it can."""
    if spec.apple_only and not is_apple_silicon():
        return "needs an Apple Silicon Mac"
    if not os.path.exists(voices_python()):
        return "neural voices are not set up — see the README"
    if spec.needs_espeak and espeak_paths() is None:
        return "needs espeak-ng — brew install espeak-ng"
    return ""
