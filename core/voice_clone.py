"""
core/voice_clone.py
-------------------
High-level voice cloning orchestration layer.

VoiceCloner acts as the bridge between the GUI and the low-level TTSEngine.
It:
  - Validates and preprocesses the reference (speaker) audio
  - Saves a clean preprocessed copy for XTTS-v2 to use as the speaker WAV
  - Calls TTSEngine.generate() with the correct parameters
  - Maintains a history of generated audio files
  - Provides reference audio information for display in the GUI

Why a separate class from TTSEngine?
  TTSEngine deals with the raw model API and audio chunks.
  VoiceCloner deals with user-facing concerns: file validation,
  reference audio preprocessing, history tracking, and error messages
  that are appropriate for display in the GUI.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import torch

from core.audio_utils import (
    get_audio_info,
    preprocess_reference_audio,
    save_wav,
    AudioInfo,
)
from core.helpers import (
    ensure_dir,
    format_duration,
    human_file_size,
    timestamp_filename,
    validate_audio_file,
)
from core.tts_engine import TTSEngine
from config.settings import APP_CONFIG, AUDIO_DIR, OUTPUTS_DIR
from utils.logger import setup_logger

log = setup_logger(__name__)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ReferenceAudioInfo:
    """Metadata about the currently loaded reference (speaker) audio."""
    original_path: Path
    processed_path: Path
    duration_sec: float
    sample_rate: int
    channels: int
    file_size_bytes: int
    bit_depth: Optional[int]

    @property
    def duration_formatted(self) -> str:
        return format_duration(self.duration_sec)

    @property
    def file_size_formatted(self) -> str:
        return human_file_size(self.file_size_bytes)

    @property
    def quality_rating(self) -> str:
        """
        Simple quality hint based on duration and sample rate.
        XTTS-v2 performs best with 6–15 seconds of clean 22 kHz+ audio.
        """
        if self.duration_sec < 3:
            return "⚠️ Too short (minimum 3s)"
        if self.duration_sec < 6:
            return "⚠️ Short (6s+ recommended)"
        if self.duration_sec > 30:
            return "⚠️ Long (trim to 30s for best results)"
        if self.sample_rate < 16_000:
            return "⚠️ Low sample rate"
        return "✅ Good"


@dataclass
class GenerationRecord:
    """A single entry in the voice generation history."""
    output_path: Path
    text_preview: str   # First 60 characters of the input text
    language: str
    duration_sec: float
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def filename(self) -> str:
        return self.output_path.name

    @property
    def timestamp_display(self) -> str:
        return self.created_at.strftime("%H:%M:%S")


# ── VoiceCloner ───────────────────────────────────────────────────────────────

class VoiceCloner:
    """
    High-level orchestrator for voice cloning operations.

    Typical usage:
        cloner = VoiceCloner(engine=TTSEngine(device="cuda"))
        cloner.set_reference_audio("audio/my_voice.wav")
        output = cloner.generate_speech("Hello, world!", language="en")
    """

    def __init__(
        self,
        engine: TTSEngine,
        normalize: bool = True,
        trim_silence: bool = True,
        max_history: int = 20,
    ) -> None:
        """
        Initialise the VoiceCloner.

        Args:
            engine:        Loaded TTSEngine instance.
            normalize:     Apply audio normalisation to reference audio.
            trim_silence:  Trim silence from reference audio.
            max_history:   Maximum number of generation records to keep.
        """
        self._engine = engine
        self._normalize = normalize
        self._trim_silence = trim_silence
        self._max_history = max_history

        self._ref_info: Optional[ReferenceAudioInfo] = None
        self._processed_ref_path: Optional[Path] = None
        self._history: list[GenerationRecord] = []

        # Ensure required directories exist
        ensure_dir(AUDIO_DIR)
        ensure_dir(OUTPUTS_DIR)

        log.info(
            "VoiceCloner initialised (normalize=%s, trim=%s)",
            normalize, trim_silence,
        )

    # ── Reference audio ───────────────────────────────────────────────────

    @property
    def has_reference(self) -> bool:
        """True if a reference audio file has been loaded and processed."""
        return (
            self._ref_info is not None
            and self._processed_ref_path is not None
            and self._processed_ref_path.exists()
        )

    @property
    def reference_info(self) -> Optional[ReferenceAudioInfo]:
        """Metadata about the currently loaded reference audio, or None."""
        return self._ref_info

    def set_reference_audio(
        self,
        path: str | Path,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> ReferenceAudioInfo:
        """
        Validate, preprocess, and register a reference audio file.

        The reference audio is:
        1. Validated (exists, correct format, minimum duration)
        2. Preprocessed (mono, 24 kHz, normalised, silence-trimmed)
        3. Saved to audio/reference_voice.wav for XTTS to reference

        Args:
            path:              Path to the user's voice recording.
            progress_callback: Optional callable(percent, message) for UI.

        Returns:
            ReferenceAudioInfo with metadata about the processed audio.

        Raises:
            ValueError:  If the file is invalid or too short.
            RuntimeError: If preprocessing fails.
        """
        p = Path(path).resolve()

        # ── Step 1: File validation ────────────────────────────────────────
        if progress_callback:
            progress_callback(10, "Validating audio file …")

        is_valid, error_msg = validate_audio_file(p)
        if not is_valid:
            raise ValueError(error_msg)

        # ── Step 2: Check duration before loading ─────────────────────────
        if progress_callback:
            progress_callback(20, "Reading audio metadata …")

        raw_info: AudioInfo = get_audio_info(p)

        if raw_info.duration_sec < APP_CONFIG.min_ref_duration_sec:
            raise ValueError(
                f"Reference audio is too short: {raw_info.duration_sec:.1f}s "
                f"(minimum: {APP_CONFIG.min_ref_duration_sec}s). "
                "Please provide a longer recording."
            )

        log.info(
            "Reference audio accepted: %s (%.2fs, %d Hz, %d ch)",
            p.name, raw_info.duration_sec, raw_info.sample_rate, raw_info.channels,
        )

        # ── Step 3: Preprocess ────────────────────────────────────────────
        if progress_callback:
            progress_callback(40, "Preprocessing audio (resample + normalise) …")

        processed_waveform, processed_sr, original_info = preprocess_reference_audio(
            path=p,
            normalize=self._normalize,
            trim=self._trim_silence,
        )

        # ── Step 4: Save processed reference ─────────────────────────────
        if progress_callback:
            progress_callback(80, "Saving preprocessed reference audio …")

        ref_save_path = AUDIO_DIR / "reference_voice.wav"
        save_wav(
            waveform=processed_waveform,
            sample_rate=processed_sr,
            output_path=ref_save_path,
            bit_depth=APP_CONFIG.bit_depth,
        )
        self._processed_ref_path = ref_save_path

        # ── Step 5: Build info object ─────────────────────────────────────
        processed_duration = processed_waveform.shape[-1] / processed_sr
        self._ref_info = ReferenceAudioInfo(
            original_path=p,
            processed_path=ref_save_path,
            duration_sec=processed_duration,
            sample_rate=processed_sr,
            channels=1,
            file_size_bytes=p.stat().st_size,
            bit_depth=raw_info.bit_depth,
        )

        if progress_callback:
            progress_callback(100, "Reference audio ready!")

        log.info(
            "Reference audio set: %s → %s (processed: %.2fs @ %d Hz)",
            p.name, ref_save_path.name, processed_duration, processed_sr,
        )
        return self._ref_info

    # ── Speech generation ─────────────────────────────────────────────────

    def generate_speech(
        self,
        text: str,
        language: str = "en",
        output_path: Optional[str | Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        temperature: float = 0.1,
        top_p: float = 0.85,
        repetition_penalty: float = 10.0,
        speed: float = 1.0,
    ) -> Path:
        """
        Generate speech in the cloned voice.

        Args:
            text:              Text to synthesise (may be multi-paragraph).
            language:          XTTS-v2 language code (e.g. "en", "te").
            output_path:       Optional explicit output path. If None, a
                               timestamped file in outputs/ is created.
            progress_callback: Optional callable(percent, message).

        Returns:
            Path to the generated WAV file.

        Raises:
            RuntimeError: If no reference audio is loaded.
            ValueError:   If text is empty.
            RuntimeError: If TTS synthesis fails.
        """
        if not self.has_reference:
            raise RuntimeError(
                "No reference audio loaded. "
                "Please select a voice file first."
            )

        if not self._engine.is_loaded:
            raise RuntimeError(
                "TTS model is not loaded. "
                "Please wait for the model to finish loading."
            )

        text = text.strip()
        if not text:
            raise ValueError("Please enter some text to generate speech.")

        log.info("Starting generation: lang=%s, text_len=%d", language, len(text))

        output = self._engine.generate(
            text=text,
            speaker_wav=str(self._processed_ref_path),
            language=language,
            output_path=output_path,
            progress_callback=progress_callback,
            normalize=self._normalize,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            speed=speed,
        )

        # Record in history
        self._add_to_history(output, text, language)

        return output

    # ── History ───────────────────────────────────────────────────────────

    @property
    def history(self) -> list[GenerationRecord]:
        """List of generated audio records, newest first."""
        return list(reversed(self._history))

    def clear_history(self) -> None:
        """Clear the in-memory generation history (does not delete files)."""
        self._history.clear()
        log.debug("Generation history cleared.")

    def _add_to_history(
        self,
        output_path: Path,
        text: str,
        language: str,
    ) -> None:
        """Add a GenerationRecord to the history, evicting old entries if needed."""
        try:
            import soundfile as sf  # type: ignore
            with sf.SoundFile(str(output_path)) as f:
                duration = f.frames / f.samplerate
        except Exception:
            duration = 0.0

        record = GenerationRecord(
            output_path=output_path,
            text_preview=text[:60].replace("\n", " "),
            language=language,
            duration_sec=duration,
        )
        self._history.append(record)

        # Evict oldest entries
        while len(self._history) > self._max_history:
            self._history.pop(0)

        log.debug("History: %d record(s)", len(self._history))

    def get_engine_info(self) -> dict:
        """Return engine metadata for display in the GUI status bar."""
        return self._engine.get_model_info()
