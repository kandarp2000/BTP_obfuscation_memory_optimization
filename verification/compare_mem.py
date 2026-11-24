#!/usr/bin/env python3
"""compare_mem.py: run the ORIGINAL and the MEMORY-OPTIMIZED OBSCURE compiler on the
same test case and compare memory, time and output.

Run inside WSL/Linux (it reads /proc and uses os.wait4). Examples:

    python3 compare_mem.py --program TinyJambu --se small
    python3 compare_mem.py --source tests/automated/basic/add.c --flags "-width 4 -depth 25"
    python3 compare_mem.py --source 'tests/automated/basic/*.c' --flags "-width 4 -depth 25" --tests 2
        (several test cases -> one summary table)

What it does, in order, one compilation at a time (never in parallel, so the
memory numbers do not disturb each other):
  1. compiles the program with the ORIGINAL compiler (OBSCURE-main, unmodified,
     in the same deterministic mode as our -seed flag: run_original_seeded.py)
  2. compiles it with the MEMORY-OPTIMIZED compiler (OBSCURE-memopt with all
     optimizations on: -opt-all -opt-o5). Advanced: --ours "<flags>" (repeatable)
     compares other flag sets instead.
  3. for every run records
       * peak memory (peak RSS from the kernel, os.wait4 -> ru_maxrss)
       * a memory timeline (VmRSS sampled every --sample-ms) and the peak per phase
       * time of every compiler phase (from the compiler's own -stats output)
  4. checks that the bytecode is the same as the original's (SHA-256 with the
     64 randomly sealed key bytes masked)
  5. functional check: runs every bytecode in the interpreter on --tests random
     inputs and compares with the plain (gcc) build of the C program
  6. prints a comparison table and writes everything to results/<label>/
"""
import argparse
import glob
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("BTP_WORK", os.path.expanduser("~/btp_demo"))
ORIG = os.path.join(WORK, "original")
OURS = os.path.join(WORK, "memopt")

SE = {  # name -> (l_in, l_out, r, s), the four secure-element sizes of the paper
    "small": (8, 8, 40, 32),
    "medium": (16, 16, 80, 64),
    "large": (32, 32, 160, 128),
    "xlarge": (64, 64, 320, 256),
}
SE_MACRO = {"small": "SE_SMALL", "medium": "SE_MEDIUM", "large": "SE_LARGE", "xlarge": "SE_EXTRALARGE"}

# bytes 28..91 of the bytecode = crypto_box_seal of the session key. libsodium
# randomises it on every compilation (by design), so it is masked when comparing.
SEAL_OFF, SEAL_LEN = 28, 64

PHASE_RE = re.compile(r"^(Frontend|Clusterization|Rectangularization|Universalization|Lowering|Serialization): ([\d.]+)")
PHASE_NAME = {
    "Frontend": "frontend (C -> HLIR)",
    "Clusterization": "clusterization (HLIR -> MLIR)",
    "Rectangularization": "universalize: rectangularize",
    "Universalization": "universalize: permutation networks",
    "Lowering": "lowering (MLIR -> LLIR)",
    "Serialization": "serialization (LLIR -> bytecode)",
}


def display(run_name):
    """Column title: ORIGINAL / MEMORY-OPTIMIZED (MEMORY-OPTIMIZED-2, ... if several)."""
    if run_name == "original":
        return "ORIGINAL"
    suffix = run_name[len("memoryoptimized"):]
    return "MEMORY-OPTIMIZED" + ("-" + suffix if suffix else "")


def env():
    e = dict(os.environ)
    shims = os.path.join(WORK, "shims")
    e["PYTHONPATH"] = shims + ":" + os.path.join(WORK, "pylib")
    e["PYTHONHASHSEED"] = "0"
    e["PYTHONUNBUFFERED"] = "1"          # phase lines arrive when printed
    e["PYTHONWARNINGS"] = "ignore"
    return e


