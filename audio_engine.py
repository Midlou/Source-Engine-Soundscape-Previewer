import pygame
import threading
import random
import time
import numpy as np
from io import BytesIO
from pitch import apply_pitch

pygame.mixer.init(frequency=44100, channels=2)

def normalize_sound_path(path: str) -> str:
    return path.replace("\\", "/").lower()

class SoundscapePlayer:
    def __init__(self, vpk_manager):
        self.vpk = vpk_manager
        self.running = False
        self.threads = []
        self.looping_sounds = []

    def stop(self):
        self.running = False
        pygame.mixer.stop()
        self.threads.clear()
        self.looping_sounds.clear()

    def play_sound(self, path, volume=1.0, pitch=1.0, loop=False):
        path = normalize_sound_path(path)

        sound = None

        if self.vpk.has_sound(path):
            data = self.vpk.load_sound(path)
            sound = pygame.mixer.Sound(file=BytesIO(data))
        else:
            print(f"[Missing sound] {path}")
            return

        sound.set_volume(volume)

        if pitch != 1.0:
            arr = pygame.sndarray.array(sound)
            arr = apply_pitch(arr, pitch)
            sound = pygame.sndarray.make_sound(arr)

        loops = -1 if loop else 0
        sound.play(loops=loops)


    def play_looping(self, entry):
        self.play_sound(
            entry["wave"],
            volume=float(entry.get("volume", 1)),
            pitch=float(entry.get("pitch", 100)) / 100,
            loop=True
        )

    # NOT PLAYING CORRECTLY
    # TODO: FIX
    def play_random(self, entry):
        def runner():
            time_range = entry.get("time", "5,10").split(",")
            tmin, tmax = float(time_range[0]), float(time_range[1])

            rndwave_block = entry["rndwave"][0]
            waves = rndwave_block["wave"]

            # Ensure list
            if isinstance(waves, str):
                waves = [waves]

            while self.running:
                time.sleep(random.uniform(tmin, tmax))

                wave = random.choice(waves)

                self.play_sound(
                    wave,
                    volume=float(entry.get("volume", 1)),
                    pitch=float(entry.get("pitch", 100)) / 100,
                    loop=False
                )

        t = threading.Thread(target=runner, daemon=True)
        self.threads.append(t)
        t.start()


    def play_soundscape(self, soundscape):
        self.stop()
        self.running = True

        for entry in soundscape.get("playlooping", []):
            self.play_looping(entry)

        for entry in soundscape.get("playrandom", []):
            self.play_random(entry)
