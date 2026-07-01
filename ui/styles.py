"""
ui/styles.py
------------
Complete dark-mode QSS (Qt Style Sheet) for the Offline AI Voice Clone app.

The design uses a deep navy + purple + cyan palette:
  Background:  #0D1117  (near-black navy — GitHub dark mode inspired)
  Surface:     #161B22  (slightly lighter — card backgrounds)
  Border:      #30363D  (subtle borders)
  Accent:      #7C3AED  (purple — primary action colour)
  Accent alt:  #06B6D4  (cyan — secondary accents)
  Success:     #22C55E  (green — success states)
  Warning:     #F59E0B  (amber — warnings)
  Error:       #EF4444  (red — errors)
  Text:        #F0F6FC  (near-white — primary text)
  Text muted:  #8B949E  (grey — secondary text)

All widgets are explicitly styled to avoid platform-specific default styles
bleeding through on Windows.
"""

# ────────────────────────────────────────────────────────────────────────────
# Colour palette (also exported for use in Python code)
# ────────────────────────────────────────────────────────────────────────────
COLORS = {
    "bg_primary":     "#0D1117",
    "bg_surface":     "#161B22",
    "bg_elevated":    "#1C2128",
    "bg_hover":       "#21262D",
    "border":         "#30363D",
    "border_focus":   "#7C3AED",
    "accent":         "#7C3AED",
    "accent_hover":   "#6D28D9",
    "accent_pressed": "#5B21B6",
    "accent_light":   "#A78BFA",
    "cyan":           "#06B6D4",
    "cyan_hover":     "#0891B2",
    "success":        "#22C55E",
    "warning":        "#F59E0B",
    "error":          "#EF4444",
    "text_primary":   "#F0F6FC",
    "text_secondary": "#8B949E",
    "text_disabled":  "#484F58",
    "drop_zone_bg":   "#1C2128",
    "drop_zone_active": "#1D1135",
}