def run_measured(cmd, cwd, sample_s):
    """Run cmd, sample its RSS, timestamp every output line, return the measurements."""
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=cwd, env=env(), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = []

    def reader():
        for line in p.stdout:
            lines.append((time.time() - t0, line.rstrip("\n")))
    th = threading.Thread(target=reader, daemon=True)
    th.start()

    timeline = []
    status_path = f"/proc/{p.pid}/status"
    while True:
        try:
            with open(status_path) as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        timeline.append((round(time.time() - t0, 3), int(line.split()[1])))
                        break
        except OSError:
            pass
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        time.sleep(sample_s)
    wall = time.time() - t0
    th.join()
    rc = os.waitstatus_to_exitcode(status)
    p.returncode = rc
    return {"rc": rc, "wall_s": round(wall, 2), "peak_rss_kb": ru.ru_maxrss,
            "timeline": timeline, "lines": lines}


def analyse(res):
    """Phase times and per-phase peak memory from the timestamped -stats lines."""
    phases, stats = [], {}
    start = 0.0
    for t, line in res["lines"]:
        m = PHASE_RE.match(line)
        if m:
            name = m.group(1)
            inside = [kb for (ts, kb) in res["timeline"] if start <= ts <= t]
            phases.append({"phase": PHASE_NAME[name], "seconds": float(m.group(2)),
                           "peak_rss_mb": round(max(inside) / 1024, 1) if inside else None})
            start = t
        for key, rx in (("hlis", r"HLIR size: (\d+)"), ("depth", r"program (?:final )?depth: (\d+)"),
                        ("width", r"program width: (\d+)"), ("llmis", r"LLIR size: (\d+)"),
                        ("total_s", r"Total compilation time: ([\d.]+)")):
            mm = re.search(rx, line)
            if mm:
                stats[key] = float(mm.group(1)) if "." in mm.group(1) else int(mm.group(1))
    # MLMIs after universalization = the line following "Universalization:"
    for i, (_, line) in enumerate(res["lines"]):
        if line.startswith("Universalization:") and i + 1 < len(res["lines"]):
            mm = re.search(r"(\d+) MLMIs", res["lines"][i + 1][1])
            if mm:
                stats["mlmis_final"] = int(mm.group(1))
    return phases, stats


def masked_digest(data):
    d = bytearray(data)
    d[SEAL_OFF:SEAL_OFF + SEAL_LEN] = bytes(SEAL_LEN)
    return hashlib.sha256(d).hexdigest()


def compare_bytes(a, b):
    diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    outside = [i for i in diff if not SEAL_OFF <= i < SEAL_OFF + SEAL_LEN]
    same = len(a) == len(b) and not outside
    return {"identical": same, "differing_bytes": len(diff),
            "differing_outside_key_header": len(outside) + abs(len(a) - len(b))}


