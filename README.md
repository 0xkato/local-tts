# Text-to-Speech Application

A clean, unified Text-to-Speech application supporting Google TTS (online) and Piper TTS (offline) engines.

## Features

- **Two TTS Engines**:
  - **Google TTS** - High-quality online TTS with 10+ languages
  - **Piper TTS** - Fast, neural network-based offline TTS
  
- **User Interface**:
  - Starts maximized for better visibility
  - Clean dropdown for engine selection
  - Adjustable speech speed (0.5x - 2.0x)
  - Multi-language support (Google TTS)
  - Real-time status updates
  - Play/Stop functionality

## Quick Start

```bash
# Clone and enter directory
git clone <your-repo-url>
cd function

# Install dependencies
pip install -r requirements.txt

# Run the application
python tts_unified.py
```

## Installation

### Basic Setup (Google TTS only)
```bash
pip install gtts pygame
```

### Full Setup (with Piper TTS)
```bash
# Install Google TTS and pygame
pip install gtts pygame

# Install Piper TTS
pip install piper-tts
```

The app will automatically download Piper voice models on first use.

### Check Available Engines
```bash
python tts_unified.py --check
```

## Usage

1. **Launch**: Run `python tts_unified.py`
2. **Select Engine**: Choose between Google TTS (online) or Piper TTS (offline)
3. **Enter Text**: Type or paste your text
4. **Configure**:
   - Adjust speed slider (0.5x - 2.0x)
   - Select language (Google TTS only)
5. **Play**: Click PLAY button to hear the text
6. **Stop**: Click STOP to interrupt

## Engine Comparison

| Feature | Google TTS | Piper TTS |
|---------|------------|-----------|
| Internet Required | Yes | No |
| Voice Quality | Excellent | Very Good |
| Speed | Moderate | Fast |
| Languages | 10+ | English |
| Size | Small | ~12MB model |

## Troubleshooting

### No engines available
```bash
# Install at least one engine
pip install gtts pygame
```

### Piper TTS not working
```bash
# Install Piper
pip install piper-tts

# The app will auto-download voice models
# Or manually download if needed
```

### Audio issues on Linux
```bash
# Install audio libraries
sudo apt-get install python3-pyaudio
sudo apt-get install libsdl2-mixer-2.0-0
```

## Requirements

- Python 3.7+
- tkinter (included with Python)
- pygame for audio playback
- Internet connection (Google TTS only)

## Project Structure

```
function/
├── tts_unified.py    # Main application
├── requirements.txt  # Dependencies
└── README.md        # Documentation
```

## License

Open source - feel free to use and modify!