"""Make phonemizer's private copy of espeak-ng loadable when a browser started us.

phonemizer copies the espeak library into a temporary folder before loading
it, so that several instances (an American and a British voice, say) each get
their own copy of its global state. When a browser starts the voices (the
Local TTS extension), every file this process writes is marked as downloaded
(com.apple.quarantine), and macOS refuses to load an unnotarized library with
that mark: Kokoro then silently skips every word missing from its dictionary.

So the copy is made as before and the mark taken off it. Should the mark not
come off, the copy is replaced by a link to the original, which carries no
mark and loads as it does from a terminal.

Standard library only: this runs in the voices environment.
"""
import ctypes
import os
import shutil
import sys

QUARANTINE = b"com.apple.quarantine"


def clear_quarantine(path) -> bool:
    """Take the downloaded-file mark off `path`; True if it is not marked now."""
    if sys.platform != "darwin":
        return True
    libc = ctypes.CDLL(None, use_errno=True)
    name = os.fsencode(os.fspath(path))
    libc.removexattr(name, QUARANTINE, 0)
    # getxattr returns -1 once the attribute is gone
    return libc.getxattr(name, QUARANTINE, None, 0, 0, 0) < 0


class CopyWithoutQuarantine:
    """Stands in for `shutil` inside phonemizer: `copy` copies and unmarks, the
    rest is shutil itself."""

    def __getattr__(self, name):
        return getattr(shutil, name)

    @staticmethod
    def copy(src, dst, *, follow_symlinks=True):
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        dst = shutil.copy(src, dst, follow_symlinks=follow_symlinks)
        if clear_quarantine(dst):
            return dst
        os.remove(dst)
        os.symlink(os.path.realpath(src), dst)
        return dst


def install(module=None) -> None:
    """Point phonemizer's espeak loader at CopyWithoutQuarantine."""
    if module is None:
        from phonemizer.backend.espeak import api as module
        if "shutil.copy(" not in open(module.__file__, encoding="utf-8").read():
            print("espeak_link: phonemizer no longer copies espeak with shutil.copy; "
                  "under a browser, Kokoro may skip unknown words", file=sys.stderr)
    module.shutil = CopyWithoutQuarantine()
