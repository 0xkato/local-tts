# Local TTS - Free Text-to-Speech App

A simple, free text-to-speech application with both online and offline options. No API keys or subscriptions required.

## Why Use This?

- **100% Free** - No API costs or usage limits
- **Privacy Option** - Use Piper TTS offline - your text never leaves your computer
- **Flexible** - Choose between online (Google TTS) or offline (Piper TTS) engines
- **Simple** - Clean UI, just type and click play

## Quick Start

1. **Clone the repo:**
```bash
git clone https://github.com/0xkato/local-tts.git
cd local-tts
```

2. **Set up with uv:**
```bash
uv venv
uv pip install -r requirements.txt
```

3. **Run the app:**
```bash
uv run python tts_unified.py
```

4. **Type your text and click PLAY!**

## Features

- **Google TTS (Online)** - Default engine with multiple languages
- **Piper TTS (Offline)** - Optional high-quality offline voice synthesis
- **Adjustable Speed** - Control how fast the text is spoken
- **Clean Interface** - Simple, easy-to-use design

## Optional: Enable Offline Mode with Piper TTS

For completely offline text-to-speech:

```bash
# Install Piper TTS
uv pip install piper-tts

# Download voice model (12MB) 
mkdir -p ~/.local/share/piper
wget -O ~/.local/share/piper/en_US-norman-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx
wget -O ~/.local/share/piper/en_US-norman-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json
```

Then select "Piper TTS" from the engine dropdown in the app.

## Alternative: Using pip

If you prefer traditional pip:

```bash
pip install -r requirements.txt
python3 tts_unified.py
```

## System Requirements

- Python 3.7+
- ~50MB disk space (includes voice model)
- Audio output device

## Troubleshooting

**"No TTS engines available"**
- Make sure you've installed dependencies: `uv pip install -r requirements.txt`

**UI looks broken on macOS**
- Try running with system Python: `/usr/local/bin/python3 tts_unified.py`

**No sound output**
- Check your system audio settings
- Make sure pygame is installed: `uv pip install pygame`

## License

MIT - Use it however you want!

## Credits

- Powered by [Piper TTS](https://github.com/rhasspy/piper) for offline synthesis
- Optional [gTTS](https://github.com/pndurette/gTTS) for online backup
