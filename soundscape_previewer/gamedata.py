"""Game content index built from a profile's VPKs and loose folders."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field

from . import keyvalues as kv
from .keyvalues import KVNode
from .soundscape import SOUND_EXTENSIONS, GameSound, parse_game_sounds
from .vpk import VPK


class FolderSource:
    """A loose game/content folder (e.g. tf/ or tf/custom/mymap)."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.entries: dict[str, str] = {}
        root = self.path
        # Picking the "sound" folder itself is also allowed.
        if os.path.basename(root).lower() == "sound":
            self._walk(root, "sound")
            return
        # A content folder (tf/, tf/custom/mymap/), or a folder of them (tf/custom/).
        roots = [root]
        if not any(os.path.isdir(os.path.join(root, s)) for s in ("sound", "scripts")):
            roots = [os.path.join(root, d) for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d))]
        for r in roots:
            for sub in ("sound", "scripts"):
                d = os.path.join(r, sub)
                if os.path.isdir(d):
                    self._walk(d, sub)

    def _walk(self, directory: str, prefix: str) -> None:
        for dirpath, _dirs, files in os.walk(directory):
            rel = os.path.relpath(dirpath, directory).replace("\\", "/")
            rel = "" if rel == "." else rel + "/"
            for f in files:
                self.entries[f"{prefix}/{rel}{f}".lower()] = os.path.join(dirpath, f)

    def read(self, path: str) -> bytes:
        with open(self.entries[path], "rb") as f:
            return f.read()


@dataclass
class GameContent:
    sources: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sounds: dict[str, object] = field(default_factory=dict)  # sound path (relative to sound/) -> source
    game_sounds: dict[str, GameSound] = field(default_factory=dict)
    soundscapes: dict[str, tuple[KVNode, str]] = field(default_factory=dict)  # lname -> (node, file)

    @classmethod
    def load(cls, vpk_paths: list[str], folders: list[str], progress=None) -> "GameContent":
        gc = cls()
        total = len(vpk_paths) + len(folders)
        step = 0
        # Loose folders override VPK content, like the engine's search paths.
        for folder in folders:
            step += 1
            if progress:
                progress(step, total, folder)
            try:
                gc.sources.append(FolderSource(folder))
            except OSError as e:
                gc.errors.append(f"{folder}: {e}")
        for path in vpk_paths:
            step += 1
            if progress:
                progress(step, total, path)
            try:
                gc.sources.append(VPK(path))
            except Exception as e:  # noqa: BLE001 - report any broken VPK
                gc.errors.append(f"{os.path.basename(path)}: {e}")
        gc._index()
        return gc

    @staticmethod
    def _source_name(src) -> str:
        return os.path.basename(src.path)

    def _index(self) -> None:
        for src in self.sources:
            for name in src.entries:
                if name.startswith("sound/") and name.endswith(SOUND_EXTENSIONS):
                    self.sounds.setdefault(name[6:], src)
        # Scripts are applied lowest priority first so higher priority wins.
        for src in reversed(self.sources):
            for name in sorted(src.entries):
                if not name.startswith("scripts/"):
                    continue
                base = name[8:]
                if "/" in base:
                    continue
                is_gs = fnmatch.fnmatch(base, "game_sounds*.txt") or fnmatch.fnmatch(base, "level_sounds*.txt")
                is_ss = fnmatch.fnmatch(base, "soundscapes_*.txt")
                if not (is_gs or is_ss) or "manifest" in base or "phonemes" in base:
                    continue
                try:
                    text = src.read(name).decode("utf-8", "replace")
                except Exception as e:  # noqa: BLE001
                    self.errors.append(f"{name}: {e}")
                    continue
                label = f"{self._source_name(src)}:{name}"
                try:
                    if is_gs:
                        self.game_sounds.update(parse_game_sounds(text, label))
                    else:
                        for node in kv.parse(text):
                            if node.is_block:
                                self.soundscapes[node.key.lower()] = (node, label)
                except kv.KVParseError as e:
                    self.errors.append(f"{label}: {e}")

    def sound_exists(self, path: str) -> bool:
        return path in self.sounds

    def read_sound(self, path: str) -> bytes | None:
        src = self.sounds.get(path)
        if src is None:
            return None
        return src.read("sound/" + path)

    def sound_source(self, path: str) -> str:
        src = self.sounds.get(path)
        return self._source_name(src) if src else ""
