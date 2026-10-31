"""Dialog to create and manage game profiles (sets of VPKs and folders)."""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..settings import Profile, VpkRef, default_tf2_profile, find_dir_vpks, steam_libraries


class ProfilesDialog(QDialog):
    def __init__(self, profiles: list[Profile], active: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Game profiles")
        self.resize(900, 520)
        self.profiles = copy.deepcopy(profiles)
        self.active = active

        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Profiles"))
        self.list = QListWidget()
        ll.addWidget(self.list, 1)
        for text, slot in (
            ("New…", self._new),
            ("Duplicate", self._duplicate),
            ("Rename…", self._rename),
            ("Delete", self._delete),
            ("Detect Team Fortress 2", self._detect_tf2),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            ll.addWidget(b)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        vbox = QGroupBox("VPK files (checked = used; higher in the list wins when files overlap)")
        vl = QVBoxLayout(vbox)
        self.vpks = QListWidget()
        vl.addWidget(self.vpks, 1)
        row = QHBoxLayout()
        for text, slot in (
            ("Add VPK…", self._add_vpk),
            ("Add all from folder…", self._add_folder_vpks),
            ("Remove", self._remove_vpk),
            ("▲", lambda: self._move_vpk(-1)),
            ("▼", lambda: self._move_vpk(1)),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        vl.addLayout(row)
        vl.addWidget(
            QLabel(
                "<small>Pick the <b>_dir.vpk</b> files. For TF2, sounds are in tf2_sound_misc / hl2_sound_misc, and "
                "soundscripts and the game's soundscapes are in tf2_misc / hl2_misc.</small>"
            )
        )
        rl.addWidget(vbox, 3)

        fbox = QGroupBox("Loose folders (optional, take priority over VPKs)")
        fl = QVBoxLayout(fbox)
        self.folders = QListWidget()
        fl.addWidget(self.folders, 1)
        row = QHBoxLayout()
        for text, slot in (("Add folder…", self._add_folder), ("Remove", self._remove_folder)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        fl.addLayout(row)
        fl.addWidget(
            QLabel(
                "<small>A folder containing <b>sound/</b> (and/or <b>scripts/</b>), e.g. <i>tf</i>, "
                "<i>tf/custom/mymap</i>, or <i>tf/custom</i> to include every custom folder. "
                "Use this for your map's custom sounds.</small>"
            )
        )
        rl.addWidget(fbox, 2)
        split.addWidget(right)
        split.setSizes([260, 640])

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.list.currentRowChanged.connect(self._show)
        self.vpks.itemChanged.connect(self._vpk_checked)
        self._fill_list()

    # ------------------------------------------------------------------
    def current(self) -> Profile | None:
        r = self.list.currentRow()
        return self.profiles[r] if 0 <= r < len(self.profiles) else None

    def _fill_list(self, select: str | None = None) -> None:
        select = select or self.active
        self.list.clear()
        row = 0
        for i, p in enumerate(self.profiles):
            self.list.addItem(p.name)
            if p.name == select:
                row = i
        if self.profiles:
            self.list.setCurrentRow(row)
        else:
            self._show(-1)

    def _show(self, _row: int) -> None:
        p = self.current()
        self.vpks.blockSignals(True)
        self.vpks.clear()
        self.folders.clear()
        if p:
            for v in p.vpks:
                it = QListWidgetItem(v.path)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if v.enabled else Qt.Unchecked)
                if not os.path.isfile(v.path):
                    it.setText(v.path + "   (missing)")
                self.vpks.addItem(it)
            self.folders.addItems(p.folders)
            self.active = p.name
        self.vpks.blockSignals(False)

    def _unique(self, name: str) -> str:
        names = {p.name for p in self.profiles}
        base, n = name, 2
        while name in names:
            name = f"{base} ({n})"
            n += 1
        return name

    def _new(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name (e.g. Team Fortress 2):")
        if ok and name.strip():
            p = Profile(self._unique(name.strip()))
            self.profiles.append(p)
            self._fill_list(p.name)

    def _duplicate(self):
        p = self.current()
        if p:
            c = copy.deepcopy(p)
            c.name = self._unique(p.name + " copy")
            self.profiles.append(c)
            self._fill_list(c.name)

    def _rename(self):
        p = self.current()
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "Name:", text=p.name)
        if ok and name.strip() and name.strip() != p.name:
            p.name = self._unique(name.strip())
            self._fill_list(p.name)

    def _delete(self):
        p = self.current()
        if p and QMessageBox.question(self, "Delete profile", f"Delete profile '{p.name}'?") == QMessageBox.Yes:
            self.profiles.remove(p)
            self.active = self.profiles[0].name if self.profiles else None
            self._fill_list()

    def _detect_tf2(self):
        p = default_tf2_profile()
        if p is None:
            QMessageBox.information(
                self,
                "Not found",
                "Team Fortress 2 was not found in your Steam libraries:\n" + "\n".join(steam_libraries() or ["(none)"]),
            )
            return
        p.name = self._unique(p.name)
        self.profiles.append(p)
        self._fill_list(p.name)

    def _vpk_checked(self, item: QListWidgetItem):
        p = self.current()
        if p:
            p.vpks[self.vpks.row(item)].enabled = item.checkState() == Qt.Checked

    def _ensure_profile(self) -> Profile | None:
        if self.current() is None:
            self._new()
        return self.current()

    def _add_paths(self, paths: list[str]):
        p = self._ensure_profile()
        if not p:
            return
        have = {v.path.lower() for v in p.vpks}
        for path in paths:
            path = os.path.normpath(path)
            if path.lower() not in have:
                p.vpks.append(VpkRef(path))
                have.add(path.lower())
        self._show(self.list.currentRow())

    def _add_vpk(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add VPK files", "", "VPK directory files (*_dir.vpk *.vpk)")
        if paths:
            self._add_paths(paths)

    def _add_folder_vpks(self):
        folder = QFileDialog.getExistingDirectory(self, "Game folder (e.g. Team Fortress 2)")
        if not folder:
            return
        found = find_dir_vpks(folder)
        if not found:
            QMessageBox.information(self, "No VPKs", "No *_dir.vpk files found in that folder.")
            return
        items, ok = _pick_many(self, "Add VPKs", "Select the VPKs to add:", found)
        if ok:
            self._add_paths(items)

    def _remove_vpk(self):
        p = self.current()
        r = self.vpks.currentRow()
        if p and 0 <= r < len(p.vpks):
            del p.vpks[r]
            self._show(self.list.currentRow())

    def _move_vpk(self, d: int):
        p = self.current()
        r = self.vpks.currentRow()
        if p and 0 <= r < len(p.vpks) and 0 <= r + d < len(p.vpks):
            p.vpks[r], p.vpks[r + d] = p.vpks[r + d], p.vpks[r]
            self._show(self.list.currentRow())
            self.vpks.setCurrentRow(r + d)

    def _add_folder(self):
        p = self._ensure_profile()
        if not p:
            return
        folder = QFileDialog.getExistingDirectory(self, "Content folder")
        if folder:
            p.folders.append(os.path.normpath(folder))
            self._show(self.list.currentRow())

    def _remove_folder(self):
        p = self.current()
        r = self.folders.currentRow()
        if p and 0 <= r < len(p.folders):
            del p.folders[r]
            self._show(self.list.currentRow())


def _pick_many(parent, title: str, label: str, items: list[str]) -> tuple[list[str], bool]:
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.resize(700, 420)
    lay = QVBoxLayout(d)
    lay.addWidget(QLabel(label))
    lst = QListWidget()
    for s in items:
        it = QListWidgetItem(s)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        name = os.path.basename(s).lower()
        it.setCheckState(Qt.Checked if ("sound" in name or "misc" in name) else Qt.Unchecked)
        lst.addItem(it)
    lay.addWidget(lst, 1)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    ok = d.exec() == QDialog.Accepted
    chosen = [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
    return chosen, ok
