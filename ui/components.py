"""
ui/components.py
----------------
Reusable custom PySide6 widgets for the AI Voice Clone application.

Custom widgets defined here:
  - DropZoneWidget     : Drag-and-drop / click-to-browse voice file zone
  - AudioWaveformWidget: Simple waveform visualiser painted with QPainter
  - HistoryListWidget  : Recent-generations list with playback controls
  - AnimatedLabel      : Status label with fade animations
  - DeviceBadge        : GPU/CPU badge shown in the header
  - WaveformWorker     : Background thread to compute waveform data

Design note:
  All custom widgets subclass QFrame or QWidget and use setProperty()
  to apply QSS class attributes defined in styles.py. This keeps styling
  data-driven and out of the Python source.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import (
    Qt,
    QThread,
    QTimer,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
    QSize,
    QPoint,
    QRect,
    Property,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QLinearGradient,
    QBrush,
    QPixmap,
    QIcon,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.styles import COLORS
from utils.logger import setup_logger

log = setup_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DropZoneWidget
# ─────────────────────────────────────────────────────────────────────────────

class DropZoneWidget(QFrame):
    """
    A clickable, drag-and-drop file zone for loading the reference voice WAV.

    Signals:
        file_selected(str): Emitted when a valid audio file is selected,
                            carrying the absolute file path.

    States (reflected via QSS class property):
        "drop-zone"        — default (no file loaded)
        "drop-zone-active" — user is dragging a file over the zone
        "drop-zone-loaded" — a file has been loaded successfully
    """

    file_selected = Signal(str)

    _VALID_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loaded_filename: Optional[str] = None
        self._setup_ui()
        self._set_state("drop-zone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(130)

    # ── UI setup ─────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 16, 20, 16)

        # Icon label
        self._icon_label = QLabel("🎤")
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 32px; background: transparent;")

        # Main text
        self._main_label = QLabel("Drop voice WAV here")
        self._main_label.setAlignment(Qt.AlignCenter)
        self._main_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {COLORS['text_primary']};"
            "background: transparent;"
        )

        # Sub text
        self._sub_label = QLabel("or click to browse")
        self._sub_label.setAlignment(Qt.AlignCenter)
        self._sub_label.setStyleSheet(
            f"font-size: 12px; color: {COLORS['text_secondary']};"
            "background: transparent;"
        )

        # File info (hidden until file loaded)
        self._file_label = QLabel("")
        self._file_label.setAlignment(Qt.AlignCenter)
        self._file_label.setWordWrap(True)
        self._file_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['success']};"
            "background: transparent;"
        )
        self._file_label.hide()

        layout.addWidget(self._icon_label)
        layout.addWidget(self._main_label)
        layout.addWidget(self._sub_label)
        layout.addWidget(self._file_label)

    # ── State management ─────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self.setProperty("class", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_loaded(self, filename: str) -> None:
        """Update the widget to show a loaded file state."""
        self._loaded_filename = filename
        self._icon_label.setText("✅")
        self._main_label.setText("Voice file loaded")
        self._sub_label.setText("Click to change file")
        self._file_label.setText(f"📁 {filename}")
        self._file_label.show()
        self._set_state("drop-zone-loaded")

    def set_idle(self) -> None:
        """Reset the widget to its default idle state."""
        self._loaded_filename = None
        self._icon_label.setText("🎤")
        self._main_label.setText("Drop voice WAV here")
        self._sub_label.setText("or click to browse")
        self._file_label.hide()
        self._set_state("drop-zone")

    # ── Events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._open_file_dialog()

    def _open_file_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Voice Recording",
            str(Path.home()),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a);;All Files (*)",
        )
        if path:
            self._emit_file(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(
                Path(u.toLocalFile()).suffix.lower() in self._VALID_EXTENSIONS
                for u in urls
            ):
                event.acceptProposedAction()
                self._set_state("drop-zone-active")
                self._icon_label.setText("📂")
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        if self._loaded_filename:
            self._set_state("drop-zone-loaded")
        else:
            self._set_state("drop-zone")
            self._icon_label.setText("🎤")

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        for url in urls:
            local_path = url.toLocalFile()
            if Path(local_path).suffix.lower() in self._VALID_EXTENSIONS:
                self._emit_file(local_path)
                break
        event.acceptProposedAction()

    def _emit_file(self, path: str) -> None:
        log.debug("File selected via drop/browse: %s", path)
        self.file_selected.emit(path)


# ─────────────────────────────────────────────────────────────────────────────
# WaveformWorker
# ─────────────────────────────────────────────────────────────────────────────

class WaveformWorker(QThread):
    """
    Background thread that loads an audio file and downsamples it to
    a fixed number of display points for the waveform visualiser.

    Signals:
        waveform_ready(np.ndarray): Emitted when waveform data is computed.
        error(str): Emitted if loading fails.
    """

    waveform_ready = Signal(object)  # np.ndarray
    error = Signal(str)

    def __init__(self, audio_path: str, num_points: int = 400) -> None:
        super().__init__()
        self._path = audio_path
        self._num_points = num_points

    def run(self) -> None:
        try:
            import soundfile as sf  # type: ignore
            data, sr = sf.read(self._path, dtype="float32", always_2d=True)
            # Downmix to mono
            mono = data.mean(axis=1)
            # Downsample to num_points by chunking
            chunk_size = max(1, len(mono) // self._num_points)
            points = np.array([
                mono[i : i + chunk_size].max() - mono[i : i + chunk_size].min()
                for i in range(0, len(mono) - chunk_size, chunk_size)
            ][: self._num_points])
            # Normalise to [0, 1]
            if points.max() > 0:
                points = points / points.max()
            self.waveform_ready.emit(points)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AudioWaveformWidget
# ─────────────────────────────────────────────────────────────────────────────

class AudioWaveformWidget(QWidget):
    """
    A custom widget that draws an audio waveform using QPainter.

    Features:
      - Gradient fill (purple → cyan)
      - Mirror effect (upper + lower halves)
      - Animated loading indicator (pulsing bars)
      - Shows "No audio loaded" placeholder when empty
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: Optional[np.ndarray] = None
        self._loading = False
        self._pulse_offset = 0
        self.setMinimumHeight(80)
        self.setMaximumHeight(120)

        # Pulse animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_pulse_tick)

    def set_audio_file(self, path: str) -> None:
        """Load and display waveform from an audio file (runs in background)."""
        self._loading = True
        self._timer.start(50)
        self.update()

        self._worker = WaveformWorker(path)
        self._worker.waveform_ready.connect(self._on_waveform_ready)
        self._worker.error.connect(self._on_waveform_error)
        self._worker.start()

    def clear(self) -> None:
        """Clear the displayed waveform."""
        self._data = None
        self._loading = False
        self._timer.stop()
        self.update()

    def _on_waveform_ready(self, data: np.ndarray) -> None:
        self._data = data
        self._loading = False
        self._timer.stop()
        self.update()

    def _on_waveform_error(self, error: str) -> None:
        log.warning("Waveform load error: %s", error)
        self._loading = False
        self._timer.stop()
        self.update()

    def _on_pulse_tick(self) -> None:
        self._pulse_offset = (self._pulse_offset + 1) % 20
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        mid = h // 2

        # Background
        painter.fillRect(0, 0, w, h, QColor(COLORS["bg_surface"]))

        if self._loading:
            self._paint_loading(painter, w, h, mid)
        elif self._data is not None and len(self._data) > 0:
            self._paint_waveform(painter, w, h, mid)
        else:
            self._paint_placeholder(painter, w, h, mid)

        painter.end()

    def _paint_waveform(self, painter: QPainter, w: int, h: int, mid: int) -> None:
        data = self._data
        n = len(data)
        bar_w = max(1.0, w / n)

        gradient = QLinearGradient(0, 0, w, 0)
        gradient.setColorAt(0.0, QColor(COLORS["cyan"]))
        gradient.setColorAt(0.5, QColor(COLORS["accent"]))
        gradient.setColorAt(1.0, QColor(COLORS["cyan"]))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))

        for i, amplitude in enumerate(data):
            x = i * bar_w
            bar_h = max(2, int(amplitude * (mid - 4)))
            # Upper half
            painter.drawRoundedRect(
                int(x), mid - bar_h, max(1, int(bar_w) - 1), bar_h, 1, 1
            )
            # Lower half (mirror)
            painter.drawRoundedRect(
                int(x), mid, max(1, int(bar_w) - 1), bar_h, 1, 1
            )

    def _paint_loading(self, painter: QPainter, w: int, h: int, mid: int) -> None:
        """Draw animated pulsing bars while waveform is loading."""
        num_bars = 20
        bar_w = w / num_bars
        painter.setPen(Qt.NoPen)

        for i in range(num_bars):
            phase = (i + self._pulse_offset) % num_bars
            amplitude = 0.3 + 0.7 * abs(np.sin(phase * np.pi / num_bars))
            bar_h = int(amplitude * (mid - 8))
            x = int(i * bar_w)
            alpha = int(100 + 155 * amplitude)
            color = QColor(COLORS["accent"])
            color.setAlpha(alpha)
            painter.setBrush(color)
            painter.drawRoundedRect(x + 1, mid - bar_h, int(bar_w) - 2, bar_h * 2, 2, 2)

    def _paint_placeholder(self, painter: QPainter, w: int, h: int, mid: int) -> None:
        """Draw a flat baseline when no audio is loaded."""
        painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.DashLine))
        painter.drawLine(8, mid, w - 8, mid)
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRect(0, 0, w, h), Qt.AlignCenter, "No audio loaded"
        )


