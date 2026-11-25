"""Scaling sweep: peak memory vs. forced depth and forced width (-depth / -width).

Usage: python3 scripts/scaling_sweep.py <program> <se> [--jobs N]
Writes results/runs/scaling_<program>_<se>.jsonl
"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from obscure_tools import ROOT, PROGRAMS, compile_prog

CONFIGS = {"baseline": [], "optimized": ["-opt-all"]}

def job(a):
    prog, se, kind, val, label, prof = a
    out = os.path.join(ROOT, "results", "bytecode", f"scal_{prog}_{se}_{kind}{val}_{label}{int(prof)}.bin")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fl = CONFIGS[label] + [f"-{kind}", str(val)] + (["-profile-mem"] if prof else [])
    r = compile_prog(PROGRAMS[prog], se, out, flags=fl)
    if os.path.exists(out): os.remove(out)
    r.pop("stdout", None); r.pop("stderr", None)
    r.update(program=prog, se=se, kind=kind, value=val, label=label, profiled=prof)
    return r

ap = argparse.ArgumentParser()
ap.add_argument("program"); ap.add_argument("se"); ap.add_argument("--jobs", type=int, default=2)
ap.add_argument("--depths", default="400,800,1600,3200")
ap.add_argument("--widths", default="4,8,16,32,64")
a = ap.parse_args()
jobs = [(a.program, a.se, "depth", int(v), lab, prof) for v in a.depths.split(",")
        for lab in CONFIGS for prof in (False, True)]
jobs += [(a.program, a.se, "width", int(v), lab, prof) for v in a.widths.split(",")
         for lab in CONFIGS for prof in (False, True)]
path = os.path.join(ROOT, "results", "runs", f"scaling_{a.program}_{a.se}.jsonl")
with open(path, "w") as f, ProcessPoolExecutor(a.jobs) as ex:
    for r in ex.map(job, jobs):
        f.write(json.dumps(r) + "\n"); f.flush()
        print(r["kind"], r["value"], r["label"], "prof" if r["profiled"] else "rss ",
              r["ok"], f"rss={r.get('maxrss_mb', 0):.0f}MB retained={r.get('univ_retained_mb')}", flush=True)
