"""Real-time soundscape mixer.

The engine receives a Plan (see soundscape.py) and keeps playing it. Applying a
new plan reconciles it with what is playing, so edits are heard immediately
without restarting loops that did not change.
"""
from __future__ import annotations

import io
import math
import random
import struct
import threading
import time
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .soundscape import NUM_POSITIONS, SOUND_NORMAL_CLIP_DIST, LoopSpec, Plan, Position, RandomSpec

try:
    import soundfile
except Exception:  # noqa: BLE001 - libsndfile missing; fall back to the wave module
    soundfile = None

try:
    import sounddevice
except Exception:  # noqa: BLE001
    sounddevice = None

SAMPLE_RATE = 44100
BLOCK = 1024
RANDOM_POSITION_DISTANCE = 36.0  # Source plays "position random" sounds 36 units away
DEFAULT_SOUNDSCAPE_FADE = 3.0  # soundscape_fadetime default
LIVE_EDIT_FADE = 0.15


# ------------------------------------------------------------------ decoding


@dataclass
class SoundData:
    samples: np.ndarray  # float32, shape (frames, channels)
    rate: int
    loop_start: int | None  # cue point; None means the sound does not loop in-game
    loop_end: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate


def read_wav_loop_points(data: bytes) -> tuple[int | None, int | None]:
    """Find the cue point (loop start) and optional smpl loop end of a WAV file."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None, None
    pos = 12
    cue = None
    loop_end = None
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if cid == b"cue " and size >= 4:
            count = struct.unpack_from("<I", data, body)[0]
            if count and size >= 4 + 24:
                _id, position, _chunk, _cstart, _bstart, offset = struct.unpack_from("<IIIIII", data, body + 4)
                cue = offset if offset else position
        elif cid == b"smpl" and size >= 36:
            nloops = struct.unpack_from("<I", data, body + 28)[0]
            if nloops and size >= 36 + 24:
                _id, _type, start, end, _frac, _count = struct.unpack_from("<IIIIII", data, body + 36)
                loop_end = end + 1
                if cue is None:
                    cue = start
        pos = body + size + (size & 1)
    return cue, loop_end


def decode(data: bytes, name: str) -> SoundData:
    samples = None
    rate = SAMPLE_RATE
    if soundfile is not None:
        try:
            samples, rate = soundfile.read(io.BytesIO(data), dtype="float32", always_2d=True)
        except Exception:  # noqa: BLE001 - try the fallback decoder
            samples = None
    if samples is None:
        with wave.open(io.BytesIO(data)) as w:
            rate = w.getframerate()
            ch = w.getnchannels()
            width = w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width == 1:
            arr = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif width == 2:
            arr = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
        else:
            raise ValueError(f"Unsupported sample width {width}")
        samples = arr.reshape(-1, ch)
    if samples.shape[1] > 2:
        samples = samples[:, :2]
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    loop_start, loop_end = (None, None)
    if name.endswith(".wav"):
        loop_start, loop_end = read_wav_loop_points(data)
    frames = len(samples)
    if loop_start is not None and not 0 <= loop_start < frames - 1:
        loop_start = 0
    end = frames if loop_end is None else max(1, min(frames, loop_end))
    return SoundData(samples, int(rate), loop_start, end)


class SoundBank:
    """Decodes sounds in background threads and caches them."""

    MISSING = object()

    def __init__(self, reader: Callable[[str], bytes | None], max_items: int = 400):
        self.reader = reader
        self._cache: dict[str, object] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="decode")
        self.max_items = max_items
        self.errors: dict[str, str] = {}

    def set_reader(self, reader: Callable[[str], bytes | None]) -> None:
        with self._lock:
            self.reader = reader
            self._cache.clear()
            self.errors.clear()

    def get(self, path: str):
        """Return SoundData, SoundBank.MISSING, or None while still loading."""
        with self._lock:
            v = self._cache.get(path)
            if v is not None or path in self._pending:
                return v
            self._pending.add(path)
        self._pool.submit(self._load, path)
        return None

    def load_now(self, path: str):
        v = self.get(path)
        while v is None:
            time.sleep(0.005)
            v = self.get(path)
        return v

    def _load(self, path: str) -> None:
        reader = self.reader
        try:
            data = reader(path)
            result = self.MISSING if data is None else decode(data, path)
            if data is None:
                self.errors[path] = "not found"
        except Exception as e:  # noqa: BLE001
            self.errors[path] = str(e)
            result = self.MISSING
        with self._lock:
            self._pending.discard(path)
            if reader is not self.reader:
                return
            if len(self._cache) >= self.max_items:
                self._cache.pop(next(iter(self._cache)))
            self._cache[path] = result


# -------------------------------------------------------------------- spatial


def distance_gain(dist: float, attenuation: float) -> float:
    """Approximation of the engine's distance falloff (SND_GetGainFromMult)."""
    if attenuation <= 0:
        return 1.0
    rel = dist * (attenuation / SOUND_NORMAL_CLIP_DIST)
    g = 10.0 if rel <= 0.1 else 1.0 / rel
    # soft compression above 0.5 so close sounds approach (but never pass) 1.0
    if g > 0.5:
        g = 0.5 + 0.5 * (1.0 - math.exp(-(g - 0.5) / 0.5))
    return g


