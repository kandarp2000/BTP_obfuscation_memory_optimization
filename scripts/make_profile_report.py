"""Build results/profile_by_phase.csv, results/profile_by_phase.png and
results/PROFILE.md from results/runs/baseline_profile.jsonl."""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from chart_style import style, SERIES, INK2
import matplotlib.pyplot as plt
from obscure_tools import ROOT

R = os.path.join(ROOT, "results")
runs = [json.loads(l) for l in open(os.path.join(R, "runs", "baseline_profile.jsonl"))]
runs = [r for r in runs if r.get("ok") and r.get("phases")]

with open(os.path.join(R, "profile_by_phase.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["program", "se", "phase", "current_mb", "peak_mb", "time_s", "process_maxrss_mb_with_tracemalloc"])
    for r in runs:
        for name, cur, peak, t in r["phases"]:
            w.writerow([r["program"], r["se"], name, cur, peak, t, round(r["maxrss_mb"], 1)])

def split(r):
    """Memory held at the end of universalize(), attributed to the phase that added it."""
    ph = {p[0]: p for p in r["phases"]}
    rect = ph["match_layers_inputs_outputs"][1]
    perm = ph["add_permutation"][1] - rect
    tot = [p for p in r["phases"] if p[0] == "TOTAL"] or [None]
    peak = max(p[2] for p in r["phases"])
    temp = peak - ph["check_dfg_integrity"][1]
    return rect, perm, peak, temp

style()
order = ["AES", "Ascon", "TinyJambu", "Photon", "tracingAES", "sum_naive", "sum_tree",
         "findmax_naive", "findmax_tree", "mnist"]
small = {r["program"]: r for r in runs if r["se"] == "small"}
progs = [p for p in order if p in small]
rect = [split(small[p])[0] for p in progs]
perm = [split(small[p])[1] for p in progs]
fig, ax = plt.subplots(figsize=(8, 0.42 * len(progs) + 1.2))
y = range(len(progs))
ax.barh(y, rect, color=SERIES[0], height=0.6, label="rectangularization (all phases before add_permutation)")
ax.barh(y, perm, left=rect, color=SERIES[1], height=0.6, label="add_permutation (routing gates)",
        edgecolor="#fcfcfb", linewidth=2)
for i, p in enumerate(progs):
    tot = rect[i] + perm[i]
    ax.text(tot * 1.01 + 1, i, f"{tot:.0f} MB  ({perm[i] / tot:.0%} routing)", va="center",
            fontsize=9, color=INK2)
ax.set_yticks(list(y)); ax.set_yticklabels(progs); ax.invert_yaxis()
ax.grid(axis="y", visible=False)
ax.set_xlabel("memory allocated inside universalize() and still held at its end (MB, tracemalloc)")
ax.set_xlim(0, max(r + q for r, q in zip(rect, perm)) * 1.35)
ax.set_title("Routing gates hold almost all universalization memory (small SE)")
ax.legend(loc="lower right", fontsize=9)
fig.savefig(os.path.join(R, "profile_by_phase.png"))

lines = ["# Profiling findings (baseline, tracemalloc inside universalize())", "",
         "| Program | SE | held at end (MB) | of which routing (add_permutation) | peak (MB) | peak above end (MB) | universalize time with profiling (s) |",
         "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
for p in progs:
    for se in ["small", "medium", "large", "xlarge"]:
        r = next((x for x in runs if x["program"] == p and x["se"] == se), None)
        if not r: continue
        rc, pm, peak, temp = split(r)
        t = sum(ph[3] for ph in r["phases"])
        lines.append(f"| {p} | {se} | {rc + pm:.1f} | {pm / (rc + pm):.0%} | {peak:.1f} | {temp:.2f} | {t:.1f} |")
open(os.path.join(R, "PROFILE.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
