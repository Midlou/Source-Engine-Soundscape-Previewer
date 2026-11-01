"""Persistent settings and game profiles (stored in settings.json)."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir() -> str:
    """data/ next to the sources, or %APPDATA%/SoundscapePreviewer for the .exe build."""
    if os.environ.get("SSP_DATA_DIR"):
        return os.environ["SSP_DATA_DIR"]
    if getattr(sys, "frozen", False):
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SoundscapePreviewer")
    return os.path.join(ROOT, "data")


DATA_DIR = _data_dir()
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


@dataclass
class VpkRef:
    path: str
    enabled: bool = True


@dataclass
class Profile:
    name: str
    vpks: list[VpkRef] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)

    def enabled_vpks(self) -> list[str]:
        return [v.path for v in self.vpks if v.enabled]

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            d.get("name", "Profile"),
            [VpkRef(v["path"], v.get("enabled", True)) for v in d.get("vpks", [])],
            list(d.get("folders", [])),
        )


@dataclass
class Settings:
    profiles: list[Profile] = field(default_factory=list)
    active_profile: str | None = None
    open_files: list[str] = field(default_factory=list)
    master_volume: float = 0.8
    auto_play: bool = True
    theme: str = "system"  # "system", "light" or "dark"
    force_loop: bool = False
    click_to_play: bool = True
    auto_save: bool = True
    auto_save_minutes: int = 5
    positions: list | None = None
    enabled_positions: list | None = None
    listener: list | None = None
    geometry: str | None = None
    window_state: str | None = None

    def profile(self, name: str | None) -> Profile | None:
        return next((p for p in self.profiles if p.name == name), None)

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return cls()
        s = cls()
        for k in asdict(s):
            if k in d and k != "profiles":
                setattr(s, k, d[k])
        s.profiles = [Profile.from_dict(p) for p in d.get("profiles", [])]
        return s

    def save(self) -> None:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, SETTINGS_PATH)


# ------------------------------------------------------------ steam helpers


def steam_libraries() -> list[str]:
    roots = []
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            roots.append(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        pass
    roots += [r"C:\Program Files (x86)\Steam", os.path.expanduser("~/.steam/steam")]
    libs: list[str] = []
    for root in roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if not os.path.isfile(vdf):
            continue
        libs.append(os.path.normpath(root))
        with open(vdf, "r", encoding="utf-8", errors="replace") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                libs.append(os.path.normpath(m.group(1).replace("\\\\", "\\")))
    seen, out = set(), []
    for lib in libs:
        if lib.lower() not in seen:
            seen.add(lib.lower())
            out.append(lib)
    return out


def find_game(folder_name: str) -> str | None:
    for lib in steam_libraries():
        p = os.path.join(lib, "steamapps", "common", folder_name)
        if os.path.isdir(p):
            return p
    return None


def find_dir_vpks(folder: str, depth: int = 2) -> list[str]:
    """Find *_dir.vpk files in a folder and its subfolders (to a small depth)."""
    found = []
    base_depth = folder.rstrip("\\/").count(os.sep)
    for dirpath, dirs, files in os.walk(folder):
        if dirpath.count(os.sep) - base_depth >= depth:
            dirs[:] = []
        for f in files:
            if f.lower().endswith("_dir.vpk"):
                found.append(os.path.join(dirpath, f))
    return sorted(found)


TF2_DEFAULT_VPKS = [
    r"tf\tf2_sound_misc_dir.vpk",
    r"tf\tf2_sound_vo_english_dir.vpk",
    r"tf\tf2_misc_dir.vpk",
    r"hl2\hl2_sound_misc_dir.vpk",
    r"hl2\hl2_sound_vo_english_dir.vpk",
    r"hl2\hl2_misc_dir.vpk",
]


def default_tf2_profile() -> Profile | None:
    game = find_game("Team Fortress 2")
    if not game:
        return None
    vpks = [VpkRef(os.path.join(game, rel)) for rel in TF2_DEFAULT_VPKS if os.path.isfile(os.path.join(game, rel))]
    if not vpks:
        return None
    folders = [os.path.join(game, "tf", "custom")] if os.path.isdir(os.path.join(game, "tf", "custom")) else []
    return Profile("Team Fortress 2", vpks, folders)