def get_stylesheet() -> str:
    """
    Return the complete application QSS stylesheet as a string.

    This is called once from main.py and applied to the QApplication.
    All widget-level overrides are contained here to keep the Python
    source files clean.
    """
    c = COLORS
    return f"""
/* ═══════════════════════════════════════════════════════════════════════
   BASE ELEMENTS
══════════════════════════════════════════════════════════════════════ */

QWidget {{
    background-color: {c['bg_primary']};
    color: {c['text_primary']};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}}

QMainWindow {{
    background-color: {c['bg_primary']};
}}

QFrame {{
    background-color: transparent;
    border: none;
}}

/* ═══════════════════════════════════════════════════════════════════════
   LABELS
══════════════════════════════════════════════════════════════════════ */

QLabel {{
    color: {c['text_primary']};
    background: transparent;
    border: none;
}}

QLabel[class="title"] {{
    font-size: 22px;
    font-weight: 700;
    color: {c['text_primary']};
    letter-spacing: 0.5px;
}}

QLabel[class="subtitle"] {{
    font-size: 12px;
    color: {c['text_secondary']};
}}

QLabel[class="section-header"] {{
    font-size: 11px;
    font-weight: 600;
    color: {c['text_secondary']};
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel[class="info-value"] {{
    font-size: 12px;
    color: {c['accent_light']};
    font-weight: 500;
}}

QLabel[class="status-ok"] {{
    color: {c['success']};
    font-weight: 600;
}}

QLabel[class="status-warn"] {{
    color: {c['warning']};
    font-weight: 600;
}}

QLabel[class="status-error"] {{
    color: {c['error']};
    font-weight: 600;
}}

/* ═══════════════════════════════════════════════════════════════════════
   BUTTONS
══════════════════════════════════════════════════════════════════════ */

QPushButton {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}}

QPushButton:hover {{
    background-color: {c['bg_hover']};
    border-color: {c['border_focus']};
}}

QPushButton:pressed {{
    background-color: {c['bg_primary']};
    border-color: {c['accent_pressed']};
}}

QPushButton:disabled {{
    background-color: {c['bg_surface']};
    color: {c['text_disabled']};
    border-color: {c['border']};
}}

/* Primary action button (Generate) */
QPushButton[class="primary"] {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 #5B21B6
    );
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    padding: 10px 24px;
    min-height: 44px;
    letter-spacing: 0.5px;
}}

QPushButton[class="primary"]:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent_hover']}, stop:1 #4C1D95
    );
}}

QPushButton[class="primary"]:pressed {{
    background: {c['accent_pressed']};
}}

QPushButton[class="primary"]:disabled {{
    background: {c['bg_elevated']};
    color: {c['text_disabled']};
}}

/* Success button (Play) */
QPushButton[class="success"] {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #16A34A, stop:1 {c['success']}
    );
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    padding: 8px 20px;
    min-height: 40px;
}}

QPushButton[class="success"]:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #15803D, stop:1 #16A34A
    );
}}

QPushButton[class="success"]:disabled {{
    background: {c['bg_elevated']};
    color: {c['text_disabled']};
}}

/* Danger button (Stop) */
QPushButton[class="danger"] {{
    background-color: {c['bg_elevated']};
    color: {c['error']};
    border: 1px solid {c['error']};
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 40px;
    font-weight: 600;
}}

QPushButton[class="danger"]:hover {{
    background-color: rgba(239, 68, 68, 0.15);
}}

QPushButton[class="danger"]:disabled {{
    color: {c['text_disabled']};
    border-color: {c['border']};
    background-color: {c['bg_elevated']};
}}

/* Icon button (small) */
QPushButton[class="icon-btn"] {{
    background: transparent;
    border: none;
    padding: 4px;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}

QPushButton[class="icon-btn"]:hover {{
    background: {c['bg_hover']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   TEXT EDIT (main input box)
══════════════════════════════════════════════════════════════════════ */

QTextEdit {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 14px;
    font-size: 14px;
    line-height: 1.6;
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}

QTextEdit:focus {{
    border-color: {c['border_focus']};
    background-color: {c['bg_elevated']};
}}

QTextEdit:disabled {{
    color: {c['text_disabled']};
    border-color: {c['border']};
}}

QPlainTextEdit {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 12px;
    font-size: 13px;
    selection-background-color: {c['accent']};
}}

QPlainTextEdit:focus {{
    border-color: {c['border_focus']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   COMBOBOX (language selector)
══════════════════════════════════════════════════════════════════════ */

QComboBox {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 6px 12px;
    padding-right: 28px;
    font-size: 13px;
    min-height: 36px;
    min-width: 160px;
}}

QComboBox:hover {{
    border-color: {c['border_focus']};
    background-color: {c['bg_elevated']};
}}

QComboBox:focus {{
    border-color: {c['border_focus']};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {c['text_secondary']};
    width: 0;
    height: 0;
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border_focus']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
    outline: none;
}}

QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 4px;
    min-height: 28px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {c['bg_hover']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   PROGRESS BAR
══════════════════════════════════════════════════════════════════════ */

QProgressBar {{
    background-color: {c['bg_surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    height: 8px;
    text-align: center;
    font-size: 11px;
    color: transparent;
}}

QProgressBar::chunk {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['cyan']}, stop:1 {c['accent']}
    );
    border-radius: 5px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   SCROLL BARS
══════════════════════════════════════════════════════════════════════ */

QScrollBar:vertical {{
    background: {c['bg_surface']};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c['text_secondary']};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

QScrollBar:horizontal {{
    background: {c['bg_surface']};
    height: 8px;
    border-radius: 4px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {c['text_secondary']};
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

/* ═══════════════════════════════════════════════════════════════════════
   LIST WIDGET (history panel)
══════════════════════════════════════════════════════════════════════ */

QListWidget {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 0;
    border: none;
}}

QListWidget::item:selected {{
    background-color: rgba(124, 58, 237, 0.3);
    color: {c['accent_light']};
    border: 1px solid rgba(124, 58, 237, 0.5);
}}

QListWidget::item:hover {{
    background-color: {c['bg_hover']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   TOOL BAR
══════════════════════════════════════════════════════════════════════ */

QToolBar {{
    background-color: {c['bg_surface']};
    border-top: 1px solid {c['border']};
    spacing: 6px;
    padding: 8px 12px;
}}

QToolBar::separator {{
    background: {c['border']};
    width: 1px;
    margin: 4px 6px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   STATUS BAR
══════════════════════════════════════════════════════════════════════ */

QStatusBar {{
    background-color: {c['bg_surface']};
    color: {c['text_secondary']};
    border-top: 1px solid {c['border']};
    font-size: 12px;
    padding: 2px 8px;
}}

QStatusBar::item {{
    border: none;
}}

/* ═══════════════════════════════════════════════════════════════════════
   MENU BAR
══════════════════════════════════════════════════════════════════════ */

QMenuBar {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border-bottom: 1px solid {c['border']};
    padding: 2px 4px;
}}

QMenuBar::item {{
    padding: 6px 12px;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: {c['bg_hover']};
}}

QMenu {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 8px 16px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {c['accent']};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   SLIDER (volume, speed)
══════════════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {{
    background: {c['bg_elevated']};
    height: 4px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {c['accent']};
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -6px 0;
    border: 2px solid {c['bg_primary']};
}}

QSlider::handle:horizontal:hover {{
    background: {c['accent_hover']};
}}

QSlider::sub-page:horizontal {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['cyan']}, stop:1 {c['accent']}
    );
    border-radius: 2px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   TOOLTIP
══════════════════════════════════════════════════════════════════════ */

QToolTip {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border_focus']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   CHECKBOX & RADIO
══════════════════════════════════════════════════════════════════════ */

QCheckBox {{
    color: {c['text_primary']};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {c['border']};
    border-radius: 4px;
    background: {c['bg_surface']};
}}

QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
}}

QCheckBox::indicator:hover {{
    border-color: {c['border_focus']};
}}

/* ═══════════════════════════════════════════════════════════════════════
   SPLITTER
══════════════════════════════════════════════════════════════════════ */

QSplitter::handle {{
    background: {c['border']};
    width: 1px;
    height: 1px;
}}

/* ═══════════════════════════════════════════════════════════════════════
   CUSTOM CLASSES (used via setProperty in Python)
══════════════════════════════════════════════════════════════════════ */

/* Card container */
QFrame[class="card"] {{
    background-color: {c['bg_surface']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 16px;
}}

/* Header bar */
QFrame[class="header"] {{
    background-color: {c['bg_surface']};
    border-bottom: 1px solid {c['border']};
}}

/* Drop zone — idle state */
QFrame[class="drop-zone"] {{
    background-color: {c['drop_zone_bg']};
    border: 2px dashed {c['border']};
    border-radius: 12px;
}}

/* Drop zone — file hovering over */
QFrame[class="drop-zone-active"] {{
    background-color: {c['drop_zone_active']};
    border: 2px dashed {c['accent']};
    border-radius: 12px;
}}

/* Drop zone — file loaded */
QFrame[class="drop-zone-loaded"] {{
    background-color: rgba(34, 197, 94, 0.08);
    border: 2px solid {c['success']};
    border-radius: 12px;
}}

/* Badge */
QLabel[class="badge-gpu"] {{
    background-color: rgba(34, 197, 94, 0.15);
    color: {c['success']};
    border: 1px solid rgba(34, 197, 94, 0.4);
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel[class="badge-cpu"] {{
    background-color: rgba(245, 158, 11, 0.15);
    color: {c['warning']};
    border: 1px solid rgba(245, 158, 11, 0.4);
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel[class="badge-loading"] {{
    background-color: rgba(6, 182, 212, 0.15);
    color: {c['cyan']};
    border: 1px solid rgba(6, 182, 212, 0.4);
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
}}
"""


def get_colors() -> dict[str, str]:
    """Return the colour palette dictionary for use in Python code."""
    return dict(COLORS)
