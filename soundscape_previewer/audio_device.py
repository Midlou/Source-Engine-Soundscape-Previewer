"""Which output device Windows is using right now.

PortAudio reads the device list once and keeps playing to the device it
opened, so when the Windows default playback device changes (headphones
plugged in, device picked in the taskbar...) the preview goes silent. The
app polls default_output_id() and reopens the stream when it changes.
"""
from __future__ import annotations

import ctypes
import sys
import uuid


def _guid(s: str):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


_CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
_IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
_CLSCTX_ALL = 0x17
_eRender, _eConsole = 0, 0


class _DefaultDevice:
    """Core Audio IMMDeviceEnumerator called through its vtable with ctypes."""

    def __init__(self):
        self.enum = None
        if sys.platform != "win32":
            return
        ole32 = ctypes.OleDLL("ole32")
        self.ole32 = ole32
        ole32.CoInitializeEx.restype = ctypes.c_long  # don't raise on S_FALSE / RPC_E_CHANGED_MODE
        ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED; Qt already did it on the GUI thread
        enum = ctypes.c_void_p()
        ole32.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_MMDeviceEnumerator)),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_guid(_IID_IMMDeviceEnumerator)),
            ctypes.byref(enum),
        )
        self.enum = enum

    @staticmethod
    def _method(obj: ctypes.c_void_p, index: int, *argtypes):
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])

    def id(self) -> str | None:
        if not self.enum:
            return None
        device = ctypes.c_void_p()
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint
        hr = self._method(self.enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            self.enum, _eRender, _eConsole, ctypes.byref(device)
        )
        if hr != 0 or not device:
            return None  # no output device at all
        try:
            text = ctypes.c_wchar_p()
            # IMMDevice::GetId
            if self._method(device, 5, ctypes.POINTER(ctypes.c_wchar_p))(device, ctypes.byref(text)) != 0:
                return None
            value = text.value
            self.ole32.CoTaskMemFree(text)
            return value
        finally:
            self._method(device, 2)(device)  # IUnknown::Release


_instance: _DefaultDevice | None = None


def default_output_id() -> str | None:
    """Endpoint id of the default playback device, or None if unknown."""
    global _instance
    try:
        if _instance is None:
            _instance = _DefaultDevice()
        return _instance.id()
    except OSError:
        return None
