"""
core/tts_engine.py
------------------
XTTS-v2 model wrapper — the heart of the voice cloning pipeline.

This module manages:
  - One-time model loading (singleton pattern via class-level state)
  - Text-to-speech inference with voice cloning
  - Text chunking for long inputs
  - Audio chunk concatenation
  - Thread-safe generation via a generation lock

Architecture:
  TTSEngine is designed as a class (not a global function) so it can emit
  Qt signals from a QThread. The actual XTTS-v2 model is held in a class
  attribute (_model), ensuring it is loaded exactly once per process even if
  multiple TTSEngine instances are created.

XTTS-v2 details:
  - Model: tts_models/multilingual/multi-dataset/xtts_v2
  - Input: text + reference WAV path + language code
  - Output: float32 numpy array at 24 000 Hz
  - Reference audio: 6–30 seconds of clean speech
  - Languages: 17 supported (en, te, hi, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, ko, hu)

Dependencies: TTS (Coqui), torch, numpy, soundfile
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import torch

from core.audio_utils import (
    concatenate_audio_chunks,
    normalize_audio,
    save_wav,
    tensor_to_numpy_audio,
)
from core.helpers import split_into_sentences, timestamp_filename
from config.settings import APP_CONFIG, OUTPUTS_DIR
from utils.logger import setup_logger

log = setup_logger(__name__)


class ModelNotLoadedError(RuntimeError):
    """Raised when inference is attempted before the model is loaded."""
    pass


class TTSEngine:
    """
    Singleton-like XTTS-v2 engine wrapper.

    The heavy TTS model is stored in ``_shared_model`` (class attribute),
    so regardless of how many ``TTSEngine`` instances exist, the model
    is only ever loaded into RAM/VRAM once.

    Usage:
        engine = TTSEngine(device="cuda")
        engine.load_model(progress_callback=my_fn)
        output_path = engine.generate(
            text="Hello, world!",
            speaker_wav="audio/my_voice.wav",
            language="en",
        )
    """

    # ── Shared state (class-level) ─────────────────────────────────────────
    _shared_model: Optional[Any] = None       # Coqui TTS model instance
    _shared_device: str = "cpu"               # Device used by the loaded model
    _model_lock: threading.Lock = threading.Lock()
    _load_complete: bool = False

    def __init__(self, device: str = "cpu") -> None:
        """
        Initialise the engine for a specific device.

        Args:
            device: "cuda" or "cpu"
        """
        self._device = device
        log.info("TTSEngine initialised for device: %s", device)

    # ── Properties ────────────────────────────────────────────────────────
    @property
    def is_loaded(self) -> bool:
        """True if the XTTS-v2 model is loaded into memory."""
        return TTSEngine._load_complete and TTSEngine._shared_model is not None

    @property
    def device(self) -> str:
        return self._device

    # ── Model loading ─────────────────────────────────────────────────────

    def load_model(
        self,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """
        Download (if necessary) and load the XTTS-v2 model into memory.

        This is thread-safe: concurrent calls will block until the first
        call completes, then return immediately (model already loaded).

        The XTTS-v2 model (~1.8 GB) is automatically downloaded from
        Hugging Face on the first call, then cached locally forever.

        Args:
            progress_callback: Optional callable(percent: int, message: str)
                               called periodically during loading to update a
                               progress bar. Values: 0–100.

        Raises:
            RuntimeError: If the model cannot be loaded.
        """
        with TTSEngine._model_lock:
            if TTSEngine._load_complete:
                log.info("Model already loaded — skipping.")
                if progress_callback:
                    progress_callback(100, "Model already loaded.")
                return

            log.info("Loading XTTS-v2 model on %s …", self._device)
            if progress_callback:
                progress_callback(5, "Importing TTS library …")

            try:
                import pathlib

                # ── Patch: restore isin_mps_friendly removed in newer transformers ──
                # Coqui TTS's tortoise autoregressive layer still imports this
                # function which was removed in transformers >= 4.40.
                try:
                    import transformers.pytorch_utils as _pt_utils  # type: ignore
                    if not hasattr(_pt_utils, "isin_mps_friendly"):
                        import torch as _torch

                        def _isin_mps_friendly(elements: _torch.Tensor, test_elements: _torch.Tensor) -> _torch.Tensor:
                            """Compat shim: elementwise isin for MPS/CPU/CUDA."""
                            return _torch.isin(elements, test_elements)

                        _pt_utils.isin_mps_friendly = _isin_mps_friendly
                        log.info("Applied isin_mps_friendly compatibility patch for transformers.")
                except Exception as _patch_err:
                    log.warning("Could not apply transformers patch: %s", _patch_err)

                # ── Locate local model files ───────────────────────────────
                model_dir = (
                    pathlib.Path.home()
                    / "AppData" / "Local" / "tts"
                    / "tts_models--multilingual--multi-dataset--xtts_v2"
                )
                config_path = model_dir / "config.json"

                use_gpu = self._device == "cuda" and torch.cuda.is_available()

                if config_path.exists() and config_path.stat().st_size > 0:
                    # ── Fast path: load directly from local files ──────────
                    log.info("Loading XTTS-v2 from local cache: %s", model_dir)
                    if progress_callback:
                        progress_callback(20, "Loading model from local cache …")

                    from TTS.tts.configs.xtts_config import XttsConfig  # type: ignore
                    from TTS.tts.models.xtts import Xtts  # type: ignore

                    config = XttsConfig()
                    config.load_json(str(config_path))

                    if progress_callback:
                        progress_callback(40, "Initialising XTTS-v2 …")

                    xtts_model = Xtts.init_from_config(config)

                    if progress_callback:
                        progress_callback(60, "Loading model weights into memory …")

                    xtts_model.load_checkpoint(
                        config,
                        checkpoint_dir=str(model_dir),
                        eval=True,
                    )

                    if use_gpu:
                        if progress_callback:
                            progress_callback(80, "Moving model to GPU …")
                        xtts_model.cuda()

                    # Wrap in a compatible interface for the rest of the codebase
                    class _XTTSWrapper:
                        """Wraps the low-level Xtts model to match the Coqui TTS high-level API."""
                        def __init__(self, m, cfg):
                            self._m = m
                            self._cfg = cfg
                            self._latent_cache: dict = {}  # cache latents per speaker file

                        def _get_latents(self, speaker_wav: str):
                            if speaker_wav not in self._latent_cache:
                                # max_ref_length=30 forces XTTS to use up to 30s of
                                # your voice for conditioning — more data = better clone
                                latents = self._m.get_conditioning_latents(
                                    audio_path=speaker_wav,
                                    max_ref_length=30,
                                    gpt_cond_len=30,
                                    gpt_cond_chunk_len=6,
                                )
                                self._latent_cache[speaker_wav] = latents
                            return self._latent_cache[speaker_wav]

                        def tts(
                            self,
                            text: str,
                            speaker_wav: str,
                            language: str = "en",
                            temperature: float = 0.1,
                            top_p: float = 0.85,
                            repetition_penalty: float = 10.0,
                            length_penalty: float = 1.0,
                            speed: float = 1.0,
                        ):
                            """Returns a numpy float32 array of audio samples.

                            Quality parameters:
                              temperature       : Lower = more faithful to your voice (0.01–1.0).
                                                  Default 0.1 gives best voice similarity.
                              top_p             : Nucleus sampling threshold (0.5–1.0).
                              repetition_penalty: Penalise repeated tokens (5–20).
                              speed             : Playback speed multiplier (0.5–2.0).
                            """
                            import numpy as _np
                            gpt_cond_latent, speaker_embedding = self._get_latents(speaker_wav)
                            out = self._m.inference(
                                text=text,
                                language=language,
                                gpt_cond_latent=gpt_cond_latent,
                                speaker_embedding=speaker_embedding,
                                temperature=temperature,
                                top_p=top_p,
                                repetition_penalty=repetition_penalty,
                                length_penalty=length_penalty,
                                speed=speed,
                                enable_text_splitting=False,  # we split ourselves
                            )
                            wav = out["wav"]
                            return _np.array(wav, dtype=_np.float32)

                    model = _XTTSWrapper(xtts_model, config)

                else:
                    # ── Fallback: let TTS library download (original behaviour) ──
                    log.warning("Local model not found — falling back to TTS download.")
                    if progress_callback:
                        progress_callback(20, "Initialising XTTS-v2 …")
                    from TTS.api import TTS  # type: ignore  # noqa: PLC0415
                    if progress_callback:
                        progress_callback(30, "Downloading model weights (first run only) …")
                    model = TTS(
                        model_name=APP_CONFIG.model_name,
                        gpu=use_gpu,
                        progress_bar=False,
                    )

                if progress_callback:
                    progress_callback(90, "Finalising model setup …")

                TTSEngine._shared_model = model
                TTSEngine._shared_device = self._device
                TTSEngine._load_complete = True

                log.info(
                    "XTTS-v2 loaded successfully (device=%s, gpu=%s)",
                    self._device, use_gpu,
                )

                if progress_callback:
                    progress_callback(100, "Model ready!")

            except ImportError as exc:
                raise RuntimeError(
                    "Coqui TTS is not installed. "
                    "Run: pip install TTS>=0.22.0"
                ) from exc
            except Exception as exc:
                log.error("Failed to load XTTS-v2 model: %s", exc, exc_info=True)
                raise RuntimeError(f"Model loading failed: {exc}") from exc

    # ── Inference ─────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        speaker_wav: str | Path,
        language: str = "en",
        output_path: Optional[str | Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        normalize: bool = True,
        temperature: float = 0.1,
        top_p: float = 0.85,
        repetition_penalty: float = 10.0,
        speed: float = 1.0,
    ) -> Path:
        """
        Generate speech in the cloned voice for the given text.

        Long texts are automatically split into sentence-level chunks,
        synthesised individually, and concatenated with crossfade.

        Args:
            text:             Input text to synthesise (may be multi-line).
            speaker_wav:      Path to the reference WAV file (speaker's voice).
            language:         XTTS-v2 language code (e.g. "en", "te", "hi").
            output_path:      Where to save the output WAV. If None, a
                              timestamped name in outputs/ is used.
            progress_callback: Optional callable(percent, message) for UI updates.
            normalize:        Whether to peak-normalise the final output.

        Returns:
            Path to the saved output WAV file.

        Raises:
            ModelNotLoadedError: If the model has not been loaded yet.
            ValueError:          If text or speaker_wav are invalid.
            RuntimeError:        If synthesis fails.
        """
        if not self.is_loaded:
            raise ModelNotLoadedError(
                "Model is not loaded. Call load_model() before generate()."
            )

        # ── Validate inputs ────────────────────────────────────────────────
        text = text.strip()
        if not text:
            raise ValueError("Input text is empty. Please type something to synthesise.")

        speaker_path = Path(speaker_wav)
        if not speaker_path.exists():
            raise ValueError(f"Reference audio file not found: {speaker_path}")

        # ── Prepare output path ────────────────────────────────────────────
        if output_path is None:
            filename = timestamp_filename(APP_CONFIG.output_prefix, APP_CONFIG.output_ext)
            output_path = OUTPUTS_DIR / filename
        out_path = Path(output_path)

        # ── Split text into chunks ────────────────────────────────────────
        chunks = split_into_sentences(text, max_chars=APP_CONFIG.max_chars_per_chunk)
        if not chunks:
            raise ValueError("Text produced no processable sentences.")

        log.info(
            "Generating speech: %d chunk(s), language=%s, speaker=%s",
            len(chunks), language, speaker_path.name,
        )

        # ── Synthesise each chunk ────────────────────────────────────────
        audio_chunks: list[torch.Tensor] = []
        start_time = time.perf_counter()

        for idx, chunk in enumerate(chunks):
            chunk_progress_start = 10 + int(80 * idx / len(chunks))
            chunk_progress_end = 10 + int(80 * (idx + 1) / len(chunks))

            if progress_callback:
                progress_callback(
                    chunk_progress_start,
                    f"Synthesising chunk {idx + 1}/{len(chunks)} …",
                )

            log.debug("Chunk %d/%d: %r", idx + 1, len(chunks), chunk[:60])

            audio_array = self._synthesise_chunk(
                chunk=chunk,
                speaker_wav=str(speaker_path),
                language=language,
                temperature=temperature,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                speed=speed,
            )

            if audio_array is None or len(audio_array) == 0:
                log.warning("Chunk %d produced empty audio — skipping.", idx + 1)
                continue

            # Convert numpy array → torch tensor [1, samples]
            tensor = torch.from_numpy(audio_array.astype(np.float32)).unsqueeze(0)
            audio_chunks.append(tensor)

            if progress_callback:
                progress_callback(
                    chunk_progress_end,
                    f"Chunk {idx + 1}/{len(chunks)} complete.",
                )

        if not audio_chunks:
            raise RuntimeError("All synthesis chunks produced empty audio.")

        # ── Concatenate chunks ────────────────────────────────────────────
        if progress_callback:
            progress_callback(92, "Joining audio chunks …")

        final_audio = concatenate_audio_chunks(audio_chunks, crossfade_ms=20)

        # ── Normalise ─────────────────────────────────────────────────────
        if normalize:
            final_audio = normalize_audio(final_audio)

        # ── Save WAV ───────────────────────────────────────────────────────
        if progress_callback:
            progress_callback(97, "Saving WAV file …")

        saved_path = save_wav(
            waveform=final_audio,
            sample_rate=APP_CONFIG.sample_rate,
            output_path=out_path,
            bit_depth=APP_CONFIG.bit_depth,
        )

        elapsed = time.perf_counter() - start_time
        duration_sec = final_audio.shape[-1] / APP_CONFIG.sample_rate
        log.info(
            "Generation complete: %.2fs of audio in %.1fs (RTF=%.2f)",
            duration_sec, elapsed,
            elapsed / duration_sec if duration_sec > 0 else 0,
        )

        if progress_callback:
            progress_callback(100, "Done!")

        return saved_path

    # ── Internal helpers ──────────────────────────────────────────────────

    def _synthesise_chunk(
        self,
        chunk: str,
        speaker_wav: str,
        language: str,
        temperature: float = 0.1,
        top_p: float = 0.85,
        repetition_penalty: float = 10.0,
        speed: float = 1.0,
    ) -> Optional[np.ndarray]:
        """
        Run XTTS-v2 inference on a single text chunk.

        Args:
            chunk:       Short text segment (< 250 chars recommended).
            speaker_wav: Path to reference WAV file.
            language:    XTTS-v2 language code.

        Returns:
            Numpy float32 array of synthesised audio samples, or None on error.
        """
        model = TTSEngine._shared_model
        if model is None:
            return None

        try:
            # XTTS-v2 inference via Coqui TTS API
            # tts_to_file is not used here so we can get the raw numpy array
            tts_kwargs: dict = dict(
                text=chunk,
                speaker_wav=speaker_wav,
                language=language,
            )
            # Pass quality params only to our _XTTSWrapper (low-level path)
            if hasattr(model, "tts") and hasattr(model, "_latent_cache"):
                tts_kwargs.update(
                    temperature=temperature,
                    top_p=top_p,
                    repetition_penalty=repetition_penalty,
                    speed=speed,
                )
            result = model.tts(**tts_kwargs)

            if result is None:
                return None

            # Result may be a list or numpy array
            if isinstance(result, list):
                return np.array(result, dtype=np.float32)
            return np.asarray(result, dtype=np.float32)

        except Exception as exc:
            log.error("Synthesis failed for chunk %r: %s", chunk[:40], exc, exc_info=True)
            raise RuntimeError(f"TTS synthesis error: {exc}") from exc

    def unload_model(self) -> None:
        """
        Unload the model from memory (RAM + VRAM).

        This frees all GPU memory and allows the model to be reloaded
        with a different device if needed.
        """
        with TTSEngine._model_lock:
            if TTSEngine._shared_model is not None:
                del TTSEngine._shared_model
                TTSEngine._shared_model = None
                TTSEngine._load_complete = False

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                log.info("XTTS-v2 model unloaded and GPU cache cleared.")

    def get_model_info(self) -> dict[str, Any]:
        """
        Return a dictionary of model information for display in the UI.

        Returns:
            Dict with model_name, device, is_loaded, gpu_name, etc.
        """
        info: dict[str, Any] = {
            "model_name": APP_CONFIG.model_name,
            "device": TTSEngine._shared_device,
            "is_loaded": self.is_loaded,
            "gpu_name": "N/A",
            "vram_used_mb": None,
        }

        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            allocated = torch.cuda.memory_allocated(0) / (1024 ** 2)
            info["vram_used_mb"] = round(allocated, 1)

        return info
