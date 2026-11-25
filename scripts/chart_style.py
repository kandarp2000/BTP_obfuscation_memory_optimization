"""Shared matplotlib style for the report figures (validated default categorical
palette, thin marks, recessive axes)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"

def style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.axisbelow": True, "font.size": 10, "axes.titlesize": 12,
        "axes.titleweight": "bold", "axes.titlelocation": "left",
        "legend.frameon": False, "lines.linewidth": 2, "lines.markersize": 6,
        "savefig.dpi": 160, "savefig.bbox": "tight",
    })
