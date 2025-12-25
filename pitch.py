import numpy as np
from scipy.signal import resample

def apply_pitch(sound_array, pitch):
    """
    pitch = 1.0 is normal
    """
    if pitch == 1.0:
        return sound_array

    length = int(len(sound_array) / pitch)
    return resample(sound_array, length)
