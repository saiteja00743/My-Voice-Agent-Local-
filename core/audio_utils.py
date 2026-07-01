"""
core/audio_utils.py
-------------------
Audio processing utilities for the Offline AI Voice Clone application.

Handles all low-level audio I/O and DSP (Digital Signal Processing):
  - Loading audio files (WAV, MP3, FLAC, etc.)
  - Validating reference audio quality
  - Resampling to XTTS-v2's native 24 kHz
  - Mono downmixing
  - Peak normalisation to -3 dBFS
  - Silence trimming (VAD-style)
  - Saving 16-bit WAV files
  - Concatenating multiple generated audio chunks

Design decisions:
  - Uses torchaudio for loading (best PyTorch integration)
  - Uses soundfile for WAV writing (more reliable than torchaudio.save on Windows)
  - All waveforms are represented as torch.Tensor (float32, shape [1, samples])
  - Returns numpy arrays only at the point of writing / playback

Dependencies: torch, torchaudio, soundfile, numpy, librosa
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch

from utils.logger import setup_logger

log = setup_logger(__name__)

# ── Attempt to import optional heavy dependencies ─────────────────────────────
try:
    import torchaudio  # type: ignore
    _HAS_TORCHAUDIO = True
except ImportError:
    _HAS_TORCHAUDIO = False
    log.warning("torchaudio not found — falling back to soundfile for audio loading.")

try:
    import librosa  # type: ignore
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False
    log.warning("librosa not found — silence trimming will use simple threshold method.")

try:
    import miniaudio  # type: ignore
    _HAS_MINIAUDIO = True
except ImportError:
    _HAS_MINIAUDIO = False
    log.warning("miniaudio not found — MP3 support may be limited.")


# ── Constants ─────────────────────────────────────────────────────────────────
TARGET_SAMPLE_RATE: int = 24_000        # XTTS-v2 native sample rate
TARGET_CHANNELS: int = 1               # Mono
TARGET_BIT_DEPTH: int = 16             # 16-bit PCM
PEAK_NORM_DB: float = -3.0             # Target peak after normalisation (dBFS)
SILENCE_DB_THRESHOLD: float = -40.0    # Below this level → silence
MIN_SILENCE_DURATION_SEC: float = 0.1  # Minimum silence segment to trim
CROSSFADE_DURATION_MS: int = 20        # Cross-fade between chunk concatenations


# ── Audio Info dataclass ──────────────────────────────────────────────────────
class AudioInfo:
    """Lightweight container for audio metadata."""

    def __init__(
        self,
        path: Path,
        sample_rate: int,
        channels: int,
        duration_sec: float,
        num_samples: int,
        bit_depth: Optional[int] = None,
    ) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.channels = channels
        self.duration_sec = duration_sec
        self.num_samples = num_samples
        self.bit_depth = bit_depth

    def __repr__(self) -> str:
        return (
            f"AudioInfo(sr={self.sample_rate}, ch={self.channels}, "
            f"dur={self.duration_sec:.2f}s, samples={self.num_samples})"
        )


# ── Public API ────────────────────────────────────────────────────────────────

def load_audio(
    path: str | Path,
    target_sr: int = TARGET_SAMPLE_RATE,
    mono: bool = True,
) -> tuple[torch.Tensor, int]:
    """
    Load an audio file and return a normalised float32 tensor.

    The returned tensor has shape [1, num_samples] (mono, float32, range [-1, 1]).
    Automatically resamples to `target_sr` if the file has a different sample rate.

    Args:
        path:      Path to the audio file.
        target_sr: Desired output sample rate (default: 24 000 Hz).
        mono:      If True, downmix to mono.

    Returns:
        Tuple of (waveform_tensor [1, samples], sample_rate).

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError:      If the file cannot be decoded.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    log.debug("Loading audio file: %s", p.name)

    waveform: torch.Tensor
    sr: int

    is_mp3 = p.suffix.lower() == ".mp3"

    if is_mp3 and _HAS_MINIAUDIO:
        # miniaudio: pure Python, no ffmpeg needed — best for MP3 on Windows
        try:
            decoded = miniaudio.decode_file(str(p))  # type: ignore
            samples = np.array(decoded.samples, dtype=np.float32) / 32768.0
            if decoded.nchannels > 1:
                samples = samples.reshape(-1, decoded.nchannels).T
            else:
                samples = samples[np.newaxis, :]
            waveform = torch.from_numpy(samples)
            sr = decoded.sample_rate
        except Exception as exc:
            raise RuntimeError(f"Failed to decode audio '{p.name}': {exc}") from exc
    elif _HAS_TORCHAUDIO:
        try:
            waveform, sr = torchaudio.load(str(p))  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"Failed to decode audio '{p.name}': {exc}") from exc
    else:
        # Last resort: soundfile (WAV/FLAC/OGG only — not MP3)
        try:
            data, sr = sf.read(str(p), dtype="float32", always_2d=True)
            waveform = torch.from_numpy(data.T)
        except Exception as exc:
            raise RuntimeError(f"Failed to load audio '{p.name}': {exc}") from exc


    # Downmix to mono
    if mono and waveform.shape[0] > 1:
        waveform = convert_to_mono(waveform)

    # Resample if needed
    if sr != target_sr:
        log.debug("Resampling from %d Hz to %d Hz", sr, target_sr)
        waveform = resample_audio(waveform, orig_sr=sr, target_sr=target_sr)
        sr = target_sr

    log.debug("Loaded: shape=%s, sr=%d, dur=%.2fs", waveform.shape, sr, waveform.shape[-1] / sr)
    return waveform, sr


