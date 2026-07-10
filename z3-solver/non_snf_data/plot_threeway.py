import json, statistics
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BG, BG2, BG3, BORDER, TEXT, SUB = "#0f1117","#1a1d2e","#242740","#2e3152","#e8eaf6","#8b8fa8"
NAIVE_C, NONSNF_C, STRUCT_C, ACC4 = "#ff6b6b", "#ffa552", "#4ecdc4", "#ffe66d"

def summ(path):
    data = json.loads(Path(path).read_text())
    times = [r["elapsed_ms"] for r in data]
    return dict(mean=statistics.mean(times),
                stdev=statistics.stdev(times) if len(times) > 1 else 0,
                n=len(times), tos=sum(r["timed_out"] for r in data))

benches = ["b3", "php3", "php4", "php5", "php6"]
labels  = ["b3\nmutex (10!)", "PHP3\n4p/3h", "PHP4\n5p/4h", "PHP5\n6p/5h", "PHP6\n7p/6h"]

naive_s, nonsnf_s, struct_s = [], [], []
for b in benches:
    n = summ(f"z3-solver/results/results_{b}_naive.json")
    m = summ(f"z3-solver/results_nonsnf/results_{b}_nonsnf.json")
    s = summ(f"z3-solver/results/results_{b}_structured.json")
    naive_s.append(n["stdev"]); nonsnf_s.append(m["stdev"]); struct_s.append(s["stdev"])

x = np.arange(len(benches))
w = 0.27
fig, ax = plt.subplots(figsize=(11, 6))
fig.patch.set_facecolor(BG); ax.set_facecolor(BG2)
ax.tick_params(colors=SUB, labelsize=9)
for spine in ax.spines.values(): spine.set_edgecolor(BORDER)
ax.grid(color=BORDER, linewidth=0.5, linestyle="--", alpha=0.5)

ax.set_yscale("log")

bars1 = ax.bar(x-w, naive_s,   w, color=NAIVE_C,  alpha=0.9, label="Naive AUFLIA")
bars2 = ax.bar(x,   nonsnf_s,  w, color=NONSNF_C, alpha=0.9, label="Non-SNF QF_LIA")
bars3 = ax.bar(x+w, struct_s,  w, color=STRUCT_C, alpha=0.9, label="Structured QF_LIA (SNF)")

for bars, color in [(bars1,NAIVE_C),(bars2,NONSNF_C),(bars3,STRUCT_C)]:
    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x()+bar.get_width()/2, h*1.15, f"{h:.1f}",
                ha="center", va="bottom", color=color, fontsize=8, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(labels, color=SUB, fontsize=9)
ax.set_ylabel("Standard Deviation of Solve Time, ms (log scale)", color=SUB)
ax.set_title(
    "Figure 8 — Three-Way Stability Comparison: Naive vs Non-SNF vs Structured QF_LIA\n"
    "Stability gap closes with theory change (AUFLIA→QF_LIA); SNF provides structural derivation and completeness, not additional variance reduction" ,
    color=TEXT, fontsize=11
)
ax.legend(facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT, fontsize=9, loc="upper left")

fig.tight_layout()
out = Path("z3-solver/figures")
out.mkdir(exist_ok=True)
fig.savefig(out / "fig8_threeway_stdev.png", dpi=150, facecolor=BG, bbox_inches="tight")
print("saved fig8_threeway_stdev.png")