@dataclass
class Spatial:
    listener: tuple[float, float] = (0.0, 0.0)
    listener_yaw: float = 0.0  # degrees, 0 = facing +Y
    positions: list = field(
        default_factory=lambda: [
            (256 * math.sin(i * math.tau / NUM_POSITIONS), 256 * math.cos(i * math.tau / NUM_POSITIONS))
            for i in range(NUM_POSITIONS)
        ]
    )
    enabled: list = field(default_factory=lambda: [True] * NUM_POSITIONS)

    def point_for(self, position: Position) -> tuple[float, float] | None | bool:
        """World point for a position, None if ambient, False if suppressed."""
        if position is None:
            return None
        if isinstance(position, int):
            if not 0 <= position < NUM_POSITIONS or not self.enabled[position]:
                return False
            return self.positions[position]
        if isinstance(position, tuple) and position[0] == "origin":
            return (position[1], position[2])
        return None

    def gains(self, point, attenuation: float, volume: float) -> tuple[float, float]:
        if point is None or point is False:
            return (0.0, 0.0) if point is False else (volume, volume)
        dx = point[0] - self.listener[0]
        dy = point[1] - self.listener[1]
        dist = math.hypot(dx, dy)
        g = volume * distance_gain(dist, attenuation)
        if dist < 1.0:
            return g, g
        angle = math.atan2(dx, dy) - math.radians(self.listener_yaw)
        pan = math.sin(angle)  # -1 left .. +1 right
        behind = 0.85 if math.cos(angle) < 0 else 1.0
        return g * behind * min(1.0, 1.0 - pan), g * behind * min(1.0, 1.0 + pan)


# --------------------------------------------------------------------- voices


