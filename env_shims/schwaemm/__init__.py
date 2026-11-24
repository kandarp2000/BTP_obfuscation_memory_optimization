"""ctypes binding for the Schwaemm AEAD wrapper shipped in compiler/schwaemm
(replaces the SWIG build, which needs swig + distutils, unavailable here)."""
import ctypes, os
_lib = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libschwaemm.so"))
_lib.free = ctypes.CDLL(None).free
def _call(fn, data, ad, nonce, key):
    out = ctypes.c_char_p(); outlen = ctypes.c_longlong()
    fn(ctypes.byref(out), ctypes.byref(outlen), data, ctypes.c_longlong(len(data)),
       ad, ctypes.c_longlong(len(ad)), nonce, key)
    if not out: raise ValueError("schwaemm failed")
    res = ctypes.string_at(out, outlen.value)
    ctypes.CDLL(None).free(out)
    return res
def schwaemm128128_encrypt(m, ad, nonce, key): return _call(_lib.schwaemm128128_encrypt, m, ad, nonce, key)
def schwaemm128128_decrypt(c, ad, nonce, key): return _call(_lib.schwaemm128128_decrypt, c, ad, nonce, key)
