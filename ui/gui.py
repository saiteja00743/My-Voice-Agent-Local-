"""
ui/gui.py
---------
Main application window for the Offline AI Voice Clone application.

This module defines:
  - ModelLoaderThread  : QThread that loads XTTS-v2 in the background
  - GenerationThread   : QThread that runs TTS generation off the UI thread
  - PlaybackThread     : QThread for non-blocking audio playback
  - MainWindow         : The primary QMainWindow with all panels and logic

Layout overview:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ HEADER: Title | Device Badge | Version                             │
  ├──────────────┬──────────────────────────────────┬──────────────────┤
  │ LEFT PANEL   │ CENTER PANEL                     │ RIGHT PANEL      │
  │ DropZone     │ QTextEdit (input)                │ Waveform preview │
  │ Voice Info   │ Char/word count                  │ History list     │
  │ Language     │ Progress bar + status            │                  │
  │ Settings     │                                  │                  │
  ├──────────────┴──────────────────────────────────┴──────────────────┤
  │ TOOLBAR: [Generate]  [Play] [Stop] [Save As]  [Copy] | [Open Dir] │
  └─────────────────────────────────────────────────────────────────────┘

Keyboard shortcuts:
  Ctrl+G  — Generate
  Space   — Play / Pause
  Ctrl+S  — Save As
  Ctrl+O  — Open voice file
  Ctrl+L  — Clear text
  Escape  — Stop playback
  F1      — Show about dialog
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt,
    QThread,
    Signal,
    QTimer,
    QSize,
    QSettings,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QFont,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config.settings import (
    APP_CONFIG,
    OUTPUTS_DIR,
    PRIMARY_LANGUAGES,
    SUPPORTED_LANGUAGES,
    UserPrefs,
    detect_device,
    get_device_info,
    load_prefs,
    save_prefs,
)
from core.tts_engine import TTSEngine
from core.voice_clone import VoiceCloner
from ui.components import (
    AnimatedLabel,
    AudioWaveformWidget,
    DeviceBadge,
    DropZoneWidget,
    HistoryListWidget,
)
from ui.styles import COLORS
from utils.logger import setup_logger

log = setup_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Background Worker Threads
# ─────────────────────────────────────────────────────────────────────────────

class ModelLoaderThread(QThread):
    """
    Loads the XTTS-v2 model in the background.
    Emits progress updates for the progress bar and status label.
    """

    progress = Signal(int, str)   # (percent, message)
    finished = Signal()
    error = Signal(str)

    def __init__(self, engine: TTSEngine) -> None:
        super().__init__()
        self._engine = engine

    def run(self) -> None:
        try:
            self._engine.load_model(progress_callback=self.progress.emit)
            self.finished.emit()
        except Exception as exc:
            log.error("Model loading failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class ReferenceLoaderThread(QThread):
    """
    Preprocesses the reference audio file in the background.
    """

    progress = Signal(int, str)
    finished = Signal(object)  # ReferenceAudioInfo
    error = Signal(str)

    def __init__(self, cloner: VoiceCloner, path: str) -> None:
        super().__init__()
        self._cloner = cloner
        self._path = path

    def run(self) -> None:
        try:
            info = self._cloner.set_reference_audio(
                self._path,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(info)
        except Exception as exc:
            log.error("Reference audio loading failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class GenerationThread(QThread):
    """
    Runs TTS generation in a background thread to keep the UI responsive.
    """

    progress = Signal(int, str)
    finished = Signal(str)  # output file path
    error = Signal(str)

    def __init__(
        self,
        cloner: VoiceCloner,
        text: str,
        language: str,
        temperature: float = 0.1,
        top_p: float = 0.85,
        repetition_penalty: float = 10.0,
        speed: float = 1.0,
    ) -> None:
        super().__init__()
        self._cloner = cloner
        self._text = text
        self._language = language
        self._temperature = temperature
        self._top_p = top_p
        self._repetition_penalty = repetition_penalty
        self._speed = speed

    def run(self) -> None:
        try:
            output_path = self._cloner.generate_speech(
                text=self._text,
                language=self._language,
                progress_callback=self.progress.emit,
                temperature=self._temperature,
                top_p=self._top_p,
                repetition_penalty=self._repetition_penalty,
                speed=self._speed,
            )
            self.finished.emit(str(output_path))
        except Exception as exc:
            log.error("Generation failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class PlaybackThread(QThread):
    """
    Plays an audio file in a background thread using sounddevice.
    """

    finished = Signal()
    error = Signal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._path = file_path
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
            import soundfile as sf    # type: ignore

            data, sr = sf.read(self._path, dtype="float32")
            # Play in blocks so stop requests are honoured quickly
            block_size = sr // 10  # 100 ms blocks
            stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
            stream.start()

            offset = 0
            while offset < len(data) and not self._stop:
                block = data[offset : offset + block_size]
                if len(block) == 0:
                    break
                stream.write(block)
                offset += block_size

            stream.stop()
            stream.close()
            self.finished.emit()

        except Exception as exc:
            log.error("Playback error: %s", exc, exc_info=True)
            # Fallback: try pygame
            try:
                import pygame  # type: ignore
                pygame.mixer.init()
                pygame.mixer.music.load(self._path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not self._stop:
                    import time
                    time.sleep(0.05)
                pygame.mixer.music.stop()
                self.finished.emit()
            except Exception as exc2:
                self.error.emit(f"Playback failed: {exc2}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """
    Primary application window for the Offline AI Voice Clone app.

    Manages:
      - Model loading lifecycle
      - Reference audio loading
      - TTS generation lifecycle
      - Audio playback
      - User preferences persistence
      - Keyboard shortcuts
      - Menu bar
    """

    def __init__(self) -> None:
        super().__init__()

        # ── Core objects ───────────────────────────────────────────────────
        self._prefs: UserPrefs = load_prefs()
        self._device: str = detect_device()
        self._device_info: dict = get_device_info()

        self._engine: TTSEngine = TTSEngine(device=self._device)
        self._cloner: VoiceCloner = VoiceCloner(
            engine=self._engine,
            normalize=self._prefs.normalize_audio,
            trim_silence=self._prefs.trim_silence,
        )

        # Thread handles
        self._model_thread: Optional[ModelLoaderThread] = None
        self._ref_thread: Optional[ReferenceLoaderThread] = None
        self._gen_thread: Optional[GenerationThread] = None
        self._play_thread: Optional[PlaybackThread] = None

        # State
        self._last_output_path: Optional[str] = None
        self._model_loaded: bool = False

        # ── Build UI ──────────────────────────────────────────────────────
        self._build_window()
        self._build_menu()
        self._build_shortcuts()
        self._apply_initial_state()

        # ── Start model loading immediately ───────────────────────────────
        QTimer.singleShot(300, self._start_model_loading)

        log.info("MainWindow initialised (device=%s)", self._device)

    # ══════════════════════════════════════════════════════════════════════
    # UI Construction
    # ══════════════════════════════════════════════════════════════════════

    def _build_window(self) -> None:
        """Set up window properties and build all panels."""
        self.setWindowTitle(f"{APP_CONFIG.app_name} v{APP_CONFIG.app_version}")
        self.setMinimumSize(APP_CONFIG.window_min_width, APP_CONFIG.window_min_height)
        self.resize(1280, 800)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Build sections
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._build_model_banner(), 0)
        root_layout.addWidget(self._build_content_area(), 1)
        root_layout.addWidget(self._build_bottom_toolbar())

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_msg = QLabel("Ready")
        self._status_device = QLabel("")
        self._status_bar.addWidget(self._status_msg, 1)
        self._status_bar.addPermanentWidget(self._status_device)
        self._update_status_device()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setProperty("class", "header")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        # App icon + title
        icon_label = QLabel("🎙️")
        icon_label.setStyleSheet("font-size: 28px; background: transparent;")

        title = QLabel(APP_CONFIG.app_name)
        title.setProperty("class", "title")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {COLORS['text_primary']};"
            "background: transparent; margin-left: 4px;"
        )

        subtitle = QLabel(f"v{APP_CONFIG.app_version}")
        subtitle.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_secondary']};"
            "background: transparent; margin-left: 6px; margin-top: 6px;"
        )

        # Device badge
        self._device_badge = DeviceBadge()

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # About button
        about_btn = QPushButton("?")
        about_btn.setFixedSize(28, 28)
        about_btn.setProperty("class", "icon-btn")
        about_btn.setToolTip("About")
        about_btn.clicked.connect(self._show_about)

        layout.addWidget(icon_label)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(16)
        layout.addWidget(self._device_badge)
        layout.addWidget(spacer)
        layout.addWidget(about_btn)

        return header

    # ── Model loading banner ──────────────────────────────────────────────

    def _build_model_banner(self) -> QFrame:
        """
        A collapsible info banner shown while the model is loading.
        Hidden once the model is ready.
        """
        self._model_banner = QFrame()
        self._model_banner.setStyleSheet(
            f"background-color: rgba(124, 58, 237, 0.12);"
            f"border-bottom: 1px solid rgba(124, 58, 237, 0.3);"
        )
        self._model_banner.setFixedHeight(48)

        layout = QHBoxLayout(self._model_banner)
        layout.setContentsMargins(20, 0, 20, 0)

        self._banner_icon = QLabel("⏳")
        self._banner_icon.setStyleSheet("font-size: 16px; background: transparent;")

        self._banner_text = QLabel(
            "Loading XTTS-v2 model … (first run downloads ~1.8 GB)"
        )
        self._banner_text.setStyleSheet(
            f"color: {COLORS['accent_light']}; font-size: 13px;"
            "font-weight: 500; background: transparent;"
        )

        self._banner_progress = QProgressBar()
        self._banner_progress.setRange(0, 100)
        self._banner_progress.setValue(0)
        self._banner_progress.setFixedWidth(200)
        self._banner_progress.setFixedHeight(6)

        layout.addWidget(self._banner_icon)
        layout.addWidget(self._banner_text)
        layout.addStretch()
        layout.addWidget(self._banner_progress)

        return self._model_banner

    # ── Content area (3-column splitter) ─────────────────────────────────

    def _build_content_area(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)

        return splitter

    # ── Left panel ────────────────────────────────────────────────────────

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 8, 16)
        layout.setSpacing(16)

        # ---- Voice File Section ----
        voice_section_label = QLabel("VOICE FILE")
        voice_section_label.setProperty("class", "section-header")

        self._drop_zone = DropZoneWidget()
        self._drop_zone.file_selected.connect(self._on_voice_file_selected)

        # Voice file info card
        self._voice_info_card = QFrame()
        self._voice_info_card.setProperty("class", "card")
        self._voice_info_card.setVisible(False)
        info_layout = QVBoxLayout(self._voice_info_card)
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(12, 10, 12, 10)

        self._info_duration = self._make_info_row("Duration:", "—")
        self._info_samplerate = self._make_info_row("Sample Rate:", "—")
        self._info_quality = self._make_info_row("Quality:", "—")

        info_layout.addLayout(self._info_duration[0])
        info_layout.addLayout(self._info_samplerate[0])
        info_layout.addLayout(self._info_quality[0])

        # ---- Language Section ----
        lang_section_label = QLabel("LANGUAGE")
        lang_section_label.setProperty("class", "section-header")

        self._lang_combo = QComboBox()
        self._lang_combo.setToolTip("Select the language of the text to synthesise")

        # Add primary languages first
        for name in PRIMARY_LANGUAGES:
            code = SUPPORTED_LANGUAGES[name]
            self._lang_combo.addItem(name, code)

        # Separator-like item
        self._lang_combo.insertSeparator(len(PRIMARY_LANGUAGES))

        # Add remaining languages alphabetically
        for name, code in sorted(SUPPORTED_LANGUAGES.items()):
            if name not in PRIMARY_LANGUAGES:
                self._lang_combo.addItem(name, code)

        # Restore last used language
        last_lang_code = self._prefs.last_language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == last_lang_code:
                self._lang_combo.setCurrentIndex(i)
                break

        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)

        # ---- Settings ----
        settings_section_label = QLabel("AUDIO SETTINGS")
        settings_section_label.setProperty("class", "section-header")

        self._normalize_cb = QCheckBox("Normalize audio")
        self._normalize_cb.setChecked(self._prefs.normalize_audio)
        self._normalize_cb.toggled.connect(self._on_settings_changed)

        self._trim_silence_cb = QCheckBox("Trim silence")
        self._trim_silence_cb.setChecked(self._prefs.trim_silence)
        self._trim_silence_cb.toggled.connect(self._on_settings_changed)

        self._autoplay_cb = QCheckBox("Auto-play after generate")
        self._autoplay_cb.setChecked(self._prefs.auto_play_after_generate)
        self._autoplay_cb.toggled.connect(self._on_settings_changed)

        # ---- Voice Quality Section ----
        quality_section_label = QLabel("VOICE QUALITY")
        quality_section_label.setProperty("class", "section-header")

        # Temperature slider — the single biggest lever for voice similarity
        temp_row = QHBoxLayout()
        temp_label = QLabel("Similarity:")
        temp_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        self._temp_value_label = QLabel("High")
        self._temp_value_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['accent_light']}; "
            "font-weight: 600; background: transparent; min-width: 36px;"
        )
        temp_row.addWidget(temp_label)
        temp_row.addStretch()
        temp_row.addWidget(self._temp_value_label)

        # Slider: 1 (temp=0.01, max similarity) → 10 (temp=1.0, creative)
        self._temp_slider = QSlider(Qt.Horizontal)
        self._temp_slider.setRange(1, 10)
        self._temp_slider.setValue(1)          # Default: maximum voice similarity
        self._temp_slider.setTickInterval(1)
        self._temp_slider.setToolTip(
            "Higher = more creative but less like your voice.\n"
            "Lower = more faithful to your exact voice."
        )
        self._temp_slider.valueChanged.connect(self._on_temp_changed)

        slider_hints = QHBoxLayout()
        hint_low = QLabel("🎯 Exact voice")
        hint_low.setStyleSheet(
            f"font-size: 9px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        hint_high = QLabel("Creative 🎨")
        hint_high.setStyleSheet(
            f"font-size: 9px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        slider_hints.addWidget(hint_low)
        slider_hints.addStretch()
        slider_hints.addWidget(hint_high)

        # Voice tips button
        tips_btn = QPushButton("🎙  How to get your exact voice")
        tips_btn.setProperty("class", "icon-btn")
        tips_btn.setFixedHeight(32)
        tips_btn.setToolTip("Tips for recording the perfect voice sample")
        tips_btn.clicked.connect(self._show_voice_tips)

        # Assemble
        layout.addWidget(voice_section_label)
        layout.addWidget(self._drop_zone)
        layout.addWidget(self._voice_info_card)
        layout.addWidget(lang_section_label)
        layout.addWidget(self._lang_combo)
        layout.addWidget(settings_section_label)
        layout.addWidget(self._normalize_cb)
        layout.addWidget(self._trim_silence_cb)
        layout.addWidget(self._autoplay_cb)
        layout.addWidget(quality_section_label)
        layout.addLayout(temp_row)
        layout.addWidget(self._temp_slider)
        layout.addLayout(slider_hints)
        layout.addSpacing(4)
        layout.addWidget(tips_btn)
        layout.addStretch()

        return panel

    def _make_info_row(
        self, label_text: str, value_text: str
    ) -> tuple[QHBoxLayout, QLabel]:
        """Create a key–value info row for the voice info card."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        key = QLabel(label_text)
        key.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        val = QLabel(value_text)
        val.setProperty("class", "info-value")
        val.setStyleSheet(
            f"font-size: 11px; color: {COLORS['accent_light']}; background: transparent;"
        )
        row.addWidget(key)
        row.addStretch()
        row.addWidget(val)
        return row, val

    # ── Center panel ──────────────────────────────────────────────────────

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(12)

        # ---- Section label ----
        text_label = QLabel("TEXT INPUT")
        text_label.setProperty("class", "section-header")

        # ---- Top toolbar (copy, clear) ----
        text_tools = QFrame()
        text_tools.setStyleSheet("background: transparent;")
        tt_layout = QHBoxLayout(text_tools)
        tt_layout.setContentsMargins(0, 0, 0, 0)
        tt_layout.setSpacing(8)

        tt_layout.addWidget(text_label)
        tt_layout.addStretch()

        copy_btn = QPushButton("📋 Copy")
        copy_btn.setProperty("class", "icon-btn")
        copy_btn.setToolTip("Copy text to clipboard (Ctrl+C)")
        copy_btn.setFixedHeight(28)
        copy_btn.clicked.connect(self._copy_text)

        clear_btn = QPushButton("🗑 Clear")
        clear_btn.setProperty("class", "icon-btn")
        clear_btn.setToolTip("Clear text input (Ctrl+L)")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._clear_text)

        tt_layout.addWidget(copy_btn)
        tt_layout.addWidget(clear_btn)

        # ---- Text input ----
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText(
            "Type or paste the text you want to hear in your cloned voice …\n\n"
            "Tip: For best results, keep paragraphs under 500 words.\n"
            "Long texts are automatically split into sentence chunks."
        )
        self._text_edit.textChanged.connect(self._on_text_changed)
        self._text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ---- Word count ----
        self._word_count_label = QLabel("0 words  •  0 characters")
        self._word_count_label.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        self._word_count_label.setAlignment(Qt.AlignRight)

        # ---- Progress ----
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)

        # ---- Status ----
        self._status_label = AnimatedLabel()
        self._status_label.set_status(
            "Select a voice file and type your text to get started.", "info"
        )

        # Assemble
        layout.addWidget(text_tools)
        layout.addWidget(self._text_edit, 1)
        layout.addWidget(self._word_count_label)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)

        return panel

    # ── Right panel ───────────────────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 16, 16, 16)
        layout.setSpacing(12)

        # ---- Waveform preview ----
        wave_label = QLabel("LAST OUTPUT")
        wave_label.setProperty("class", "section-header")

        self._waveform = AudioWaveformWidget()
        self._waveform.setStyleSheet(
            f"background-color: {COLORS['bg_surface']}; border-radius: 8px;"
        )

        # Output file info
        self._output_info = QLabel("No audio generated yet")
        self._output_info.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_secondary']}; background: transparent;"
        )
        self._output_info.setAlignment(Qt.AlignCenter)

        # ---- History ----
        self._history_widget = HistoryListWidget()
        self._history_widget.play_requested.connect(self._play_audio_file)
        self._history_widget.save_requested.connect(self._save_audio_as)

        # Assemble
        layout.addWidget(wave_label)
        layout.addWidget(self._waveform)
        layout.addWidget(self._output_info)
        layout.addSpacing(8)
        layout.addWidget(self._history_widget, 1)

        return panel

    # ── Bottom toolbar ────────────────────────────────────────────────────

    def _build_bottom_toolbar(self) -> QToolBar:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))

        # Generate button (primary CTA)
        self._generate_btn = QPushButton("⚡  Generate Speech")
        self._generate_btn.setProperty("class", "primary")
        self._generate_btn.setToolTip("Generate speech in your cloned voice (Ctrl+G)")
        self._generate_btn.setFixedHeight(44)
        self._generate_btn.setMinimumWidth(200)
        self._generate_btn.clicked.connect(self._on_generate_clicked)

        # Play button
        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setProperty("class", "success")
        self._play_btn.setToolTip("Play last generated audio (Space)")
        self._play_btn.setFixedHeight(44)
        self._play_btn.setMinimumWidth(120)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._on_play_clicked)

        # Stop button
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setProperty("class", "danger")
        self._stop_btn.setToolTip("Stop playback (Esc)")
        self._stop_btn.setFixedHeight(44)
        self._stop_btn.setMinimumWidth(100)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)

        # Save As button
        self._save_btn = QPushButton("💾  Save As …")
        self._save_btn.setProperty("class", "default")
        self._save_btn.setToolTip("Save generated audio to a custom location (Ctrl+S)")
        self._save_btn.setFixedHeight(44)
        self._save_btn.setMinimumWidth(130)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_clicked)

        # Open outputs folder
        open_dir_btn = QPushButton("📂  Outputs")
        open_dir_btn.setProperty("class", "icon-btn")
        open_dir_btn.setToolTip("Open the outputs folder in Explorer")
        open_dir_btn.setFixedHeight(44)
        open_dir_btn.clicked.connect(self._open_outputs_folder)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        toolbar.addWidget(self._generate_btn)
        toolbar.addSeparator()
        toolbar.addWidget(self._play_btn)
        toolbar.addWidget(self._stop_btn)
        toolbar.addSeparator()
        toolbar.addWidget(self._save_btn)
        toolbar.addWidget(spacer)
        toolbar.addWidget(open_dir_btn)

        return toolbar

    # ── Menu bar ──────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        open_voice_action = QAction("Open Voice File …", self)
        open_voice_action.setShortcut(QKeySequence("Ctrl+O"))
        open_voice_action.triggered.connect(self._open_voice_file_dialog)
        file_menu.addAction(open_voice_action)

        file_menu.addSeparator()

        save_action = QAction("Save Audio As …", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self._on_save_clicked)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        open_outputs_action = QAction("Open Outputs Folder", self)
        open_outputs_action.triggered.connect(self._open_outputs_folder)
        file_menu.addAction(open_outputs_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Edit menu
        edit_menu = menubar.addMenu("Edit")

        clear_action = QAction("Clear Text", self)
        clear_action.setShortcut(QKeySequence("Ctrl+L"))
        clear_action.triggered.connect(self._clear_text)
        edit_menu.addAction(clear_action)

        copy_action = QAction("Copy Text", self)
        copy_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy_action.triggered.connect(self._copy_text)
        edit_menu.addAction(copy_action)

        # Generate menu
        gen_menu = menubar.addMenu("Generate")

        generate_action = QAction("Generate Speech", self)
        generate_action.setShortcut(QKeySequence("Ctrl+G"))
        generate_action.triggered.connect(self._on_generate_clicked)
        gen_menu.addAction(generate_action)

        # Help menu
        help_menu = menubar.addMenu("Help")

        tips_action = QAction("🎙  How to Get Your Exact Voice", self)
        tips_action.setShortcut(QKeySequence("F2"))
        tips_action.triggered.connect(self._show_voice_tips)
        help_menu.addAction(tips_action)

        help_menu.addSeparator()

        about_action = QAction("About …", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ── Keyboard shortcuts ────────────────────────────────────────────────

    def _build_shortcuts(self) -> None:
        # Space = play/pause
        QShortcut(QKeySequence("Space"), self, self._on_play_clicked)
        # Escape = stop
        QShortcut(QKeySequence("Escape"), self, self._on_stop_clicked)

    # ── Initial state ─────────────────────────────────────────────────────

    def _apply_initial_state(self) -> None:
        """Restore last used voice file if it still exists."""
        if self._prefs.last_voice_file:
            p = Path(self._prefs.last_voice_file)
            if p.exists():
                QTimer.singleShot(500, lambda: self._on_voice_file_selected(str(p)))

    # ══════════════════════════════════════════════════════════════════════
    # Model Loading
    # ══════════════════════════════════════════════════════════════════════

    def _start_model_loading(self) -> None:
        """Start the background model loading thread."""
        log.info("Starting model loader thread …")
        self._model_thread = ModelLoaderThread(self._engine)
        self._model_thread.progress.connect(self._on_model_progress)
        self._model_thread.finished.connect(self._on_model_loaded)
        self._model_thread.error.connect(self._on_model_error)
        self._model_thread.start()

    def _on_model_progress(self, percent: int, message: str) -> None:
        self._banner_progress.setValue(percent)
        self._banner_text.setText(f"Loading XTTS-v2 … {message}")
        self._status_msg.setText(f"⏳ {message}")

    def _on_model_loaded(self) -> None:
        self._model_loaded = True
        self._model_banner.setVisible(False)

        # Update device badge
        info = self._engine.get_model_info()
        if info["device"] == "cuda":
            self._device_badge.set_gpu(info.get("gpu_name", ""))
        else:
            self._device_badge.set_cpu()

        self._status_label.set_status("Model ready! Select a voice file to begin.", "success")
        self._status_msg.setText("✅ XTTS-v2 model loaded and ready")
        self._update_generate_btn_state()

        log.info("Model loaded — UI updated to ready state")

    def _on_model_error(self, error: str) -> None:
        self._model_banner.setStyleSheet(
            "background-color: rgba(239, 68, 68, 0.1);"
            "border-bottom: 1px solid rgba(239, 68, 68, 0.3);"
        )
        self._banner_icon.setText("❌")
        self._banner_text.setText(f"Model loading failed: {error}")
        self._banner_text.setStyleSheet(f"color: {COLORS['error']}; font-size: 12px;")
        self._status_label.set_status(f"Model error: {error}", "error")
        log.error("Model loading error shown in UI: %s", error)

    # ══════════════════════════════════════════════════════════════════════
    # Voice File
    # ══════════════════════════════════════════════════════════════════════

    def _open_voice_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Your Voice Recording",
            str(Path.home()),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a);;All Files (*)",
        )
        if path:
            self._on_voice_file_selected(path)

    def _on_voice_file_selected(self, path: str) -> None:
        """Called when user selects a voice file via drag-drop or browser."""
        log.info("Voice file selected: %s", path)
        self._status_label.set_status(f"Loading voice file: {Path(path).name} …", "loading")
        self._progress_bar.setValue(0)
        self._generate_btn.setEnabled(False)

        self._ref_thread = ReferenceLoaderThread(self._cloner, path)
        self._ref_thread.progress.connect(self._on_ref_progress)
        self._ref_thread.finished.connect(self._on_ref_loaded)
        self._ref_thread.error.connect(self._on_ref_error)
        self._ref_thread.start()

    def _on_ref_progress(self, percent: int, message: str) -> None:
        self._progress_bar.setValue(percent)
        self._status_label.set_status(message, "loading")

    def _on_ref_loaded(self, info) -> None:
        self._progress_bar.setValue(100)
        self._drop_zone.set_loaded(info.original_path.name)

        # Update info card
        self._info_duration[1].setText(info.duration_formatted)
        self._info_samplerate[1].setText(f"{info.sample_rate:,} Hz")
        self._info_quality[1].setText(info.quality_rating)
        self._voice_info_card.setVisible(True)

        # Save preference
        self._prefs.last_voice_file = str(info.original_path)
        save_prefs(self._prefs)

        self._status_label.set_status(
            f"Voice loaded: {info.original_path.name} ({info.duration_formatted})",
            "success",
        )
        self._progress_bar.setValue(0)
        self._update_generate_btn_state()

        # Show waveform of reference audio
        self._waveform.set_audio_file(str(info.processed_path))
        self._output_info.setText(
            f"Reference: {info.original_path.name}  •  {info.duration_formatted}"
        )

        log.info("Reference audio info displayed in UI")

    def _on_ref_error(self, error: str) -> None:
        self._progress_bar.setValue(0)
        self._status_label.set_status(f"Voice file error: {error}", "error")
        self._drop_zone.set_idle()
        self._voice_info_card.setVisible(False)
        QMessageBox.warning(self, "Voice File Error", error)

    # ══════════════════════════════════════════════════════════════════════
    # Speech Generation
    # ══════════════════════════════════════════════════════════════════════

    def _on_generate_clicked(self) -> None:
        """User clicked Generate or pressed Ctrl+G."""
        text = self._text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty Text", "Please enter some text to generate speech.")
            return

        if not self._cloner.has_reference:
            QMessageBox.warning(
                self, "No Voice File",
                "Please select a voice recording file before generating speech."
            )
            return

        if not self._model_loaded:
            QMessageBox.information(
                self, "Model Loading",
                "The XTTS-v2 model is still loading. Please wait a moment."
            )
            return

        language = self._lang_combo.currentData() or "en"
        log.info("Generate clicked: lang=%s, text_len=%d", language, len(text))

        # UI state: generating
        self._generate_btn.setEnabled(False)
        self._generate_btn.setText("⏳  Generating …")
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._progress_bar.setValue(5)
        self._status_label.set_status("Starting speech generation …", "loading")

        # Read quality params from UI
        temperature = self._slider_to_temperature(self._temp_slider.value())

        # Launch generation thread
        self._gen_thread = GenerationThread(
            self._cloner, text, language,
            temperature=temperature,
            top_p=0.85,
            repetition_penalty=10.0,
            speed=1.0,
        )
        self._gen_thread.progress.connect(self._on_gen_progress)
        self._gen_thread.finished.connect(self._on_gen_finished)
        self._gen_thread.error.connect(self._on_gen_error)
        self._gen_thread.start()

    def _on_gen_progress(self, percent: int, message: str) -> None:
        self._progress_bar.setValue(percent)
        self._status_label.set_status(message, "loading")

    def _on_gen_finished(self, output_path: str) -> None:
        self._last_output_path = output_path
        self._progress_bar.setValue(100)

        fname = Path(output_path).name
        self._status_label.set_status(f"Generated: {fname}", "success")
        self._status_msg.setText(f"✅ Saved: {output_path}")

        # Re-enable buttons
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText("⚡  Generate Speech")
        self._play_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

        # Update waveform + info
        self._waveform.set_audio_file(output_path)
        self._output_info.setText(f"📄 {fname}")

        # Add to history
        text = self._text_edit.toPlainText().strip()
        language = self._lang_combo.currentData() or "en"
        lang_name = self._lang_combo.currentText()
        from datetime import datetime
        self._history_widget.add_item(
            file_path=output_path,
            text_preview=text[:60],
            language=language,
            duration=self._get_audio_duration(output_path),
            timestamp=datetime.now().strftime("%H:%M:%S"),
        )

        # Also update cloner history
        for record in self._cloner.history:
            pass  # Already tracked in cloner

        # Auto-play
        if self._prefs.auto_play_after_generate:
            QTimer.singleShot(200, lambda: self._play_audio_file(output_path))

        QTimer.singleShot(3000, lambda: self._progress_bar.setValue(0))
        log.info("Generation finished, UI updated: %s", output_path)

    def _on_gen_error(self, error: str) -> None:
        self._progress_bar.setValue(0)
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText("⚡  Generate Speech")
        self._status_label.set_status(f"Error: {error}", "error")
        QMessageBox.critical(self, "Generation Error", f"Speech generation failed:\n\n{error}")

    def _get_audio_duration(self, path: str) -> float:
        try:
            import soundfile as sf  # type: ignore
            with sf.SoundFile(path) as f:
                return f.frames / f.samplerate
        except Exception:
            return 0.0

    # ══════════════════════════════════════════════════════════════════════
    # Playback
    # ══════════════════════════════════════════════════════════════════════

    def _on_play_clicked(self) -> None:
        if self._last_output_path:
            self._play_audio_file(self._last_output_path)

    def _play_audio_file(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(self, "File Not Found", f"Audio file not found:\n{path}")
            return

        # Stop any existing playback
        if self._play_thread and self._play_thread.isRunning():
            self._play_thread.request_stop()
            self._play_thread.wait(500)

        self._play_btn.setText("🔊  Playing …")
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.set_status(f"Playing: {Path(path).name}", "info")

        self._play_thread = PlaybackThread(path)
        self._play_thread.finished.connect(self._on_playback_finished)
        self._play_thread.error.connect(self._on_playback_error)
        self._play_thread.start()

    def _on_stop_clicked(self) -> None:
        if self._play_thread and self._play_thread.isRunning():
            self._play_thread.request_stop()
        self._on_playback_finished()

    def _on_playback_finished(self) -> None:
        self._play_btn.setText("▶  Play")
        self._play_btn.setEnabled(self._last_output_path is not None)
        self._stop_btn.setEnabled(False)
        self._status_label.set_status("Playback complete.", "info")

    def _on_playback_error(self, error: str) -> None:
        self._on_playback_finished()
        self._status_label.set_status(f"Playback error: {error}", "error")

    # ══════════════════════════════════════════════════════════════════════
    # Save
    # ══════════════════════════════════════════════════════════════════════

    def _on_save_clicked(self) -> None:
        if self._last_output_path:
            self._save_audio_as(self._last_output_path)

    def _save_audio_as(self, source_path: str) -> None:
        default_dir = self._prefs.last_output_dir or str(Path.home() / "Desktop")
        default_name = Path(source_path).name

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Audio File",
            os.path.join(default_dir, default_name),
            "WAV Audio (*.wav);;All Files (*)",
        )
        if not dest_path:
            return

        try:
            shutil.copy2(source_path, dest_path)
            self._prefs.last_output_dir = str(Path(dest_path).parent)
            save_prefs(self._prefs)
            self._status_label.set_status(f"Saved to: {dest_path}", "success")
            log.info("File saved to: %s", dest_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{exc}")

    def _open_outputs_folder(self) -> None:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(OUTPUTS_DIR)])

    # ══════════════════════════════════════════════════════════════════════
    # Settings & Text Events
    # ══════════════════════════════════════════════════════════════════════

    def _on_text_changed(self) -> None:
        text = self._text_edit.toPlainText()
        words = len(text.split()) if text.strip() else 0
        self._word_count_label.setText(f"{words} words  •  {len(text)} characters")

    def _on_language_changed(self, _index: int) -> None:
        lang_code = self._lang_combo.currentData()
        self._prefs.last_language = lang_code or "en"
        save_prefs(self._prefs)

    def _on_settings_changed(self) -> None:
        self._prefs.normalize_audio = self._normalize_cb.isChecked()
        self._prefs.trim_silence = self._trim_silence_cb.isChecked()
        self._prefs.auto_play_after_generate = self._autoplay_cb.isChecked()
        save_prefs(self._prefs)
        # Update cloner settings
        self._cloner._normalize = self._prefs.normalize_audio
        self._cloner._trim_silence = self._prefs.trim_silence

    def _copy_text(self) -> None:
        text = self._text_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._status_label.set_status("Text copied to clipboard.", "success")

    def _clear_text(self) -> None:
        self._text_edit.clear()
        self._word_count_label.setText("0 words  •  0 characters")

    # ══════════════════════════════════════════════════════════════════════
    # Helper methods
    # ══════════════════════════════════════════════════════════════════════

    def _update_generate_btn_state(self) -> None:
        ready = self._model_loaded and self._cloner.has_reference
        self._generate_btn.setEnabled(ready)

    def _update_status_device(self) -> None:
        info = self._device_info
        if info["device"] == "cuda":
            self._status_device.setText(
                f"GPU: {info['gpu_name']}  •  CUDA {info['cuda_version']}  "
                f"•  PyTorch {info['pytorch_version']}"
            )
        else:
            self._status_device.setText(
                f"CPU Mode  •  PyTorch {info['pytorch_version']}"
            )

    # ── Temperature slider helpers ─────────────────────────────────────────

    @staticmethod
    def _slider_to_temperature(value: int) -> float:
        """Map slider 1–10 → temperature 0.01–1.0 (exponential feel)."""
        # value 1 → 0.01 (most faithful),  value 10 → 1.0 (most creative)
        return round(0.01 + (value - 1) * 0.11, 2)

    def _on_temp_changed(self, value: int) -> None:
        """Update the label next to the temperature slider."""
        temp = self._slider_to_temperature(value)
        if value <= 2:
            label = "Highest"
        elif value <= 4:
            label = "High"
        elif value <= 6:
            label = "Medium"
        elif value <= 8:
            label = "Low"
        else:
            label = "Creative"
        self._temp_value_label.setText(label)
        self._temp_slider.setToolTip(
            f"Temperature: {temp:.2f}  ({'Most faithful to your voice' if value <= 2 else 'More creative, less like you' if value >= 7 else 'Balanced'})"
        )

    # ── Voice Tips dialog ─────────────────────────────────────────────────

    def _show_voice_tips(self) -> None:
        """Show a detailed guide on how to get the best voice clone quality."""
        dlg = QDialog(self)
        dlg.setWindowTitle("🎙  How to Get Your Exact Voice")
        dlg.setMinimumSize(560, 620)
        dlg.resize(600, 680)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        title = QLabel("Get Your Exact Voice — Complete Guide")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {COLORS['text_primary']};"
        )
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(4, 4, 4, 4)

        sections = [
            (
                "🔴  #1 Problem: Your current voice file is a SONG",
                "<b>You are using a song MP3 as your voice sample.</b><br><br>"
                "Songs have music, reverb, harmony, and effects — the AI gets confused "
                "between your voice and the instruments. The output will NOT sound like you.<br><br>"
                "<b>👉 You MUST record your own clean voice. See Step 1 below.</b>",
                "#ef4444",
            ),
            (
                "✅  Step 1 — Record the perfect voice sample",
                "<b>What to record:</b><br>"
                "• Use your phone's Voice Recorder app (or Audacity on PC)<br>"
                "• Speak naturally for <b>10–30 seconds</b> (not shorter, not longer)<br>"
                "• Read a paragraph of text — any text you like<br>"
                "• Use <b>Indian English</b> if that is how you normally speak<br><br>"
                "<b>Recording conditions:</b><br>"
                "• Quiet room — no fan, AC, TV, or street noise<br>"
                "• Hold your phone 15–20 cm from your mouth<br>"
                "• Speak at your normal pace — not too fast, not too slow<br>"
                "• No long pauses — steady, continuous speech<br><br>"
                "<b>Save as:</b> WAV or MP3 file, then drag it into this app.",
                "#22c55e",
            ),
            (
                "✅  Step 2 — Set the Similarity slider to maximum",
                "In the left panel, under <b>VOICE QUALITY</b>, drag the "
                "<b>Similarity slider all the way to the left (🎯 Exact voice)</b>.<br><br>"
                "This sets <b>Temperature = 0.01</b> — the lowest possible value — which "
                "tells the AI to copy your voice as faithfully as possible instead of being creative.",
                "#7c3aed",
            ),
            (
                "✅  Step 3 — Select the correct language",
                "If you speak <b>Telugu</b>, select <b>Telugu</b> from the Language dropdown.<br>"
                "If you speak <b>Hindi</b>, select <b>Hindi</b>.<br>"
                "If you speak <b>English (Indian accent)</b>, select <b>English</b>.<br><br>"
                "Using the wrong language causes an accent mismatch and the AI will "
                "not sound like you even with a perfect voice sample.",
                "#f59e0b",
            ),
            (
                "✅  Step 4 — Type text in the same language",
                "The text you type must match your selected language.<br>"
                "If your voice sample is Telugu, type Telugu text.<br><br>"
                "Tip: Keep each generation under <b>200 characters</b> for highest quality. "
                "Shorter = more accurate voice clone.",
                "#06b6d4",
            ),
            (
                "💡  Quick checklist before generating",
                "☐ Voice file = clean recording of YOUR voice (no music/background)<br>"
                "☐ Duration: 10–30 seconds<br>"
                "☐ Quality card shows <b>✅ Good</b><br>"
                "☐ Similarity slider = leftmost position (🎯 Exact voice)<br>"
                "☐ Language matches your speech<br>"
                "☐ Text matches selected language",
                "#64748b",
            ),
        ]

        for title_text, body_html, color in sections:
            card = QFrame()
            card.setStyleSheet(
                f"background: rgba(255,255,255,0.04); border-radius: 8px;"
                f"border-left: 3px solid {color};"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(6)

            sec_title = QLabel(title_text)
            sec_title.setStyleSheet(
                f"font-size: 13px; font-weight: 700; color: {color}; background: transparent;"
            )

            sec_body = QLabel(body_html)
            sec_body.setWordWrap(True)
            sec_body.setTextFormat(Qt.RichText)
            sec_body.setStyleSheet(
                f"font-size: 12px; color: {COLORS['text_secondary']}; background: transparent; line-height: 1.6;"
            )

            card_layout.addWidget(sec_title)
            card_layout.addWidget(sec_body)
            content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)

        dlg.exec()

    def _show_about(self) -> None:
        info = self._engine.get_model_info()
        device_str = f"GPU ({info.get('gpu_name', '')})" if info["device"] == "cuda" else "CPU"
        QMessageBox.about(
            self,
            f"About {APP_CONFIG.app_name}",
            f"<h2>{APP_CONFIG.app_name}</h2>"
            f"<p>Version {APP_CONFIG.app_version}</p>"
            f"<p>A fully offline AI voice cloning desktop application.<br>"
            f"Powered by <b>XTTS-v2</b> (Coqui TTS).</p>"
            f"<hr>"
            f"<p><b>Model:</b> {APP_CONFIG.model_name}<br>"
            f"<b>Device:</b> {device_str}<br>"
            f"<b>Sample Rate:</b> {APP_CONFIG.sample_rate:,} Hz<br>"
            f"<b>Supported Languages:</b> {len(SUPPORTED_LANGUAGES)}</p>"
            f"<hr>"
            f"<p><b>Keyboard Shortcuts:</b><br>"
            f"Ctrl+G — Generate  •  Space — Play<br>"
            f"Ctrl+S — Save  •  Esc — Stop<br>"
            f"Ctrl+O — Open file  •  Ctrl+L — Clear text</p>",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Window lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def closeEvent(self, event: QCloseEvent) -> None:
        """Clean up threads and save preferences before closing."""
        log.info("Application closing …")

        # Stop running threads
        for thread in (self._play_thread, self._gen_thread, self._ref_thread, self._model_thread):
            if thread and thread.isRunning():
                try:
                    thread.terminate()
                    thread.wait(1000)
                except Exception:
                    pass

        save_prefs(self._prefs)
        log.info("Preferences saved, exiting.")
        event.accept()