def get_audio_info(path: str | Path) -> AudioInfo:
    """
    Read audio metadata without loading the full waveform into memory.

    Args:
        path: Path to the audio file.

    Returns:
        AudioInfo object with sample_rate, channels, duration, etc.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError:      If metadata cannot be read.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    bit_depth: Optional[int] = None

    if _HAS_TORCHAUDIO:
        try:
            info = torchaudio.info(str(p))  # type: ignore
            sr = info.sample_rate
            channels = info.num_channels
            num_samples = info.num_frames
            duration = num_samples / sr if sr > 0 else 0.0
        except Exception as exc:
            raise RuntimeError(f"Cannot read metadata from '{p.name}': {exc}") from exc
    else:
        try:
            with sf.SoundFile(str(p)) as f:
                sr = f.samplerate
                channels = f.channels
                num_samples = f.frames
                duration = num_samples / sr if sr > 0 else 0.0
        except Exception as exc:
            raise RuntimeError(f"Cannot read metadata from '{p.name}': {exc}") from exc

    # Read bit depth from WAV header (best-effort)
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as wf:
                bit_depth = wf.getsampwidth() * 8
        except Exception:
            pass

    return AudioInfo(
        path=p,
        sample_rate=sr,
        channels=channels,
        duration_sec=duration,
        num_samples=num_samples,
        bit_depth=bit_depth,
    )


def convert_to_mono(waveform: torch.Tensor) -> torch.Tensor:
    """
    Downmix a multi-channel waveform to mono by averaging all channels.

    Args:
        waveform: Input tensor of shape [channels, samples] or [1, samples].

    Returns:
        Mono tensor of shape [1, samples].
    """
    if waveform.shape[0] == 1:
        return waveform
    mono = waveform.mean(dim=0, keepdim=True)
    log.debug("Downmixed %d channels to mono", waveform.shape[0])
    return mono


def resample_audio(
    waveform: torch.Tensor,
    orig_sr: int,
    target_sr: int,
) -> torch.Tensor:
    """
    Resample a waveform tensor to a target sample rate.

    Uses torchaudio.functional.resample (Kaiser-windowed sinc interpolation)
    when available; falls back to librosa for numpy arrays otherwise.

    Args:
        waveform:  Input tensor [1, samples] or [channels, samples].
        orig_sr:   Original sample rate in Hz.
        target_sr: Target sample rate in Hz.

    Returns:
        Resampled tensor with the same channel count.
    """
    if orig_sr == target_sr:
        return waveform

    if _HAS_TORCHAUDIO:
        return torchaudio.functional.resample(waveform, orig_sr, target_sr)  # type: ignore

    if _HAS_LIBROSA:
        # Fall back to librosa (numpy path)
        arr = waveform.squeeze(0).numpy()
        resampled = librosa.resample(arr, orig_sr=orig_sr, target_sr=target_sr)  # type: ignore
        return torch.from_numpy(resampled).unsqueeze(0)

    raise RuntimeError(
        "Neither torchaudio nor librosa is available for resampling. "
        "Please install one: pip install torchaudio  or  pip install librosa"
    )


def normalize_audio(waveform: torch.Tensor, target_db: float = PEAK_NORM_DB) -> torch.Tensor:
    """
    Peak-normalise a waveform to the target dBFS level.

    Peak normalisation scales the entire waveform so that the maximum
    absolute amplitude equals the target level. This prevents clipping
    while maximising perceived loudness.

    Args:
        waveform:  Input float32 tensor [1, samples].
        target_db: Target peak level in dBFS (default: -3.0 dBFS).

    Returns:
        Normalised tensor, same shape as input.
    """
    peak = waveform.abs().max()
    if peak < 1e-8:
        log.warning("Audio is essentially silent — normalisation skipped.")
        return waveform

    target_linear = 10 ** (target_db / 20.0)
    scale = target_linear / peak.item()
    normalised = waveform * scale

    log.debug(
        "Normalised: peak=%.4f → %.4f (scale=%.4f, target=%.1f dBFS)",
        peak.item(), normalised.abs().max().item(), scale, target_db,
    )
    return normalised


def trim_silence(
    waveform: torch.Tensor,
    sample_rate: int = TARGET_SAMPLE_RATE,
    threshold_db: float = SILENCE_DB_THRESHOLD,
    min_silence_sec: float = MIN_SILENCE_DURATION_SEC,
) -> torch.Tensor:
    """
    Remove leading and trailing silence from a waveform.

    Uses librosa's `effects.trim` when available; falls back to a simple
    energy-threshold approach.

    Args:
        waveform:        Input float32 tensor [1, samples].
        sample_rate:     Sample rate (used only for the librosa path).
        threshold_db:    dBFS threshold below which audio is considered silence.
        min_silence_sec: Minimum silence duration to remove (seconds).

    Returns:
        Trimmed tensor [1, samples]. May be shorter than input.
    """
    arr = waveform.squeeze(0).numpy()

    if _HAS_LIBROSA:
        trimmed, _ = librosa.effects.trim(  # type: ignore
            arr,
            top_db=abs(threshold_db),
            frame_length=2048,
            hop_length=512,
        )
    else:
        # Simple energy-threshold trimming
        threshold_linear = 10 ** (threshold_db / 20.0)
        above = np.where(np.abs(arr) > threshold_linear)[0]
        if len(above) == 0:
            log.warning("Entire waveform is below silence threshold — skipping trim.")
            return waveform
        start = max(0, above[0] - int(min_silence_sec * sample_rate))
        end = min(len(arr), above[-1] + int(min_silence_sec * sample_rate))
        trimmed = arr[start:end]

    log.debug(
        "Trimmed silence: %d → %d samples (%.2fs → %.2fs)",
        len(arr), len(trimmed),
        len(arr) / sample_rate, len(trimmed) / sample_rate,
    )
    return torch.from_numpy(trimmed).unsqueeze(0)


def concatenate_audio_chunks(
    chunks: list[torch.Tensor],
    crossfade_ms: int = CROSSFADE_DURATION_MS,
    sample_rate: int = TARGET_SAMPLE_RATE,
) -> torch.Tensor:
    """
    Concatenate a list of audio tensors with optional linear crossfade.

    When crossfade_ms > 0, adjacent chunks are blended over a short overlap
    to avoid clicks at chunk boundaries.

    Args:
        chunks:       List of float32 tensors [1, samples].
        crossfade_ms: Crossfade duration in milliseconds (0 to disable).
        sample_rate:  Audio sample rate.

    Returns:
        Single concatenated tensor [1, total_samples].
    """
    if not chunks:
        raise ValueError("Cannot concatenate an empty list of audio chunks.")
    if len(chunks) == 1:
        return chunks[0]

    crossfade_samples = int(crossfade_ms * sample_rate / 1000)

    if crossfade_samples == 0:
        return torch.cat(chunks, dim=-1)

    result = chunks[0]
    for next_chunk in chunks[1:]:
        result = _crossfade_join(result, next_chunk, crossfade_samples)

    log.debug(
        "Concatenated %d chunks into %.2fs of audio",
        len(chunks), result.shape[-1] / sample_rate,
    )
    return result


def _crossfade_join(
    a: torch.Tensor,
    b: torch.Tensor,
    crossfade_samples: int,
) -> torch.Tensor:
    """
    Internal: join two audio tensors with a linear crossfade at the boundary.
    """
    cf = min(crossfade_samples, a.shape[-1], b.shape[-1])

    fade_out = torch.linspace(1.0, 0.0, cf)
    fade_in = torch.linspace(0.0, 1.0, cf)

    a_body = a[..., :-cf]
    a_tail = a[..., -cf:] * fade_out
    b_head = b[..., :cf] * fade_in
    b_body = b[..., cf:]

    overlap = a_tail + b_head
    return torch.cat([a_body, overlap, b_body], dim=-1)


def save_wav(
    waveform: torch.Tensor,
    sample_rate: int,
    output_path: str | Path,
    bit_depth: int = TARGET_BIT_DEPTH,
) -> Path:
    """
    Save a waveform tensor to a 16-bit PCM WAV file.

    Args:
        waveform:    Float32 tensor [1, samples] in range [-1, 1].
        sample_rate: Audio sample rate in Hz.
        output_path: Destination file path (will be created/overwritten).
        bit_depth:   Target bit depth (16 or 32).

    Returns:
        Resolved Path to the saved WAV file.

    Raises:
        RuntimeError: If the file cannot be saved.
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    # Ensure mono (squeeze channel dim if present)
    arr = waveform.squeeze(0).cpu().numpy()

    # Clip to prevent overflow before int conversion
    arr = np.clip(arr, -1.0, 1.0)

    subtype = "PCM_16" if bit_depth == 16 else "PCM_32"

    try:
        sf.write(str(out), arr, samplerate=sample_rate, subtype=subtype)
    except Exception as exc:
        raise RuntimeError(f"Failed to save WAV to '{out}': {exc}") from exc

    file_size = out.stat().st_size
    log.info(
        "Saved WAV: %s (%.2fs, %d Hz, %d-bit, %.1f KB)",
        out.name,
        len(arr) / sample_rate,
        sample_rate,
        bit_depth,
        file_size / 1024,
    )
    return out


