"""local-tts as a package other front ends can install and import."""
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_python(code):
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                          text=True, timeout=60)


def test_the_engine_imports_without_tkinter():
    """The browser plugin's host has no window and may have no Tk at all."""
    result = run_python("import sys, local_tts.engine; print('tkinter' in sys.modules)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_importing_the_engine_prints_nothing():
    """A host that talks over stdout cannot have pygame greeting it there."""
    result = run_python("import local_tts.engine")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_dependency_check_runs_as_a_module():
    result = subprocess.run([sys.executable, "-m", "local_tts", "--check"], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "Kokoro" in result.stdout


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")
def test_the_wheel_carries_the_voice_worker(tmp_path):
    """The worker runs as a script from the installed package, next to the
    catalog it imports -- and nothing else of ours, so nothing in that folder
    can shadow a module the voices environment imports."""
    # Built from a copy: setuptools leaves build/ and *.egg-info behind
    src = tmp_path / "src"
    shutil.copytree(REPO, src, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", "build", "*.egg-info"))
    out = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(src)],
                   check=True, capture_output=True, timeout=300)
    wheel = next(p for p in os.listdir(out) if p.endswith(".whl"))
    names = zipfile.ZipFile(out / wheel).namelist()
    voices = sorted(n for n in names if n.startswith("local_tts/voices/"))
    assert voices == ["local_tts/voices/__init__.py", "local_tts/voices/voice_catalog.py",
                      "local_tts/voices/voice_worker.py"]
    assert "local_tts/engine.py" in names and "local_tts/app.py" in names
    assert not [n for n in names if n.startswith("tests/")]
