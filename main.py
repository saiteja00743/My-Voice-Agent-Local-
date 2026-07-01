"""
main.py
-------
Application entry point for the Offline AI Voice Clone.

Responsibilities:
  1. Bootstrap: set up high-DPI scaling and platform hints before QApplication
  2. Ensure all required directories exist
  3. Create the QApplication and apply the global stylesheet
  4. Show an animated splash screen during startup
  5. Instantiate and show MainWindow
  6. Run the Qt event loop

Run:
    python main.py
    or via setup.bat
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# ── Must be done BEFORE importing PySide6 ────────────────────────────────────
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
# Disable Coqui TTS telemetry (privacy)
os.environ.setdefault("COQUI_TOS_AGREED", "1")
# Suppress HuggingFace tokenizer parallelism warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Suppress some PyTorch warnings
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── Now safe to import Qt ────────────────────────────────────────────────────
from PySide6.QtWidgets import QApplication, QSplashScreen, QLabel
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont, QLinearGradient

# ── Internal imports ──────────────────────────────────────────────────────────
from config.settings import ensure_directories, APP_CONFIG
from ui.styles import get_stylesheet, COLORS
from ui.gui import MainWindow
from utils.logger import setup_logger

log = setup_logger("main")


# ─────────────────────────────────────────────────────────────────────────────
# Splash screen
# ─────────────────────────────────────────────────────────────────────────────

def _build_splash_pixmap(width: int = 540, height: int = 300) -> QPixmap:
    """
    Create a custom splash screen pixmap using QPainter.
    No external image file required.

    Returns:
        A QPixmap with a gradient background, title, and subtitle.
    """
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # ── Background gradient ────────────────────────────────────────────────
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#0D1117"))
    gradient.setColorAt(1.0, QColor("#1C1040"))
    painter.fillRect(0, 0, width, height, gradient)

    # ── Outer border ───────────────────────────────────────────────────────
    from PySide6.QtGui import QPen
    from PySide6.QtCore import QRect
    painter.setPen(QPen(QColor(COLORS["accent"]), 2))
    painter.drawRoundedRect(2, 2, width - 4, height - 4, 16, 16)

    # ── Accent bar at top ──────────────────────────────────────────────────
    accent_gradient = QLinearGradient(0, 0, width, 6)
    accent_gradient.setColorAt(0.0, QColor(COLORS["cyan"]))
    accent_gradient.setColorAt(1.0, QColor(COLORS["accent"]))
    painter.setPen(Qt.NoPen)
    painter.fillRect(2, 2, width - 4, 4, accent_gradient)

    # ── Icon ──────────────────────────────────────────────────────────────
    icon_font = QFont("Segoe UI Emoji", 48)
    painter.setFont(icon_font)
    painter.setPen(QColor(COLORS["text_primary"]))
    painter.drawText(QRect(0, 30, width, 90), Qt.AlignCenter, "🎙️")

    # ── App title ─────────────────────────────────────────────────────────
    title_font = QFont("Segoe UI", 28, QFont.Bold)
    painter.setFont(title_font)
    painter.setPen(QColor(COLORS["text_primary"]))
    painter.drawText(QRect(0, 115, width, 50), Qt.AlignCenter, APP_CONFIG.app_name)

    # ── Subtitle ──────────────────────────────────────────────────────────
    subtitle_font = QFont("Segoe UI", 12)
    painter.setFont(subtitle_font)
    painter.setPen(QColor(COLORS["text_secondary"]))
    painter.drawText(
        QRect(0, 162, width, 30),
        Qt.AlignCenter,
        "Offline · XTTS-v2 · GPU Accelerated · Open Source",
    )

    # ── Version ───────────────────────────────────────────────────────────
    version_font = QFont("Segoe UI", 10)
    painter.setFont(version_font)
    painter.setPen(QColor(COLORS["accent_light"]))
    painter.drawText(
        QRect(0, height - 46, width, 22),
        Qt.AlignCenter,
        f"v{APP_CONFIG.app_version}  •  {APP_CONFIG.app_author}",
    )

    # ── Loading text ──────────────────────────────────────────────────────
    loading_font = QFont("Segoe UI", 10)
    painter.setFont(loading_font)
    painter.setPen(QColor(COLORS["text_secondary"]))
    painter.drawText(
        QRect(0, height - 26, width, 20),
        Qt.AlignCenter,
        "Initialising …",
    )

    painter.end()
    return pixmap


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """
    Application entry point.

    Returns:
        Exit code (0 on normal exit).
    """
    log.info("=" * 60)
    log.info("Starting %s v%s", APP_CONFIG.app_name, APP_CONFIG.app_version)
    log.info("Python %s | Platform: %s", sys.version.split()[0], sys.platform)
    log.info("=" * 60)

    # ── Ensure all required directories exist ─────────────────────────────
    ensure_directories()
    log.debug("Directories verified.")

    # ── Create QApplication ───────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName(APP_CONFIG.app_name)
    app.setApplicationVersion(APP_CONFIG.app_version)
    app.setOrganizationName(APP_CONFIG.app_author)
    app.setStyle("Fusion")  # Fusion style plays nicely with custom QSS

    # Apply global stylesheet
    app.setStyleSheet(get_stylesheet())

    # ── Splash screen ─────────────────────────────────────────────────────
    splash_pixmap = _build_splash_pixmap()
    splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
    splash.setAttribute(Qt.WA_TranslucentBackground, False)
    splash.show()
    app.processEvents()

    log.debug("Splash screen displayed.")

    # ── Build main window (deferred slightly to allow splash to render) ────
    window: list[MainWindow] = []

    def _show_main() -> None:
        w = MainWindow()
        window.append(w)
        w.show()
        splash.finish(w)
        log.info("Main window shown.")

    QTimer.singleShot(1800, _show_main)

    # ── Run event loop ────────────────────────────────────────────────────
    exit_code = app.exec()
    log.info("Application exited with code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
