"""Compile every benchmark program for every SE size with a given set of flags.

Usage: python3 scripts/run_matrix.py <label> [--jobs N] [--programs a,b] [--se small,medium]
                                     [--repeat K] [-- extra compiler flags...]
Writes results/runs/<label>.jsonl (one JSON object per compilation).
"""
import argparse, json, os, re, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from obscure_tools import ROOT, SE, PROGRAMS, compile_prog

def job(args):
    label, prog, se, flags, rep, keep = args
    out_dir = os.path.join(ROOT, "results", "bytecode", label)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{prog}_{se}.bin")
    r = compile_prog(PROGRAMS[prog], se, out, flags=flags)
    if not keep and os.path.exists(out):
        os.remove(out)
    # keep the per-phase memory rows printed by -profile-mem
    phases = []
    for line in r.get("stdout", "").splitlines():
        m = re.match(r"\[mem\] (\S+)\s+current=\s*([\d.]+) MB\s+peak=\s*([\d.]+) MB\s+time=\s*([\d.]+) s", line)
        if m:
            phases.append([m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))])
    if phases:
        r["phases"] = phases
    r.pop("stdout", None)
    if r["ok"]:
        r.pop("stderr", None)
    r.update(label=label, program=prog, se=se, flags=" ".join(flags), rep=rep)
    return r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--programs", default=",".join(PROGRAMS))
    ap.add_argument("--se", default=",".join(SE))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--keep", action="store_true", help="keep the bytecode files")
    ap.add_argument("--resume", action="store_true",
                    help="append to an existing result file and skip finished cases")
    ap.add_argument("flags", nargs="*")
    a = ap.parse_args()
    jobs = [(a.label, p, se, a.flags, rep, a.keep)
            for rep in range(a.repeat)
            for p in a.programs.split(",") for se in a.se.split(",")]
    os.makedirs(os.path.join(ROOT, "results", "runs"), exist_ok=True)
    path = os.path.join(ROOT, "results", "runs", f"{a.label}.jsonl")
    mode = "w"
    if a.resume and os.path.exists(path):
        done = {(r["program"], r["se"], r["rep"]) for r in map(json.loads, open(path))}
        jobs = [j for j in jobs if (j[1], j[2], j[4]) not in done]
        mode = "a"
    if not jobs:
        print("nothing to do"); return
    with open(path, mode) as f, ProcessPoolExecutor(a.jobs) as ex:
        for r in ex.map(job, jobs):
            f.write(json.dumps(r) + "\n"); f.flush()
            print(f"{r['program']:14s} {r['se']:7s} rep={r['rep']} ok={r['ok']} "
                  f"wall={r['wall']:.1f}s rss={r.get('maxrss_mb',0):.0f}MB "
                  f"univ_peak={r.get('univ_peak_mb','-')} digest={r.get('digest','')[:12]}",
                  flush=True)

if __name__ == "__main__":
    main()
