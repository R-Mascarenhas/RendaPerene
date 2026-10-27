"""Keep the Windows installer from replacing a running packaged application."""

import ctypes
import hashlib
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.SHGetFolderPathW.argtypes = (
    wintypes.HWND,
    ctypes.c_int,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
)
shell32.SHGetFolderPathW.restype = ctypes.c_long
profile_directory = ctypes.create_unicode_buffer(32768)
if shell32.SHGetFolderPathW(None, 0x001C, None, 0, profile_directory) != 0:
    raise OSError("Cannot resolve the Windows user profile for installer protection")
profile_hash = hashlib.sha256(profile_directory.value.lower().encode("utf-16-le")).hexdigest()
# The OS closes this handle on process exit. Every instance keeps a reference,
# including the interval before Streamlit imports the application.
application_mutex = kernel32.CreateMutexW(None, False, f"Global\\RendaPerene.{profile_hash}")
if not application_mutex:
    raise ctypes.WinError(ctypes.get_last_error())
