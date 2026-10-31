"""Small reusable editor widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QWidget,
)

from ..soundscape import NUM_POSITIONS, SOUNDLEVEL_CHOICES, attenuation_value, parse_range

SOUND_MIME = "text/plain"


def fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def fmt_range(lo: float, hi: float) -> str:
    return fmt(lo) if abs(lo - hi) < 1e-9 else f"{fmt(lo)},{fmt(hi)}"


def spin(lo: float, hi: float, step: float, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setAccelerated(True)
    return s


class RangeEdit(QWidget):
    """Edits a Source random range "min,max" (or a single value)."""

    changed = Signal(str)

    def __init__(self, lo: float, hi: float, step: float, decimals: int = 2, suffix: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.min = spin(lo, hi, step, decimals, suffix)
        self.max = spin(lo, hi, step, decimals, suffix)
        lay.addWidget(self.min, 1)
        lay.addWidget(QLabel("to"))
        lay.addWidget(self.max, 1)
        self._loading = False
        self.min.valueChanged.connect(self._min_changed)
        self.max.valueChanged.connect(self._max_changed)

    def set_text(self, text: str | None, default: tuple[float, float]) -> None:
        lo, hi = parse_range(text, default)
        self._loading = True
        self.min.setValue(lo)
        self.max.setValue(hi)
        self._loading = False

    def text(self) -> str:
        return fmt_range(self.min.value(), self.max.value())

    def _min_changed(self, v: float) -> None:
        if self._loading:
            return
        if self.max.value() < v:
            self._loading = True
            self.max.setValue(v)
            self._loading = False
        self.changed.emit(self.text())

    def _max_changed(self, v: float) -> None:
        if self._loading:
            return
        if self.min.value() > v:
            self._loading = True
            self.min.setValue(v)
            self._loading = False
        self.changed.emit(self.text())


class PositionCombo(QComboBox):
    """None (ambient) / 0-7 / random."""

    def __init__(self, allow_random: bool = True, none_label: str = "None (ambient, everywhere)"):
        super().__init__()
        self.addItem(none_label, None)
        for i in range(NUM_POSITIONS):
            self.addItem(f"Position {i}", str(i))
        if allow_random:
            self.addItem("Random (36 units away)", "random")

    def set_value(self, value: str | None) -> None:
        if value is None:
            self.setCurrentIndex(0)
            return
        v = value.strip().lower()
        idx = self.findData(v)
        if idx < 0:
            try:
                idx = self.findData(str(int(float(v))))
            except ValueError:
                idx = 0
        self.setCurrentIndex(max(0, idx))

    def value(self) -> str | None:
        return self.currentData()


class FalloffEdit(QWidget):
    """Edits either "attenuation" or "soundlevel" of a rule."""

    changed = Signal()

    def __init__(self, default_label: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.addItems([default_label, "Attenuation", "Sound level"])
        self.att = spin(0, 10, 0.05, 2)
        self.lvl = QComboBox()
        self.lvl.setEditable(True)
        self.lvl.addItems(SOUNDLEVEL_CHOICES)
        lay.addWidget(self.mode)
        lay.addWidget(self.att, 1)
        lay.addWidget(self.lvl, 1)
        self._loading = False
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.att.valueChanged.connect(self._emit)
        self.lvl.currentTextChanged.connect(self._emit)
        self._update_visibility()

    def _update_visibility(self) -> None:
        m = self.mode.currentIndex()
        self.att.setVisible(m == 1)
        self.lvl.setVisible(m == 2)

    def _mode_changed(self) -> None:
        self._update_visibility()
        self._emit()

    def _emit(self, *_):
        if not self._loading:
            self.changed.emit()

    def load(self, attenuation: str | None, soundlevel: str | None) -> None:
        self._loading = True
        if soundlevel is not None:
            self.mode.setCurrentIndex(2)
            self.lvl.setCurrentText(soundlevel)
        elif attenuation is not None:
            self.mode.setCurrentIndex(1)
            self.att.setValue(attenuation_value(attenuation))
        else:
            self.mode.setCurrentIndex(0)
        self._update_visibility()
        self._loading = False

    def values(self) -> tuple[str | None, str | None]:
        """(attenuation, soundlevel); None means remove the key."""
        m = self.mode.currentIndex()
        if m == 1:
            return fmt(self.att.value()), None
        if m == 2:
            return None, self.lvl.currentText().strip() or None
        return None, None


class WaveLineEdit(QLineEdit):
    """Line edit that replaces its text when a sound is dropped on it."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a sound here, or type a path / soundscript name")

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        text = e.mimeData().text().strip().splitlines()
        if text:
            self.setText(text[0])
            self.editingFinished.emit()
        e.acceptProposedAction()


class WaveListWidget(QListWidget):
    """List of rndwave entries; accepts dropped sounds."""

    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        lines = [t.strip() for t in e.mimeData().text().splitlines() if t.strip()]
        if lines:
            self.dropped.emit(lines)
        e.setDropAction(Qt.CopyAction)
        e.accept()
