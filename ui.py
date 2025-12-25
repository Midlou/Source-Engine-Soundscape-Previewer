import tkinter as tk
from soundscape_parser import load_soundscapes
from audio_engine import SoundscapePlayer
from tkinter import filedialog
from vpk_manager import VPKManager

class App:
    def __init__(self):
        self.vpk = VPKManager()
        self.player = SoundscapePlayer(self.vpk)
        self.data = {}
        self.root = tk.Tk()
        self.root.title("Source Soundscape Preview")

        self.listbox = tk.Listbox(self.root)
        self.listbox.pack(fill="both", expand=True)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack()

        tk.Button(btn_frame, text="Load", command=self.load).pack(side="left")
        tk.Button(btn_frame, text="Play", command=self.play).pack(side="left")
        tk.Button(btn_frame, text="Stop", command=self.stop).pack(side="left")
        tk.Button(btn_frame, text="Add VPK", command=self.add_vpk).pack(side="left")

    def load(self):
        self.data = load_soundscapes("./soundscape_scripts/soundscapes_mvm_cloudpiercer_b5.txt")
        self.listbox.delete(0, tk.END)
        for name in self.data.keys():
            self.listbox.insert(tk.END, name)

    def play(self):
        sel = self.listbox.get(tk.ACTIVE)
        self.player.play_soundscape(self.data[sel][0])

    def stop(self):
        self.player.stop()

    def run(self):
        self.root.mainloop()

    def add_vpk(self):
        path = filedialog.askopenfilename(
            title="Select *_dir.vpk",
            filetypes=[("VPK files", "*_dir.vpk")]
        )
        if path:
            self.vpk.add_vpk(path)
