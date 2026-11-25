"""Aggregate all runs into results/results.csv, results/ablation_table.md and figures."""
import csv, glob, json, os, statistics, sys
sys.path.insert(0, os.path.dirname(__file__))
from chart_style import style, SERIES, INK2
import matplotlib.pyplot as plt
from obscure_tools import ROOT

R = os.path.join(ROOT, "results")
def load(label):
    p = os.path.join(R, "runs", f"{label}.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

ORDER = ["AES", "Ascon", "TinyJambu", "Photon", "tracingAES", "sum_naive", "sum_tree",
         "findmax_naive", "findmax_tree", "mnist"]
SES = ["small", "medium", "large", "xlarge"]
FIELDS = ["label", "program", "se", "rep", "flags", "ok", "maxrss_mb", "univ_retained_mb",
          "univ_peak_mb", "univ_time", "total_time", "wall", "mlmis_rect", "mlmis_final",
          "depth", "width", "bytes", "digest", "error"]

# ---- results.csv: every run ------------------------------------------------
rows = []
for p in sorted(glob.glob(os.path.join(R, "runs", "*.jsonl"))):
    for l in open(p):
        r = json.loads(l); r.setdefault("label", os.path.basename(p)[:-6]); rows.append(r)
with open(os.path.join(R, "results.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader()
    for r in rows: w.writerow(r)

def idx(label):
    d = {}
    for r in load(label):
        if r.get("ok"):
            # early profile runs only stored the per-phase rows: memory held
            # at the end of universalize() = "current" of its last phase
            if r.get("univ_retained_mb") is None and r.get("phases"):
                r["univ_retained_mb"] = r["phases"][-1][1]
            d.setdefault((r["program"], r["se"]), []).append(r)
    return d
def get(d, k, field, agg=statistics.median):
    vals = [r[field] for r in d.get(k, []) if r.get(field) is not None]
    return agg(vals) if vals else None
def pct(a, b):
    return f"{(b - a) / a:+.1%}" if a and b is not None else "-"
def fmt(x, nd=1):
    return "-" if x is None else f"{x:,.{nd}f}"

base, prof_b, prof_o = idx("baseline"), idx("baseline_profile"), idx("opt_all_prof")
abl = [("baseline", "baseline"), ("opt_o1", "+O1"), ("opt_o1o2", "+O1+O2"),
       ("opt_o1o2o3", "+O1+O2+O3"), ("opt_all", "+O1..O4"), ("opt_layering", "+O1..O4 +layering")]
D = {lab: idx(lab) for lab, _ in abl}
out = []

# ---- Table 1: identical output ----------------------------------------------
out += ["## 1. Identical output (masked SHA-256 of the bytecode vs. baseline, seed 1)", "",
        "| Configuration | identical / compared |", "| --- | ---: |"]
for lab, name in abl[1:5] + [("opt_all_prof", "+O1..O4 with -profile-mem")]:
    d = idx(lab); n = s = 0
    for k, rs in d.items():
        if k in base:
            n += 1; s += rs[0]["digest"] == base[k][0]["digest"]
    if n: out.append(f"| {name} | {s} / {n} |")

# ---- Table 2: ablation, peak RSS ---------------------------------------------
out += ["", "## 2. Ablation: whole-compiler peak RSS (MB), small SE", "",
        "| Program | " + " | ".join(n for _, n in abl) + " | change O1..O4 | change +layering |",
        "| --- |" + " ---: |" * (len(abl) + 2)]
for p in ORDER:
    k = (p, "small")
    if k not in base: continue
    vals = [get(D[l], k, "maxrss_mb") for l, _ in abl]
    out.append(f"| {p} | " + " | ".join(fmt(v) for v in vals) +
               f" | {pct(vals[0], vals[4])} | {pct(vals[0], vals[5])} |")

# ---- Table 3: all SEs, baseline vs optimized ----------------------------------
out += ["", "## 3. All SE sizes: baseline vs. O1..O4 (identical output) vs. +layering", "",
        "| Program | SE | peak RSS base (MB) | O1..O4 | change | +layering | change | held after universalize base (MB) | O1..O4 | #LLMIs base | +layering |",
        "| --- | --- |" + " ---: |" * 9]
for p in ORDER:
    for se in SES:
        k = (p, se)
        if k not in base: continue
        b, o, l = get(base, k, "maxrss_mb"), get(D["opt_all"], k, "maxrss_mb"), get(D["opt_layering"], k, "maxrss_mb")
        rb, ro = get(prof_b, k, "univ_retained_mb"), get(prof_o, k, "univ_retained_mb")
        out.append(f"| {p} | {se} | {fmt(b)} | {fmt(o)} | {pct(b, o)} | {fmt(l)} | {pct(b, l)} | "
                   f"{fmt(rb)} | {fmt(ro)} | {fmt(get(base, k, 'mlmis_final'), 0)} | "
                   f"{fmt(get(D['opt_layering'], k, 'mlmis_final'), 0)} |")

# ---- Table 4: time --------------------------------------------------------------
tb, to = idx("time_baseline"), idx("time_opt_all")
if tb:
    out += ["", "## 4. Compile time, median of 3 runs, small SE, one job at a time (s)", "",
            "| Program | universalize base | O1..O4 | change | total base | O1..O4 | change |",
            "| --- |" + " ---: |" * 6]
    for p in ORDER:
        k = (p, "small")
        if k not in tb: continue
        ub, uo = get(tb, k, "univ_time"), get(to, k, "univ_time")
        cb, co = get(tb, k, "total_time"), get(to, k, "total_time")
        out.append(f"| {p} | {fmt(ub, 2)} | {fmt(uo, 2)} | {pct(ub, uo)} | {fmt(cb, 2)} | {fmt(co, 2)} | {pct(cb, co)} |")

open(os.path.join(R, "ablation_table.md"), "w").write("\n".join(out) + "\n")
print("\n".join(out))

# ---- Figure: ablation ------------------------------------------------------------
style()
progs = [p for p in ORDER if (p, "small") in base]
show = [("baseline", "baseline"), ("opt_all", "O1–O4 (identical output)"),
        ("opt_layering", "O1–O4 + layering (stretch)")]
fig, ax = plt.subplots(figsize=(9, 4.2))
wbar = 0.26
for j, (lab, name) in enumerate(show):
    xs = [i + (j - 1) * wbar for i in range(len(progs))]
    ys = [get(D[lab], (p, "small"), "maxrss_mb") or 0 for p in progs]
    ax.bar(xs, ys, width=wbar - 0.03, color=SERIES[j], label=name)
ax.set_xticks(range(len(progs))); ax.set_xticklabels(progs, rotation=30, ha="right")
ax.set_ylabel("peak RSS of the whole compiler (MB)")
ax.grid(axis="x", visible=False)
ax.set_title("Peak memory per program, small SE")
ax.legend(loc="upper left", fontsize=9)
fig.savefig(os.path.join(R, "ablation_rss.png"))

# ---- Figure: scaling ---------------------------------------------------------------
for path in glob.glob(os.path.join(R, "runs", "scaling_*.jsonl")):
    rs = [json.loads(l) for l in open(path)]
    rs = [r for r in rs if r.get("ok")]
    name = os.path.basename(path)[8:-6]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, kind, xl in [(axes[0], "depth", "forced depth (-depth)"),
                         (axes[1], "width", "forced width (-width)")]:
        for j, (lab, nm) in enumerate([("baseline", "baseline"), ("optimized", "O1–O4")]):
            pts = sorted((r["value"], r["univ_retained_mb"]) for r in rs
                         if r["kind"] == kind and r["label"] == lab and r["profiled"]
                         and r.get("univ_retained_mb") is not None)
            if pts:
                ax.plot([x for x, _ in pts], [y for _, y in pts], marker="o", color=SERIES[j], label=nm)
        ax.set_xlabel(xl); ax.set_ylim(bottom=0)
        ax.set_ylabel("memory held after universalize() (MB)")
        ax.legend(fontsize=9)
    axes[0].set_title(f"Scaling with depth ({name})")
    axes[1].set_title(f"Scaling with width ({name})")
    fig.tight_layout()
    fig.savefig(os.path.join(R, f"scaling_{name}.png"))
