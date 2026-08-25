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
- **Two engines** -- Google TTS (online, multiple languages) or Piper TTS (offline, private)
- **Reads pasted articles cleanly** -- markdown, links and URLs are stripped rather than spelled out
- **Dark themed UI** -- colored transport buttons, highlighted current sentence

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
than sitting there doing nothing. Piper honours speed natively and needs no
extra setup.

## Requirements

- Python 3.7+
- Audio output device
- ffmpeg (optional) -- speed control for Google TTS

## Tests

```bash
python -m pytest tests/
```

UI tests need a working Tk display and skip automatically without one.

## License

MIT
