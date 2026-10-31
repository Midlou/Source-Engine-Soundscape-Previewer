"""Browser for the sounds, soundscripts and soundscapes of the active profile."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..gamedata import GameContent

MAX_RESULTS = 3000
_PLACEHOLDER = "__placeholder__"


class _DragTree(QTreeWidget):
    def mimeData(self, items):
        md = QMimeData()
        md.setText("\n".join(i.data(0, Qt.UserRole) for i in items if i.data(0, Qt.UserRole)))
        return md


class _DragList(QListWidget):
    def mimeData(self, items):
        md = QMimeData()
        md.setText("\n".join(i.data(Qt.UserRole) or i.text() for i in items))
        return md


def _search_box(placeholder: str) -> QLineEdit:
    s = QLineEdit()
    s.setPlaceholderText(placeholder)
    s.setClearButtonEnabled(True)
    return s


class SoundBrowser(QWidget):
    previewRequested = Signal(str, bool)  # sound path, loop
    stopRequested = Signal()
    useRequested = Signal(str)  # sound path or soundscript name
    playSoundscape = Signal(str)
    copySoundscape = Signal(str)
    useSoundscape = Signal(str)
    selectionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.content: GameContent | None = None
        self._paths: list[str] = []
        self.info_provider = None  # callable(path) -> str
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # ---- sound files
        files = QWidget()
        fl = QVBoxLayout(files)
        fl.setContentsMargins(0, 4, 0, 0)
        self.search = _search_box("Search sounds (e.g. ambient wind loop)")
        fl.addWidget(self.search)
        self.stack = QStackedWidget()
        self.tree = _DragTree()
        self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.results = _DragList()
        self.results.setDragEnabled(True)
        self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results.setUniformItemSizes(True)
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.results)
        fl.addWidget(self.stack, 1)
        self.info = QLabel("No profile loaded.")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fl.addWidget(self.info)
        row = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_loop = QPushButton("⟳ Loop")
        self.btn_loop.setToolTip("Play looped (from the cue point if the file has one)")
        self.btn_stop = QPushButton("■ Stop")
        self.btn_use = QPushButton("Use in rule")
        self.btn_use.setToolTip("Set as the wave of the selected looping rule, or add to the selected random rule")
        for b in (self.btn_play, self.btn_loop, self.btn_stop, self.btn_use):
            row.addWidget(b)
        fl.addLayout(row)
        self.tabs.addTab(files, "Sound files")

        # ---- soundscripts
        scripts = QWidget()
        sl = QVBoxLayout(scripts)
        sl.setContentsMargins(0, 4, 0, 0)
        self.gs_search = _search_box("Search soundscript entries (e.g. Ambient.)")
        sl.addWidget(self.gs_search)
        self.gs_list = _DragList()
        self.gs_list.setDragEnabled(True)
        self.gs_list.setUniformItemSizes(True)
        sl.addWidget(self.gs_list, 1)
        self.gs_info = QLabel("")
        self.gs_info.setWordWrap(True)
        sl.addWidget(self.gs_info)
        row = QHBoxLayout()
        self.gs_play = QPushButton("▶ Play")
        self.gs_stop = QPushButton("■ Stop")
        self.gs_use = QPushButton("Use in rule")
        for b in (self.gs_play, self.gs_stop, self.gs_use):
            row.addWidget(b)
        sl.addLayout(row)
        self.tabs.addTab(scripts, "Soundscripts")

        # ---- game soundscapes
        scapes = QWidget()
        cl = QVBoxLayout(scapes)
        cl.setContentsMargins(0, 4, 0, 0)
        self.ss_search = _search_box("Search game soundscapes")
        cl.addWidget(self.ss_search)
        self.ss_list = QListWidget()
        self.ss_list.setUniformItemSizes(True)
        cl.addWidget(self.ss_list, 1)
        self.ss_info = QLabel("")
        self.ss_info.setWordWrap(True)
        cl.addWidget(self.ss_info)
        row = QHBoxLayout()
        self.ss_play = QPushButton("▶ Play")
        self.ss_copy = QPushButton("Copy to my file")
        self.ss_copy.setToolTip("Copy this soundscape into the selected soundscape file so you can edit it")
        self.ss_use = QPushButton("Add as sub-soundscape")
        for b in (self.ss_play, self.ss_copy, self.ss_use):
            row.addWidget(b)
        cl.addLayout(row)
        self.tabs.addTab(scapes, "Game soundscapes")

        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.gs_search.textChanged.connect(self._fill_game_sounds)
        self.ss_search.textChanged.connect(self._fill_soundscapes)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._play(False) if it.data(0, Qt.UserRole) else None)
        self.results.itemDoubleClicked.connect(lambda _it: self._play(False))
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.results.itemSelectionChanged.connect(self._sel_changed)
        self.btn_play.clicked.connect(lambda: self._play(False))
        self.btn_loop.clicked.connect(lambda: self._play(True))
        self.btn_stop.clicked.connect(self.stopRequested)
        self.btn_use.clicked.connect(self._use)
        self.gs_list.currentItemChanged.connect(self._gs_selected)
        self.gs_list.itemDoubleClicked.connect(lambda _it: self._gs_play())
        self.gs_play.clicked.connect(self._gs_play)
        self.gs_stop.clicked.connect(self.stopRequested)
        self.gs_use.clicked.connect(lambda: self.gs_list.currentItem() and self.useRequested.emit(self.gs_list.currentItem().text()))
        self.ss_list.currentItemChanged.connect(self._ss_selected)
        self.ss_list.itemDoubleClicked.connect(lambda it: self.playSoundscape.emit(it.text()))
        self.ss_play.clicked.connect(lambda: self.ss_list.currentItem() and self.playSoundscape.emit(self.ss_list.currentItem().text()))
        self.ss_copy.clicked.connect(lambda: self.ss_list.currentItem() and self.copySoundscape.emit(self.ss_list.currentItem().text()))
        self.ss_use.clicked.connect(lambda: self.ss_list.currentItem() and self.useSoundscape.emit(self.ss_list.currentItem().text()))

    # ------------------------------------------------------------------
    def set_content(self, content: GameContent | None) -> None:
        self.content = content
        self._paths = sorted(content.sounds) if content else []
        self._build_tree()
        self._run_search()
        self._fill_game_sounds()
        self._fill_soundscapes()
        if content is None:
            self.info.setText("No profile loaded. Create one in Profiles → Manage profiles.")
        else:
            self.info.setText(f"{len(self._paths):,} sounds. Double-click to play, drag into a rule to use.")

    def _build_tree(self) -> None:
        self.tree.clear()
        root: dict = {}
        for p in self._paths:
            node = root
            parts = p.split("/")
            for d in parts[:-1]:
                node = node.setdefault(d + "/", {})
            node[parts[-1]] = p
        self._tree_data = root
        self._add_children(self.tree.invisibleRootItem(), root)

    def _add_children(self, parent: QTreeWidgetItem, node: dict) -> None:
        folders = sorted(k for k in node if k.endswith("/"))
        files = sorted(k for k in node if not k.endswith("/"))
        for f in folders:
            it = QTreeWidgetItem([f[:-1]])
            it.setData(0, Qt.UserRole + 1, node[f])
            it.setFlags(it.flags() & ~Qt.ItemIsDragEnabled)
            QTreeWidgetItem(it, [_PLACEHOLDER])
            parent.addChild(it)
        for f in files:
            it = QTreeWidgetItem([f])
            it.setData(0, Qt.UserRole, node[f])
            parent.addChild(it)

    def _expand(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).text(0) == _PLACEHOLDER:
            item.takeChild(0)
            self._add_children(item, item.data(0, Qt.UserRole + 1))

    def _run_search(self) -> None:
        terms = self.search.text().lower().split()
        if not terms:
            self.stack.setCurrentWidget(self.tree)
            return
        self.stack.setCurrentWidget(self.results)
        self.results.clear()
        count = 0
        for p in self._paths:
            if all(t in p for t in terms):
                it = QListWidgetItem(p)
                it.setData(Qt.UserRole, p)
                self.results.addItem(it)
                count += 1
                if count >= MAX_RESULTS:
                    break
        self.info.setText(f"{count:,}{'+' if count >= MAX_RESULTS else ''} matching sounds")

    def selected_sounds(self) -> list[str]:
        if self.tabs.currentIndex() == 1:
            it = self.gs_list.currentItem()
            return [it.text()] if it else []
        if self.stack.currentWidget() is self.tree:
            return [i.data(0, Qt.UserRole) for i in self.tree.selectedItems() if i.data(0, Qt.UserRole)]
        return [i.data(Qt.UserRole) for i in self.results.selectedItems()]

    def selected_sound(self) -> str | None:
        s = self.selected_sounds()
        return s[0] if s else None

    def _sel_changed(self) -> None:
        s = self.selected_sound()
        if s and self.info_provider:
            self.info.setText(self.info_provider(s))
        self.selectionChanged.emit()

    def _play(self, loop: bool) -> None:
        s = self.selected_sound()
        if s:
            self.previewRequested.emit(s, loop)
            if self.info_provider:
                self.info.setText(self.info_provider(s))

    def _use(self) -> None:
        for s in self.selected_sounds():
            self.useRequested.emit(s)

    # ---- soundscripts
    def _fill_game_sounds(self) -> None:
        self.gs_list.clear()
        if not self.content:
            return
        terms = self.gs_search.text().lower().split()
        names = sorted(gs.name for k, gs in self.content.game_sounds.items() if all(t in k for t in terms))
        for n in names[:MAX_RESULTS]:
            self.gs_list.addItem(n)
        self.gs_info.setText(f"{len(names):,} soundscript entries. They can be used as a 'wave' value.")

    def _gs_selected(self, item) -> None:
        if not item or not self.content:
            return
        gs = self.content.game_sounds.get(item.text().lower())
        if gs:
            waves = "<br>".join(gs.waves[:8]) + ("<br>…" if len(gs.waves) > 8 else "")
            self.gs_info.setText(
                f"<b>{gs.name}</b> ({gs.source})<br>volume {gs.volume[0]:g}-{gs.volume[1]:g}, "
                f"pitch {gs.pitch[0]:g}-{gs.pitch[1]:g}<br>{waves}"
            )

    def _gs_play(self) -> None:
        item = self.gs_list.currentItem()
        if item and self.content:
            gs = self.content.game_sounds.get(item.text().lower())
            if gs:
                import random

                from ..soundscape import normalize_wave

                self.previewRequested.emit(normalize_wave(random.choice(gs.waves)), False)

    # ---- game soundscapes
    def _fill_soundscapes(self) -> None:
        self.ss_list.clear()
        if not self.content:
            return
        terms = self.ss_search.text().lower().split()
        names = sorted(node.key for k, (node, _src) in self.content.soundscapes.items() if all(t in k for t in terms))
        self.ss_list.addItems(names)
        self.ss_info.setText(f"{len(names):,} soundscapes from the game's scripts")

    def _ss_selected(self, item) -> None:
        if not item or not self.content:
            return
        node, src = self.content.soundscapes[item.text().lower()]
        rules = [c.key for c in node.children if c.is_block]
        self.ss_info.setText(f"<b>{node.key}</b><br>{src}<br>{len(rules)} rules")
