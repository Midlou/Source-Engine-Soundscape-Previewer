"""Main application window: ties files, editor, browser and audio together."""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QByteArray, QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtCore import QLocale, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import keyvalues as kv
from ..audio import DEFAULT_SOUNDSCAPE_FADE, LIVE_EDIT_FADE, Engine, SoundBank, read_wav_loop_points
from ..gamedata import GameContent
from ..keyvalues import KVNode
from ..settings import Settings, default_tf2_profile
from ..soundscape import (
    RULE_LOOPING,
    RULE_RANDOM,
    RULE_SUBSCAPE,
    PlanBuilder,
    SoundscapeFile,
    is_wave_file,
    new_soundscape,
    normalize_wave,
    validate,
)
from .about import WIKI_URL, about_body, about_title
from .browser import SoundBrowser
from .editor import SoundscapeEditor
from .positions import PositionsView
from .preferences_dialog import PreferencesDialog
from .profiles_dialog import ProfilesDialog
from .script_editor import ScriptEditor
from .theme import THEMES, apply_theme


NEW_FILE_TEMPLATE = """// Soundscapes for my map.
// Save as tf/scripts/soundscapes_<mapname>.txt (or pack it into the BSP).

"mymap.outside"
{
	"dsp"	"1"
	"fadetime"	"2"

	"playlooping"
	{
		"volume"	"0.6"
		"pitch"	"100"
		"wave"	"ambient/outdoors.wav"
	}

	// birds chirping around the player
	"playrandom"
	{
		"time"	"3,8"
		"volume"	"0.3,0.6"
		"pitch"	"90,110"
		"position"	"random"
		"soundlevel"	"SNDLVL_70dB"
		"rndwave"
		{
			"wave"	"ambient/rottenburg/smallbird_01.wav"
			"wave"	"ambient/rottenburg/smallbird_02.wav"
			"wave"	"ambient/rottenburg/smallbird_03.wav"
		}
	}
}
"""


