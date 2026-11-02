"""Publication figures from saved results only; no model fitting or filtering."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "figures"
TEAL, PURPLE, GRAY = "#007C91", "#79549A", "#A5ADB7"
plt.rcParams.update({
    "font.family": "STIXGeneral", "font.size": 10.5, "axes.titlesize": 11.5,
    "axes.labelsize": 10.5, "xtick.labelsize": 9.5, "ytick.labelsize": 9.5,
    "pdf.fonttype": 42, "ps.fonttype": 42, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": "#56616C",
    "axes.linewidth": .6, "xtick.major.width": .6, "ytick.major.width": .6,
    "savefig.facecolor": "white", "figure.facecolor": "white",
})
REPORTS = {k: json.loads((ROOT / f"artifacts/reports/sampling-k{k}-v1/analysis.json").read_text()) for k in (4, 8, 16)}


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", metadata={"Creator": "", "Producer": "", "CreationDate": None})
    fig.savefig(OUT / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def style(ax):
    ax.axhline(0, color="#606A74", lw=.7, zorder=1)
    ax.grid(axis="y", color="#E9EDF0", lw=.55)
    ax.set_axisbelow(True)
    ax.tick_params(length=3)


fig, axes = plt.subplots(1, 2, figsize=(6.0, 2.65))
for ax, metric, title, color, label in zip(axes,
        ("centroid_rmsd", "energy_score"),
        ("A   Endpoint RMSD", "B   Statistical energy score"),
        (TEAL, PURPLE), ("Endpoint RMSD gain (Å)", "Energy-score gain (Å)")):
    means, low, high = [], [], []
    for index, k in enumerate((4, 8, 16)):
        a = REPORTS[k]["analysis"]
        rows = a["per_protein"]
        gains = -np.array([r["delta"][metric] for r in rows])
        ci = a["bootstrap"][0]["ci_percentile"][metric]
        means.append(gains.mean()); low.append(-ci["high"]); high.append(-ci["low"])
        # Fixed horizontal offsets distinguish the eight proteins, not extra replicates.
        ax.scatter(index + np.linspace(-.12, .12, len(gains)), gains, s=12,
                   color=GRAY, alpha=.65, edgecolors="none", zorder=2)
    means = np.array(means)
    ax.plot(range(3), means, color=color, lw=1.6, zorder=3)
    ax.errorbar(range(3), means, yerr=[means-low, high-means], fmt="o", color=color,
                ecolor=color, capsize=3, markersize=5, lw=1.35, zorder=4)
    ax.set_xticks(range(3), ["4", "8", "16"])
    ax.set_xlim(-.38, 2.38)
    ax.set_xlabel("Draws per model, K")
    ax.set_ylabel(label)
    ax.set_title(title, loc="left", fontweight="bold", pad=10)
    style(ax)
axes[0].set_ylim(-.005, .047)
axes[1].set_ylim(-.013, .027)
fig.subplots_adjust(left=.105, right=.99, top=.84, bottom=.22, wspace=.42)
save(fig, "sampling_sensitivity")

fig, axes = plt.subplots(1, 2, figsize=(6.0, 3.05), sharey=True)
rows4, rows16 = (REPORTS[k]["analysis"]["per_protein"] for k in (4, 16))
assert [r["protein_id"] for r in rows4] == [r["protein_id"] for r in rows16]
y = np.arange(len(rows4))
for ax, metric, title, color in zip(axes, ("centroid_rmsd", "energy_score"),
        ("C   Endpoint RMSD", "D   Statistical energy score"), (TEAL, PURPLE)):
    gain4 = -np.array([r["delta"][metric] for r in rows4])
    gain16 = -np.array([r["delta"][metric] for r in rows16])
    ax.axvline(0, color="#606A74", lw=.7, zorder=1)
    for yy, old, new in zip(y, gain4, gain16):
        ax.plot([old, new], [yy, yy], color=GRAY, lw=1.25, zorder=2)
    ax.scatter(gain4, y, s=23, facecolor="white", edgecolor=GRAY, linewidth=1, zorder=3)
    ax.scatter(gain16, y, s=25, color=color, edgecolor="white", linewidth=.5, zorder=4)
    ax.set_title(title, loc="left", fontweight="bold", pad=9)
    ax.set_xlabel("Source − adapted error (Å)")
    ax.grid(axis="x", color="#E9EDF0", lw=.55)
    ax.set_axisbelow(True)
    ax.set_yticks(y, [r["protein_id"] for r in rows4])
    ax.tick_params(length=3)
axes[0].invert_yaxis()
axes[0].set_xlim(-.003, .045)
axes[1].set_xlim(-.010, .025)
fig.legend(handles=[Line2D([0],[0], marker="o", color="none", markerfacecolor="white", markeredgecolor=GRAY, label="K = 4"),
                    Line2D([0],[0], marker="o", color="none", markerfacecolor="#44515E", markeredgecolor="white", label="K = 16")],
           loc="upper center", bbox_to_anchor=(.55, 1.025), ncol=2, frameon=False, fontsize=8)
fig.subplots_adjust(left=.15, right=.99, top=.82, bottom=.17, wspace=.25)
save(fig, "protein_sensitivity")

summary = {str(k): REPORTS[k]["report"]["per_seed_summary"][0] for k in (4,8,16)}
(OUT / "plotted_values.json").write_text(json.dumps(summary, indent=2) + "\n")
print("Saved two vector figures and exact plotted values.")