def interpreter_for(se):
    """Interpreter built for this SE size (runtime/ is fixed at build time)."""
    d = os.path.join(WORK, "interp", se)
    exe = os.path.join(d, "interpreter")
    if os.path.exists(exe):
        return exe
    if os.path.exists(d):
        shutil.rmtree(d)
    shutil.copytree(os.path.join(ORIG, "runtime"), d)
    cfg = os.path.join(d, "SEconfig.h")
    txt = open(cfg).read()
    for name, macro in SE_MACRO.items():
        txt = re.sub(rf"#define {macro}\s+\d", f"#define {macro} {1 if name == se else 0}", txt)
    open(cfg, "w").write(txt)
    subprocess.run(["make", "-s", "-C", d, "CFLAGS=-O3 -w -I" + os.path.join(WORK, "shims", "include"),
                    "LIBS=/lib/x86_64-linux-gnu/libsodium.so.23 -lm"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe


def functional_check(src_rel, se, bins, n_tests, outdir, seed):
    """Run every bytecode and the plain C build on the same random inputs."""
    native = os.path.join(outdir, "native")
    out = subprocess.run([sys.executable, os.path.join(HERE, "native_ref.py"), src_rel, native],
                         cwd=ORIG, capture_output=True, text=True, check=True).stdout.split()
    n_in, n_out = int(out[0]), int(out[1])
    interp = interpreter_for(se)
    rng = random.Random(seed)
    results = {name: 0 for name in bins}
    examples = []
    for k in range(n_tests):
        inputs = [str(rng.getrandbits(32)) for _ in range(n_in)]
        ref = subprocess.run([native] + inputs, capture_output=True, text=True).stdout.split()
        row = {"inputs_first4": inputs[:4], "plain_C_first4": ref[:4]}
        for name, path in bins.items():
            got = subprocess.run([interp, path, "--inputs", ",".join(inputs), "--out_count", str(n_out)],
                                 capture_output=True, text=True).stdout.split()
            row[name + "_first4"] = got[:4]
            if got == ref:
                results[name] += 1
        examples.append(row)
    return {"tests": n_tests, "n_inputs": n_in, "n_outputs": n_out, "passed": results, "examples": examples}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--program", nargs="+",
                   help="one or more names in tests/automated/programs (AES, TinyJambu, Photon, ...)")
    g.add_argument("--source", nargs="+",
                   help="one or more C files relative to the repo root, or a quoted pattern, "
                        "e.g. 'tests/automated/basic/*.c'")
    ap.add_argument("--se", default="small", choices=SE, help="secure-element size (default small)")
    ap.add_argument("--flags", default="", help="extra flags given to BOTH compilers, e.g. '-width 4 -depth 25'")
    ap.add_argument("--ours", action="append", default=None,
                    help="flag set for our compiler; repeat to compare several (default: '-opt-all -opt-o5')")
    ap.add_argument("--seed", type=int, default=1, help="compilation seed, same for both (default 1)")
    ap.add_argument("--tests", type=int, default=3, help="random functional tests (0 = skip)")
    ap.add_argument("--sample-ms", type=int, default=50, help="RSS sampling period")
    ap.add_argument("--label", help="results folder name (default <program>_<se>)")
    ap.add_argument("--skip-original", action="store_true", help="reuse the original run saved under --label")
    ap.add_argument("--repeat", type=int, default=1, help="compile each version N times, report the median")
    ap.add_argument("--no-warmup", action="store_true", help="skip the unmeasured warm-up compile")
    # allow "--ours -opt-all" / "--flags -width 4" (values that start with '-')
    argv, i = [], 1
    while i < len(sys.argv):
        if sys.argv[i] in ("--ours", "--flags") and i + 1 < len(sys.argv):
            argv.append(f"{sys.argv[i]}={sys.argv[i + 1]}"); i += 2
        else:
            argv.append(sys.argv[i]); i += 1
    args = ap.parse_args(argv)

    # list of test cases: --program A B ... or --source f1.c f2.c ... (patterns like
    # tests/automated/basic/*.c are expanded relative to the repository root)
    if args.program:
        cases = [(f"tests/automated/programs/{p}.c", p) for p in args.program]
    else:
        cases = []
        for pat in args.source:
            found = sorted(glob.glob(pat, root_dir=ORIG)) if any(c in pat for c in "*?[") else [pat]
            cases += [(f, os.path.splitext(os.path.basename(f))[0]) for f in found]
    if not cases:
        sys.exit("no test case found")
    ours_sets = args.ours or ["-opt-all -opt-o5"]

    if len(cases) == 1:
        src, name = cases[0]
        compare_one(src, name, args, ours_sets, verbose=True)
        return

    # several test cases: one short summary table at the end
    rows = []
    for k, (src, name) in enumerate(cases, 1):
        print(f"[{k}/{len(cases)}] {name} ...", flush=True)
        s = compare_one(src, name, args, ours_sets, verbose=False, warmup=(k == 1))
        rows.append((name, s))
    line = "=" * (26 + 6 * 12 + 4)
    print("\n" + line)
    print(f"{'test case':26}{'ORIGINAL':>12}{'MEM-OPT':>12}{'change':>12}{'same output':>14}{'functional':>12}")
    print(f"{'':26}{'(MB)':>12}{'(MB)':>12}")
    print("-" * len(line))
    all_same = all_func = True
    for name, s in rows:
        o = s["runs"]["original"]
        m = s["runs"]["memoryoptimized"] if "memoryoptimized" in s["runs"] else list(s["runs"].values())[1]
        same = m["vs_original"]["identical"]
        fc = s.get("functional")
        func = "-" if not fc else f"{min(fc['passed'].values())}/{fc['tests']}"
        all_same &= same
        all_func &= (not fc) or min(fc["passed"].values()) == fc["tests"]
        print(f"{name[:25]:26}{o['peak_rss_mb']:>12.1f}{m['peak_rss_mb']:>12.1f}"
              f"{(m['peak_rss_mb'] - o['peak_rss_mb']) / o['peak_rss_mb'] * 100:>11.1f}%"
              f"{('YES' if same else 'NO'):>14}{func:>12}")
    print(line)
    print(f"same output as original for all {len(rows)} test cases: {'YES' if all_same else 'NO'}")
    print(f"all functional tests passed: {'YES' if all_func else 'NO'}")


def compare_one(src, name, args, ours_sets, verbose=True, warmup=True):
    if verbose:
        label = args.label or f"{name}_{args.se}"
    else:  # one of many test cases: keep them together in results/batch/
        label = os.path.join("batch", f"{name}_{args.se}")
    outdir = os.path.join(HERE, "results", label)
    bindir = os.path.join(WORK, "out", label)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(bindir, exist_ok=True)
    l_in, l_out, r, s = SE[args.se]
    common = ["-r", str(r), "-lin", str(l_in), "-lout", str(l_out), "-s", str(s), "-stats"] + args.flags.split()
    say = print if verbose else (lambda *a, **k: None)

    runs = []  # (name, cmd, cwd)
    runs.append(("original", [sys.executable, os.path.join(HERE, "run_original_seeded.py"), ORIG] + common +
                 [src, "-o", os.path.join(bindir, "original.bin")], ORIG))
    for i, fl in enumerate(ours_sets):
        rn = "memoryoptimized" if len(ours_sets) == 1 else f"memoryoptimized{i + 1}"
        runs.append((rn, [sys.executable, "compiler/src/main.py"] + common +
                     ["-seed", str(args.seed)] + fl.split() + [src, "-o", os.path.join(bindir, rn + ".bin")], OURS))

    say(f"== {name}  SE={args.se} (l_in={l_in}, l_out={l_out}, r={r}, s={s})  seed={args.seed}")
    summary = {"program": name, "source": src, "se": args.se, "seed": args.seed, "common_flags": common,
               "machine": f"{os.cpu_count()} cpus, "
               f"{os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30:.1f} GB RAM",
               "python": sys.version.split()[0], "runs": {}}
    prev_path = os.path.join(outdir, "summary.json")
    if args.skip_original and os.path.exists(prev_path):
        summary["runs"]["original"] = json.load(open(prev_path))["runs"]["original"]
        runs = runs[1:]
    os.environ["DEMO_SEED"] = str(args.seed)

    if warmup and not args.no_warmup:
        # The first run of each repo compiles its .py files into __pycache__,
        # which costs extra memory. Warm both up on a tiny program first so that
        # this one-off cost does not count against either side.
        say("-- warm-up (tiny program, not measured) ...", flush=True)
        tiny = ["-r", "40", "-lin", "8", "-lout", "8", "-s", "32", "tests/automated/basic/add.c",
                "-o", os.path.join(bindir, "warmup.bin")]
        subprocess.run([sys.executable, os.path.join(HERE, "run_original_seeded.py"), ORIG] + tiny,
                       cwd=ORIG, env=env(), capture_output=True)
        subprocess.run([sys.executable, "compiler/src/main.py", "-seed", "1"] + ours_sets[0].split() + tiny,
                       cwd=OURS, env=env(), capture_output=True)

    for rn, cmd, cwd in runs:
        flags = "" if rn == "original" else " ".join(cmd[cmd.index("-seed"):-3])
        say(f"-- compiling with the {display(rn)} compiler ...", flush=True)
        peaks, walls = [], []
        for rep in range(args.repeat):
            res = run_measured(cmd, cwd, args.sample_ms / 1000)
            if res["rc"] != 0:
                break
            peaks.append(res["peak_rss_kb"] / 1024)
            walls.append(res["wall_s"])
            if args.repeat > 1:
                say(f"   run {rep + 1}/{args.repeat}: peak RSS {peaks[-1]:8.1f} MB   wall {walls[-1]:7.1f} s", flush=True)
        if res["rc"] == 0:
            res["peak_rss_kb"] = statistics.median(peaks) * 1024
            res["wall_s"] = round(statistics.median(walls), 2)
        with open(os.path.join(outdir, f"log_{rn}.txt"), "w") as f:
            f.write("\n".join(f"[{t:8.2f}s] {l}" for t, l in res["lines"]) + "\n")
        with open(os.path.join(outdir, f"timeline_{rn}.csv"), "w") as f:
            f.write("t_s,rss_mb\n" + "".join(f"{t},{kb / 1024:.1f}\n" for t, kb in res["timeline"]))
        if res["rc"] != 0:
            print("\n".join(l for _, l in res["lines"][-20:]))
            sys.exit(f"{rn} failed (exit code {res['rc']})")
        phases, stats = analyse(res)
        binp = os.path.join(bindir, rn + ".bin")
        data = open(binp, "rb").read()
        summary["runs"][rn] = {"flags": flags, "peak_rss_mb": round(res["peak_rss_kb"] / 1024, 1),
                               "wall_s": res["wall_s"], "all_peaks_mb": [round(p, 1) for p in peaks],
                               "all_walls_s": walls, "phases": phases, "stats": stats,
                               "bytes": len(data), "masked_sha256": masked_digest(data), "bin": binp}
        say(f"   peak RSS {res['peak_rss_kb'] / 1024:8.1f} MB   wall {res['wall_s']:7.1f} s"
              + ("  (median)" if args.repeat > 1 else ""), flush=True)

    base = summary["runs"]["original"]
    orig_bytes = open(base["bin"], "rb").read()
    for rn, rr in summary["runs"].items():
        if rn != "original":
            rr["vs_original"] = compare_bytes(orig_bytes, open(rr["bin"], "rb").read())

    if args.tests > 0:
        say(f"-- functional check: {args.tests} random inputs, interpreter (SE={args.se}) vs plain C", flush=True)
        bins = {rn: rr["bin"] for rn, rr in summary["runs"].items()}
        summary["functional"] = functional_check(src, args.se, bins, args.tests, bindir, args.seed)

    json.dump(summary, open(os.path.join(outdir, "summary.json"), "w"), indent=1)
    if not verbose:
        return summary

    # ------------------------------------------------------------------ report
    # Only what shows the two claims: memory is reduced, and the output is the same.
    # (Per-phase memory and times are still saved in summary.json for the report.)
    names = list(summary["runs"])
    w = 20
    print("\n" + "=" * (34 + w * len(names)))
    print(f"{'':34}" + "".join(f"{display(n):>{w}}" for n in names))
    if len(names) > 2:  # several flag sets compared: show which is which
        print(f"{'flags':34}" + "".join(f"{(summary['runs'][n]['flags'].replace('-seed ' + str(args.seed), '').strip() or '-'):>{w}}" for n in names))

    def row(title, fn):
        print(f"{title:34}" + "".join(f"{fn(summary['runs'][n]):>{w}}" for n in names))
    row("peak memory (MB)", lambda r: f"{r['peak_rss_mb']:.1f}")
    row("change vs original", lambda r: f"{(r['peak_rss_mb'] - base['peak_rss_mb']) / base['peak_rss_mb'] * 100:+.1f}%")
    row("memory saved (MB)", lambda r: f"{base['peak_rss_mb'] - r['peak_rss_mb']:.1f}")
    row("compile time (s)", lambda r: f"{r['wall_s']:.1f}")
    print("-" * (34 + w * len(names)))
    row("bytecode size (bytes)", lambda r: f"{r['bytes']:,}")
    row("same output as original?", lambda r: "reference" if "vs_original" not in r else
        ("YES" if r["vs_original"]["identical"] else "NO"))
    if "functional" in summary:
        fc = summary["functional"]
        row("functional tests passed", lambda r: f"{fc['passed'][[k for k, v in summary['runs'].items() if v is r][0]]}/{fc['tests']}")
    print("=" * (34 + w * len(names)))
    print(f"results saved in {outdir}")
    return summary


if __name__ == "__main__":
    main()
