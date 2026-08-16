import base64
import ctypes
import ctypes.wintypes
import json
import os
import sys
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data):
    buffer = ctypes.create_string_buffer(data or b"")
    blob = DATA_BLOB(len(data or b""), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _free_blob(blob):
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(plaintext):
    if os.name != "nt":
        raise RuntimeError("DPAPI secret storage is only supported on Windows")
    blob_in, _keepalive = _blob(plaintext.encode("utf-8"))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError(f"CryptProtectData failed: {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _free_blob(blob_out)


def unprotect(payload):
    if os.name != "nt":
        raise RuntimeError("DPAPI secret storage is only supported on Windows")
    blob_in, _keepalive = _blob(payload)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
    finally:
        _free_blob(blob_out)


def load_secrets(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    secrets = {}
    for key, value in (data or {}).items():
        if not isinstance(value, str) or not value:
            continue
        try:
            secrets[key] = unprotect(base64.b64decode(value))
        except Exception:
            secrets[key] = ""
    return secrets


def save_secrets(secrets, path):
    path = Path(path)
    encoded = {}
    for key, value in (secrets or {}).items():
        if value:
            encoded[key] = base64.b64encode(protect(str(value))).decode("ascii")
    if encoded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(encoded, ensure_ascii=True, indent=2), encoding="utf-8")
    elif path.exists():
        path.unlink()
