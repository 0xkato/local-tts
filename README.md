# Local TTS

We didn't want to pay for a text-to-speech Chrome extension, so we built our own.

## What It Does

Paste in an article, hit play, and listen. The app splits your text into sentences and reads them one at a time with natural-sounding neural voices that run entirely on your machine, so you can pause, skip around, and pick up where you left off -- even after closing the app.

## Quick Start

```bash
git clone https://github.com/0xkato/local-tts.git
cd local-tts
brew install espeak-ng ffmpeg        # Kokoro needs espeak-ng; speed control needs ffmpeg

# The app itself (any Python 3.10+ with Tk)
uv venv && uv pip install -e .

# The voices, in an environment of their own (Python 3.11+)
uv venv -p 3.11 ~/.local/share/local-tts/voices-env
VIRTUAL_ENV=~/.local/share/local-tts/voices-env uv pip install ".[voices]"

.venv/bin/local-tts
```

`local-tts --check` lists anything that is still missing. `python tts_unified.py`
starts the app too.

## Voices

Pick one from the engine dropdown, with a voice picker beside it:

| Engine | Voices | Download | Runs on |
|---|---|---|---|
| Kokoro *(default)* | Heart, Bella, Nicole, Michael, Emma, ... | 330 MB | Apple Silicon Mac |
| Phonon | Everly, Hugh, Spencer, Hadley, ... | 220 MB | any laptop |
| Ming 3.0 | James, Emma, Stella, George, Charlotte | 3 GB | recent Apple Silicon Mac |

Kokoro with the Heart voice is the default; where Kokoro cannot run (not an
Apple Silicon Mac, or no espeak-ng) the app opens on Phonon instead. A model
downloads the first time you select it, and only one is in memory at a time.

The voices run in a worker process using that second environment, so the
app's own Python stays light. The app finds the environment on its own; set
`LOCAL_TTS_VOICES_PYTHON` to use one somewhere else. Worker output goes to
`~/.local/share/local-tts/voices-worker.log`.

## Features

- **Sentence-by-sentence playback** -- text is split into sentences, played one at a time with the current sentence highlighted
- **Switch voices mid-article** -- change engine or voice and it carries on from the same sentence in the new voice
- **Keyboard control** -- space to play/pause, arrows to skip, up/down for speed, escape to stop
- **Click to jump** -- click any sentence in the text to start reading from there
- **Pause and resume** -- stop mid-article, come back later, pick up right where you left off
- **Remembers your article** -- reopen the app and your text is still there, resumed where you stopped
- **Progress tracking** -- percentage plus an estimate of the time left
- **Speed control** -- defaults to 1.5x, adjustable from 0.5x to 2.0x. Kokoro changes speed natively; the other voices are re-timed with ffmpeg, which keeps the pitch (without ffmpeg the slider is disabled for them rather than doing nothing)
- **Reads pasted articles cleanly** -- markdown, links and URLs are stripped rather than spelled out
- **Dark themed UI** -- colored transport buttons, highlighted current sentence

## Requirements

- Python 3.10+ with Tk for the app, Python 3.11+ for the voices
- An Apple Silicon Mac for Kokoro and Ming; Phonon runs anywhere
- espeak-ng (Kokoro) and ffmpeg (speed control)
- Audio output device

## Using the engine from other code

The engine is a package without any window code, so other front ends can
install and import it:

```bash
pip install "local-tts @ git+https://github.com/0xkato/local-tts@v1.1.1"
```

```python
from local_tts.engine import NeuralTTSEngine, PlaybackController, VoiceWorkerClient
from local_tts.voices import voice_catalog
```

`local_tts/app.py` is the desktop window built on it.

## Tests

```bash
python -m pytest tests/
```

UI tests need a working Tk display and skip automatically without one. The
voice worker is tested against a built-in fake voice, so no models are needed.

## License

MIT
