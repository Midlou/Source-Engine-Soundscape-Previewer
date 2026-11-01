"""Preferences window: one tab per group of options."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..settings import Settings
from .about import about_body, about_title
from .theme import THEMES


class PreferencesDialog(QDialog):
    """Edits a copy of the options; the caller applies them when accepted."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(420)
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # ---- appearance
        page = QWidget()
        form = QFormLayout(page)
        self.theme = QComboBox()
        for key, label in THEMES.items():
            self.theme.addItem("System (follow Windows)" if key == "system" else label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form.addRow("Theme", self.theme)
        self.tabs.addTab(page, "Appearance")

        # ---- saving
        page = QWidget()
        form = QFormLayout(page)
        self.auto_save = QCheckBox("Save modified files automatically")
        self.auto_save.setChecked(settings.auto_save)
        form.addRow(self.auto_save)
        self.auto_save_minutes = QSpinBox()
        self.auto_save_minutes.setRange(1, 120)
        self.auto_save_minutes.setSuffix(" min")
        self.auto_save_minutes.setValue(max(1, int(settings.auto_save_minutes)))
        self.auto_save_minutes.setEnabled(settings.auto_save)
        self.auto_save.toggled.connect(self.auto_save_minutes.setEnabled)
        form.addRow("Interval", self.auto_save_minutes)
        note = QLabel("New files that were never saved are skipped until you save them once.")
        note.setWordWrap(True)
        note.setEnabled(False)
        form.addRow(note)
        self.tabs.addTab(page, "Saving")

        # ---- about (same text as Help → About)
        about = QLabel(about_title() + about_body())
        about.setTextFormat(Qt.RichText)
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        about.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        about.setContentsMargins(8, 4, 8, 8)
        scroll = QScrollArea()
        scroll.setWidget(about)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.tabs.addTab(scroll, "About")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def apply_to(self, settings: Settings) -> None:
        settings.theme = self.theme.currentData()
        settings.auto_save = self.auto_save.isChecked()
        settings.auto_save_minutes = self.auto_save_minutes.value()
