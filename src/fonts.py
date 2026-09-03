"""Shared Thai font registration for ReportLab PDF generation.

Both the bill generator (src/pdf_generator_reportlab.py) and the sales
report (src/sales_report.py) need a Thai-capable font registered with
ReportLab. This module centralizes that discovery so both call sites get
identical font-selection behavior, and caches the result so repeated calls
(one per PDFGenerator instance, one per sales-report request, ...) don't
re-probe the filesystem or re-register fonts with ReportLab every time.
"""
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Priority 1: bundled Sarabun font (works on every platform, including
# Linux/Render, where no system Thai font is installed).
_BUNDLED_REGULAR = os.path.join(_BASE_DIR, 'fonts', 'Sarabun-Regular.ttf')
_BUNDLED_BOLD = os.path.join(_BASE_DIR, 'fonts', 'Sarabun-Bold.ttf')

# Priority 2: system Tahoma (macOS/Windows).
_TAHOMA_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Tahoma.ttf',
    '/Library/Fonts/Tahoma.ttf',
    r'C:\Windows\Fonts\tahoma.ttf',
    r'C:\Windows\Fonts\Tahoma.ttf',
]
_TAHOMA_BOLD_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Tahoma Bold.ttf',
    '/Library/Fonts/Tahoma Bold.ttf',
    r'C:\Windows\Fonts\tahomabd.ttf',
    r'C:\Windows\Fonts\Tahomabd.ttf',
]

_cached_fonts = None


def _find_font(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def register_thai_fonts():
    """Register a Thai-capable TrueType font with ReportLab.

    Returns (font_name, bold_font_name) — either ('ThaiFont', 'ThaiFont-Bold')
    if a usable TTF was found and registered, or ('Helvetica', 'Helvetica-Bold')
    as a last-resort fallback (no Thai glyphs, but never crashes).

    The result is cached after the first call: subsequent calls return the
    same tuple without touching the filesystem or calling
    pdfmetrics.registerFont() again.
    """
    global _cached_fonts
    if _cached_fonts is not None:
        return _cached_fonts

    if os.path.exists(_BUNDLED_REGULAR):
        regular_path = _BUNDLED_REGULAR
        bold_path = _BUNDLED_BOLD if os.path.exists(_BUNDLED_BOLD) else _BUNDLED_REGULAR
    else:
        regular_path = _find_font(_TAHOMA_CANDIDATES)
        bold_path = _find_font(_TAHOMA_BOLD_CANDIDATES)

    try:
        if not regular_path:
            raise FileNotFoundError("No Thai font found")
        pdfmetrics.registerFont(TTFont('ThaiFont', regular_path))
        pdfmetrics.registerFont(TTFont('ThaiFont-Bold', bold_path or regular_path))
        _cached_fonts = ('ThaiFont', 'ThaiFont-Bold')
        print(f"Thai font loaded: {regular_path}")
    except Exception as e:
        print(f"Font loading error: {e}")
        _cached_fonts = ('Helvetica', 'Helvetica-Bold')

    return _cached_fonts
