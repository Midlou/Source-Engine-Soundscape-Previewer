"""Reader for Valve Pak (VPK) archives, versions 1 and 2.

Only the "_dir.vpk" file needs to be opened; data stored in the numbered
archives ("_000.vpk", "_001.vpk", ...) is read on demand.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

VPK_SIGNATURE = 0x55AA1234
EMBEDDED_ARCHIVE = 0x7FFF


class VPKError(Exception):
    pass


@dataclass(slots=True)
class VPKEntry:
    crc: int
    preload: bytes
    archive_index: int
    offset: int
    length: int


class VPK:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not self.path.lower().endswith("_dir.vpk"):
            # Single-file VPKs (no numbered archives) are also supported.
            self.base = self.path[:-4]
        else:
            self.base = self.path[: -len("_dir.vpk")]
        self.entries: dict[str, VPKEntry] = {}
        self._data_offset = 0
        self._read_directory()

    def _read_directory(self) -> None:
        with open(self.path, "rb") as f:
            data = f.read()
        if len(data) < 12:
            raise VPKError("File too small to be a VPK")
        signature, version, tree_size = struct.unpack_from("<III", data, 0)
        if signature != VPK_SIGNATURE:
            raise VPKError("Not a VPK file (bad signature)")
        if version == 1:
            header_size = 12
        elif version == 2:
            header_size = 28
        else:
            raise VPKError(f"Unsupported VPK version {version}")
        self._data_offset = header_size + tree_size

        pos = header_size
        end = header_size + tree_size

        def read_str() -> str:
            nonlocal pos
            nul = data.index(b"\0", pos)
            s = data[pos:nul].decode("utf-8", "replace")
            pos = nul + 1
            return s

        entries = self.entries
        while pos < end:
            ext = read_str()
            if not ext:
                break
            while True:
                directory = read_str()
                if not directory:
                    break
                while True:
                    name = read_str()
                    if not name:
                        break
                    crc, preload_len, archive, offset, length, term = struct.unpack_from(
                        "<IHHIIH", data, pos
                    )
                    pos += 18
                    if term != 0xFFFF:
                        raise VPKError("Corrupt VPK directory entry")
                    preload = data[pos : pos + preload_len]
                    pos += preload_len
                    parts = []
                    if directory != " ":
                        parts.append(directory)
                    filename = name if ext == " " else f"{name}.{ext}"
                    parts.append(filename)
                    full = "/".join(parts).lower()
                    entries[full] = VPKEntry(crc, preload, archive, offset, length)

    def __contains__(self, path: str) -> bool:
        return path.lower().replace("\\", "/") in self.entries

    def read(self, path: str) -> bytes:
        entry = self.entries[path.lower().replace("\\", "/")]
        if entry.length == 0:
            return entry.preload
        if entry.archive_index == EMBEDDED_ARCHIVE:
            archive_path = self.path
            offset = self._data_offset + entry.offset
        else:
            archive_path = f"{self.base}_{entry.archive_index:03d}.vpk"
            offset = entry.offset
        with open(archive_path, "rb") as f:
            f.seek(offset)
            body = f.read(entry.length)
        return entry.preload + body
