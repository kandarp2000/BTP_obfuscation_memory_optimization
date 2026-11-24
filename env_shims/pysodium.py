"""Minimal pysodium stand-in: calls the system libsodium through ctypes."""
import ctypes, ctypes.util
_lib = ctypes.CDLL(ctypes.util.find_library("sodium") or "libsodium.so.23")
assert _lib.sodium_init() >= 0
crypto_box_SEALBYTES = _lib.crypto_box_sealbytes()
def crypto_box_seal(msg: bytes, pk: bytes) -> bytes:
    out = ctypes.create_string_buffer(len(msg) + crypto_box_SEALBYTES)
    if _lib.crypto_box_seal(out, msg, ctypes.c_ulonglong(len(msg)), pk) != 0:
        raise ValueError("crypto_box_seal failed")
    return out.raw
