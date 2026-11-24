"""Make the report figures from verification/results/*/ (run with any Python that has matplotlib).

    python plot_results.py            -> writes ../report/figures/*.pdf and *.png

Only measured data is plotted: every number comes from results/<label>/summary.json
and timeline_*.csv written by compare_mem.py.
"""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(os.path.dirname(HERE), "report", "figures")
os.makedirs(OUT, exist_ok=True)

# fixed categorical order (validated default palette, light mode); hatches for B/W print
SERIES = {
    "original": ("Original OBSCURE", "#2a78d6", ""),
    "ours1": ("Ours: O1-O4", "#eb6834", "//"),
    "ours2": ("Ours: O1-O5", "#1baf7a", "\\\\"),
    "ours3": ("Ours: O1-O5 + layering", "#eda100", "xx"),
}
INK, MUTED, GRID = "#1f1f1e", "#5f5e5a", "#dedcd5"
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 10,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
})


def load(label):
    p = os.path.join(RES, label, "summary.json")
    return json.load(open(p)) if os.path.exists(p) else None


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), bbox_inches="tight", dpi=200)
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- Fig: peak memory, % of original
SMALL = ["TinyJambu_small", "AES_small", "tracingAES_small", "sum_tree_small", "Ascon_small", "Photon_large"]
rows = [(lab, load(lab)) for lab in SMALL if load(lab)]
if rows:
    fig, ax = plt.subplots(figsize=(6.6, 3.2))
    keys = ["ours1", "ours2"]
    bw = 0.36
    for k, key in enumerate(keys):
        name, col, hatch = SERIES[key]
        xs, ys = [], []
        for i, (lab, s) in enumerate(rows):
            if key in s["runs"]:
                base = s["runs"]["original"]["peak_rss_mb"]
                xs.append(i + (k - 0.5) * bw)
                ys.append(100 * s["runs"][key]["peak_rss_mb"] / base)
        bars = ax.bar(xs, ys, bw * 0.92, color=col, hatch=hatch, edgecolor="white", linewidth=0.5, label=name)
        for x, y in zip(xs, ys):
            ax.text(x, y - 8, f"{y - 100:+.1f}%", ha="center", va="top", fontsize=7.5, color=INK,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))
    ax.axhline(100, color=SERIES["original"][1], lw=1.5, label="Original OBSCURE = 100%")
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([s["program"] + "\n" + s["se"] + " SE" for _, s in rows], fontsize=8.5)
    ax.set_ylabel("Peak memory (% of original)")
    ax.set_ylim(0, 115)
    ax.legend(loc="lower left", fontsize=8.5, ncol=3, bbox_to_anchor=(0, 1.0))
    save(fig, "fig_peak_memory_percent")

# ---------------------------------------------------------------- Fig: memory timeline + phases (medium test)
for lab in ("Photon_large", "TinyJambu_small"):
    s = load(lab)
    if not s:
        continue
    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    for key in [k for k in ("original", "ours1", "ours2") if k in s["runs"]]:
        # align the runs at the end of clusterization: the passes before it are
        # unchanged, and their run-to-run time noise would shift the curves
        t0 = 0.0
        for line in open(os.path.join(RES, lab, f"log_{key}.txt")):
            if "] Clusterization:" in line:
                t0 = float(line.split("s]")[0].strip("[ "))
        t, m = [], []
        with open(os.path.join(RES, lab, f"timeline_{key}.csv")) as f:
            for r in csv.DictReader(f):
                if float(r["t_s"]) >= t0 - 5:
                    t.append(float(r["t_s"]) - t0)
                    m.append(float(r["rss_mb"]))
        ax.plot(t, m, color=SERIES[key][1], lw=1.6,
                label=f"{SERIES[key][0]}  (peak {s['runs'][key]['peak_rss_mb']:.1f} MB)")
    ax.set_xlabel("Time since the end of clusterization (s)  [universalization -> lowering -> serialization]")
    ax.set_ylabel("Resident memory, RSS (MB)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", fontsize=8.5)
    save(fig, f"fig_timeline_{lab}")

# ---------------------------------------------------------------- Fig: peak per phase (medium test)
for lab in ("Photon_large", "TinyJambu_small"):
    s = load(lab)
    if not s:
        continue
    keys = [k for k in ("original", "ours1", "ours2") if k in s["runs"]]
    phases = [p["phase"] for p in s["runs"]["original"]["phases"]]
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    bw = 0.8 / len(keys)
    for k, key in enumerate(keys):
        name, col, hatch = SERIES[key]
        ys = [p["peak_rss_mb"] or 0 for p in s["runs"][key]["phases"]]
        ax.bar([i + (k - (len(keys) - 1) / 2) * bw for i in range(len(ys))], ys, bw * 0.92,
               color=col, hatch=hatch, edgecolor="white", linewidth=0.5, label=name)
    names = {"frontend": "frontend", "clusterization": "cluster-\nization",
             "universalize: rectangularize": "univ.:\nrectangularize",
             "universalize: permutation networks": "univ.:\nperm. networks",
             "lowering": "lowering", "serialization": "serial-\nization"}
    short = [next(v for k, v in names.items() if p.startswith(k)) for p in phases]
    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels(short, fontsize=7.2)
    ax.set_ylabel("Peak RSS during phase (MB)")
    ax.legend(loc="upper left", fontsize=8.5)
    save(fig, f"fig_phase_peaks_{lab}")

# ---------------------------------------------------------------- LaTeX table snippets of the measured numbers
lines = []
for lab, s in rows:
    o = s["runs"]["original"]
    def cell(key):
        if key not in s["runs"]:
            return "--", "--"
        r = s["runs"][key]
        return f"{r['peak_rss_mb']:.1f}", f"{(r['peak_rss_mb'] - o['peak_rss_mb']) / o['peak_rss_mb'] * 100:+.1f}\\%"
    a, da = cell("ours1")
    b, db = cell("ours2")
    same = all(r.get("vs_original", {}).get("identical", True) for k, r in s["runs"].items() if k in ("ours1", "ours2"))
    fc = s.get("functional", {})
    func = "/".join(str(fc["passed"][k]) for k in ("original", "ours1", "ours2") if k in fc.get("passed", {})) + f" of {fc.get('tests', 0)}" if fc else "--"
    lines.append(f"{s['program']} & {s['se']} & {o['peak_rss_mb']:.1f} & {a} & {da} & {b} & {db} & "
                 f"{'Yes' if same else 'No'} & {func} \\\\")
open(os.path.join(OUT, "table_peak.tex"), "w").write("\n".join(lines) + "\n")
print("wrote table_peak.tex")
