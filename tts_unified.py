#!/usr/bin/env python3
"""
Unified Text-to-Speech Application
Supports Google TTS and Piper TTS engines
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import os
import sys
import tempfile
import subprocess
from typing import Optional, Callable
from abc import ABC, abstractmethod

# Required imports
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class TTSEngine(ABC):
    """Abstract base class for TTS engines"""
    
    @abstractmethod
    def speak(self, text: str, speed: float, callback: Optional[Callable] = None) -> None:
        """Generate and play speech from text"""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop current speech playback"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get the display name of this engine"""
        pass


class GoogleTTSEngine(TTSEngine):
    """Google TTS using gTTS"""
    
    def __init__(self):
        self.is_playing = False
        self.current_audio_file = None
        if PYGAME_AVAILABLE:
            pygame.mixer.init()
    
    def speak(self, text: str, speed: float, callback: Optional[Callable] = None, language: str = "en") -> None:
        if not GTTS_AVAILABLE or not PYGAME_AVAILABLE:
            raise Exception("gTTS or pygame not available")
        
        self.is_playing = True
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
                self.current_audio_file = tmp_file.name
            
            slow = speed < 1.0
            tts = gTTS(text=text, lang=language, slow=slow)
            tts.save(self.current_audio_file)
            
            pygame.mixer.music.load(self.current_audio_file)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy() and self.is_playing:
                pygame.time.Clock().tick(10)
        finally:
            self.is_playing = False
            if self.current_audio_file and os.path.exists(self.current_audio_file):
                try:
                    os.unlink(self.current_audio_file)
                except:
                    pass
            if callback:
                callback()
    
    def stop(self) -> None:
        self.is_playing = False
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
    
    def is_available(self) -> bool:
        return GTTS_AVAILABLE and PYGAME_AVAILABLE
    
    def get_name(self) -> str:
        return "Google TTS"


