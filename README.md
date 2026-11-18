# Local TTS

We didn't want to pay for a text-to-speech Chrome extension, so we built our own.

## What It Does

Paste in an article, hit play, and listen. The app splits your text into sentences and reads them one at a time, so you can pause, skip around, and pick up where you left off -- even after closing the app.

## Quick Start

```bash
git clone https://github.com/0xkato/local-tts.git
cd local-tts
uv venv && uv pip install -r requirements.txt
uv run python tts_unified.py
```

## Features

- **Sentence-by-sentence playback** -- text is split into sentences, played one at a time with the current sentence highlighted
- **Keyboard control** -- space to play/pause, arrows to skip, up/down for speed, escape to stop
- **Click to jump** -- click any sentence in the text to start reading from there
- **Pause and resume** -- stop mid-article, come back later, pick up right where you left off
- **Remembers your article** -- reopen the app and your text is still there, resumed where you stopped
- **Progress tracking** -- percentage plus an estimate of the time left
- **Speed control** -- defaults to 1.5x, adjustable from 0.5x to 2.0x
- **Seven engines, one dropdown** -- five neural voices (below), Piper TTS (offline) and Google TTS (online, multiple languages). Switch mid-article and it carries on from the same sentence in the new voice
- **Reads pasted articles cleanly** -- markdown, links and URLs are stripped rather than spelled out
- **Dark themed UI** -- colored transport buttons, highlighted current sentence

## Neural Voices (Recommended)

Much more natural than Piper or Google, and still fully offline. Each one
appears in the engine dropdown, with a voice picker beside it:

| Voice | Weight | Download | Runs on |
|---|---|---|---|
| Kokoro *(default, "Heart" voice)* | light | 330 MB | Apple Silicon Mac |
| Phonon | light | 220 MB | any laptop |
| Ming 3.0 | medium | 3 GB | recent Apple Silicon Mac |
| Breeze TTS 2 | heavy | 7.6 GB | Apple Silicon Mac, 16 GB+ RAM (non-commercial licence) |
| Fish Drama 3 | very heavy | 24 GB | Apple Silicon Mac, 32 GB+ RAM |

Kokoro with the Heart voice is the default; where Kokoro cannot run (not an
Apple Silicon Mac, or no espeak-ng) the app opens on Phonon instead. The
heavier voices work the machine hard (fans, heat); pick one only when you
want it. A model downloads
the first time you select it, and only one is ever in memory -- switching to
another voice, or to Piper/Google, frees it.

They run in a worker process with an environment of their own (Python 3.11+),
so the app's own setup stays untouched:

```bash
brew install espeak-ng ffmpeg      # Kokoro needs espeak-ng; speed control needs ffmpeg
uv venv -p 3.11 ~/.local/share/local-tts/voices-env
VIRTUAL_ENV=~/.local/share/local-tts/voices-env uv pip install -r requirements-voices.txt
```

The app finds that environment on its own; set `LOCAL_TTS_VOICES_PYTHON` to use
one somewhere else. Worker output goes to `~/.local/share/local-tts/voices-worker.log`.

Breeze and Drama 3 copy a reference voice rather than having built-in ones.
The first time either is used, Breeze designs a "soothing narrator" voice from
a text description and saves it to `~/.local/share/local-tts/voices/` (a WAV
plus its transcript). Swap in your own clip there to change it. It stays out
of the repo because Breeze's outputs carry its non-commercial licence.

## Offline Mode (Optional)

Want it fully offline? Install Piper TTS:

```bash
uv pip install piper-tts
```

Then download a voice model (12MB):

```bash
mkdir -p ~/.local/share/piper
wget -O ~/.local/share/piper/en_US-norman-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx
wget -O ~/.local/share/piper/en_US-norman-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json
```

Select "Piper TTS" from the engine dropdown.

## Speed Control on Google TTS

Google TTS has no real speed setting -- only "normal" and "slow" -- so changing
the speed does nothing on its own. The app re-times the audio with ffmpeg
instead, which preserves pitch:

```bash
brew install ffmpeg
```

Without ffmpeg the speed slider is disabled while Google TTS is selected, rather
than sitting there doing nothing. Piper and Kokoro honour speed natively; the
other neural voices are re-timed with ffmpeg the same way Google's are.

## Requirements

- Python 3.7+
- Audio output device
- ffmpeg (optional) -- speed control for Google TTS

## Tests

```bash
python -m pytest tests/
```

UI tests need a working Tk display and skip automatically without one. The
voice worker is tested against a built-in fake voice, so no models are needed.

## License

MIT
