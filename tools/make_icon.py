"""Build assets/logo-ssp.ico (used for the .exe) from assets/logo-ssp.png.

Run it again after changing the logo: python tools/make_icon.py
"""
import os
import struct

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(logo: QImage, size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    logo.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> None:
    logo = QImage(os.path.join(ROOT, "assets", "logo-ssp.png"))
    if logo.isNull():
        raise SystemExit("Could not read assets/logo-ssp.png")
    images = [png_bytes(logo, s) for s in SIZES]
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    for size, data in zip(SIZES, images):
        side = size % 256  # 0 means 256 in an .ico entry
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(os.path.join(ROOT, "assets", "logo-ssp.ico"), "wb") as f:
        f.write(header + entries + b"".join(images))


if __name__ == "__main__":
    main()
