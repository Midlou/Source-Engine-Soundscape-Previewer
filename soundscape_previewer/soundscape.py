"""Soundscape model: files, value parsing, playback plans and validation.

Behaviour follows the Source engine's c_soundscape.cpp as described on
https://developer.valvesoftware.com/wiki/Soundscape
"""
from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass, field
from typing import Callable, Union

from . import keyvalues as kv
from .keyvalues import KVNode

SOUND_EXTENSIONS = (".wav", ".mp3", ".ogg")
# Leading "sound characters" Source uses to flag streaming, music, spatial stereo...
SOUND_CHARS = "*#@<>^)(}$!?&~`+%"

RULE_LOOPING = "playlooping"
RULE_RANDOM = "playrandom"
RULE_SUBSCAPE = "playsoundscape"
RULE_TYPES = (RULE_LOOPING, RULE_RANDOM, RULE_SUBSCAPE)
SCAPE_SETTINGS = ("dsp", "dsp_spatial", "dsp_volume", "fadetime", "soundmixer")

NUM_POSITIONS = 8
ATTN_NORM = 0.8
SOUND_NORMAL_CLIP_DIST = 1000.0

SNDLVL_NAMES = {
    "SNDLVL_NONE": 0,
    "SNDLVL_IDLE": 60,
    "SNDLVL_STATIC": 66,
    "SNDLVL_NORM": 75,
    "SNDLVL_TALKING": 80,
    "SNDLVL_GUNFIRE": 140,
}
ATTN_NAMES = {
    "ATTN_NONE": 0.0,
    "ATTN_NORM": 0.8,
    "ATTN_IDLE": 2.0,
    "ATTN_STATIC": 1.25,
    "ATTN_RICOCHET": 1.5,
    "ATTN_GUNFIRE": 0.27,
}
SOUNDLEVEL_CHOICES = ["SNDLVL_NONE"] + [f"SNDLVL_{d}dB" for d in range(20, 185, 5)] + [
    "SNDLVL_IDLE",
    "SNDLVL_STATIC",
    "SNDLVL_NORM",
    "SNDLVL_TALKING",
    "SNDLVL_GUNFIRE",
]


# ------------------------------------------------------------ value parsing


def normalize_wave(name: str) -> str:
    """Turn a soundscape 'wave' value into a lowercase path relative to sound/."""
    s = name.strip().lstrip(SOUND_CHARS).replace("\\", "/").lower()
    s = s.lstrip("/")
    if s.startswith("sound/"):
        s = s[6:]
    return s


def is_wave_file(name: str) -> bool:
    return normalize_wave(name).endswith(SOUND_EXTENSIONS)


def parse_float(s: str | None, default: float = 0.0) -> float:
    if s is None:
        return default
    m = re.match(r"\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", s)
    return float(m.group(0)) if m else default


def parse_range(s: str | None, default: tuple[float, float]) -> tuple[float, float]:
    """Parse "a" or "a,b" (Source randomized values)."""
    if s is None or not s.strip():
        return default
    u = s.strip().upper()
    if u in ("VOL_NORM",):
        return (1.0, 1.0)
    if u in ("PITCH_NORM",):
        return (100.0, 100.0)
    if u in ("PITCH_LOW",):
        return (95.0, 95.0)
    if u in ("PITCH_HIGH",):
        return (120.0, 120.0)
    parts = s.split(",")
    lo = parse_float(parts[0], default[0])
    hi = parse_float(parts[1], lo) if len(parts) > 1 else lo
    return (min(lo, hi), max(lo, hi))


def soundlevel_to_db(s: str | None) -> float | None:
    if s is None:
        return None
    u = s.strip().upper()
    if u in SNDLVL_NAMES:
        return float(SNDLVL_NAMES[u])
    m = re.match(r"SNDLVL_(\d+)DB", u)
    if m:
        return float(m.group(1))
    try:
        return parse_range(s, (75, 75))[0]
    except ValueError:
        return None


