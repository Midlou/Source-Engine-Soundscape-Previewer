"""Structured editor for one soundscape and its rules."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..keyvalues import KVNode
from ..soundscape import (
    RULE_LOOPING,
    RULE_RANDOM,
    RULE_SUBSCAPE,
    describe_rule,
    new_rule,
    parse_float,
)
from .widgets import FalloffEdit, PositionCombo, RangeEdit, WaveLineEdit, WaveListWidget, fmt, spin

RULE_LABELS = {RULE_LOOPING: "Looping", RULE_RANDOM: "Random", RULE_SUBSCAPE: "Sub-soundscape"}
RULE_COLORS = {RULE_LOOPING: "#3b82f6", RULE_RANDOM: "#f59e0b", RULE_SUBSCAPE: "#a855f7"}


def _position_text(rule: KVNode) -> str:
    if rule.get("origin"):
        return "origin"
    p = rule.get("position")
    if p is None:
        return "ambient"
    return p


class _BaseForm(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.rule: KVNode | None = None
        self._loading = False

    def set_rule(self, rule: KVNode) -> None:
        self.rule = rule
        self._loading = True
        try:
            self.load()
        finally:
            self._loading = False

    def load(self) -> None:  # pragma: no cover - overridden
        pass

    def put(self, key: str, value: str | None) -> None:
        if self._loading or self.rule is None:
            return
        if self.rule.get(key) == value and (value is not None or self.rule.find(key) is None):
            return
        self.rule.set(key, value)
        self.changed.emit()

    def put_falloff(self, edit: FalloffEdit) -> None:
        if self._loading or self.rule is None:
            return
        att, lvl = edit.values()
        self.rule.set("attenuation", att)
        self.rule.set("soundlevel", lvl)
        self.changed.emit()

    def put_position(self, combo: PositionCombo) -> None:
        if self._loading or self.rule is None:
            return
        self.rule.set("origin", None)
        self.rule.set("position", combo.value())
        self.changed.emit()


class LoopForm(_BaseForm):
    previewWave = Signal(str)

    def __init__(self, selected_sound: Callable[[], str | None]):
        super().__init__()
        self.selected_sound = selected_sound
        form = QFormLayout(self)
        self.wave = WaveLineEdit()
        use = QPushButton("Use selected")
        use.setToolTip("Use the sound selected in the sound browser")
        play = QPushButton("▶")
        play.setFixedWidth(32)
        play.setToolTip("Preview this sound on its own")
        row = QHBoxLayout()
        row.addWidget(self.wave, 1)
        row.addWidget(use)
        row.addWidget(play)
        form.addRow("Wave", row)
        self.volume = spin(0, 1, 0.05, 3)
        form.addRow("Volume", self.volume)
        self.pitch = spin(1, 255, 1, 0, " %")
        form.addRow("Pitch", self.pitch)
        self.position = PositionCombo(allow_random=True)
        form.addRow("Position", self.position)
        self.falloff = FalloffEdit("Default (ATTN_NORM 0.8)")
        form.addRow("Falloff", self.falloff)
        self.origin = QLineEdit()
        self.origin.setPlaceholderText("x, y, z  (optional, overrides position)")
        form.addRow("Origin", self.origin)
        form.addRow(QLabel("<small>playlooping does not accept random ranges. Files loop from their cue point.</small>"))

        self.wave.editingFinished.connect(lambda: self.put("wave", self.wave.text().strip()))
        use.clicked.connect(self._use_selected)
        play.clicked.connect(lambda: self.previewWave.emit(self.wave.text().strip()))
        self.volume.valueChanged.connect(lambda v: self.put("volume", fmt(v)))
        self.pitch.valueChanged.connect(lambda v: self.put("pitch", fmt(v)))
        self.position.currentIndexChanged.connect(lambda _: self.put_position(self.position))
        self.falloff.changed.connect(lambda: self.put_falloff(self.falloff))
        self.origin.editingFinished.connect(lambda: self.put("origin", self.origin.text().strip() or None))

    def _use_selected(self):
        s = self.selected_sound()
        if s:
            self.wave.setText(s)
            self.put("wave", s)

    def load(self):
        r = self.rule
        self.wave.setText(r.get("wave", ""))
        self.volume.setValue(parse_float(r.get("volume"), 0.0))
        self.pitch.setValue(parse_float(r.get("pitch"), 100.0))
        self.position.set_value(r.get("position"))
        self.falloff.load(r.get("attenuation"), r.get("soundlevel"))
        self.origin.setText(r.get("origin", ""))


class RandomForm(_BaseForm):
    previewWave = Signal(str)
    triggerNow = Signal()

    def __init__(self, selected_sound: Callable[[], str | None]):
        super().__init__()
        self.selected_sound = selected_sound
        form = QFormLayout(self)
        self.time = RangeEdit(0, 3600, 0.5, 2, " s")
        form.addRow("Time between", self.time)
        self.volume = RangeEdit(0, 1, 0.05, 3)
        form.addRow("Volume", self.volume)
        self.pitch = RangeEdit(1, 255, 1, 0, " %")
        form.addRow("Pitch", self.pitch)
        self.position = PositionCombo(allow_random=True)
        form.addRow("Position", self.position)
        self.falloff = FalloffEdit("Default (none - heard everywhere)")
        form.addRow("Falloff", self.falloff)
        self.origin = QLineEdit()
        self.origin.setPlaceholderText("x, y, z  (optional, overrides position)")
        form.addRow("Origin", self.origin)

        box = QGroupBox("rndwave (one is picked at random each time)")
        bl = QVBoxLayout(box)
        self.waves = WaveListWidget()
        self.waves.setSelectionMode(QAbstractItemView.ExtendedSelection)
        bl.addWidget(self.waves)
        br = QHBoxLayout()
        add = QPushButton("Add selected")
        add.setToolTip("Add the sound selected in the sound browser (or drag sounds here)")
        rem = QPushButton("Remove")
        play = QPushButton("▶ Preview")
        trig = QPushButton("⚡ Trigger now")
        trig.setToolTip("Play this rule immediately in the running soundscape")
        for b in (add, rem, play, trig):
            br.addWidget(b)
        bl.addLayout(br)
        form.addRow(box)

        self.time.changed.connect(lambda t: self.put("time", t))
        self.volume.changed.connect(lambda t: self.put("volume", t))
        self.pitch.changed.connect(lambda t: self.put("pitch", t))
        self.position.currentIndexChanged.connect(lambda _: self.put_position(self.position))
        self.falloff.changed.connect(lambda: self.put_falloff(self.falloff))
        self.origin.editingFinished.connect(lambda: self.put("origin", self.origin.text().strip() or None))
        add.clicked.connect(self._add_selected)
        rem.clicked.connect(self._remove)
        play.clicked.connect(self._preview)
        trig.clicked.connect(self.triggerNow.emit)
        self.waves.dropped.connect(self._add_waves)
        self.waves.itemDoubleClicked.connect(lambda it: self.previewWave.emit(it.text()))
        self.waves.itemChanged.connect(self._item_edited)

    def _rndwave(self) -> KVNode:
        node = self.rule.find("rndwave")
        if node is None or not node.is_block:
            node = KVNode("rndwave", children=[])
            self.rule.children.append(node)
        return node

    def _add_waves(self, waves: list[str]):
        if self.rule is None:
            return
        node = self._rndwave()
        for w in waves:
            node.children.append(KVNode("wave", w))
        self.set_rule(self.rule)
        self.changed.emit()

    def _add_selected(self):
        s = self.selected_sound()
        if s:
            self._add_waves([s])

    def _remove(self):
        if self.rule is None:
            return
        node = self._rndwave()
        rows = sorted((self.waves.row(i) for i in self.waves.selectedItems()), reverse=True)
        wave_nodes = node.find_all("wave")
        for r in rows:
            if r < len(wave_nodes):
                node.children.remove(wave_nodes[r])
        self.set_rule(self.rule)
        self.changed.emit()

    def _item_edited(self, item: QListWidgetItem):
        if self._loading or self.rule is None:
            return
        wave_nodes = self._rndwave().find_all("wave")
        r = self.waves.row(item)
        if r < len(wave_nodes):
            wave_nodes[r].value = item.text().strip()
            self.changed.emit()

    def _preview(self):
        items = self.waves.selectedItems() or ([self.waves.item(0)] if self.waves.count() else [])
        if items:
            self.previewWave.emit(items[0].text())

    def load(self):
        r = self.rule
        self.time.set_text(r.get("time"), (10, 10))
        self.volume.set_text(r.get("volume"), (1, 1))
        self.pitch.set_text(r.get("pitch"), (100, 100))
        self.position.set_value(r.get("position"))
        self.falloff.load(r.get("attenuation"), r.get("soundlevel"))
        self.origin.setText(r.get("origin", ""))
        self.waves.clear()
        rnd = r.find("rndwave")
        for c in rnd.find_all("wave") if rnd is not None and rnd.is_block else []:
            it = QListWidgetItem(c.value)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.waves.addItem(it)


class SubscapeForm(_BaseForm):
    def __init__(self, soundscape_names: Callable[[], list[str]]):
        super().__init__()
        self.soundscape_names = soundscape_names
        form = QFormLayout(self)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.NoInsert)
        form.addRow("Soundscape", self.name)
        self.volume = spin(0, 4, 0.05, 3)
        form.addRow("Volume", self.volume)
        self.position = spin(0, 7, 1, 0)
        form.addRow("Position offset", self.position)
        self.override = PositionCombo(allow_random=False, none_label="(not set)")
        form.addRow("positionoverride", self.override)
        self.ambient = PositionCombo(allow_random=False, none_label="(not set)")
        form.addRow("ambientpositionoverride", self.ambient)
        form.addRow(
            QLabel(
                "<small>Plays a whole soundscape inside this one. Its DSP settings are ignored.<br>"
                "positionoverride: all positioned sounds play from one position.<br>"
                "ambientpositionoverride: all ambient sounds play from one position.</small>"
            )
        )
        self.name.currentTextChanged.connect(lambda t: self.put("name", t.strip()))
        self.volume.valueChanged.connect(lambda v: self.put("volume", fmt(v)))
        self.position.valueChanged.connect(lambda v: self.put("position", None if v == 0 else fmt(v)))
        self.override.currentIndexChanged.connect(lambda _: self.put("positionoverride", self.override.value()))
        self.ambient.currentIndexChanged.connect(lambda _: self.put("ambientpositionoverride", self.ambient.value()))

    def load(self):
        r = self.rule
        self.name.clear()
        self.name.addItems(self.soundscape_names())
        self.name.setCurrentText(r.get("name", ""))
        self.volume.setValue(parse_float(r.get("volume"), 1.0))
        self.position.setValue(parse_float(r.get("position"), 0))
        self.override.set_value(r.get("positionoverride"))
        self.ambient.set_value(r.get("ambientpositionoverride"))


class SoundscapeEditor(QWidget):
    changed = Signal()  # rules or settings edited
    renamed = Signal(str)  # new name requested
    previewWave = Signal(str)
    triggerRule = Signal(object)
    mutesChanged = Signal()
    ruleSelected = Signal(object)

    COL_TYPE, COL_SOUND, COL_POS, COL_NEXT, COL_MUTE, COL_SOLO = range(6)

    def __init__(self, selected_sound: Callable[[], str | None], soundscape_names: Callable[[], list[str]]):
        super().__init__()
        self.scape: KVNode | None = None
        self.muted: set[int] = set()
        self.soloed: set[int] = set()
        self._loading = False
        self.active_uids: set[int] = set()
        self.active_waves: dict[int, set[int]] = {}  # rule uid -> rndwave entries playing now
        self.timers: dict[int, tuple[float, int]] = {}  # rule uid -> (seconds to next play, entry)
        self.expanded_uids: set[int] = set()

        outer = QVBoxLayout(self)
        top = QGroupBox("Soundscape")
        tf = QFormLayout(top)
        self.name = QLineEdit()
        tf.addRow("Name", self.name)
        row = QHBoxLayout()
        self.dsp = spin(-1, 255, 1, 0)
        self.dsp.setSpecialValueText("(not set)")
        self.dsp.setToolTip("DSP preset (room_type). 0 disables DSP, 1 = automatic. Not simulated in the preview.")
        self.dsp_spatial = spin(-1, 255, 1, 0)
        self.dsp_spatial.setSpecialValueText("(not set)")
        self.dsp_volume = spin(-0.01, 4, 0.05, 2)
        self.dsp_volume.setSpecialValueText("(not set)")
        self.fadetime = spin(-0.01, 60, 0.25, 2, " s")
        self.fadetime.setSpecialValueText("(default 3s)")
        self.fadetime.setToolTip("Crossfade time when this soundscape starts")
        for label, w in (("dsp", self.dsp), ("dsp_spatial", self.dsp_spatial), ("dsp_volume", self.dsp_volume), ("fadetime", self.fadetime)):
            row.addWidget(QLabel(label))
            row.addWidget(w, 1)
        tf.addRow(row)
        self.soundmixer = QLineEdit()
        self.soundmixer.setPlaceholderText("(not set)")
        tf.addRow("soundmixer", self.soundmixer)
        outer.addWidget(top)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.btn_loop = QPushButton("+ Looping")
        self.btn_random = QPushButton("+ Random")
        self.btn_sub = QPushButton("+ Sub-soundscape")
        for b in (self.btn_loop, self.btn_random, self.btn_sub):
            bar.addWidget(b)
        ll.addLayout(bar)
        self.rules = QTreeWidget()
        self.rules.setHeaderLabels(["Rule", "Sound / soundscape", "Pos", "Next", "M", "S"])
        self.rules.setRootIsDecorated(True)
        self.rules.setExpandsOnDoubleClick(False)
        self.rules.setTextElideMode(Qt.ElideMiddle)  # keep file names visible in long paths
        self.rules.setUniformRowHeights(True)
        h = self.rules.header()
        h.setSectionResizeMode(self.COL_SOUND, QHeaderView.Stretch)
        for c in (self.COL_TYPE, self.COL_POS, self.COL_MUTE, self.COL_SOLO):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_NEXT, QHeaderView.Fixed)
        self.rules.setColumnWidth(self.COL_NEXT, self.fontMetrics().horizontalAdvance("▶ playing") + 12)
        self.rules.headerItem().setToolTip(self.COL_NEXT, "Time until a random rule plays again, and which sound it picked")
        self.rules.headerItem().setToolTip(self.COL_MUTE, "Mute (preview only, not saved)")
        self.rules.headerItem().setToolTip(self.COL_SOLO, "Solo (preview only, not saved)")
        ll.addWidget(self.rules, 1)
        bar2 = QHBoxLayout()
        self.btn_dup = QPushButton("Duplicate")
        self.btn_del = QPushButton("Remove")
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        for b in (self.btn_dup, self.btn_del, self.btn_up, self.btn_down):
            bar2.addWidget(b)
        ll.addLayout(bar2)
        split.addWidget(left)

        self.stack = QStackedWidget()
        self.empty = QLabel("Select a rule to edit it.\n\nLooping: a sound that plays constantly.\nRandom: sounds played at random intervals.\nSub-soundscape: plays another soundscape inside this one.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.loop_form = LoopForm(selected_sound)
        self.random_form = RandomForm(selected_sound)
        self.sub_form = SubscapeForm(soundscape_names)
        for w in (self.empty, self.loop_form, self.random_form, self.sub_form):
            self.stack.addWidget(w)
        split.addWidget(self.stack)
        split.setSizes([500, 440])
        outer.addWidget(split, 1)

        for f in (self.loop_form, self.random_form, self.sub_form):
            f.changed.connect(self._rule_changed)
        self.loop_form.previewWave.connect(self.previewWave)
        self.random_form.previewWave.connect(self.previewWave)
        self.random_form.triggerNow.connect(lambda: self.triggerRule.emit(self.current_rule()))
        self.btn_loop.clicked.connect(lambda: self.add_rule(RULE_LOOPING))
        self.btn_random.clicked.connect(lambda: self.add_rule(RULE_RANDOM))
        self.btn_sub.clicked.connect(lambda: self.add_rule(RULE_SUBSCAPE))
        self.btn_dup.clicked.connect(self._duplicate)
        self.btn_del.clicked.connect(self._remove)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.rules.currentItemChanged.connect(self._select)
        self.rules.itemChanged.connect(self._item_changed)
        self.rules.itemDoubleClicked.connect(self._item_double_clicked)
        self.rules.itemExpanded.connect(lambda it: self.expanded_uids.add(it.data(0, Qt.UserRole).uid))
        self.rules.itemCollapsed.connect(lambda it: self.expanded_uids.discard(it.data(0, Qt.UserRole).uid))

        self.name.editingFinished.connect(self._rename)
        self.dsp.valueChanged.connect(lambda v: self._put("dsp", None if v < 0 else fmt(v)))
        self.dsp_spatial.valueChanged.connect(lambda v: self._put("dsp_spatial", None if v < 0 else fmt(v)))
        self.dsp_volume.valueChanged.connect(lambda v: self._put("dsp_volume", None if v < 0 else fmt(v)))
        self.fadetime.valueChanged.connect(lambda v: self._put("fadetime", None if v < 0 else fmt(v)))
        self.soundmixer.editingFinished.connect(lambda: self._put("soundmixer", self.soundmixer.text().strip() or None))
        self.setEnabled(False)

    # ------------------------------------------------------------------
    def rule_nodes(self) -> list[KVNode]:
        return [c for c in self.scape.children if c.is_block] if self.scape else []

    def current_rule(self) -> KVNode | None:
        """The selected rule (also when one of its rndwave entries is selected)."""
        it = self.rules.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    @staticmethod
    def _rule_item(it: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        if it is None:
            return None
        return it.parent() if it.parent() is not None else it

    def set_soundscape(self, scape: KVNode | None, select_index: int | None = None) -> None:
        self.scape = scape
        self.setEnabled(scape is not None)
        self._loading = True
        try:
            if scape is None:
                self.name.clear()
                self.rules.clear()
                self.stack.setCurrentWidget(self.empty)
                return
            self.name.setText(scape.key)

            def val(key, default):
                v = scape.get(key)
                return default if v is None else parse_float(v, default)

            self.dsp.setValue(val("dsp", -1))
            self.dsp_spatial.setValue(val("dsp_spatial", -1))
            self.dsp_volume.setValue(val("dsp_volume", -0.01))
            self.fadetime.setValue(val("fadetime", -0.01))
            self.soundmixer.setText(scape.get("soundmixer", ""))
        finally:
            self._loading = False
        self.refresh_rules(select_index)

    def refresh_rules(self, select_index: int | None = None) -> None:
        cur = self.current_rule()
        self._loading = True
        self.rules.clear()
        select_item = None
        for i, rule in enumerate(self.rule_nodes()):
            it = QTreeWidgetItem()
            it.setData(0, Qt.UserRole, rule)
            self._fill_item(it, rule)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(self.COL_MUTE, Qt.Checked if rule.uid in self.muted else Qt.Unchecked)
            it.setCheckState(self.COL_SOLO, Qt.Checked if rule.uid in self.soloed else Qt.Unchecked)
            self.rules.addTopLevelItem(it)
            it.setExpanded(rule.uid in self.expanded_uids)
            if rule is cur or (select_index is not None and i == select_index):
                select_item = it
        self._loading = False
        if select_item is None and self.rules.topLevelItemCount() and select_index is not None:
            select_item = self.rules.topLevelItem(min(select_index, self.rules.topLevelItemCount() - 1))
        if select_item is not None:
            self.rules.setCurrentItem(select_item)
        else:
            self.stack.setCurrentWidget(self.empty)

    def _fill_item(self, it: QTreeWidgetItem, rule: KVNode) -> None:
        k = rule.key.lower()
        it.setText(self.COL_TYPE, RULE_LABELS.get(k, rule.key))
        it.setText(self.COL_SOUND, describe_rule(rule))
        it.setToolTip(self.COL_SOUND, "\n".join(c.value or "" for c in rule.children or () if c.key.lower() in ("wave", "name")) or "")
        it.setText(self.COL_POS, _position_text(rule) if k != RULE_SUBSCAPE else "")
        active = rule.uid in self.active_uids
        font = it.font(self.COL_SOUND)
        font.setBold(active)
        it.setFont(self.COL_SOUND, font)
        if k == RULE_RANDOM:
            self._fill_waves(it, rule)
        self._update_live(it, rule)
        self._update_silenced(it, rule)

    def _is_silenced(self, rule: KVNode) -> bool:
        return rule.uid in self.muted or (bool(self.soloed) and rule.uid not in self.soloed)

    def _update_silenced(self, it: QTreeWidgetItem, rule: KVNode) -> None:
        """Grey out muted rules, and every rule outside the solo set."""
        grey = QBrush(self.palette().placeholderText().color())
        silenced = self._is_silenced(rule)
        normal = QBrush()  # default text color of the current theme
        it.setForeground(self.COL_TYPE, grey if silenced else QBrush(QColor(RULE_COLORS.get(rule.key.lower(), "#888"))))
        for col in (self.COL_SOUND, self.COL_POS, self.COL_NEXT):
            it.setForeground(col, grey if silenced else normal)
        for i in range(it.childCount()):
            child = it.child(i)
            child.setForeground(self.COL_TYPE, grey)
            for col in (self.COL_SOUND, self.COL_NEXT):
                child.setForeground(col, grey if silenced else normal)

    def _update_all_silenced(self) -> None:
        self._loading = True
        for i in range(self.rules.topLevelItemCount()):
            it = self.rules.topLevelItem(i)
            self._update_silenced(it, it.data(0, Qt.UserRole))
        self._loading = False

    def changeEvent(self, e):
        if e.type() == QEvent.PaletteChange:
            self._update_all_silenced()
        super().changeEvent(e)

    def _update_live(self, it: QTreeWidgetItem, rule: KVNode) -> None:
        """Next-play timer and bold for the rndwave entry playing right now."""
        timer = self.timers.get(rule.uid)
        it.setText(self.COL_NEXT, f"{max(0.0, timer[0]):.1f}s" if timer else "")
        playing = self.active_waves.get(rule.uid, set())
        for i in range(it.childCount()):
            child = it.child(i)
            idx = child.data(0, Qt.UserRole + 1)
            if idx in playing:
                text = "▶ playing"
            elif timer and timer[1] == idx:
                text = f"{max(0.0, timer[0]):.1f}s"
            else:
                text = ""
            child.setText(self.COL_NEXT, text)
            font = child.font(self.COL_SOUND)
            if font.bold() != (idx in playing):
                font.setBold(idx in playing)
                child.setFont(self.COL_SOUND, font)

    def _fill_waves(self, it: QTreeWidgetItem, rule: KVNode) -> None:
        """Show each rndwave entry of a playrandom rule as a child row."""
        rnd = rule.find("rndwave")
        waves = [c.value or "" for c in rnd.find_all("wave")] if rnd is not None and rnd.is_block else []
        if [it.child(i).data(0, Qt.UserRole + 2) for i in range(it.childCount())] == waves:
            return
        current = self.rules.currentItem()
        current_row = it.indexOfChild(current) if current is not None and current.parent() is it else None
        self.rules.blockSignals(True)
        try:
            it.takeChildren()
            grey = QBrush(self.palette().placeholderText().color())
            for idx, wave in enumerate(waves):
                name = wave.replace("\\", "/").rsplit("/", 1)[-1]
                child = QTreeWidgetItem(["wave", name])
                child.setData(0, Qt.UserRole, rule)
                child.setData(0, Qt.UserRole + 1, idx)
                child.setData(0, Qt.UserRole + 2, wave)
                child.setForeground(self.COL_TYPE, grey)
                child.setToolTip(self.COL_SOUND, f"{wave}\nDouble-click to preview")
                child.setFlags(child.flags() & ~Qt.ItemIsUserCheckable)
                it.addChild(child)
            if current_row is not None:
                self.rules.setCurrentItem(it.child(min(current_row, it.childCount() - 1)) if waves else it)
        finally:
            self.rules.blockSignals(False)

    def set_active(
        self,
        uids: set[int],
        waves: dict[int, set[int]] | None = None,
        timers: dict[int, tuple[float, int]] | None = None,
    ) -> None:
        """Highlight audible rules and rndwave entries; update next-play timers."""
        waves = waves or {}
        timers = timers or {}
        refill = uids != self.active_uids
        self.active_uids, self.active_waves, self.timers = uids, waves, timers
        self._loading = True
        for i in range(self.rules.topLevelItemCount()):
            it = self.rules.topLevelItem(i)
            rule = it.data(0, Qt.UserRole)
            if refill:
                self._fill_item(it, rule)
            else:
                self._update_live(it, rule)
        self._loading = False

    # ------------------------------------------------------------------
    def _select(self, item, _prev=None):
        rule = item.data(0, Qt.UserRole) if item else None
        self.ruleSelected.emit(rule)
        if rule is None:
            self.stack.setCurrentWidget(self.empty)
            return
        k = rule.key.lower()
        form = {RULE_LOOPING: self.loop_form, RULE_RANDOM: self.random_form, RULE_SUBSCAPE: self.sub_form}.get(k)
        if form is None:
            self.stack.setCurrentWidget(self.empty)
            return
        if form.rule is not rule or item.parent() is None:
            form.set_rule(rule)
        self.stack.setCurrentWidget(form)
        if form is self.random_form:
            wave_idx = item.data(0, Qt.UserRole + 1)
            self.random_form.waves.setCurrentRow(wave_idx if wave_idx is not None else -1)

    def _item_double_clicked(self, item, _column):
        rule = item.data(0, Qt.UserRole)
        if item.parent() is not None:
            self.previewWave.emit(item.data(0, Qt.UserRole + 2))
        elif rule is not None and rule.key.lower() == RULE_LOOPING and rule.get("wave"):
            self.previewWave.emit(rule.get("wave"))
        else:
            item.setExpanded(not item.isExpanded())

    def select_rule(self, uid: int) -> None:
        for i in range(self.rules.topLevelItemCount()):
            it = self.rules.topLevelItem(i)
            if it.data(0, Qt.UserRole).uid == uid:
                self.rules.setCurrentItem(it)
                return

    def _rule_changed(self):
        it = self._rule_item(self.rules.currentItem())
        if it:
            self._loading = True
            self._fill_item(it, it.data(0, Qt.UserRole))
            self._loading = False
        self.changed.emit()

    def _item_changed(self, item, column):
        if self._loading or item.parent() is not None:
            return
        rule = item.data(0, Qt.UserRole)
        if column == self.COL_MUTE:
            (self.muted.add if item.checkState(column) == Qt.Checked else self.muted.discard)(rule.uid)
            self._update_all_silenced()
            self.mutesChanged.emit()
        elif column == self.COL_SOLO:
            (self.soloed.add if item.checkState(column) == Qt.Checked else self.soloed.discard)(rule.uid)
            self._update_all_silenced()
            self.mutesChanged.emit()

    def _put(self, key, value):
        if self._loading or self.scape is None:
            return
        # keep settings before the first rule, as Valve's files do
        if value is not None and self.scape.find(key) is None:
            idx = next((i for i, c in enumerate(self.scape.children) if c.is_block), len(self.scape.children))
            self.scape.children.insert(idx, KVNode(key, value))
        else:
            self.scape.set(key, value)
        self.changed.emit()

    def _rename(self):
        if self._loading or self.scape is None:
            return
        new = self.name.text().strip()
        if new and new != self.scape.key:
            self.renamed.emit(new)

    def add_rule(self, rule_type: str, rule: KVNode | None = None) -> KVNode:
        rule = rule or new_rule(rule_type)
        self.scape.children.append(rule)
        self.refresh_rules(len(self.rule_nodes()) - 1)
        self.changed.emit()
        return rule

    def _duplicate(self):
        rule = self.current_rule()
        if rule is None:
            return
        copy = rule.clone()
        idx = self.scape.children.index(rule)
        self.scape.children.insert(idx + 1, copy)
        self.refresh_rules(self.rule_nodes().index(copy))
        self.changed.emit()

    def _remove(self):
        rule = self.current_rule()
        if rule is None:
            return
        row = self.rule_nodes().index(rule)
        self.scape.children.remove(rule)
        self.muted.discard(rule.uid)
        self.soloed.discard(rule.uid)
        self.refresh_rules(row)
        self.changed.emit()

    def _move(self, delta: int):
        rule = self.current_rule()
        if rule is None:
            return
        rules = self.rule_nodes()
        i = rules.index(rule)
        j = i + delta
        if not 0 <= j < len(rules):
            return
        ch = self.scape.children
        a, b = ch.index(rules[i]), ch.index(rules[j])
        ch[a], ch[b] = ch[b], ch[a]
        self.refresh_rules(j)
        self.changed.emit()