# ─────────────────────────────────────────────────────────────────────────────
# HistoryListWidget
# ─────────────────────────────────────────────────────────────────────────────

class HistoryListWidget(QFrame):
    """
    Displays a list of recently generated audio files.

    Each item shows: filename, text preview, language, duration.
    Double-clicking an item emits `play_requested` with the file path.

    Signals:
        play_requested(str): Emitted when user wants to play a history item.
        save_requested(str): Emitted when user wants to save/export a history item.
    """

    play_requested = Signal(str)
    save_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {COLORS['border']};"
        )
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(12, 0, 12, 0)

        title = QLabel("📜 Recent Generations")
        title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {COLORS['text_secondary']};"
            "letter-spacing: 0.5px;"
        )

        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("class", "icon-btn")
        clear_btn.setFixedWidth(50)
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']};")
        clear_btn.clicked.connect(self.clear_history)

        hdr_layout.addWidget(title)
        hdr_layout.addStretch()
        hdr_layout.addWidget(clear_btn)

        # List
        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)

        # Placeholder
        self._placeholder = QLabel("No audio generated yet.\nGenerate speech to see history.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; padding: 20px;"
        )

        layout.addWidget(header)
        layout.addWidget(self._list)
        layout.addWidget(self._placeholder)
        self._list.hide()

    def add_item(
        self,
        file_path: str,
        text_preview: str,
        language: str,
        duration: float,
        timestamp: str,
    ) -> None:
        """Add a new item to the history list."""
        self._placeholder.hide()
        self._list.show()

        filename = Path(file_path).name
        duration_str = f"{duration:.1f}s"
        lang_flags = {"en": "🇬🇧", "te": "🇮🇳", "hi": "🇮🇳"}
        flag = lang_flags.get(language, "🌐")

        display = f"{flag}  {filename}\n  {text_preview[:45]}…  •  {duration_str}  •  {timestamp}"

        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, file_path)
        item.setToolTip(f"File: {file_path}\nText: {text_preview}\nDuration: {duration_str}")

        # Insert at top
        self._list.insertItem(0, item)

    def clear_history(self) -> None:
        """Remove all items from the history display."""
        self._list.clear()
        self._list.hide()
        self._placeholder.show()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path and Path(path).exists():
            self.play_requested.emit(path)

    def _show_context_menu(self, pos: QPoint) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._list.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.UserRole)

        menu = QMenu(self)
        play_action = menu.addAction("▶  Play")
        save_action = menu.addAction("💾  Save As …")
        menu.addSeparator()
        open_folder_action = menu.addAction("📂  Open in Explorer")
        remove_action = menu.addAction("🗑  Remove from list")

        action = menu.exec(self._list.mapToGlobal(pos))

        if action == play_action and path:
            self.play_requested.emit(path)
        elif action == save_action and path:
            self.save_requested.emit(path)
        elif action == open_folder_action and path:
            import subprocess
            subprocess.Popen(["explorer", "/select,", path])
        elif action == remove_action:
            row = self._list.row(item)
            self._list.takeItem(row)
            if self._list.count() == 0:
                self._list.hide()
                self._placeholder.show()