class Voice:
    def __init__(self, data: SoundData, pitch: float, loop: bool):
        self.data = data
        self.pos = 0.0
        self.pitch = pitch
        self.loop = loop and data.loop_start is not None
        self.gain = (0.0, 0.0)
        self.target = (0.0, 0.0)
        self.fade = 0.0
        self.fade_target = 1.0
        self.fade_step = 1.0  # change per sample
        self.done = False
        self.level = 0.0

    def set_fade(self, target: float, seconds: float) -> None:
        self.fade_target = target
        self.fade_step = 1.0 / max(1.0, seconds * SAMPLE_RATE)

    def render(self, n: int) -> np.ndarray | None:
        d = self.data
        step = d.rate / SAMPLE_RATE * self.pitch / 100.0
        idx = self.pos + step * np.arange(n, dtype=np.float64)
        end = d.loop_end
        if self.loop:
            ls = d.loop_start
            length = end - ls
            over = idx >= end
            if over.any():
                idx[over] = ls + np.mod(idx[over] - ls, length)
            i0 = idx.astype(np.int64)
            i1 = i0 + 1
            i1[i1 >= end] = ls
            self.pos = idx[-1] + step
            if self.pos >= end:
                self.pos = ls + (self.pos - ls) % length
            valid = None
        else:
            valid = idx < end - 1
            if not valid.any():
                self.done = True
                return None
            idx = np.minimum(idx, end - 1)
            i0 = idx.astype(np.int64)
            i1 = np.minimum(i0 + 1, end - 1)
            self.pos = idx[-1] + step
            if self.pos >= end - 1:
                self.done = True
        frac = (idx - i0).astype(np.float32)[:, None]
        s = d.samples
        out = s[i0] * (1.0 - frac) + s[i1] * frac
        if valid is not None and not valid.all():
            out[~valid] = 0.0
        if out.shape[1] == 1:
            out = np.repeat(out, 2, axis=1)

        # fades and gain ramps
        f0 = self.fade
        if f0 != self.fade_target:
            delta = self.fade_step * n
            f1 = min(self.fade_target, f0 + delta) if self.fade_target > f0 else max(self.fade_target, f0 - delta)
        else:
            f1 = f0
        self.fade = f1
        g0, g1 = self.gain, self.target
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        fade = f0 + (f1 - f0) * ramp
        out[:, 0] *= (g0[0] + (g1[0] - g0[0]) * ramp) * fade
        out[:, 1] *= (g0[1] + (g1[1] - g0[1]) * ramp) * fade
        self.gain = g1
        if f1 <= 0.0 and self.fade_target <= 0.0:
            self.done = True
        self.level = float(np.abs(out).max()) if len(out) else 0.0
        return out


@dataclass
class _LoopState:
    spec: LoopSpec
    voice: Voice | None = None
    fade_in: float = LIVE_EDIT_FADE
    missing: bool = False


@dataclass
class _RandomState:
    spec: RandomSpec
    next_time: float


@dataclass
class _OneShot:
    voice: Voice
    point: object  # resolved world point / None / False
    position: Position
    attenuation: float
    volume: float
    key: str
    wave: str


@dataclass
class Event:
    time: float
    key: str
    wave: str
    point: object


