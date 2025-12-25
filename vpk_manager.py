import vpk
import os

class VPKManager:
    def __init__(self):
        self.vpks = []
        self.sound_index = {}  # "ambient/foo.wav" -> vpk_file_object

    def add_vpk(self, dir_vpk_path):
        archive = vpk.open(dir_vpk_path)
        self.vpks.append(archive)

        for path in archive:
            if not path.startswith("sound/"):
                continue

            rel = path[len("sound/"):].replace("\\", "/").lower()
            self.sound_index[rel] = archive

    def has_sound(self, sound_path):
        return sound_path.lower() in self.sound_index

    def load_sound(self, sound_path):
        key = sound_path.lower()
        archive = self.sound_index.get(key)

        if not archive:
            raise FileNotFoundError(sound_path)

        return archive[f"sound/{key}"].read()