def soundlevel_to_attenuation(db: float) -> float:
    return 20.0 / (db - 50.0) if db > 50 else (0.0 if db <= 0 else 4.0)


def attenuation_value(s: str) -> float:
    u = s.strip().upper()
    if u in ATTN_NAMES:
        return ATTN_NAMES[u]
    return parse_range(s, (ATTN_NORM, ATTN_NORM))[0]


def rule_attenuation(rule: KVNode, default: float) -> float:
    """Return the attenuation of a rule (0 means it can be heard everywhere)."""
    att = default
    for c in rule.children or ():
        k = c.key.lower()
        if c.is_block:
            continue
        if k == "attenuation":
            att = attenuation_value(c.value)
        elif k == "soundlevel":
            db = soundlevel_to_db(c.value)
            if db is not None:
                att = soundlevel_to_attenuation(db)
    return att


def parse_origin(s: str | None) -> tuple[float, float, float] | None:
    if not s:
        return None
    parts = [p for p in re.split(r"[,\s]+", s.strip()) if p]
    try:
        vals = [float(p) for p in parts[:3]]
    except ValueError:
        return None
    while len(vals) < 3:
        vals.append(0.0)
    return tuple(vals)  # type: ignore[return-value]


# Position: None = ambient (non-positional), int = position index, "random", or ("origin", x, y)
Position = Union[None, int, str, tuple]


def parse_position(rule: KVNode) -> Position:
    origin = parse_origin(rule.get("origin"))
    if origin is not None:
        return ("origin", origin[0], origin[1])
    pos = rule.get("position")
    if pos is None:
        return None
    if pos.strip().lower() == "random":
        return "random"
    try:
        return int(parse_float(pos, 0))
    except ValueError:
        return None


# ------------------------------------------------------------- game sounds


@dataclass
class GameSound:
    """A soundscript entry (e.g. "Ambient.Wind") from game_sounds_*.txt."""

    name: str
    waves: list[str]
    volume: tuple[float, float] = (1.0, 1.0)
    pitch: tuple[float, float] = (100.0, 100.0)
    soundlevel: float | None = None
    source: str = ""


def parse_game_sounds(text: str, source: str = "") -> dict[str, GameSound]:
    out: dict[str, GameSound] = {}
    for node in kv.parse(text):
        if not node.is_block:
            continue
        waves = [c.value for c in node.find_all("wave") if not c.is_block]
        rnd = node.find("rndwave")
        if rnd is not None and rnd.is_block:
            waves += [c.value for c in rnd.find_all("wave") if not c.is_block]
        if not waves:
            continue
        out[node.key.lower()] = GameSound(
            node.key,
            waves,
            parse_range(node.get("volume"), (1.0, 1.0)),
            parse_range(node.get("pitch"), (100.0, 100.0)),
            soundlevel_to_db(node.get("soundlevel")),
            source,
        )
    return out


# ----------------------------------------------------------- soundscape file


