"""Load espeak-ng in place instead of from a fresh copy.

phonemizer copies the espeak library into a temporary folder before loading
it, so that several instances can each hold their own. When a browser starts
the voices (the Local TTS extension), every file this process writes is
marked as downloaded, and macOS refuses to load an unnotarized library with
that mark: the copy fails where the original loads fine, and Kokoro silently
skips every word it has no dictionary entry for. A link to the original
loads the original. One phonemizer instance per worker needs no copy.

Standard library only: this runs in the voices environment.
"""
import os
import shutil


class LinkInsteadOfCopy:
    """Stands in for `shutil` inside phonemizer: `copy` links, the rest is shutil."""

    def __getattr__(self, name):
        return getattr(shutil, name)

    @staticmethod
    def copy(src, dst, *, follow_symlinks=True):
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        os.symlink(os.path.realpath(src), dst)
        return dst


def install(module=None) -> None:
    """Point phonemizer's espeak loader at LinkInsteadOfCopy."""
    if module is None:
        from phonemizer.backend.espeak import api as module
    module.shutil = LinkInsteadOfCopy()
