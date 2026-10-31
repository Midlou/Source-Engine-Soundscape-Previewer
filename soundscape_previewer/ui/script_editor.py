"""Plain-text editor for a whole soundscape file, with KeyValues highlighting."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    return f


class KVHighlighter(QSyntaxHighlighter):
    RULES = re.compile(r'"(playlooping|playrandom|playsoundscape|rndwave)"', re.I)
    KEYS = re.compile(
        r'"(wave|volume|pitch|time|position|soundlevel|attenuation|origin|name|dsp|dsp_spatial|dsp_volume|'
        r'fadetime|soundmixer|positionoverride|ambientpositionoverride|suppress_on_restore)"',
        re.I,
    )

    def __init__(self, doc):
        super().__init__(doc)
        self.f_string = _fmt("#16a34a")
        self.f_rule = _fmt("#2563eb", bold=True)
        self.f_key = _fmt("#9333ea")
        self.f_comment = _fmt("#6b7280", italic=True)
        self.f_brace = _fmt("#d97706", bold=True)
        self.f_scape = _fmt("#dc2626", bold=True)

    def highlightBlock(self, text: str) -> None:
        for m in re.finditer(r'"[^"]*"', text):
            self.setFormat(m.start(), m.end() - m.start(), self.f_string)
        for m in self.KEYS.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f_key)
        for m in self.RULES.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f_rule)
        # top-level soundscape names: a quoted string at the start of an unindented line
        m = re.match(r'^"[^"]*"\s*$', text)
        if m:
            self.setFormat(0, m.end(), self.f_scape)
        for m in re.finditer(r"[{}]", text):
            self.setFormat(m.start(), 1, self.f_brace)
        # comments (outside strings)
        in_str = False
        for i, ch in enumerate(text):
            if ch == '"':
                in_str = not in_str
            elif not in_str and text.startswith("//", i):
                self.setFormat(i, len(text) - i, self.f_comment)
                break


class ScriptEditor(QWidget):
    """Emits textEdited(text) after the user stops typing."""

    textEdited = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QPlainTextEdit()
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(10)
        self.edit.setFont(font)
        self.edit.setTabStopDistance(self.edit.fontMetrics().horizontalAdvance(" ") * 4)
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = KVHighlighter(self.edit.document())
        lay.addWidget(self.edit, 1)
        self.status = QLabel("Edits here are applied live while you type.")
        lay.addWidget(self.status)
        self._programmatic = False
        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(lambda: self.textEdited.emit(self.edit.toPlainText()))
        self.edit.textChanged.connect(self._changed)

    def _changed(self):
        if not self._programmatic:
            self._timer.start()

    def set_text(self, text: str) -> None:
        if text == self.edit.toPlainText():
            return
        self._programmatic = True
        bar = self.edit.verticalScrollBar().value()
        cur = self.edit.textCursor().position()
        self.edit.setPlainText(text)
        c = self.edit.textCursor()
        c.setPosition(min(cur, len(text)))
        self.edit.setTextCursor(c)
        self.edit.verticalScrollBar().setValue(bar)
        self._programmatic = False

    def is_editing(self) -> bool:
        return self.edit.hasFocus() or self._timer.isActive()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet("color: #dc2626;" if error else "")

    def goto_line(self, line: int) -> None:
        block = self.edit.document().findBlockByLineNumber(max(0, line - 1))
        c = QTextCursor(block)
        self.edit.setTextCursor(c)
        self.edit.centerCursor()
        self.edit.setFocus(Qt.OtherFocusReason)