# ─────────────────────────────────────────────────────────────────────────────
# AnimatedLabel (status message)
# ─────────────────────────────────────────────────────────────────────────────

class AnimatedLabel(QLabel):
    """
    A QLabel that fades in/out on text updates and supports status icons.

    Usage:
        label = AnimatedLabel()
        label.set_status("Generating speech …", "info")
        label.set_status("Done!", "success")
        label.set_status("Error: …", "error")
    """

    STATUS_STYLES = {
        "info":    ("ℹ️  ", COLORS["text_secondary"]),
        "success": ("✅  ", COLORS["success"]),
        "warning": ("⚠️  ", COLORS["warning"]),
        "error":   ("❌  ", COLORS["error"]),
        "loading": ("⏳  ", COLORS["cyan"]),
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("font-size: 12px; padding: 4px 0;")
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def set_status(self, message: str, level: str = "info") -> None:
        """
        Update the displayed status message with an icon prefix.

        Args:
            message: The status text to display.
            level:   One of "info", "success", "warning", "error", "loading".
        """
        icon, color = self.STATUS_STYLES.get(level, ("", COLORS["text_secondary"]))
        self.setText(f"{icon}{message}")
        self.setStyleSheet(
            f"font-size: 12px; color: {color}; padding: 4px 0; background: transparent;"
        )

    def clear_status(self) -> None:
        """Clear the status message."""
        self.setText("")


# ─────────────────────────────────────────────────────────────────────────────
# DeviceBadge
# ─────────────────────────────────────────────────────────────────────────────

class DeviceBadge(QLabel):
    """
    A small badge widget that shows whether the app is running on GPU or CPU.
    Displayed in the application header.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(24)
        self.set_loading()

    def set_gpu(self, gpu_name: str = "") -> None:
        short = gpu_name.replace("NVIDIA ", "").split("(")[0].strip()
        short = short[:20] if len(short) > 20 else short
        self.setText(f"⚡ GPU: {short}" if short else "⚡ GPU")
        self.setProperty("class", "badge-gpu")
        self._refresh()

    def set_cpu(self) -> None:
        self.setText("🖥️ CPU Mode")
        self.setProperty("class", "badge-cpu")
        self._refresh()

    def set_loading(self) -> None:
        self.setText("⏳ Loading model …")
        self.setProperty("class", "badge-loading")
        self._refresh()

    def _refresh(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
