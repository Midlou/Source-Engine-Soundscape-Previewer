# Source Engine Soundscape Previewer

A desktop tool for level designers to **listen to Source engine soundscapes
without launching the game**. Edit a soundscape and hear the change right away.

It is built for Team Fortress 2 mapping and works with any Source game whose
assets are stored in VPK files (HL2, CS:S, Portal, Garry's Mod, mods...).

![Soundscape Previewer](docs/screenshot.png)

## Why

Normally, testing a soundscape means saving the script, launching the game,
loading the map and walking into the `env_soundscape`. You repeat that for
every volume or pitch tweak. This tool reads sounds directly from the game's
VPK files and plays the soundscape the way the engine does, so you can tune
it in seconds.

## Features

- **Live preview.** Changes to volumes, pitches, sounds, positions and rules
  are heard right away, without restarting the loops that are already playing.
- **Game profiles.** Create a profile per game (e.g. *Team Fortress 2*) and
  choose which `_dir.vpk` files and loose content folders it uses. A TF2 profile
  is detected and created automatically from your Steam libraries.
- **Sound browser.** Search and preview all sounds in the profile's VPKs. It
  shows duration, sample rate, which VPK each sound comes from, and whether a
  WAV has a cue point (needed to loop in-game).
  - Soundscript entries (`Ambient.Wind`...) and the game's own soundscapes are
    browsable too. You can play stock soundscapes, copy them into your file,
    or use them as sub-soundscapes.
- **Multiple soundscape files.** Open many `soundscapes_*.txt` files at once,
  each with many soundscapes. Create, rename, duplicate and delete soundscapes.
- **Two ways to edit:**
  - a structured editor for `playlooping`, `playrandom` and `playsoundscape`
    rules, with drag & drop from the sound browser and per-rule
    **mute / solo**;
  - a script editor with syntax highlighting, applied live as you type.
    Comments in your files are preserved.
- **External editor support.** The file is watched on disk. Save it from
  Notepad++ or VS Code and the preview updates.
- **Positions map.** A top-down view in Hammer units. Drag the listener and
  positions 0–7 to hear distance falloff (`attenuation` / `soundlevel`) and
  stereo panning. Random sounds flash where they play. Turn a position off to
  simulate an unset `env_soundscape` target.
- **Crossfades.** With *Play selection* on, switching soundscapes crossfades
  using `fadetime`, like walking between soundscapes in-game.
- **Problems panel.** Catches mistakes before you compile:
  - missing sound files
  - looping WAVs without a cue point, and MP3 loops
  - `playrandom` without `rndwave`
  - unknown sub-soundscapes
  - names that clash with other soundscapes
  - duplicate loops (only one instance plays in-game)
  - positioned random sounds without attenuation

## Requirements

- Windows (Linux/macOS should work but are untested)
- Python 3.10+
- A Source game installed (for its VPK files)

## Installation

```bat
git clone https://github.com/Midlou/Source-Engine-Soundscape-Previewer.git
cd Source-Engine-Soundscape-Previewer
setup.bat
```

`setup.bat` creates a virtual environment in `.venv` and installs the
dependencies: PySide6, numpy, sounddevice and soundfile.

Manual setup:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Running

```bat
run.bat
```

or

```bat
.venv\Scripts\python main.py
```

## Usage

1. **Pick a profile.** On first start a *Team Fortress 2* profile is created
   if TF2 is installed. Otherwise open **Profiles → Manage profiles**, create a
   profile and add the game's `*_dir.vpk` files.
   - For TF2, sounds are in `tf2_sound_misc` / `hl2_sound_misc`.
   - Soundscripts and stock soundscapes are in `tf2_misc` / `hl2_misc`.
   - Add your map's content folder (e.g. `tf/custom/mymap`) under *Loose
     folders* to use custom sounds.
2. **Open or create a soundscape file.** Use **File → New** for a template,
   or **File → Open** for an existing `soundscapes_*.txt`.
3. **Press Play (F5)** and edit. Drag sounds from the browser into rules, move
   positions on the map, or type in the *Script* tab.
4. **Save** as `tf/scripts/soundscapes_<mapname>.txt`, or pack it into your BSP.

### Shortcuts

| Key | Action |
| --- | --- |
| F5 / F6 | Play / stop the selected soundscape |
| Ctrl+N / Ctrl+O / Ctrl+S | New / open / save file |
| Ctrl+Shift+N | New soundscape |
| Ctrl+D / F2 | Duplicate / rename soundscape |

Positions map: drag to move, right-drag to turn the listener, mouse wheel to
zoom, middle-drag to pan, double-click a position to switch it off.

## Engine accuracy

Behaviour follows the [Valve Developer Wiki](https://developer.valvesoftware.com/wiki/Soundscape)
and the engine's soundscape code.

**Simulated**
- `playlooping`, `playrandom` (`time`, `volume`, `pitch` ranges, `rndwave`)
- `playsoundscape` with `volume`, `position` offset, `positionoverride` and
  `ambientpositionoverride`
- positions 0–7, `position random` (36 units from the listener) and `origin`
- `attenuation` / `soundlevel` falloff
- loops from WAV cue points: like the engine, a WAV without one plays once.
  You can override this with *Loop files without cue points*.
- sound characters (`*`, `#`, `)`, ...), soundscript names as waves, and
  `fadetime`

**Not simulated (but edited and saved):** DSP presets (`dsp`, `dsp_spatial`,
`dsp_volume`), `soundmixer`, and occlusion. Distance falloff is a close
approximation of the engine's formula.

## Project structure

```
main.py                         entry point
soundscape_previewer/
  vpk.py                        VPK v1/v2 reader
  keyvalues.py                  KeyValues parser/writer that keeps comments
  soundscape.py                 soundscape model, playback plans, validation
  gamedata.py                   profile content index (sounds, soundscripts, soundscapes)
  audio.py                      decoding, cue points, real-time mixer
  settings.py                   settings, profiles, Steam detection
  ui/                           PySide6 interface
```

Settings and profiles are saved in `data/settings.json`. This file is not
committed.

## License

[MIT](LICENSE) © 2026 Midlou

Dependencies keep their own licenses: PySide6/Qt (LGPL v3), numpy (BSD),
sounddevice (MIT), soundfile (BSD, bundles libsndfile under LGPL). This
project does not include any Valve game content. Sounds are read at runtime
from your own game installation.
