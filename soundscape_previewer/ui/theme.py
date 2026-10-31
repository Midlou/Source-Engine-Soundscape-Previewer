"""Application color theme (follow Windows, or force light/dark)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

THEMES = {"system": "System", "light": "Light", "dark": "Dark"}


def apply_theme(theme: str) -> None:
    """Switch the Fusion palette; Qt also updates the window title bars."""
    hints = QGuiApplication.styleHints()
    if theme == "light":
        hints.setColorScheme(Qt.ColorScheme.Light)
    elif theme == "dark":
        hints.setColorScheme(Qt.ColorScheme.Dark)
    else:
        hints.unsetColorScheme()


def is_dark() -> bool:
    return QGuiApplication.palette().window().color().lightness() < 128
