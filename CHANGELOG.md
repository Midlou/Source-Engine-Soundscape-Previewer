# Changelog

## 1.4

- **Soundscape files per game profile.** Each profile remembers its own open
  files, also between sessions. Switching profiles closes the current files
  and opens that profile's list, or none if it has no saved files. If there
  are unsaved changes it asks first, and Cancel stays on the current profile.
- **Open recent** button next to Open file, listing the last 15 files of the
  current profile. Missing files are greyed out, and the list can be cleared.
- **New app icon** on the .exe, the window and the taskbar.
- **New name in the app:** Source Soundscape Previewer. File names and the
  settings folder did not change.
- **Blocked while a profile loads:** the sound browser, Play and sound previews
  wait until the profile's sounds are ready. Stop and rule editing still work.
- Open file on a file that is already open now selects it.
- Playback stops when you switch profiles.
- **Fix:** switching profiles no longer shows a false number of problems. The
  Problems tab shows "loading" until the sounds are ready.
- **Fix:** switching profiles quickly can no longer leave the sounds of the
  wrong profile loaded.

## 1.3

- **Undo and redo.** Ctrl+Z / Ctrl+Y (also in the new Edit menu) undo and
  redo soundscape edits: rule values, adding, removing and moving rules,
  dropped sounds, renames and Script tab edits. Quick edits are grouped into
  one step, and undoing back to the saved version clears the unsaved marker.
- **Follows audio device changes.** When the Windows playback device changes
  (headphones plugged in, device picked in the taskbar...), the preview moves
  to the new device and keeps playing, without restarting the app.
- **Fix:** clicking a rule's mute or solo box quickly started a full-volume
  preview of its sound that ignored the mute and played to the end. Fast
  clicks now just toggle the box.
- **Fix:** editing in the Script tab no longer resets the rules' mute and solo
  boxes.

## 1.2

- **Preferences window** (File → Preferences…, Ctrl+,) with Appearance,
  Saving and About tabs. The theme option moved here from the View menu.
- **Auto save.** Modified files are saved every 5 minutes by default. It can
  be turned off or set from 1 to 120 minutes in Preferences → Saving. New
  files are skipped until you save them once.
- **Drop sounds on the rule list** to add them as looping rules, one rule per
  sound.
- **Volume and pitch columns** in the rule list, showing the values the engine
  plays (defaults included).
- **Open all** button in the sound browser, next to Collapse all.
- **Actions button on the positions map** with Reset positions, Reset player
  position, Reset view and Reset all.
- The README and About now state clearly that the software was developed by
  AI (Claude), directed by Midlou.

## 1.1

- **Theme option.** View → Theme lets you choose System (follow Windows),
  Light or Dark. The script editor's syntax colors adapt to dark mode.
- **Muted rules are greyed out.** Muted rules, and every rule outside the solo
  set when a rule is soloed, are shown in a muted text color.
- **Single-click play in the sound browser.** A new checkbox (on by default)
  plays sound files and soundscript entries with one click. Ctrl/Shift-click
  still only selects, and double-click and the Play button work as before.
- **Collapse all** button in the Sound files tab closes every open folder.

## 1.0

- First release.
