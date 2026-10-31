"""Self test for packaged builds: `SoundscapePreviewer.exe --self-test [log file]`.

Checks that everything a frozen build needs is bundled (Qt, libsndfile,
PortAudio) and that the core pipeline works, without opening windows or
touching the user's settings. Exit code 0 means success.
"""
from __future__ import annotations

import io
import os
import tempfile
import traceback


def _make_wav() -> bytes:
    import numpy as np
    import soundfile

    t = np.arange(4410) / 44100.0
    buf = io.BytesIO()
    soundfile.write(buf, (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"), 44100, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _checks(log) -> None:
    import sounddevice

    log(f"PortAudio: {sounddevice.get_portaudio_version()[1]}")

    from . import audio
    from .soundscape import PlanBuilder, SoundscapeFile

    wav = _make_wav()
    data = audio.decode(wav, "test.wav")
    assert len(data.samples) == 4410, "WAV decode failed"
    log(f"libsndfile: {audio.soundfile.__libsndfile_version__}")

    sf = SoundscapeFile()
    sf.set_text('"test.scape" { "playlooping" { "volume" "1" "wave" "test.wav" } }')
    plan = PlanBuilder(lambda _n: None, lambda _n: None).build(sf.soundscapes[0])
    assert len(plan.loops) == 1, "plan build failed"

    bank = audio.SoundBank(lambda _p: wav)
    engine = audio.Engine(bank)
    engine.force_loop = True
    bank.load_now("test.wav")
    engine.apply_plan(plan, 0.01)
    peak = max(float(abs(engine._mix(audio.BLOCK)).max()) for _ in range(20))
    assert peak > 0.01, "mixer produced silence"
    log(f"mixer peak: {peak:.3f}")

    from PySide6.QtWidgets import QApplication

    from .ui import main_window

    app = QApplication.instance() or QApplication([])
    audio.Engine.start = lambda self: None  # no audio device needed
    w = main_window.MainWindow()
    w.show()
    app.processEvents()
    w.engine.close()
    w.hide()
    log("main window: ok")


def run(log_path: str | None = None) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["SSP_DATA_DIR"] = tempfile.mkdtemp(prefix="ssp-selftest-")
    lines: list[str] = []
    code = 0
    try:
        _checks(lines.append)
        lines.append("SELF TEST PASSED")
    except Exception:  # noqa: BLE001 - report everything
        lines.append(traceback.format_exc())
        lines.append("SELF TEST FAILED")
        code = 1
    text = "\n".join(lines) + "\n"
    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        try:
            print(text)
        except Exception:  # noqa: BLE001 - windowed builds have no console
            pass
    return code
