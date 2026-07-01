"""
config/settings.py
------------------
Application-wide configuration for the Offline AI Voice Clone app.

Contains:
  - AppConfig  : dataclass holding all runtime constants
  - UserPrefs  : dataclass for user-editable preferences (backed by app_config.json)
  - detect_device() : returns "cuda" or "cpu" based on PyTorch availability
  - load_prefs() / save_prefs() : read/write app_config.json

Design decision:
  Two separate classes keep read-only constants (AppConfig) separate from
  mutable user preferences (UserPrefs). This makes it easy to pass either
  through the app without accidentally mutating constants.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ── Root directories ──────────────────────────────────────────────────────────
ROOT_DIR: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = ROOT_DIR / "config"
MODELS_DIR: Path = ROOT_DIR / "models"
AUDIO_DIR: Path = ROOT_DIR / "audio"
OUTPUTS_DIR: Path = ROOT_DIR / "outputs"
ASSETS_DIR: Path = ROOT_DIR / "assets"
LOGS_DIR: Path = ROOT_DIR / "logs"

CONFIG_JSON: Path = CONFIG_DIR / "app_config.json"


# ── Supported languages (XTTS-v2 language codes) ─────────────────────────────
SUPPORTED_LANGUAGES: dict[str, str] = {
    "English":  "en",
    "Telugu":   "te",
    "Hindi":    "hi",
    "Spanish":  "es",
    "French":   "fr",
    "German":   "de",
    "Italian":  "it",
    "Portuguese": "pt",
    "Polish":   "pl",
    "Turkish":  "tr",
    "Russian":  "ru",
    "Dutch":    "nl",
    "Czech":    "cs",
    "Arabic":   "ar",
    "Chinese":  "zh-cn",
    "Japanese": "ja",
    "Korean":   "ko",
    "Hungarian": "hu",
}

# Language codes shown first in the GUI dropdown (user's primary languages)
PRIMARY_LANGUAGES: list[str] = ["English", "Telugu"]


@dataclass(frozen=True)
class AppConfig:
    """
    Read-only application constants. Instantiated once at startup.
    All paths are absolute and pre-resolved.
    """

    # Application identity
    app_name: str = "AI Voice Clone"
    app_version: str = "1.0.0"
    app_author: str = "Offline AI Studio"

    # XTTS-v2 model identifier (Hugging Face model hub ID)
    model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"

    # Audio processing
    sample_rate: int = 24_000          # XTTS-v2 native sample rate (24 kHz)
    bit_depth: int = 16                # WAV bit depth
    channels: int = 1                  # Mono output
    min_ref_duration_sec: float = 3.0  # Minimum reference audio length
    max_ref_duration_sec: float = 30.0 # Maximum reference audio length
    silence_threshold_db: float = -40.0  # dB below which is considered silence

    # Text processing
    max_chars_per_chunk: int = 250     # Max characters per TTS chunk
    sentence_delimiters: str = ".!?。！？"

    # UI sizing
    window_min_width: int = 1100
    window_min_height: int = 720

    # File management
    output_prefix: str = "voice_clone"
    output_ext: str = ".wav"

    # Directories (as strings for JSON serialisability)
    models_dir: str = str(MODELS_DIR)
    outputs_dir: str = str(OUTPUTS_DIR)
    audio_dir: str = str(AUDIO_DIR)
    assets_dir: str = str(ASSETS_DIR)


@dataclass
class UserPrefs:
    """
    Mutable user preferences — persisted to/from app_config.json.
    Defaults match app_config.json.
    """
    theme: str = "dark"
    last_voice_file: str = ""
    last_language: str = "en"
    last_output_dir: str = ""
    auto_play_after_generate: bool = True
    normalize_audio: bool = True
    trim_silence: bool = True
    max_history_items: int = 20


def detect_device() -> str:
    """
    Detect whether CUDA (GPU) is available.

    Returns:
        "cuda"  — if an NVIDIA GPU with CUDA support is found
        "cpu"   — fallback for CPU-only systems
    """
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            return "cuda"
        return "cpu"
    except ImportError:
        return "cpu"


def get_device_info() -> dict[str, str]:
    """
    Returns a dictionary with device info for display in the GUI status bar.

    Returns:
        dict with keys: device, gpu_name, cuda_version, pytorch_version
    """
    info: dict[str, str] = {
        "device": "cpu",
        "gpu_name": "N/A",
        "cuda_version": "N/A",
        "pytorch_version": "N/A",
    }
    try:
        import torch  # type: ignore
        info["pytorch_version"] = torch.__version__
        if torch.cuda.is_available():
            info["device"] = "cuda"
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["cuda_version"] = torch.version.cuda or "N/A"
    except ImportError:
        pass
    return info


def load_prefs() -> UserPrefs:
    """
    Load user preferences from app_config.json.
    If the file is missing or corrupted, returns default UserPrefs.

    Returns:
        UserPrefs instance populated from JSON file.
    """
    if not CONFIG_JSON.exists():
        return UserPrefs()

    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as fh:
            data: dict = json.load(fh)

        # Build UserPrefs from JSON data; ignore unknown keys
        known_fields = {f.name for f in UserPrefs.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return UserPrefs(**filtered)

    except (json.JSONDecodeError, TypeError, ValueError):
        # Return defaults silently on parse errors
        return UserPrefs()


def save_prefs(prefs: UserPrefs) -> None:
    """
    Persist user preferences to app_config.json.

    Args:
        prefs: The UserPrefs instance to serialise.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_JSON, "w", encoding="utf-8") as fh:
        json.dump(asdict(prefs), fh, indent=2)


def ensure_directories() -> None:
    """
    Create all required application directories if they don't exist.
    Called once at startup.
    """
    for directory in [MODELS_DIR, AUDIO_DIR, OUTPUTS_DIR, ASSETS_DIR, LOGS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


# ── Module-level singletons ───────────────────────────────────────────────────
APP_CONFIG: AppConfig = AppConfig()
