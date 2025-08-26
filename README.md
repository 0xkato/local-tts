# Local TTS - Free Text-to-Speech App

A simple, free text-to-speech application that works completely offline. No API keys, no subscriptions, no internet required (after initial setup).

## Why Use This?

- **100% Free** - No API costs or usage limits
- **Privacy First** - Your text never leaves your computer
- **Works Offline** - Once set up, no internet needed
- **High Quality** - Natural sounding voices using Piper TTS
- **Simple** - Clean UI, just type and click play

## Quick Start

### macOS/Linux/Windows

1. **Clone the repo:**
```bash
git clone https://github.com/yourusername/local-tts.git
cd local-tts
```

2. **Run the setup script:**
```bash
bash setup_and_run.sh
```

3. **Type your text and click PLAY!**

That's it! The app will install everything it needs and start automatically.

## Features

- **Piper TTS (Offline)** - High-quality offline voice synthesis
- **Google TTS (Online)** - Optional backup with multiple languages
- **Adjustable Speed** - Control how fast the text is spoken
- **Clean Interface** - Simple, easy-to-use design

## Manual Installation

If you prefer to install manually:

```bash
# Install Python dependencies
pip install gtts pygame piper-tts

# Download voice model (12MB)
mkdir -p ~/.local/share/piper
wget -O ~/.local/share/piper/en_US-norman-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx
wget -O ~/.local/share/piper/en_US-norman-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json

# Run the app
python3 tts_unified.py
```

## Using with uv (Python Package Manager)

If you use `uv` for Python package management:

```bash
uv venv
uv pip install gtts pygame piper-tts
uv run python tts_unified.py
```

## System Requirements

- Python 3.7+
- ~50MB disk space (includes voice model)
- Audio output device

## Troubleshooting

**"No TTS engines available"**
- Run `bash setup_and_run.sh` to install all dependencies

**UI looks broken on macOS**
- Use the provided `run_tts.command` file or run with: `/usr/local/bin/python3 tts_unified.py`

**No sound output**
- Check your system audio settings
- Make sure pygame is installed: `pip install pygame`

## License

MIT - Use it however you want!

## Credits

- Powered by [Piper TTS](https://github.com/rhasspy/piper) for offline synthesis
- Optional [gTTS](https://github.com/pndurette/gTTS) for online backup