def preprocess_reference_audio(
    path: str | Path,
    normalize: bool = True,
    trim: bool = True,
) -> tuple[torch.Tensor, int, AudioInfo]:
    """
    Full preprocessing pipeline for a reference (speaker) audio file.

    Steps:
    1. Load and decode the audio
    2. Downmix to mono
    3. Resample to 24 kHz
    4. Optionally trim silence
    5. Optionally peak-normalise
    6. Return processed waveform + original metadata

    Args:
        path:      Path to the reference audio file.
        normalize: Whether to apply peak normalisation.
        trim:      Whether to trim leading/trailing silence.

    Returns:
        Tuple of (processed_waveform, sample_rate, original_info).
    """
    # Get metadata before loading
    info = get_audio_info(path)
    log.info(
        "Preprocessing reference audio: %s (%.2fs, %d Hz, %d ch)",
        Path(path).name, info.duration_sec, info.sample_rate, info.channels,
    )

    # Load + resample + mono
    waveform, sr = load_audio(path, target_sr=TARGET_SAMPLE_RATE, mono=True)

    # Trim silence
    if trim:
        waveform = trim_silence(waveform, sample_rate=sr)

    # Normalise
    if normalize:
        waveform = normalize_audio(waveform)

    return waveform, sr, info


def tensor_to_numpy_audio(waveform: torch.Tensor) -> np.ndarray:
    """
    Convert a float32 torch Tensor [1, samples] to a numpy float32 array.
    Suitable for passing to sounddevice or pygame for playback.

    Args:
        waveform: Float32 tensor [1, samples] or [samples].

    Returns:
        1-D numpy float32 array.
    """
    if waveform.dim() == 2:
        arr = waveform.squeeze(0)
    else:
        arr = waveform
    return arr.cpu().numpy().astype(np.float32)
