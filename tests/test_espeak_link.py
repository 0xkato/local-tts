"""Kokoro's espeak-ng fallback must load when a browser started the worker."""
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "local_tts", "voices"))

import espeak_link  # noqa: E402


def test_the_copy_is_a_link_to_the_real_file(tmp_path):
    real = tmp_path / "lib" / "libespeak-ng.1.dylib"
    real.parent.mkdir()
    real.write_bytes(b"library")
    alias = tmp_path / "lib" / "libespeak-ng.dylib"
    alias.symlink_to("libespeak-ng.1.dylib")
    dest = tmp_path / "tmp" / "libespeak-ng.1.dylib"
    dest.parent.mkdir()

    result = espeak_link.LinkInsteadOfCopy.copy(alias, dest, follow_symlinks=False)

    assert result == dest
    assert dest.is_symlink()
    assert os.readlink(dest) == str(real.resolve())


def test_a_directory_destination_keeps_the_name(tmp_path):
    real = tmp_path / "libespeak-ng.1.dylib"
    real.write_bytes(b"library")
    folder = tmp_path / "copy"
    folder.mkdir()
    result = espeak_link.LinkInsteadOfCopy.copy(real, folder)
    assert result == os.path.join(folder, "libespeak-ng.1.dylib")
    assert os.path.islink(result)


def test_everything_else_is_the_real_shutil(tmp_path):
    folder = tmp_path / "tempdir"
    folder.mkdir()
    (folder / "link").symlink_to(tmp_path)
    espeak_link.LinkInsteadOfCopy().rmtree(folder)
    assert not folder.exists() and tmp_path.exists()


def test_install_swaps_shutil_in_phonemizer_only():
    import shutil
    module = types.SimpleNamespace(shutil=shutil)
    espeak_link.install(module)
    assert isinstance(module.shutil, espeak_link.LinkInsteadOfCopy)
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
loaded = [p for p in glob.glob(os.path.join(tempfile.gettempdir(), "*", "libespeak-ng*.dylib"))
          if os.path.islink(p) and os.readlink(p) == os.path.realpath(sys.argv[2])]
print(backend.phonemize(["Kubernetes"])[0].strip())
print("linked" if loaded else "copied")
"""


@pytest.mark.skipif(not (os.path.exists(VOICES_PYTHON) and os.path.exists(HOMEBREW_ESPEAK)),
                    reason="needs the voices environment and Homebrew espeak-ng")
def test_phonemizer_really_works_through_the_link():
    data = "/opt/homebrew/opt/espeak-ng/share/espeak-ng-data"
    out = subprocess.run([VOICES_PYTHON, "-c", PHONEMIZE, os.path.dirname(espeak_link.__file__),
                          HOMEBREW_ESPEAK, data], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    phonemes, how = out.stdout.split("\n")[:2]
    assert phonemes and how == "linked", out.stdout
