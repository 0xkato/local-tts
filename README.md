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
- **Pause and resume** -- stop mid-article, come back later, pick up right where you left off
- **Transport controls** -- prev, play/pause, stop, next -- like a media player
- **Progress tracking** -- see how far through the text you are as a percentage
- **Persistent position** -- close the app, reopen it, paste the same text, and it asks if you want to resume
- **Speed control** -- defaults to 1.5x, adjustable from 0.5x to 2.0x
- **Two engines** -- Google TTS (online, multiple languages) or Piper TTS (offline, private)
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

## Requirements

- Python 3.7+
- Audio output device

## License

MIT