class PiperTTSEngine(TTSEngine):
    """Piper TTS for offline high-quality speech"""
    
    def __init__(self):
        self.is_playing = False
        self.current_audio_file = None
        self.piper_dir = os.path.expanduser("~/.local/share/piper")
        self.voice_model = os.path.join(self.piper_dir, "en_US-norman-medium.onnx")
        self.voice_config = os.path.join(self.piper_dir, "en_US-norman-medium.onnx.json")
        if PYGAME_AVAILABLE:
            pygame.mixer.init()
    
    def speak(self, text: str, speed: float, callback: Optional[Callable] = None) -> None:
        if not self.is_available():
            raise Exception("Piper TTS not available")
        
        self.is_playing = True
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                self.current_audio_file = tmp_file.name
            
            length_scale = 1.0 / speed
            
            process = subprocess.Popen(
                ["piper", "--model", self.voice_model, "--output_file", self.current_audio_file, "--length_scale", str(length_scale)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=text)
            
            if process.returncode != 0:
                raise Exception(f"Piper failed: {stderr}")
            
            pygame.mixer.music.load(self.current_audio_file)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy() and self.is_playing:
                pygame.time.Clock().tick(10)
        finally:
            self.is_playing = False
            if self.current_audio_file and os.path.exists(self.current_audio_file):
                try:
                    os.unlink(self.current_audio_file)
                except:
                    pass
            if callback:
                callback()
    
    def stop(self) -> None:
        self.is_playing = False
        if PYGAME_AVAILABLE:
            pygame.mixer.music.stop()
    
    def is_available(self) -> bool:
        if not PYGAME_AVAILABLE:
            return False
        
        # Check if piper command is available
        if not self.check_piper_installed():
            return False
        
        return os.path.exists(self.voice_model)
    
    def get_name(self) -> str:
        return "Piper TTS"
    
    def check_piper_installed(self) -> bool:
        """Check if Piper is installed"""
        try:
            # Try to run piper with --help to see if it's installed
            result = subprocess.run(["piper", "--help"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
    
    def download_model(self, status_callback: Callable[[str], None]) -> bool:
        """Download the Piper voice model"""
        try:
            import urllib.request
            
            os.makedirs(self.piper_dir, exist_ok=True)
            
            model_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx"
            config_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json"
            
            status_callback("Downloading model file (12MB)...")
            urllib.request.urlretrieve(model_url, self.voice_model)
            
            status_callback("Downloading config file...")
            urllib.request.urlretrieve(config_url, self.voice_config)
            
            status_callback("Voice model downloaded successfully!")
            return True
        except Exception as e:
            status_callback(f"Download failed: {str(e)}")
            return False


class UnifiedTTSApp:
    """Main application window"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Text to Speech")
        
        # Start with appropriate window size for each platform
        if sys.platform == "darwin":  # macOS
            # On macOS, set a more reasonable window size
            self.root.geometry("900x700")
            # Center the window
            self.root.update_idletasks()
            width = 900
            height = 700
            x = (self.root.winfo_screenwidth() // 2) - (width // 2)
            y = (self.root.winfo_screenheight() // 2) - (height // 2)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            # For Linux and Windows, try to maximize
            try:
                self.root.attributes('-zoomed', True)
            except:
                try:
                    self.root.wm_state('normal')
                    self.root.geometry("{0}x{1}+0+0".format(
                        self.root.winfo_screenwidth(), 
                        self.root.winfo_screenheight()
                    ))
                except:
                    self.root.geometry("1000x800")
        
        if sys.platform == "darwin":
            self.root.minsize(800, 600)
        else:
            self.root.minsize(900, 700)
        
        # Initialize engines
        self.engines = {
            'google': GoogleTTSEngine(),
            'piper': PiperTTSEngine()
        }
        
        self.current_engine = None
        self.is_speaking = False
        self.speaking_thread = None
        
        self.create_ui()
        self.check_engines_and_initialize()
    
    def create_ui(self):
        """Create the user interface"""
        
        # Main container with better padding
        if sys.platform == "darwin":  # Reduce padding on macOS
            main_frame = tk.Frame(self.root, padx=20, pady=15)
        else:
            main_frame = tk.Frame(self.root, padx=40, pady=30)
        main_frame.pack(expand=True, fill='both')
        
        # Title
        title_frame = tk.Frame(main_frame)
        title_frame.pack(pady=(0, 20))
        
        title_label = tk.Label(title_frame, text="Text to Speech", font=("Arial", 28, "bold"))
        title_label.pack()
        
        subtitle_label = tk.Label(title_frame, text="Powered by Google TTS and Piper TTS", font=("Arial", 13), fg="gray")
        subtitle_label.pack()
        
        # Engine selection
        engine_frame = tk.Frame(main_frame)
        engine_frame.pack(pady=15, fill='x')
        
        engine_label = tk.Label(engine_frame, text="Select Engine:", font=("Arial", 14))
        engine_label.pack(side=tk.LEFT, padx=(0, 15))
        
        self.engine_var = tk.StringVar()
        self.engine_combo = ttk.Combobox(
            engine_frame,
            textvariable=self.engine_var,
            state="readonly",
            width=35,
            font=("Arial", 12)
        )
        self.engine_combo.pack(side=tk.LEFT, padx=5)
        self.engine_combo.bind('<<ComboboxSelected>>', self.on_engine_change)
        
        self.engine_status = tk.Label(engine_frame, text="", font=("Arial", 11))
        self.engine_status.pack(side=tk.LEFT, padx=15)
        
        # Download button for Piper (hidden by default)
        if sys.platform == "darwin":  # macOS
            self.download_button = tk.Button(
                engine_frame,
                text="Download Voice Model",
                command=self.download_piper_model,
                font=("Arial", 11),
                highlightbackground="#2196F3"
            )
        else:
            self.download_button = tk.Button(
                engine_frame,
                text="Download Voice Model",
                command=self.download_piper_model,
                bg="#2196F3",
                fg="white",
                font=("Arial", 11),
                cursor="hand2"
            )
        
        # Text area
        text_label = tk.Label(main_frame, text="Enter text to speak:", font=("Arial", 14))
        text_label.pack(pady=(15, 5), anchor='w')
        
        text_frame = tk.Frame(main_frame)
        text_frame.pack(padx=5, pady=5, expand=True, fill='both')
        
        self.text_area = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=("Arial", 12),
            relief=tk.FLAT,
            borderwidth=2,
            highlightthickness=1
        )
        self.text_area.pack(expand=True, fill='both')
        
        # Controls frame
        controls_frame = tk.Frame(main_frame)
        controls_frame.pack(pady=20)
        
        # Language selection (for Google TTS)
        self.lang_frame = tk.Frame(controls_frame)
        
        lang_label = tk.Label(self.lang_frame, text="Language:", font=("Arial", 12))
        lang_label.pack(side=tk.LEFT, padx=10)
        
        self.lang_var = tk.StringVar(value="en")
        languages = [
            ("English", "en"),
            ("Spanish", "es"),
            ("French", "fr"),
            ("German", "de"),
            ("Italian", "it"),
            ("Portuguese", "pt"),
            ("Russian", "ru"),
            ("Japanese", "ja"),
            ("Korean", "ko"),
            ("Chinese", "zh")
        ]
        
        self.lang_combo = ttk.Combobox(
            self.lang_frame,
            textvariable=self.lang_var,
            values=[f"{name} ({code})" for name, code in languages],
            state="readonly",
            width=25,
            font=("Arial", 11)
        )
        self.lang_combo.set("English (en)")
        self.lang_combo.pack(side=tk.LEFT, padx=10)
        
        # Speed control
        speed_frame = tk.Frame(controls_frame)
        speed_frame.pack(pady=15)
        
        speed_label = tk.Label(speed_frame, text="Speed:", font=("Arial", 12))
        speed_label.pack(side=tk.LEFT, padx=10)
        
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_slider = tk.Scale(
            speed_frame,
            from_=0.5,
            to=2.0,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=self.speed_var,
            length=300,
            command=self.update_speed_label,
            showvalue=False
        )
        self.speed_slider.pack(side=tk.LEFT, padx=10)
        
        self.speed_label = tk.Label(speed_frame, text="1.0x", font=("Arial", 12))
        self.speed_label.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = tk.Frame(controls_frame)
        button_frame.pack(pady=20)
        
        if sys.platform == "darwin":  # macOS
            self.play_button = tk.Button(
                button_frame,
                text="▶ PLAY",
                command=self.toggle_play,
                font=("Arial", 16, "bold"),
                width=20,
                height=2,
                highlightbackground="#4CAF50"
            )
        else:
            self.play_button = tk.Button(
                button_frame,
                text="▶ PLAY",
                command=self.toggle_play,
                bg="#4CAF50",
                fg="white",
                font=("Arial", 16, "bold"),
                width=20,
                height=2,
                cursor="hand2"
            )
        self.play_button.pack()
        
        # Status
        self.status_label = tk.Label(controls_frame, text="Checking engines...", fg="gray", font=("Arial", 11))
        self.status_label.pack(pady=10)
    
    def check_engines_and_initialize(self):
        """Check available engines and initialize"""
        available_engines = []
        engine_items = []
        
        # Check Piper TTS FIRST (so it appears first in dropdown)
        piper_engine = self.engines['piper']
        if piper_engine.is_available():
            available_engines.append('piper')
            engine_items.append("Piper TTS (Offline)")
        elif piper_engine.check_piper_installed():
            engine_items.append("Piper TTS (Model Not Downloaded)")
        else:
            engine_items.append("Piper TTS (Not Installed - pip install piper-tts)")
        
        # Check Google TTS SECOND
        if self.engines['google'].is_available():
            available_engines.append('google')
            engine_items.append("Google TTS (Online)")
        else:
            engine_items.append("Google TTS (Not Available - Install gtts & pygame)")
        
        self.engine_combo['values'] = engine_items
        
        # Always select first item in list (Piper will be first if available)
        if available_engines:
            # Select the first available engine in the dropdown
            self.engine_combo.current(0)
            
            # Set the current engine based on what's first
            first_item = engine_items[0]
            if "Piper TTS (Offline)" in first_item:
                self.current_engine = self.engines['piper']
            elif "Google TTS (Online)" in first_item:
                self.current_engine = self.engines['google']
            else:
                # Neither is fully available, but set based on what's selected
                for engine_key in available_engines:
                    if engine_key == 'piper' and "Piper" in first_item:
                        self.current_engine = self.engines['piper']
                        break
                    elif engine_key == 'google' and "Google" in first_item:
                        self.current_engine = self.engines['google']
                        break
            
            self.on_engine_change()
            self.status_label.config(text="Ready", fg="green")
        else:
            self.engine_combo.current(0)
            self.status_label.config(text="No TTS engines available. Please install dependencies.", fg="red")
            self.play_button.config(state="disabled")
    
    def on_engine_change(self, event=None):
        """Handle engine selection change"""
        selection = self.engine_combo.get()
        
        # Hide download button by default
        self.download_button.pack_forget()
        
        if "Google TTS (Online)" in selection:
            self.current_engine = self.engines['google']
            self.lang_frame.pack(pady=10)
            self.play_button.config(state="normal")
            self.status_label.config(text="Ready - Google TTS", fg="green")
            
        elif "Piper TTS (Offline)" in selection:
            self.current_engine = self.engines['piper']
            self.lang_frame.pack_forget()
            self.play_button.config(state="normal")
            self.status_label.config(text="Ready - Piper TTS", fg="green")
            
        elif "Model Not Downloaded" in selection:
            self.current_engine = None
            self.lang_frame.pack_forget()
            self.play_button.config(state="disabled")
            self.download_button.pack(side=tk.LEFT, padx=20)
            self.status_label.config(text="Download voice model to use Piper TTS", fg="orange")
            
        else:
            # Not available
            self.current_engine = None
            self.play_button.config(state="disabled")
            if "Google" in selection:
                self.status_label.config(text="Install: pip install gtts pygame", fg="orange")
            else:
                self.status_label.config(text="Install: pip install piper-tts", fg="orange")
    
    def download_piper_model(self):
        """Download Piper voice model"""
        self.download_button.config(state="disabled", text="Downloading...")
        self.status_label.config(text="Downloading voice model...", fg="blue")
        
        def download_thread():
            def update_status(msg):
                self.root.after(0, lambda: self.status_label.config(text=msg, fg="blue"))
            
            success = self.engines['piper'].download_model(update_status)
            
            if success:
                self.root.after(0, self.refresh_engines_after_download)
            else:
                self.root.after(0, lambda: self.download_button.config(state="normal", text="Download Voice Model"))
        
        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()
    
    def refresh_engines_after_download(self):
        """Refresh engine list after downloading Piper model"""
        self.download_button.pack_forget()
        self.check_engines_and_initialize()
        
        # Select Piper TTS if now available
        engine_items = self.engine_combo['values']
        for i, item in enumerate(engine_items):
            if "Piper TTS (Offline)" in item:
                self.engine_combo.current(i)
                self.on_engine_change()
                break
    
    def update_speed_label(self, value):
        """Update the speed label"""
        speed = float(value)
        self.speed_label.config(text=f"{speed:.1f}x")
    
    def toggle_play(self):
        """Toggle between play and stop"""
        if self.is_speaking:
            self.stop_speaking()
        else:
            text = self.text_area.get("1.0", tk.END).strip()
            if text:
                self.play_text(text)
            else:
                messagebox.showwarning("No Text", "Please enter some text to speak")
    
    def play_text(self, text):
        """Play the text using the selected engine"""
        if not self.current_engine or not self.current_engine.is_available():
            messagebox.showerror("Error", "Selected TTS engine is not available")
            return
        
        self.is_speaking = True
        if sys.platform == "darwin":
            self.play_button.config(text="⏹ STOP")
        else:
            self.play_button.config(text="⏹ STOP", bg="#f44336")
        self.status_label.config(text="Speaking...", fg="blue")
        
        # Get language if using Google TTS
        kwargs = {'speed': self.speed_var.get(), 'callback': self.reset_ui}
        if isinstance(self.current_engine, GoogleTTSEngine):
            lang_code = self.lang_combo.get().split("(")[1].split(")")[0]
            kwargs['language'] = lang_code
        
        # Start speaking in a separate thread
        self.speaking_thread = threading.Thread(
            target=lambda: self.speak_with_error_handling(text, **kwargs)
        )
        self.speaking_thread.daemon = True
        self.speaking_thread.start()
    
    def speak_with_error_handling(self, text, **kwargs):
        """Speak with error handling"""
        try:
            self.current_engine.speak(text, **kwargs)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to speak: {str(e)}"))
            self.root.after(0, self.reset_ui)
    
    def stop_speaking(self):
        """Stop the current speech"""
        self.is_speaking = False
        if self.current_engine:
            self.current_engine.stop()
        self.reset_ui()
    
    def reset_ui(self):
        """Reset UI to ready state"""
        self.is_speaking = False
        if sys.platform == "darwin":
            self.play_button.config(text="▶ PLAY")
        else:
            self.play_button.config(text="▶ PLAY", bg="#4CAF50")
        
        if self.current_engine:
            engine_name = self.current_engine.get_name()
            self.status_label.config(text=f"Ready - {engine_name}", fg="green")
        else:
            self.status_label.config(text="Ready", fg="green")


def check_dependencies():
    """Check and display available dependencies"""
    print("Text-to-Speech Application")
    print("=" * 40)
    print("Checking dependencies...")
    print()
    
    deps = {
        'gtts': GTTS_AVAILABLE,
        'pygame': PYGAME_AVAILABLE
    }
    
    available = []
    missing = []
    
    for dep, status in deps.items():
        if status:
            available.append(dep)
            print(f"✓ {dep} - Available")
        else:
            missing.append(dep)
            print(f"✗ {dep} - Not installed")
    
    # Check for Piper (cross-platform)
    piper_available = False
    try:
        result = subprocess.run(["piper", "--help"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            piper_available = True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        piper_available = False
    
    if piper_available:
        print("✓ piper - Available")
        available.append('piper')
    else:
        print("✗ piper - Not installed")
        missing.append('piper')
    
    print()
    
    if missing:
        print("To install missing dependencies:")
        print("-" * 40)
        if 'gtts' in missing or 'pygame' in missing:
            python_deps = [d for d in missing if d in ['gtts', 'pygame']]
            print(f"pip install {' '.join(python_deps)}")
        if 'piper' in missing:
            print("pip install piper-tts")
        print()
    
    if not PYGAME_AVAILABLE:
        print("WARNING: pygame is required for audio playback!")
        print("Install with: pip install pygame")
        return False
    
    return True


def main():
    """Main entry point"""
    # Check dependencies with --check flag
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        check_dependencies()
        return
    
    # Create and run the application
    root = tk.Tk()
    app = UnifiedTTSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()