class SoundscapeFile:
    """A soundscapes_*.txt file containing any number of soundscapes."""

    def __init__(self, path: str | None = None, nodes: list[KVNode] | None = None):
        self.path = path
        self.nodes: list[KVNode] = nodes or []
        self.trailing: list[str] = []
        self.dirty = False
        self.disk_mtime: float | None = None
        # Text of a file that failed to parse; kept so nothing is lost on save.
        self.raw_text: str | None = None

    @property
    def display_name(self) -> str:
        return os.path.basename(self.path) if self.path else "untitled.txt"

    @property
    def soundscapes(self) -> list[KVNode]:
        return [n for n in self.nodes if n.is_block]

    def find(self, name: str) -> KVNode | None:
        n = name.lower()
        for s in self.soundscapes:
            if s.key.lower() == n:
                return s
        return None

    @classmethod
    def load(cls, path: str) -> "SoundscapeFile":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        sf = cls(path)
        sf.disk_mtime = os.path.getmtime(path)
        try:
            sf.set_text(text)
        except kv.KVParseError:
            sf.raw_text = text
            raise
        finally:
            sf.dirty = False
        sf.disk_mtime = os.path.getmtime(path)
        return sf

    def set_text(self, text: str) -> None:
        """Replace content with parsed text (raises KVParseError)."""
        nodes, trailing = kv.parse_full(text)
        self.nodes, self.trailing = nodes, trailing
        self.raw_text = None
        self.dirty = True

    def to_text(self) -> str:
        if self.raw_text is not None:
            return self.raw_text
        return kv.dumps(self.nodes, self.trailing)

    def save(self, path: str | None = None) -> None:
        if path:
            self.path = path
        if not self.path:
            raise ValueError("No path to save to")
        with open(self.path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(self.to_text())
        self.dirty = False
        self.disk_mtime = os.path.getmtime(self.path)


def new_soundscape(name: str) -> KVNode:
    return KVNode(name, children=[KVNode("dsp", "1")])


def new_rule(rule_type: str) -> KVNode:
    if rule_type == RULE_LOOPING:
        children = [KVNode("volume", "0.5"), KVNode("pitch", "100"), KVNode("wave", "")]
    elif rule_type == RULE_RANDOM:
        children = [
            KVNode("time", "5,15"),
            KVNode("volume", "0.3,0.6"),
            KVNode("pitch", "95,105"),
            KVNode("rndwave", children=[]),
        ]
    else:
        children = [KVNode("name", ""), KVNode("volume", "1.0")]
    return KVNode(rule_type, children=children)


def rule_waves(rule: KVNode) -> list[str]:
    """All wave values referenced by a playlooping/playrandom rule."""
    waves = [c.value for c in rule.find_all("wave") if not c.is_block and c.value]
    rnd = rule.find("rndwave")
    if rnd is not None and rnd.is_block:
        waves += [c.value for c in rnd.find_all("wave") if not c.is_block and c.value]
    return waves


def describe_rule(rule: KVNode) -> str:
    k = rule.key.lower()
    if k == RULE_SUBSCAPE:
        return rule.get("name") or "(no name)"
    waves = rule_waves(rule)
    if not waves:
        return "(no sound)"
    first = waves[0].replace("\\", "/").split("/")[-1]
    return first if len(waves) == 1 else f"{first} +{len(waves) - 1}"


# ------------------------------------------------------------ playback plan


@dataclass
class WaveChoice:
    path: str  # normalized, relative to sound/
    volume: tuple[float, float] = (1.0, 1.0)  # multiplier from a soundscript
    pitch: tuple[float, float] = (100.0, 100.0)


@dataclass
class LoopSpec:
    key: str
    rule_uid: int
    wave: WaveChoice
    volume: float
    pitch: float
    attenuation: float
    position: Position
    label: str = ""


@dataclass
class RandomSpec:
    key: str
    rule_uid: int
    waves: list[WaveChoice]
    time: tuple[float, float]
    volume: tuple[float, float]
    pitch: tuple[float, float]
    attenuation: float
    position: Position
    label: str = ""


@dataclass
class Plan:
    name: str
    loops: list[LoopSpec] = field(default_factory=list)
    randoms: list[RandomSpec] = field(default_factory=list)
    dsp: int | None = None
    dsp_volume: float = 1.0
    fadetime: float | None = None
    soundmixer: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class _SubParams:
    volume: float = 1.0
    start_position: int = 0
    position_override: int = -1
    ambient_position_override: int = -1


class PlanBuilder:
    def __init__(
        self,
        lookup_soundscape: Callable[[str], KVNode | None],
        lookup_game_sound: Callable[[str], GameSound | None],
    ):
        self.lookup_soundscape = lookup_soundscape
        self.lookup_game_sound = lookup_game_sound

    def resolve_wave(self, value: str) -> list[WaveChoice]:
        if is_wave_file(value):
            return [WaveChoice(normalize_wave(value))]
        gs = self.lookup_game_sound(value.strip().lower())
        if gs is None:
            return [WaveChoice(normalize_wave(value))]
        return [WaveChoice(normalize_wave(w), gs.volume, gs.pitch) for w in gs.waves]

    def build(
        self,
        scape: KVNode,
        muted: set[int] | None = None,
        soloed: set[int] | None = None,
    ) -> Plan:
        plan = Plan(scape.key)
        for c in scape.children or ():
            k = c.key.lower()
            if c.is_block:
                continue
            if k == "dsp":
                plan.dsp = int(parse_float(c.value, 0))
            elif k == "dsp_volume":
                plan.dsp_volume = parse_float(c.value, 1.0)
            elif k == "fadetime":
                plan.fadetime = parse_float(c.value, 0.0)
            elif k == "soundmixer":
                plan.soundmixer = c.value
        self._add(plan, scape, _SubParams(), "", {scape.key.lower()}, muted or set(), soloed or set(), True)
        return plan

    @staticmethod
    def _map_position(pos: Position, p: _SubParams) -> Position:
        if isinstance(pos, int):
            if p.position_override >= 0:
                return p.position_override
            return pos + p.start_position
        if pos is None and p.ambient_position_override >= 0:
            return p.ambient_position_override
        return pos

    def _add(self, plan, scape, params, prefix, visiting, muted, soloed, top) -> None:
        for i, rule in enumerate(scape.children or ()):
            if not rule.is_block:
                continue
            k = rule.key.lower()
            if top:
                if rule.uid in muted:
                    continue
                if soloed and rule.uid not in soloed:
                    continue
            key = f"{prefix}{i}"
            label = f"{scape.key} / {k} #{i}"
            if k == RULE_LOOPING:
                vol = parse_float(rule.get("volume"), 0.0) * params.volume
                wave = rule.get("wave")
                if not wave or vol <= 0:
                    continue
                pitch = parse_float(rule.get("pitch"), 100.0)
                choices = self.resolve_wave(wave)
                choice = random.choice(choices)
                plan.loops.append(
                    LoopSpec(
                        key,
                        rule.uid,
                        choice,
                        vol,
                        pitch,
                        rule_attenuation(rule, ATTN_NORM),
                        self._map_position(parse_position(rule), params),
                        label,
                    )
                )
            elif k == RULE_RANDOM:
                waves: list[WaveChoice] = []
                for w in rule_waves(rule):
                    waves += self.resolve_wave(w)
                if not waves:
                    continue
                vol = parse_range(rule.get("volume"), (1.0, 1.0))
                vol = (vol[0] * params.volume, vol[1] * params.volume)
                plan.randoms.append(
                    RandomSpec(
                        key,
                        rule.uid,
                        waves,
                        parse_range(rule.get("time"), (10.0, 10.0)),
                        vol,
                        parse_range(rule.get("pitch"), (100.0, 100.0)),
                        rule_attenuation(rule, 0.0),
                        self._map_position(parse_position(rule), params),
                        label,
                    )
                )
            elif k == RULE_SUBSCAPE:
                name = (rule.get("name") or "").strip()
                if not name:
                    continue
                if name.lower() in visiting:
                    plan.warnings.append(f"Recursive playsoundscape '{name}' ignored")
                    continue
                sub = self.lookup_soundscape(name)
                if sub is None:
                    plan.warnings.append(f"Soundscape '{name}' not found")
                    continue
                sp = _SubParams(
                    params.volume * parse_float(rule.get("volume"), 1.0),
                    params.start_position + int(parse_float(rule.get("position"), 0)),
                    params.position_override,
                    params.ambient_position_override,
                )
                po = rule.get("positionoverride")
                if po is not None:
                    sp.position_override = self._map_position(int(parse_float(po, 0)), params)
                apo = rule.get("ambientpositionoverride")
                if apo is not None:
                    sp.ambient_position_override = self._map_position(int(parse_float(apo, 0)), params)
                self._add(plan, sub, sp, f"{key}>{name.lower()}/", visiting | {name.lower()}, muted, soloed, False)


# --------------------------------------------------------------- validation


@dataclass
class Problem:
    severity: str  # "error" | "warning" | "info"
    soundscape: str
    rule: str
    message: str
    rule_uid: int | None = None


def validate(
    sfile: SoundscapeFile,
    lookup_soundscape: Callable[[str], KVNode | None],
    lookup_game_sound: Callable[[str], GameSound | None],
    sound_exists: Callable[[str], bool],
    loop_info: Callable[[str], bool | None],
    other_names: dict[str, str],
) -> list[Problem]:
    """Check a soundscape file for common mistakes.

    loop_info(path) returns True if the sound has a cue point, False if not,
    None if unknown. other_names maps lowercase soundscape names defined
    elsewhere to where they are defined.
    """
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for scape in sfile.soundscapes:
        sname = scape.key
        lname = sname.lower()
        seen[lname] = seen.get(lname, 0) + 1
        if seen[lname] == 2:
            problems.append(Problem("error", sname, "", "Soundscape name is defined more than once in this file"))
        if lname in other_names:
            problems.append(
                Problem("warning", sname, "", f"Name also defined in {other_names[lname]} (names must be globally unique)")
            )
        loop_waves: dict[str, int] = {}
        for i, rule in enumerate(scape.children or ()):
            if not rule.is_block:
                continue
            k = rule.key.lower()
            rdesc = f"#{i} {rule.key}"

            def add(sev, msg):
                problems.append(Problem(sev, sname, rdesc, msg, rule.uid))

            if k not in RULE_TYPES:
                add("warning", f"Unknown rule '{rule.key}'")
                continue
            if k == RULE_SUBSCAPE:
                name = rule.get("name")
                if not name:
                    add("error", "playsoundscape has no 'name'")
                elif lookup_soundscape(name) is None:
                    add("error", f"Soundscape '{name}' not found")
                elif name.lower() == lname:
                    add("error", "Soundscape plays itself")
                continue
            if k == RULE_LOOPING:
                if rule.find("rndwave") is not None:
                    add("warning", "playlooping ignores 'rndwave'; use 'wave'")
                if not rule.get("wave"):
                    add("error", "playlooping has no 'wave'")
                vol = rule.get("volume")
                if vol is not None and "," in vol:
                    add("warning", "playlooping does not support random ranges (volume)")
                if parse_float(vol, 0) <= 0:
                    add("warning", "Volume is 0 or missing; the sound will not play")
            if k == RULE_RANDOM:
                if rule.find("rndwave") is None:
                    add("error", "playrandom requires its waves inside an 'rndwave' block")
                elif not rule_waves(rule):
                    add("error", "rndwave block is empty")
                if rule.get("time") is None:
                    add("warning", "No 'time' set (defaults to 10 seconds)")
                if isinstance(parse_position(rule), int) and rule.get("attenuation") is None and rule.get("soundlevel") is None:
                    add("warning", "Positioned playrandom without attenuation/soundlevel plays everywhere")
            pos = parse_position(rule)
            if isinstance(pos, int) and not 0 <= pos < NUM_POSITIONS:
                add("error", f"Position {pos} is out of range (0-7)")
            if pos == "random" and k == RULE_LOOPING:
                add("info", "'position random' on playlooping only works in newer engine branches")

            for w in rule_waves(rule):
                if not is_wave_file(w):
                    gs = lookup_game_sound(w.strip().lower())
                    if gs is None:
                        add("error", f"'{w}' is neither a sound file nor a known soundscript entry")
                    continue
                path = normalize_wave(w)
                if not sound_exists(path):
                    add("error", f"Sound file not found: {path}")
                    continue
                if k == RULE_LOOPING:
                    loop_waves[path] = loop_waves.get(path, 0) + 1
                    if loop_waves[path] == 2:
                        add("warning", f"'{path}' is looped more than once; most branches play only one instance")
                    if path.endswith(".mp3"):
                        add("warning", "MP3 files cannot loop in Source")
                    else:
                        has_cue = loop_info(path)
                        if has_cue is False:
                            add("warning", f"'{path}' has no cue point; it will play once instead of looping")
    return problems
