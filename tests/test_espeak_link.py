"""Kokoro's espeak-ng fallback must load when a browser started the worker."""
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "local_tts", "voices"))

import espeak_link  # noqa: E402


def make_library(tmp_path):
    real = tmp_path / "lib" / "libespeak-ng.1.dylib"
    real.parent.mkdir()
    real.write_bytes(b"library")
    dest = tmp_path / "tmp"
    dest.mkdir()
    return real, dest / real.name


def test_the_copy_is_a_real_copy_when_nothing_marks_it(tmp_path):
    real, dest = make_library(tmp_path)
    result = espeak_link.CopyWithoutQuarantine.copy(real, dest, follow_symlinks=False)
    assert result == dest and not dest.is_symlink()
    assert dest.read_bytes() == b"library"


@pytest.mark.skipif(sys.platform != "darwin", reason="quarantine is a macOS mark")
def test_a_quarantined_copy_has_the_mark_removed(tmp_path, monkeypatch):
    """Started by a browser, every file the worker writes arrives marked."""
    real, dest = make_library(tmp_path)
    marking_copy = espeak_link.shutil.copy

    def copy_and_mark(src, dst, **kw):
        out = marking_copy(src, dst, **kw)
        subprocess.run(["xattr", "-w", "com.apple.quarantine", "0081;00000000;Firefox;", str(out)],
                       check=True)
        return out

    monkeypatch.setattr(espeak_link.shutil, "copy", copy_and_mark)
    result = espeak_link.CopyWithoutQuarantine.copy(real, dest, follow_symlinks=False)
    assert not dest.is_symlink()
    marks = subprocess.run(["xattr", str(result)], capture_output=True, text=True).stdout
    assert "com.apple.quarantine" not in marks


def test_a_mark_that_will_not_come_off_falls_back_to_a_link(tmp_path, monkeypatch):
    real, dest = make_library(tmp_path)
    monkeypatch.setattr(espeak_link, "clear_quarantine", lambda path: False)
    result = espeak_link.CopyWithoutQuarantine.copy(real, dest, follow_symlinks=False)
    assert dest.is_symlink() and os.readlink(dest) == str(real.resolve())
    assert result == dest


def test_copying_over_an_existing_file_replaces_it(tmp_path):
    real, dest = make_library(tmp_path)
    dest.write_bytes(b"stale")
    espeak_link.CopyWithoutQuarantine.copy(real, dest)
    assert dest.read_bytes() == b"library"


def test_a_directory_destination_keeps_the_name(tmp_path):
    real, dest = make_library(tmp_path)
    result = espeak_link.CopyWithoutQuarantine.copy(real, dest.parent)
    assert result == str(dest)
    assert os.path.isfile(result)


def test_everything_else_is_the_real_shutil(tmp_path):
    folder = tmp_path / "tempdir"
    folder.mkdir()
    (folder / "link").symlink_to(tmp_path)
    espeak_link.CopyWithoutQuarantine().rmtree(folder)
    assert not folder.exists() and tmp_path.exists()


def test_install_swaps_shutil_in_phonemizer_only():
    import shutil
    module = types.SimpleNamespace(shutil=shutil)
    espeak_link.install(module)
    assert isinstance(module.shutil, espeak_link.CopyWithoutQuarantine)
    assert shutil.copy is not module.shutil.copy


VOICES_PYTHON = os.path.expanduser("~/.local/share/local-tts/voices-env/bin/python")
HOMEBREW_ESPEAK = "/opt/homebrew/opt/espeak-ng/lib/libespeak-ng.dylib"

PHONEMIZE = """
import os, sys, glob, tempfile
sys.path.insert(0, sys.argv[1])
import espeak_link
espeak_link.install()
from phonemizer.backend.espeak.wrapper import EspeakWrapper
EspeakWrapper.set_library(sys.argv[2])
EspeakWrapper.set_data_path(sys.argv[3])
from phonemizer.backend import EspeakBackend
backend = EspeakBackend("en-us")
import phonemizer.backend.espeak.api as api
copies = [p for p in glob.glob(os.path.join(tempfile.gettempdir(), "*", "libespeak-ng*.dylib"))
          if os.path.isfile(p) and not os.path.islink(p)]
print(backend.phonemize(["Kubernetes"])[0].strip())
print(type(api.shutil).__name__)
"""


@pytest.mark.skipif(not (os.path.exists(VOICES_PYTHON) and os.path.exists(HOMEBREW_ESPEAK)),
                    reason="needs the voices environment and Homebrew espeak-ng")
def test_phonemizer_really_works_through_the_link():
    data = "/opt/homebrew/opt/espeak-ng/share/espeak-ng-data"
    out = subprocess.run([VOICES_PYTHON, "-c", PHONEMIZE, os.path.dirname(espeak_link.__file__),
                          HOMEBREW_ESPEAK, data], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    phonemes, patched = out.stdout.split("\n")[:2]
    assert phonemes and patched == "CopyWithoutQuarantine", out.stdout
