# AI Voice Clone

> Clone your voice. Generate speech. Fully offline.

A desktop app that clones your voice from a short recording and synthesizes speech in your own voice — in English, Telugu, and 16 more languages. No cloud. No API keys. No subscription.

---

## Quick Start

**Option 1 — One click**
```
Double-click setup.bat
```

**Option 2 — Manual**
```powershell
python -m venv venv
venv\Scripts\activate

# GPU (recommended)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118

# CPU only
pip install torch torchaudio

pip install TTS>=0.22.0
pip install PySide6 sounddevice pygame numpy librosa soundfile scipy colorlog colorama

python main.py
```

> **First launch:** The XTTS-v2 model (~1.8 GB) downloads automatically. Internet required only once.

---

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 64-bit | Windows 11 |
| Python | 3.10 | 3.11 |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB free | 10 GB free |
| GPU | *(CPU fallback)* | NVIDIA 6 GB+ VRAM |

---

## How to Use

1. **Record your voice** — 6–30 seconds of clean speech, saved as `.wav`
2. **Drop the file** onto the voice zone (or click to browse)
3. **Pick a language** from the dropdown
4. **Type your text** in the input box
5. **Press `Ctrl+G`** to generate
6. **Play or save** the output

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+G` | Generate speech |
| `Space` | Play last audio |
| `Ctrl+S` | Save audio |
| `Ctrl+O` | Open voice file |
| `Ctrl+L` | Clear text |
| `Escape` | Stop playback |

---

## Performance

| Hardware | ~10 words | ~50 words |
|---|---|---|
| RTX 4090 | 1.5s | 4s |
| RTX 3080 | 2.5s | 7s |
| RTX 3060 | 3.5s | 10s |
| GTX 1080 Ti | 6s | 18s |
| CPU (i7) | 90s | ~5 min |

---

## Supported Languages

English · Telugu · Hindi · Spanish · French · German · Italian · Portuguese · Polish · Russian · Chinese · Japanese · Korean · and more

---

## Project Structure

```
├── main.py              # Entry point
├── setup.bat            # One-click installer
├── requirements.txt     # Dependencies
├── config/              # Settings & user config
├── core/                # TTS engine, voice cloning, audio utils
├── ui/                  # GUI, styles, custom widgets
├── utils/               # Logging
├── models/              # XTTS-v2 weights (auto-downloaded)
├── outputs/             # Generated audio
└── logs/                # App logs
```

---

## Troubleshooting

**CUDA not detected** → Install [CUDA Toolkit 11.8](https://developer.nvidia.com/cuda-11-8-0-download-archive), then reinstall PyTorch with the `cu118` flag.

**Model download fails** → Ensure internet is available on first launch only.

**Poor voice quality** → Use 10–20 seconds of clean, quiet reference audio at 24 kHz.

**Out of GPU memory** → The app automatically falls back to CPU.

---

## Credits

- [Coqui TTS](https://github.com/coqui-ai/TTS) — XTTS-v2 engine
- [PyTorch](https://pytorch.org/) — Deep learning backend
- [PySide6](https://www.qt.io/) — GUI framework

---

*Built for offline AI productivity.*