class _Loader(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soundscape Previewer")
        self.resize(1500, 900)
        self.settings = Settings.load()
        if self.settings.theme not in THEMES:
            self.settings.theme = "system"
        apply_theme(self.settings.theme)
        self.content: GameContent | None = None
        self.files: list[SoundscapeFile] = []
        self.current_file: SoundscapeFile | None = None
        self.current_name: str | None = None
        self.playing: tuple | None = None  # (file or None for game, name)
        self._loop_cache: dict[str, bool | None] = {}
        self._loader_thread = None

        self.bank = SoundBank(self._read_sound)
        self.engine = Engine(self.bank)
        self.engine.master = self.settings.master_volume
        self.engine.force_loop = self.settings.force_loop
        sp = self.engine.spatial
        if self.settings.positions and len(self.settings.positions) == len(sp.positions):
            sp.positions = [tuple(p) for p in self.settings.positions]
        if self.settings.enabled_positions and len(self.settings.enabled_positions) == len(sp.enabled):
            sp.enabled = list(self.settings.enabled_positions)
        if self.settings.listener:
            sp.listener = tuple(self.settings.listener[:2])
            if len(self.settings.listener) > 2:
                sp.listener_yaw = self.settings.listener[2]
        self.engine.start()

        self.builder = PlanBuilder(self.lookup_soundscape, self.lookup_game_sound)
        self._build_ui()
        self._build_actions()

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed_on_disk)

        self._replan_timer = QTimer(self, singleShot=True, interval=60)
        self._replan_timer.timeout.connect(lambda: self._replan(LIVE_EDIT_FADE))
        self._validate_timer = QTimer(self, singleShot=True, interval=500)
        self._validate_timer.timeout.connect(self._validate)
        self._ui_timer = QTimer(self, interval=33)
        self._ui_timer.timeout.connect(self._tick)
        self._ui_timer.start()
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save)
        self._update_auto_save_timer()

        if self.settings.geometry:
            self.restoreGeometry(QByteArray.fromBase64(self.settings.geometry.encode()))
        if self.settings.window_state:
            self.restoreState(QByteArray.fromBase64(self.settings.window_state.encode()))
        else:
            self.resizeDocks([self.dock_files, self.dock_browser], [260, 460], Qt.Horizontal)
            self.resizeDocks([self.dock_positions], [280], Qt.Vertical)

        for path in self.settings.open_files:
            if os.path.isfile(path):
                self._open_path(path, select=False)
        self._refresh_tree()
        if not self.settings.profiles:
            tf2 = default_tf2_profile()
            if tf2:
                self.settings.profiles.append(tf2)
                self.settings.active_profile = tf2.name
                self.statusBar().showMessage("Created a 'Team Fortress 2' profile from your Steam install.", 8000)
        self._fill_profile_combo()
        self._load_profile()
        if self.engine.error:
            QMessageBox.warning(self, "Audio", self.engine.error)

    # ================================================================ UI
    def _build_ui(self) -> None:
        # ---- left: files & soundscapes
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Soundscape files"])
        self.tree.header().setSectionResizeMode(QHeaderView.Stretch)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._tree_selected)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._play_selected() if it.data(0, Qt.UserRole + 1) else None)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        ll.addWidget(self.tree, 1)
        for text, slot in (("New soundscape", self._new_soundscape), ("New file", self._new_file), ("Open file…", self._open_file)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            ll.addWidget(b)
        dock = QDockWidget("Soundscapes", self)
        dock.setObjectName("dock_files")
        dock.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.dock_files = dock

        # ---- right: browser
        self.browser = SoundBrowser()
        self.browser.info_provider = self._sound_info
        self.browser.previewRequested.connect(self._preview)
        self.browser.stopRequested.connect(self.engine.stop_preview)
        self.browser.useRequested.connect(self._use_sound)
        self.browser.playSoundscape.connect(self._play_game_soundscape)
        self.browser.copySoundscape.connect(self._copy_game_soundscape)
        self.browser.useSoundscape.connect(self._add_subscape)
        self.browser.chk_click_play.setChecked(self.settings.click_to_play)
        self.browser.chk_click_play.toggled.connect(self._click_play_toggled)
        dock = QDockWidget("Sound browser", self)
        dock.setObjectName("dock_browser")
        dock.setWidget(self.browser)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.dock_browser = dock

        # ---- bottom: positions
        self.positions = PositionsView(self.engine)
        self.positions.changed.connect(self._save_settings_soon)
        dock = QDockWidget("Listener && positions (top-down, Hammer units)", self)
        dock.setObjectName("dock_positions")
        dock.setWidget(self.positions)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.dock_positions = dock

        # ---- center
        self.editor = SoundscapeEditor(self.browser.selected_sound, self._soundscape_names)
        self.editor.changed.connect(self._model_changed)
        self.editor.renamed.connect(self._rename_current)
        self.editor.previewWave.connect(lambda w: self._preview(normalize_wave(w) if is_wave_file(w) else w, False))
        self.editor.triggerRule.connect(self._trigger_rule)
        self.editor.mutesChanged.connect(lambda: self._replan(LIVE_EDIT_FADE))
        self.script = ScriptEditor()
        self.script.textEdited.connect(self._script_edited)
        self.problems = QTreeWidget()
        self.problems.setHeaderLabels(["", "Soundscape", "Rule", "Problem"])
        self.problems.setRootIsDecorated(False)
        self.problems.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.problems.itemDoubleClicked.connect(self._goto_problem)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.editor, "Editor")
        self.tabs.addTab(self.script, "Script")
        self.tabs.addTab(self.problems, "Problems")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        # ---- toolbar
        tb = QToolBar("Main")
        tb.setObjectName("toolbar_main")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addWidget(QLabel(" Profile: "))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.activated.connect(self._profile_chosen)
        tb.addWidget(self.profile_combo)
        b = QPushButton("Manage…")
        b.clicked.connect(self._manage_profiles)
        tb.addWidget(b)
        tb.addSeparator()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setToolTip("Play the selected soundscape (F5)")
        self.btn_play.clicked.connect(self._play_selected)
        tb.addWidget(self.btn_play)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setToolTip("Stop everything (F6)")
        self.btn_stop.clicked.connect(self._stop)
        tb.addWidget(self.btn_stop)
        self.chk_follow = QCheckBox("Play selection")
        self.chk_follow.setToolTip("While playing, switching soundscapes crossfades to the selected one, like walking into it in-game")
        self.chk_follow.setChecked(self.settings.auto_play)
        self.chk_follow.toggled.connect(self._follow_toggled)
        tb.addWidget(self.chk_follow)
        self.chk_force_loop = QCheckBox("Loop files without cue points")
        self.chk_force_loop.setToolTip("In-game, a playlooping WAV without a cue point plays only once. Check to loop them anyway.")
        self.chk_force_loop.setChecked(self.settings.force_loop)
        self.chk_force_loop.toggled.connect(self._force_loop_toggled)
        tb.addWidget(self.chk_force_loop)
        tb.addSeparator()
        tb.addWidget(QLabel(" Volume "))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(120)
        self.volume.setValue(int(self.settings.master_volume * 100))
        self.volume.valueChanged.connect(self._volume_changed)
        tb.addWidget(self.volume)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedSize(90, 12)
        tb.addWidget(self.meter)

        self.status_profile = QLabel("")
        self.statusBar().addPermanentWidget(self.status_profile)
        self.load_progress = QProgressBar()
        self.load_progress.setFixedWidth(160)
        self.load_progress.hide()
        self.statusBar().addPermanentWidget(self.load_progress)

    def _build_actions(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")

        def act(menu: QMenu, text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        act(m, "New soundscape file", self._new_file, "Ctrl+N")
        act(m, "Open soundscape file…", self._open_file, "Ctrl+O")
        act(m, "Save", self._save_current, "Ctrl+S")
        act(m, "Save as…", self._save_as)
        act(m, "Save all", self._save_all, "Ctrl+Shift+S")
        act(m, "Close file", self._close_current_file, "Ctrl+W")
        m.addSeparator()
        act(m, "Preferences…", self._preferences, "Ctrl+,")
        m.addSeparator()
        act(m, "Exit", self.close)
        m = mb.addMenu("&Soundscape")
        act(m, "New soundscape", self._new_soundscape, "Ctrl+Shift+N")
        act(m, "Duplicate", self._duplicate_soundscape, "Ctrl+D")
        act(m, "Rename…", self._rename_dialog, "F2")
        act(m, "Delete", self._delete_soundscape)
        m.addSeparator()
        act(m, "Play", self._play_selected, "F5")
        act(m, "Stop", self._stop, "F6")
        m = mb.addMenu("&Profiles")
        act(m, "Manage profiles…", self._manage_profiles)
        act(m, "Reload profile", self._load_profile)
        m = mb.addMenu("&View")
        for d in (self.dock_files, self.dock_browser, self.dock_positions):
            m.addAction(d.toggleViewAction())
        act(m, "Reset positions view", self.positions.reset_view)
        m = mb.addMenu("&Help")
        act(m, "Soundscape documentation (wiki)", lambda: QDesktopServices.openUrl(QUrl(WIKI_URL)))
        act(m, "About Soundscape Previewer", self._about)

    # =========================================================== profiles
    def _fill_profile_combo(self) -> None:
        self.profile_combo.clear()
        for p in self.settings.profiles:
            self.profile_combo.addItem(p.name)
        if self.settings.active_profile:
            i = self.profile_combo.findText(self.settings.active_profile)
            if i >= 0:
                self.profile_combo.setCurrentIndex(i)
        if self.profile_combo.count() == 0:
            self.profile_combo.addItem("(no profiles)")

    def _profile_chosen(self, _i: int) -> None:
        name = self.profile_combo.currentText()
        if self.settings.profile(name) and name != self.settings.active_profile:
            self.settings.active_profile = name
            self.settings.save()
            self._load_profile()

    def _manage_profiles(self) -> None:
        d = ProfilesDialog(self.settings.profiles, self.settings.active_profile, self)
        if d.exec():
            self.settings.profiles = d.profiles
            self.settings.active_profile = d.active if self.settings.profile(d.active) else (
                d.profiles[0].name if d.profiles else None
            )
            self.settings.save()
            self._fill_profile_combo()
            self._load_profile()

    def _load_profile(self) -> None:
        prof = self.settings.profile(self.settings.active_profile)
        if prof is None and self.settings.profiles:
            prof = self.settings.profiles[0]
            self.settings.active_profile = prof.name
        if prof is None:
            self._set_content(None, "")
            self.status_profile.setText("No game profile — Profiles → Manage profiles")
            return
        loader = _Loader(self)
        loader.progress.connect(self._load_progress)
        loader.finished.connect(self._set_content)
        self._loader = loader
        self.load_progress.show()
        self.status_profile.setText(f"Loading {prof.name}…")
        vpks, folders = prof.enabled_vpks(), list(prof.folders)

        def work():
            try:
                gc = GameContent.load(vpks, folders, lambda a, b, c: loader.progress.emit(a, b, c))
                loader.finished.emit(gc, prof.name)
            except Exception as e:  # noqa: BLE001
                gc = GameContent(errors=[str(e)])
                loader.finished.emit(gc, prof.name)

        self._loader_thread = threading.Thread(target=work, daemon=True)
        self._loader_thread.start()

    def _load_progress(self, step: int, total: int, path: str) -> None:
        self.load_progress.setRange(0, max(1, total))
        self.load_progress.setValue(step)
        self.statusBar().showMessage(f"Reading {os.path.basename(path)}…")

    def _set_content(self, content: GameContent | None, name: str) -> None:
        self.load_progress.hide()
        self.content = content
        self._loop_cache.clear()
        self.bank.set_reader(self._read_sound)
        self.browser.set_content(content)
        if content is not None:
            msg = f"{name}: {len(content.sounds):,} sounds, {len(content.soundscapes)} game soundscapes"
            if content.errors:
                msg += f" ({len(content.errors)} warnings)"
                self.status_profile.setToolTip("\n".join(content.errors[:30]))
            self.status_profile.setText(msg)
            self.statusBar().clearMessage()
        self._replan(LIVE_EDIT_FADE)
        self._validate()

    # ===================================================== lookups/helpers
    def _read_sound(self, path: str) -> bytes | None:
        return self.content.read_sound(path) if self.content else None

    def lookup_soundscape(self, name: str) -> KVNode | None:
        for f in self.files:
            n = f.find(name)
            if n is not None:
                return n
        if self.content:
            hit = self.content.soundscapes.get(name.lower())
            if hit:
                return hit[0]
        return None

    def lookup_game_sound(self, name: str):
        return self.content.game_sounds.get(name) if self.content else None

    def _soundscape_names(self) -> list[str]:
        names = []
        for f in self.files:
            names += [s.key for s in f.soundscapes]
        if self.content:
            names += sorted(n.key for n, _ in self.content.soundscapes.values())
        return names

    def _has_cue(self, path: str) -> bool | None:
        if path in self._loop_cache:
            return self._loop_cache[path]
        result = None
        if self.content and path.endswith(".wav"):
            try:
                data = self.content.read_sound(path)
                if data:
                    result = read_wav_loop_points(data)[0] is not None
            except OSError:
                result = None
        self._loop_cache[path] = result
        return result

    def _sound_info(self, path: str) -> str:
        if not self.content:
            return path
        src = self.content.sound_source(path)
        data = self.bank.get(path)
        if data is None:
            QTimer.singleShot(150, self.browser._sel_changed)
            return f"<b>{path}</b><br>{src} · loading…"
        if data is SoundBank.MISSING:
            return f"<b>{path}</b><br>{src} · could not decode: {self.bank.errors.get(path, '')}"
        ch = "stereo" if data.samples.shape[1] == 2 else "mono"
        if path.endswith(".mp3"):
            loop = "mp3 (cannot loop in-game)"
        elif data.loop_start is not None:
            loop = f"<span style='color:#16a34a'>cue point at sample {data.loop_start} (loops)</span>"
        else:
            loop = "<span style='color:#d97706'>no cue point (plays once in playlooping)</span>"
        return f"<b>{path}</b><br>{src} · {data.duration:.2f}s · {data.rate} Hz {ch}<br>{loop}"

    # ============================================================ files
    def _refresh_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        select = None
        for f in self.files:
            fi = QTreeWidgetItem([("● " if f.dirty else "") + f.display_name])
            fi.setToolTip(0, f.path or "Not saved yet")
            fi.setData(0, Qt.UserRole, f)
            font = fi.font(0)
            font.setBold(True)
            fi.setFont(0, font)
            self.tree.addTopLevelItem(fi)
            for s in f.soundscapes:
                label = s.key
                if self.playing and self.playing[0] is f and self.playing[1].lower() == s.key.lower():
                    label = "🔊 " + label
                si = QTreeWidgetItem([label])
                si.setData(0, Qt.UserRole, f)
                si.setData(0, Qt.UserRole + 1, s.key)
                fi.addChild(si)
                if f is self.current_file and self.current_name and s.key.lower() == self.current_name.lower():
                    select = si
            fi.setExpanded(True)
            if f is self.current_file and select is None and self.current_name is None:
                select = fi
        if select is not None:
            self.tree.setCurrentItem(select)
        self.tree.blockSignals(False)

    def _update_file_labels(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            f = it.data(0, Qt.UserRole)
            it.setText(0, ("● " if f.dirty else "") + f.display_name)
            for j in range(it.childCount()):
                c = it.child(j)
                name = c.data(0, Qt.UserRole + 1)
                playing = self.playing and self.playing[0] is f and self.playing[1].lower() == name.lower()
                c.setText(0, ("🔊 " if playing else "") + name)

    def _tree_selected(self, item, _prev=None) -> None:
        if item is None:
            return
        f = item.data(0, Qt.UserRole)
        name = item.data(0, Qt.UserRole + 1)
        self.current_file = f
        self.current_name = name
        scape = f.find(name) if name else None
        self.editor.set_soundscape(scape)
        self._sync_script(force=True)
        self._validate()
        if scape is not None and self.playing and self.chk_follow.isChecked():
            self._play(f, scape.key)

    def current_scape(self) -> KVNode | None:
        if self.current_file and self.current_name:
            return self.current_file.find(self.current_name)
        return None

    def _open_path(self, path: str, select: bool = True) -> SoundscapeFile | None:
        path = os.path.abspath(path)
        for f in self.files:
            if f.path and os.path.normcase(f.path) == os.path.normcase(path):
                return f
        try:
            f = SoundscapeFile.load(path)
        except kv.KVParseError as e:
            QMessageBox.warning(self, "Parse error", f"{path}\n\n{e}\n\nFix it in the Script tab.")
            f = SoundscapeFile(path)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                f.raw_text = fh.read()
            f.disk_mtime = os.path.getmtime(path)
        except OSError as e:
            QMessageBox.warning(self, "Open failed", str(e))
            return None
        self.files.append(f)
        self.watcher.addPath(path)
        if select:
            self.current_file = f
            self.current_name = f.soundscapes[0].key if f.soundscapes else None
            self._refresh_tree()
            self._tree_selected(self.tree.currentItem())
        self._remember_files()
        return f

    def _open_file(self) -> None:
        start = os.path.dirname(self.current_file.path) if self.current_file and self.current_file.path else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Open soundscape file", start, "Soundscape scripts (*.txt);;All files (*)")
        for p in paths:
            self._open_path(p)

    def _new_file(self) -> None:
        f = SoundscapeFile()
        f.set_text(NEW_FILE_TEMPLATE)
        self.files.append(f)
        self.current_file = f
        self.current_name = f.soundscapes[0].key
        self._refresh_tree()
        self._tree_selected(self.tree.currentItem())

    def _save_file(self, f: SoundscapeFile, save_as: bool = False) -> bool:
        if save_as or not f.path:
            start = f.path or os.path.join(os.path.expanduser("~"), "soundscapes_mymap.txt")
            path, _ = QFileDialog.getSaveFileName(self, "Save soundscape file", start, "Soundscape scripts (*.txt)")
            if not path:
                return False
            if f.path:
                self.watcher.removePath(f.path)
            f.path = path
        try:
            f.save()
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return False
        if f.path not in self.watcher.files():
            self.watcher.addPath(f.path)
        self._remember_files()
        self._update_file_labels()
        self.statusBar().showMessage(f"Saved {f.path}", 4000)
        return True

    def _save_current(self) -> None:
        if self.current_file:
            self._save_file(self.current_file)

    def _save_as(self) -> None:
        if self.current_file:
            self._save_file(self.current_file, save_as=True)
            self._refresh_tree()

    def _save_all(self) -> None:
        for f in self.files:
            if f.dirty:
                self._save_file(f)

    # =========================================================== auto save
    def _update_auto_save_timer(self) -> None:
        self.settings.auto_save_minutes = max(1, int(self.settings.auto_save_minutes))
        if self.settings.auto_save:
            self._auto_save_timer.start(self.settings.auto_save_minutes * 60_000)
        else:
            self._auto_save_timer.stop()

    def _auto_save(self) -> None:
        """Save modified files that already have a path. Never opens a dialog."""
        saved, failed = [], []
        for f in self.files:
            if not f.dirty or not f.path:
                continue  # new files need "Save as" first
            try:
                f.save()
                saved.append(f)
            except OSError:
                failed.append(f)
        if saved:
            self._remember_files()
            self._update_file_labels()
        if failed:
            self.statusBar().showMessage("Auto save failed for " + ", ".join(f.display_name for f in failed), 8000)
        elif saved:
            self.statusBar().showMessage(f"Auto saved {len(saved)} file{'s' if len(saved) != 1 else ''}", 4000)

    def _confirm_discard(self, f: SoundscapeFile) -> bool:
        if not f.dirty:
            return True
        r = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save changes to {f.display_name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if r == QMessageBox.Save:
            return self._save_file(f)
        return r == QMessageBox.Discard

    def _close_current_file(self) -> None:
        f = self.current_file
        if f is None or not self._confirm_discard(f):
            return
        if self.playing and self.playing[0] is f:
            self._stop()
        self.files.remove(f)
        if f.path:
            self.watcher.removePath(f.path)
        self.current_file = self.files[0] if self.files else None
        self.current_name = None
        self._refresh_tree()
        self._tree_selected(self.tree.currentItem()) if self.tree.currentItem() else self.editor.set_soundscape(None)
        self._remember_files()

    def _remember_files(self) -> None:
        self.settings.open_files = [f.path for f in self.files if f.path]
        self.settings.save()

    def _file_changed_on_disk(self, path: str) -> None:
        f = next((x for x in self.files if x.path and os.path.normcase(x.path) == os.path.normcase(path)), None)
        if f is None:
            return
        # editors often replace the file, which drops the watch
        QTimer.singleShot(200, lambda: os.path.isfile(path) and path not in self.watcher.files() and self.watcher.addPath(path))
        if not os.path.isfile(path):
            return
        mtime = os.path.getmtime(path)
        if f.disk_mtime is not None and abs(mtime - f.disk_mtime) < 1e-6:
            return
        if f.dirty and QMessageBox.question(
            self, "File changed", f"{f.display_name} changed on disk. Reload and lose your changes?"
        ) != QMessageBox.Yes:
            f.disk_mtime = mtime
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                f.set_text(fh.read())
        except kv.KVParseError as e:
            self.statusBar().showMessage(f"{f.display_name} changed on disk but has an error: {e}", 8000)
            return
        except OSError:
            return
        f.dirty = False
        f.disk_mtime = mtime
        self.statusBar().showMessage(f"Reloaded {f.display_name} from disk", 4000)
        self._after_structure_change()

    # ======================================================= soundscapes
    def _unique_name(self, f: SoundscapeFile, base: str) -> str:
        name, n = base, 2
        while f.find(name) is not None:
            name = f"{base}_{n}"
            n += 1
        return name

    def _ensure_file(self) -> SoundscapeFile:
        if self.current_file is None:
            f = SoundscapeFile()
            self.files.append(f)
            self.current_file = f
        return self.current_file

    def _new_soundscape(self) -> None:
        f = self._ensure_file()
        name, ok = QInputDialog.getText(self, "New soundscape", "Name (e.g. mymap.outside):", text=self._unique_name(f, "mymap.new"))
        if not ok or not name.strip():
            return
        name = self._unique_name(f, name.strip())
        f.nodes.append(new_soundscape(name))
        self._select_after_change(f, name)

    def _duplicate_soundscape(self) -> None:
        s = self.current_scape()
        if s is None:
            return
        f = self.current_file
        c = s.clone()
        c.key = self._unique_name(f, s.key + "_copy")
        f.nodes.insert(f.nodes.index(s) + 1, c)
        self._select_after_change(f, c.key)

    def _rename_dialog(self) -> None:
        s = self.current_scape()
        if s is None:
            return
        name, ok = QInputDialog.getText(self, "Rename soundscape", "Name:", text=s.key)
        if ok and name.strip():
            self._rename_current(name.strip())

    def _rename_current(self, name: str) -> None:
        s = self.current_scape()
        f = self.current_file
        if s is None or name == s.key:
            return
        if f.find(name) is not None and f.find(name) is not s:
            QMessageBox.warning(self, "Rename", f"'{name}' already exists in this file.")
            self.editor.set_soundscape(s)
            return
        was_playing = self.playing and self.playing[0] is f and self.playing[1].lower() == s.key.lower()
        s.key = name
        if was_playing:
            self.playing = (f, name)
        self._select_after_change(f, name)

    def _delete_soundscape(self) -> None:
        s = self.current_scape()
        if s is None:
            return
        if QMessageBox.question(self, "Delete", f"Delete soundscape '{s.key}'?") != QMessageBox.Yes:
            return
        f = self.current_file
        idx = f.soundscapes.index(s)
        f.nodes.remove(s)
        rest = f.soundscapes
        self._select_after_change(f, rest[min(idx, len(rest) - 1)].key if rest else None)

    def _select_after_change(self, f: SoundscapeFile, name: str | None) -> None:
        f.dirty = True
        self.current_file = f
        self.current_name = name
        self._refresh_tree()
        self._tree_selected(self.tree.currentItem())
        self._model_changed()

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        m = QMenu(self)
        if item is not None:
            is_scape = item.data(0, Qt.UserRole + 1) is not None
            if is_scape:
                m.addAction("▶ Play", self._play_selected)
                m.addAction("Rename…", self._rename_dialog)
                m.addAction("Duplicate", self._duplicate_soundscape)
                m.addAction("Delete", self._delete_soundscape)
                m.addSeparator()
            m.addAction("New soundscape", self._new_soundscape)
            m.addAction("Save", self._save_current)
            m.addAction("Save as…", self._save_as)
            f = item.data(0, Qt.UserRole)
            if f.path:
                m.addAction("Show in Explorer", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(f.path))))
            m.addAction("Close file", self._close_current_file)
        else:
            m.addAction("New file", self._new_file)
            m.addAction("Open file…", self._open_file)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ============================================================ editing
    def _model_changed(self) -> None:
        f = self.current_file
        if f is not None and not f.dirty:
            f.dirty = True
            self._update_file_labels()
        self._sync_script()
        self._replan_timer.start()
        self._validate_timer.start()

    def _sync_script(self, force: bool = False) -> None:
        f = self.current_file
        if f is None:
            self.script.set_text("")
            return
        if force or not self.script.is_editing():
            self.script.set_text(f.to_text())
            self.script.set_status("Edits here are applied live while you type.")

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is self.script:
            self._sync_script(force=True)
        elif self.tabs.widget(idx) is self.problems:
            self._validate()

    def _script_edited(self, text: str) -> None:
        f = self.current_file
        if f is None:
            f = self._ensure_file()
        if text == f.to_text():
            return
        try:
            f.set_text(text)
        except kv.KVParseError as e:
            self.script.set_status(f"⚠ {e} — the last valid version keeps playing.", error=True)
            return
        self._after_structure_change()
        self.script.set_status("✓ Parsed and applied.")

    def _after_structure_change(self) -> None:
        """The node tree of a file was replaced (text edit or reload)."""
        f = self.current_file
        rule_idx = None
        cur = self.editor.current_rule()
        if cur is not None and self.editor.scape is not None:
            rules = self.editor.rule_nodes()
            rule_idx = rules.index(cur) if cur in rules else None
        if f is not None and self.current_name and f.find(self.current_name) is None:
            self.current_name = f.soundscapes[0].key if f.soundscapes else None
        self._refresh_tree()
        scape = self.current_scape()
        self.editor.set_soundscape(scape, rule_idx)
        self._update_file_labels()
        if self.tabs.currentWidget() is not self.script:
            self._sync_script(force=True)
        self._replan(LIVE_EDIT_FADE)
        self._validate_timer.start()

    def _use_sound(self, sound: str) -> None:
        rule = self.editor.current_rule()
        scape = self.current_scape()
        if scape is None:
            self.statusBar().showMessage("Select a soundscape first", 3000)
            return
        if rule is None or rule.key.lower() == RULE_SUBSCAPE:
            rule = self.editor.add_rule(RULE_LOOPING)
            rule.set("wave", sound)
        elif rule.key.lower() == RULE_LOOPING:
            rule.set("wave", sound)
        elif rule.key.lower() == RULE_RANDOM:
            rnd = rule.find("rndwave")
            if rnd is None or not rnd.is_block:
                rnd = KVNode("rndwave", children=[])
                rule.children.append(rnd)
            rnd.children.append(KVNode("wave", sound))
        self.editor.refresh_rules()
        self._model_changed()

    def _add_subscape(self, name: str) -> None:
        if self.current_scape() is None:
            self.statusBar().showMessage("Select a soundscape first", 3000)
            return
        rule = self.editor.add_rule(RULE_SUBSCAPE)
        rule.set("name", name)
        self.editor.refresh_rules()
        self._model_changed()

    def _copy_game_soundscape(self, name: str) -> None:
        if not self.content:
            return
        node = self.content.soundscapes[name.lower()][0].clone()
        f = self._ensure_file()
        node.key = self._unique_name(f, node.key)
        f.nodes.append(node)
        self._select_after_change(f, node.key)

    # ============================================================ playback
    def _play(self, f: SoundscapeFile | None, name: str) -> None:
        changed = self.playing is None or self.playing[0] is not f or self.playing[1].lower() != name.lower()
        self.playing = (f, name)
        if changed:
            scape = self._playing_node()
            fade = DEFAULT_SOUNDSCAPE_FADE
            if scape is not None:
                ft = scape.get("fadetime")
                if ft is not None:
                    try:
                        v = float(ft)
                        fade = v if v > 0 else DEFAULT_SOUNDSCAPE_FADE
                    except ValueError:
                        pass
            first = self.engine.plan is None
            self._replan(0.3 if first else fade)
        self._update_file_labels()

    def _play_selected(self) -> None:
        s = self.current_scape()
        if s is not None:
            self._play(self.current_file, s.key)

    def _play_game_soundscape(self, name: str) -> None:
        self._play(None, name)

    def _stop(self) -> None:
        self.playing = None
        self.engine.stop(0.4)
        self.engine.stop_preview()
        self._update_file_labels()

    def _playing_node(self) -> KVNode | None:
        if not self.playing:
            return None
        f, name = self.playing
        if f is None:
            hit = self.content.soundscapes.get(name.lower()) if self.content else None
            return hit[0] if hit else None
        return f.find(name)

    def _replan(self, fade: float) -> None:
        if not self.playing:
            return
        scape = self._playing_node()
        if scape is None:
            self.engine.stop(0.3)
            return
        displayed = self.editor.scape is scape
        plan = self.builder.build(
            scape,
            self.editor.muted if displayed else set(),
            self.editor.soloed if displayed else set(),
        )
        self.engine.apply_plan(plan, fade)
        if plan.warnings:
            self.statusBar().showMessage("; ".join(plan.warnings), 5000)

    def _trigger_rule(self, rule: KVNode | None) -> None:
        scape = self.current_scape()
        if rule is None or scape is None:
            return
        if self._playing_node() is not scape:
            self._play(self.current_file, scape.key)
            self._replan(0.3)
        idx = scape.children.index(rule)
        self.engine.trigger(str(idx))

    def _preview(self, path: str, loop: bool) -> None:
        if not is_wave_file(path):
            gs = self.lookup_game_sound(path.strip().lower())
            if gs is None:
                self.statusBar().showMessage(f"Unknown sound '{path}'", 3000)
                return
            import random

            path = normalize_wave(random.choice(gs.waves))
        if self.content and not self.content.sound_exists(path):
            self.statusBar().showMessage(f"Sound not found in this profile: {path}", 4000)
            return
        self.engine.preview(path, loop)
        self.statusBar().showMessage(f"Previewing {path}", 3000)

    def _preferences(self) -> None:
        dlg = PreferencesDialog(self.settings, self)
        if dlg.exec() != QDialog.Accepted:
            return
        dlg.apply_to(self.settings)
        apply_theme(self.settings.theme)
        self._update_auto_save_timer()
        self._save_settings_soon()

    def _follow_toggled(self, on: bool) -> None:
        self.settings.auto_play = on
        self._save_settings_soon()

    def _click_play_toggled(self, on: bool) -> None:
        self.settings.click_to_play = on
        self._save_settings_soon()

    def _force_loop_toggled(self, on: bool) -> None:
        self.engine.force_loop = on
        self.settings.force_loop = on
        self._save_settings_soon()
        if self.playing:
            # restart loops so the setting applies
            plan = self.engine.plan
            self.engine.apply_plan(None, 0.1)
            self.engine.apply_plan(plan, 0.1)

    def _volume_changed(self, v: int) -> None:
        self.engine.master = v / 100.0
        self.settings.master_volume = v / 100.0
        self._save_settings_soon()

    def _tick(self) -> None:
        snap = self.engine.snapshot()
        self.positions.update_snapshot(snap)
        self.meter.setValue(int(min(1.0, snap["peak"]) * 100))
        scape = self.editor.scape
        active: set[int] = set()
        waves: dict[int, set[int]] = {}
        timers: dict[int, tuple[float, int]] = {}
        if scape is not None and self._playing_node() is scape:
            children = scape.children

            def rule_uid(key: str) -> int | None:
                try:
                    i = int(key.split(">")[0])
                except ValueError:
                    return None
                return children[i].uid if 0 <= i < len(children) else None

            for lp in snap["loops"]:
                uid = rule_uid(lp["key"])
                if uid is not None and lp["playing"] and lp["level"] > 0.001:
                    active.add(uid)
            for shot in snap["oneshots"]:
                uid = rule_uid(shot["key"])
                if uid is None:
                    continue
                active.add(uid)
                if ">" not in shot["key"]:  # rndwave rows exist only for the rule's own entries
                    waves.setdefault(uid, set()).add(shot["entry"])
            for key, (remaining, entry) in snap["randoms"].items():
                uid = rule_uid(key)
                if uid is not None and ">" not in key:
                    timers[uid] = (remaining, entry)
        self.editor.set_active(active, waves, timers)
        if self.engine.error and not getattr(self, "_shown_engine_error", False):
            self._shown_engine_error = True
            self.statusBar().showMessage(self.engine.error, 10000)

    # ========================================================= validation
    def _validate(self) -> None:
        self.problems.clear()
        f = self.current_file
        if f is None:
            self.tabs.setTabText(2, "Problems")
            return
        others: dict[str, str] = {}
        for other in self.files:
            if other is not f:
                for s in other.soundscapes:
                    others[s.key.lower()] = other.display_name
        if self.content:
            for k, (_n, src) in self.content.soundscapes.items():
                others.setdefault(k, src)
        problems = validate(
            f,
            self.lookup_soundscape,
            self.lookup_game_sound,
            self.content.sound_exists if self.content else (lambda _p: True),
            self._has_cue,
            others,
        )
        icons = {"error": "⛔", "warning": "⚠", "info": "ℹ"}
        for p in problems:
            it = QTreeWidgetItem([icons.get(p.severity, ""), p.soundscape, p.rule, p.message])
            it.setData(0, Qt.UserRole, (p.soundscape, p.rule_uid))
            self.problems.addTopLevelItem(it)
        n_err = sum(1 for p in problems if p.severity == "error")
        n_warn = sum(1 for p in problems if p.severity == "warning")
        self.tabs.setTabText(2, f"Problems ({n_err} ⛔ {n_warn} ⚠)" if problems else "Problems")

    def _goto_problem(self, item) -> None:
        name, uid = item.data(0, Qt.UserRole)
        self.current_name = name
        self._refresh_tree()
        self._tree_selected(self.tree.currentItem())
        if uid is not None:
            self.editor.select_rule(uid)
        self.tabs.setCurrentWidget(self.editor)

    # ============================================================ misc
    def _save_settings_soon(self) -> None:
        if not hasattr(self, "_settings_timer"):
            self._settings_timer = QTimer(self, singleShot=True, interval=1000)
            self._settings_timer.timeout.connect(self._save_settings)
        self._settings_timer.start()

    def _save_settings(self) -> None:
        sp = self.engine.spatial
        self.settings.positions = [list(p) for p in sp.positions]
        self.settings.enabled_positions = list(sp.enabled)
        self.settings.listener = [sp.listener[0], sp.listener[1], sp.listener_yaw]
        self.settings.geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.window_state = bytes(self.saveState().toBase64()).decode()
        self.settings.save()

    def _about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("About Soundscape Previewer")
        box.setTextFormat(Qt.RichText)
        box.setText(about_title())
        box.setInformativeText(about_body())
        box.setIcon(QMessageBox.Information)
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
        box.exec()

    def closeEvent(self, e) -> None:
        for f in list(self.files):
            if not self._confirm_discard(f):
                e.ignore()
                return
        self._save_settings()
        self.engine.close()
        e.accept()


def run() -> int:
    import sys

    # Source scripts use "." decimals; don't let a system locale turn them into ","
    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Soundscape Previewer")
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    return app.exec()
