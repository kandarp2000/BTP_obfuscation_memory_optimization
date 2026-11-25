"""Shared helpers for the memory-optimization experiments.

Run from the repository root. PYTHONPATH must contain the dependency shims
(see README_PROJECT.md).
"""
import hashlib, os, re, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPILER = os.path.join(ROOT, "compiler", "compiler.py")

# (l_in, l_out, r, s) for the four SE sizes of the paper (Table 1 / runtime/SEconfig.h)
SE = {
    "small":  (8, 8, 40, 32),
    "medium": (16, 16, 80, 64),
    "large":  (32, 32, 160, 128),
    "xlarge": (64, 64, 320, 256),
}

PROGRAMS = {  # name -> C file used by the automated tests
    "AES":            "tests/automated/programs/AES.c",
    "Ascon":          "tests/automated/programs/Ascon.c",
    "TinyJambu":      "tests/automated/programs/TinyJambu.c",
    "Photon":         "tests/automated/programs/Photon.c",
    "sum_naive":      "tests/automated/programs/sum_naive.c",
    "sum_tree":       "tests/automated/programs/sum_tree.c",
    "findmax_naive":  "tests/automated/programs/findmax_naive.c",
    "findmax_tree":   "tests/automated/programs/findmax_tree.c",
    "tracingAES":     "tests/automated/programs/tracingAES.c",
    "mnist":          "tests/automated/programs/mnist.c",
}

# The 64-byte sealed-box header (crypto_box_seal of the shared key) is randomized
# by libsodium on every compilation. It sits right after 6*4 bytes of metadata and
# the 4-byte memory_count. Everything else in the bytecode is deterministic.
SEAL_OFF, SEAL_LEN = 28, 64

def masked_digest(path):
    data = bytearray(open(path, "rb").read())
    data[SEAL_OFF:SEAL_OFF + SEAL_LEN] = b"\0" * SEAL_LEN
    return hashlib.sha256(data).hexdigest()

def env():
    e = dict(os.environ)
    e["PYTHONHASHSEED"] = "0"
    return e

STAT_RE = {
    "mlmis_rect":   re.compile(r"Rectangularization: .*?\n\s+MLIR size: (\d+) MLMIs", re.S),
    "mlmis_final":  re.compile(r"Universalization: .*?\n\s+MLIR size: (\d+) MLMIs", re.S),
    "llmis":        re.compile(r"LLIR size: (\d+) LLMIs"),
    "univ_time":    re.compile(r"Universalization: ([\d.]+) sec"),
    "total_time":   re.compile(r"Total compilation time: ([\d.]+) sec"),
    "depth":        re.compile(r"program (?:final )?depth: (\d+)"),
    "width":        re.compile(r"program width: (\d+)"),
    "univ_retained_mb": re.compile(r"\[mem\] universalize TOTAL\s+current=\s*([\d.]+) MB"),
    "univ_peak_mb": re.compile(r"\[mem\] universalize TOTAL .*?peak=\s*([\d.]+) MB"),
}

def compile_prog(src, se, out, flags=(), seed=1, timeout=1800, extra=()):
    """Compile `src` and return dict(ok, stdout, wall, maxrss_mb, stats...)."""
    l_in, l_out, r, s = SE[se]
    cmd = [sys.executable, COMPILER, "-r", str(r), "-lin", str(l_in), "-lout", str(l_out),
           "-s", str(s), "-stats", "-seed", str(seed), "-o", out, *flags, *extra, src]
    t0 = time.time()
    with tempfile.TemporaryFile("w+") as fo, tempfile.TemporaryFile("w+") as fe:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env(), stdout=fo, stderr=fe, text=True)
        # os.wait4 gives the child's resource usage, including its peak RSS
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            if time.time() - t0 > timeout:
                p.kill(); os.wait4(p.pid, 0)
                return {"ok": False, "error": "timeout", "wall": time.time() - t0}
            time.sleep(0.05)
        fo.seek(0); fe.seek(0)
        stdout, stderr = fo.read(), fe.read()
    rc = os.waitstatus_to_exitcode(status)
    res = {"ok": rc == 0, "wall": time.time() - t0,
           "stdout": stdout, "stderr": stderr[-2000:],
           "maxrss_mb": ru.ru_maxrss / 1024}
    for k, rx in STAT_RE.items():
        mm = rx.search(stdout)
        if mm:
            res[k] = float(mm.group(1))
    if res["ok"] and os.path.exists(out):
        res["bytes"] = os.path.getsize(out)
        res["digest"] = masked_digest(out)
    return res