class Engine:
    def __init__(self, bank: SoundBank):
        self.bank = bank
        self.spatial = Spatial()
        self.master = 0.8
        self.force_loop = False
        self._lock = threading.RLock()
        self._loops: dict[str, _LoopState] = {}
        self._randoms: dict[str, _RandomState] = {}
        self._fading: list[Voice] = []
        self._oneshots: list[_OneShot] = []
        self._preview: Voice | None = None
        self.preview_name: str | None = None
        self.plan: Plan | None = None
        self.samples_played = 0
        self.events: deque[Event] = deque(maxlen=64)
        self.peak = 0.0
        self.stream = None
        self.error: str | None = None
        self._rng = random.Random()

    # ------------------------------------------------------------- stream
    def start(self) -> None:
        if sounddevice is None:
            self.error = "The 'sounddevice' module could not be loaded (no audio output)."
            return
        try:
            self.stream = sounddevice.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=BLOCK,
                callback=self._callback,
                latency="low",
            )
            self.stream.start()
        except Exception as e:  # noqa: BLE001
            self.error = f"Could not open audio device: {e}"
            self.stream = None

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    @property
    def now(self) -> float:
        return self.samples_played / SAMPLE_RATE

    # ----------------------------------------------------------- control
    def apply_plan(self, plan: Plan | None, fade: float = LIVE_EDIT_FADE) -> None:
        """Start/replace the playing soundscape. Matching loops keep playing."""
        with self._lock:
            old_loops = self._loops
            new_loops: dict[str, _LoopState] = {}
            unmatched = dict(old_loops)
            for spec in plan.loops if plan else []:
                st = unmatched.get(spec.key)
                if st is None or st.spec.wave.path != spec.wave.path:
                    st = next((s for s in unmatched.values() if s.spec.wave.path == spec.wave.path), None)
                if st is not None and st.spec.wave.path == spec.wave.path:
                    unmatched.pop(st.spec.key, None)
                    if st.voice is not None:
                        st.voice.pitch = spec.pitch
                        st.voice.set_fade(1.0, fade)
                    st.spec = spec
                else:
                    st = _LoopState(spec, fade_in=fade)
                new_loops[spec.key] = st
            for st in unmatched.values():
                if st.voice is not None:
                    st.voice.set_fade(0.0, fade)
                    self._fading.append(st.voice)
            self._loops = new_loops

            new_randoms: dict[str, _RandomState] = {}
            for spec in plan.randoms if plan else []:
                st = self._randoms.get(spec.key)
                if st is None:
                    lo, hi = spec.time
                    st = _RandomState(spec, self.now + 0.5 * self._rng.uniform(lo, hi))
                else:
                    # Shorten the wait if the new max time is lower than what's left.
                    if st.next_time - self.now > spec.time[1]:
                        st.next_time = self.now + self._rng.uniform(*spec.time)
                    st.spec = spec
                new_randoms[spec.key] = st
            self._randoms = new_randoms
            self.plan = plan
            for spec in plan.loops if plan else []:
                self.bank.get(spec.wave.path)
            for spec in plan.randoms if plan else []:
                for w in spec.waves:
                    self.bank.get(w.path)

    def stop(self, fade: float = 0.5) -> None:
        self.apply_plan(None, fade)

    def trigger(self, key: str) -> None:
        with self._lock:
            st = self._randoms.get(key)
            if st is not None:
                st.next_time = self.now

    def preview(self, path: str, loop: bool = False) -> None:
        data = self.bank.load_now(path)
        with self._lock:
            if self._preview is not None:
                self._preview.set_fade(0.0, 0.03)
                self._fading.append(self._preview)
            self._preview = None
            self.preview_name = None
            if data is SoundBank.MISSING:
                return
            v = Voice(data, 100.0, loop)
            if loop and data.loop_start is None:
                data_loop = SoundData(data.samples, data.rate, 0, data.loop_end)
                v = Voice(data_loop, 100.0, True)
            v.set_fade(1.0, 0.01)
            v.gain = v.target = (1.0, 1.0)
            self._preview = v
            self.preview_name = path

    def stop_preview(self) -> None:
        with self._lock:
            if self._preview is not None:
                self._preview.set_fade(0.0, 0.05)
                self._fading.append(self._preview)
                self._preview = None
                self.preview_name = None

    @property
    def previewing(self) -> bool:
        return self._preview is not None and not self._preview.done

    # --------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        with self._lock:
            loops = []
            for st in self._loops.values():
                pt = self.spatial.point_for(st.spec.position)
                loops.append(
                    {
                        "key": st.spec.key,
                        "uid": st.spec.rule_uid,
                        "wave": st.spec.wave.path,
                        "point": pt,
                        "position": st.spec.position,
                        "level": st.voice.level if st.voice else 0.0,
                        "missing": st.missing,
                        "loops": bool(st.voice and st.voice.loop),
                        "playing": bool(st.voice and not st.voice.done),
                        "attenuation": st.spec.attenuation,
                    }
                )
            shots = [
                {"key": s.key, "wave": s.wave, "point": s.point, "level": s.voice.level, "attenuation": s.attenuation}
                for s in self._oneshots
                if not s.voice.done
            ]
            randoms = {k: st.next_time - self.now for k, st in self._randoms.items()}
            return {
                "loops": loops,
                "oneshots": shots,
                "randoms": randoms,
                "peak": self.peak,
                "plan": self.plan.name if self.plan else None,
                "now": self.now,
            }

    # ------------------------------------------------------------ mixing
    def _callback(self, outdata, frames, _time, _status) -> None:
        try:
            mix = self._mix(frames)
        except Exception as e:  # noqa: BLE001 - never let the audio thread die
            self.error = f"Mixer error: {e}"
            mix = np.zeros((frames, 2), np.float32)
        outdata[:] = mix

    def _start_oneshot(self, st: _RandomState) -> None:
        spec = st.spec
        choice = self._rng.choice(spec.waves)
        data = self.bank.get(choice.path)
        if data is None or data is SoundBank.MISSING:
            return
        sp = self.spatial
        if spec.position == "random":
            a = self._rng.uniform(0, math.tau)
            point = (
                sp.listener[0] + RANDOM_POSITION_DISTANCE * math.sin(a),
                sp.listener[1] + RANDOM_POSITION_DISTANCE * math.cos(a),
            )
        else:
            point = sp.point_for(spec.position)
        if point is False:
            return  # position not defined: Source suppresses the sound
        vol = self._rng.uniform(*spec.volume) * self._rng.uniform(*choice.volume)
        pitch = self._rng.uniform(*spec.pitch) * self._rng.uniform(*choice.pitch) / 100.0
        v = Voice(data, pitch, loop=False)
        v.fade = 1.0
        g = sp.gains(point, spec.attenuation, vol)
        v.gain = v.target = g
        self._oneshots.append(_OneShot(v, point, spec.position, spec.attenuation, vol, spec.key, choice.path))
        self.events.append(Event(self.now, spec.key, choice.path, point))

    def _mix(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2), np.float32)
        with self._lock:
            sp = self.spatial
            now = self.now
            for st in self._randoms.values():
                if now >= st.next_time:
                    self._start_oneshot(st)
                    st.next_time = now + max(0.05, self._rng.uniform(*st.spec.time))

            for st in self._loops.values():
                if st.voice is None:
                    data = self.bank.get(st.spec.wave.path)
                    if data is None:
                        continue
                    if data is SoundBank.MISSING:
                        st.missing = True
                        continue
                    if self.force_loop and data.loop_start is None:
                        data = SoundData(data.samples, data.rate, 0, data.loop_end)
                    st.voice = Voice(data, st.spec.pitch, loop=True)
                    st.voice.set_fade(1.0, st.fade_in)
                    pt = sp.point_for(st.spec.position)
                    st.voice.gain = sp.gains(pt, st.spec.attenuation, st.spec.volume)
                v = st.voice
                if v.done:
                    continue
                vol = st.spec.volume * (st.spec.wave.volume[0] + st.spec.wave.volume[1]) / 2
                v.target = sp.gains(sp.point_for(st.spec.position), st.spec.attenuation, vol)
                buf = v.render(n)
                if buf is not None:
                    out += buf

            alive = []
            for s in self._oneshots:
                if s.position is not None and s.position != "random" and isinstance(s.position, int):
                    s.point = sp.point_for(s.position)
                s.voice.target = sp.gains(s.point, s.attenuation, s.volume)
                buf = s.voice.render(n)
                if buf is not None:
                    out += buf
                if not s.voice.done:
                    alive.append(s)
            self._oneshots = alive

            still = []
            for v in self._fading:
                buf = v.render(n)
                if buf is not None:
                    out += buf
                if not v.done:
                    still.append(v)
            self._fading = still

            if self._preview is not None:
                buf = self._preview.render(n)
                if buf is not None:
                    out += buf
                if self._preview.done:
                    self._preview = None
                    self.preview_name = None

            self.samples_played += n
        out *= self.master
        # soft limiter: untouched below 0.8, smoothly saturates towards 1.0
        a = np.abs(out)
        hot = a > 0.8
        if hot.any():
            out[hot] = np.sign(out[hot]) * (0.8 + 0.2 * np.tanh((a[hot] - 0.8) / 0.2))
        self.peak = float(np.abs(out).max())
        return out
