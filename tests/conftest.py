"""Suite-wide setup.

The app lists the neural voices and warms up the selected one at startup. In
tests that would launch the real voice worker and load a model for every UI
test, so the voices environment is pointed somewhere empty: the neural
engines then report "not set up" and the app falls back to Piper/Google,
exactly as on a machine without them. Tests that need the worker pass an
interpreter explicitly.
"""
import os

os.environ["LOCAL_TTS_VOICES_PYTHON"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "no-voices-env", "bin", "python")
