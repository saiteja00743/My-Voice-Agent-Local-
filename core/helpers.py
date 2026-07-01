"""
core/helpers.py
---------------
General-purpose utility functions used across the application.

Contains:
  - timestamp_filename()  : Unique timestamped output filenames
  - ensure_dir()          : Safe directory creation
  - format_duration()     : Human-readable seconds → "Xm Ys"
  - sanitize_text()       : Clean input text for TTS
  - split_into_sentences(): Split long text into TTS-friendly chunks
  - get_model_dir()       : Resolve the XTTS model cache path
  - validate_audio_file() : Quick validation of an audio file path

Design note:
  All functions are pure / stateless — they take inputs and return outputs
  with no side effects except `ensure_dir`. This makes them easy to test
  and reuse anywhere in the codebase.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.logger import setup_logger

log = setup_logger(__name__)

# ── Supported audio file extensions ──────────────────────────────────────────
VALID_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
)


def timestamp_filename(prefix: str = "output", ext: str = ".wav") -> str:
    """
    Generate a unique filename based on the current timestamp.

    Args:
        prefix: Filename prefix (e.g., "voice_clone").
        ext:    File extension including the dot (e.g., ".wav").

    Returns:
        A filename string like "voice_clone_20240615_143022.wav".

    Example:
        >>> timestamp_filename("voice_clone", ".wav")
        'voice_clone_20240615_143022.wav'
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{prefix}_{ts}{ext}"


def ensure_dir(path: str | Path) -> Path:
    """
    Create a directory (and all parents) if it does not exist.

    Args:
        path: Directory path as string or Path.

    Returns:
        The resolved Path object.
    """
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds (may be float).

    Returns:
        Formatted string, e.g. "1m 23s", "45s", "0s".

    Example:
        >>> format_duration(83.4)
        '1m 23s'
        >>> format_duration(7.0)
        '7s'
    """
    secs = max(0, int(seconds))
    minutes, secs = divmod(secs, 60)
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def sanitize_text(text: str) -> str:
    """
    Clean user input text before passing it to the TTS engine.

    Operations performed:
    1. Normalize Unicode to NFC form
    2. Strip leading/trailing whitespace
    3. Collapse multiple consecutive whitespace characters to a single space
    4. Remove control characters (except newlines and tabs)
    5. Limit consecutive newlines to a maximum of 2

    Args:
        text: Raw input text from the GUI text box.

    Returns:
        Cleaned text string safe for TTS processing.
    """
    # Normalize Unicode
    text = unicodedata.normalize("NFC", text)

    # Remove control characters (keep newlines \n and tabs \t)
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("Cc", "Cf")
        or ch in ("\n", "\t", "\r")
    )

    # Normalize whitespace within lines
    lines = text.splitlines()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]

    # Collapse more than 2 consecutive blank lines to 2
    result_lines: list[str] = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 2:
                result_lines.append(line)
        else:
            blank_count = 0
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def split_into_sentences(
    text: str,
    max_chars: int = 250,
    delimiters: str = ".!?。！？\n",
) -> list[str]:
    """
    Split long text into sentence-level chunks suitable for XTTS-v2.

    XTTS-v2 performs best on shorter chunks (< 250 characters). This
    function splits at sentence boundaries while respecting the max_chars
    limit. Chunks that are too long are further split at commas or spaces.

    Args:
        text:       Input text (may be multi-line).
        max_chars:  Maximum characters per chunk.
        delimiters: Characters that mark sentence boundaries.

    Returns:
        List of text chunks, each within the max_chars limit.

    Example:
        >>> split_into_sentences("Hello world. How are you?", max_chars=20)
        ['Hello world.', 'How are you?']
    """
    if not text.strip():
        return []

    # Build regex pattern from delimiters
    escaped = re.escape(delimiters)
    # Split while keeping the delimiter attached to the preceding text
    raw_sentences: list[str] = re.split(rf"(?<=[{escaped}])\s*", text)

    chunks: list[str] = []

    for sentence in raw_sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            # Further split long sentences at commas, then at word boundaries
            sub_chunks = _split_long_sentence(sentence, max_chars)
            chunks.extend(sub_chunks)

    return [c for c in chunks if c.strip()]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """
    Internal helper: split a single long sentence that exceeds max_chars.
    Tries comma splits first, then falls back to word-boundary splits.
    """
    # Try splitting at commas first
    parts = re.split(r",\s*", sentence)
    result: list[str] = []
    current = ""

    for part in parts:
        candidate = f"{current}, {part}".strip(", ") if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                result.append(current.strip())
            # If single part is still too long, split by words
            if len(part) > max_chars:
                result.extend(_split_by_words(part, max_chars))
                current = ""
            else:
                current = part

    if current:
        result.append(current.strip())

    return result


def _split_by_words(text: str, max_chars: int) -> list[str]:
    """
    Internal helper: split text at word boundaries within max_chars.
    Hard fallback for very long words.
    """
    words = text.split()
    chunks: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If a single word exceeds max_chars, hard-split it
            if len(word) > max_chars:
                for i in range(0, len(word), max_chars):
                    chunks.append(word[i : i + max_chars])
                current = ""
            else:
                current = word

    if current:
        chunks.append(current)

    return chunks


def get_model_dir() -> Path:
    """
    Resolve the XTTS-v2 model cache directory.

    Priority:
    1. <project_root>/models/  (preferred for fully offline use)
    2. System Coqui TTS cache (~/.local/share/tts)

    Returns:
        Absolute Path to the model directory.
    """
    local_model_dir = Path(__file__).resolve().parent.parent / "models"
    local_model_dir.mkdir(parents=True, exist_ok=True)
    return local_model_dir


def validate_audio_file(path: str | Path) -> tuple[bool, str]:
    """
    Validate that a file exists and has a supported audio extension.

    Args:
        path: Path to the audio file.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
        If valid, error_message is an empty string.

    Example:
        >>> validate_audio_file("my_voice.wav")
        (True, '')
        >>> validate_audio_file("document.pdf")
        (False, 'Unsupported file type: .pdf')
    """
    p = Path(path)

    if not p.exists():
        return False, f"File not found: {p.name}"

    if not p.is_file():
        return False, f"Path is not a file: {p.name}"

    if p.suffix.lower() not in VALID_AUDIO_EXTENSIONS:
        return False, (
            f"Unsupported file type: {p.suffix}. "
            f"Supported: {', '.join(sorted(VALID_AUDIO_EXTENSIONS))}"
        )

    # Basic size check (at least 1 KB)
    if p.stat().st_size < 1024:
        return False, f"File is too small to be a valid audio file: {p.name}"

    return True, ""


def count_words(text: str) -> tuple[int, int]:
    """
    Count words and characters in text.

    Args:
        text: Input text string.

    Returns:
        Tuple of (word_count, char_count).
    """
    stripped = text.strip()
    words = len(stripped.split()) if stripped else 0
    return words, len(text)


def human_file_size(size_bytes: int) -> str:
    """
    Convert a file size in bytes to a human-readable string.

    Args:
        size_bytes: File size in bytes.

    Returns:
        Human-readable string like "1.4 MB", "320 KB".

    Example:
        >>> human_file_size(1_500_000)
        '1.4 MB'
    """
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"
