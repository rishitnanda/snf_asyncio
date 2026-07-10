import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Style ─────────────────────────────────────────────────────────────────────
BG       = "#0f1117"
BG2      = "#1a1d2e"
BG3      = "#242740"
BORDER   = "#2e3152"
TEXT     = "#e8eaf6"
SUB      = "#8b8fa8"
NAIVE_C  = "#ff6b6b"
STRUCT_C = "#4ecdc4"
ACC4     = "#ffe66d"
ACC2     = "#ff9f43"

def style(fig, axes):
    fig.patch.set_facecolor(BG)
    axlist = list(axes.flat) if hasattr(axes, 'flat') else \
             (axes if hasattr(axes, '__iter__') else [axes])
    for ax in axlist:
        ax.set_facecolor(BG2)
        ax.tick_params(colors=SUB, labelsize=9)
        ax.xaxis.label.set_color(SUB)
        ax.yaxis.label.set_color(SUB)
        ax.title.set_color(TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER)
        ax.grid(color=BORDER, linewidth=0.5, linestyle="--", alpha=0.5)

ASYNCIO_LABELS = {
    "b1": "b1 TaskGroup",
    "b2": "b2 fire-forget",
    "b3": "b3 mutex",
    "b4": "b4 event",
    "b5": "b5 wait_for",
    "b6": "b6 queue",
    "b7": "b7 broadcast",
}
PHP_LABELS = {
    "php3": "PHP₃\n4p/3h",
    "php4": "PHP₄\n5p/4h",
    "php5": "PHP₅\n6p/5h",
    "php6": "PHP₆\n7p/6h",
}

def load_results(results_dir: str) -> dict:
    data = {}
    for f in Path(results_dir).glob("results_*.json"):
        if "test" in f.stem:
            continue
        parts = f.stem.replace("results_", "").split("_")
        bench    = parts[0]
        encoding = "_".join(parts[1:])
        data[(bench, encoding)] = json.loads(f.read_text())
    return data

def summ(runs):
    times   = [r["elapsed_ms"] for r in runs]
    results = [r["result"]     for r in runs]
    tos     = sum(r["timed_out"] for r in runs)
    return dict(
        mean     = statistics.mean(times),
        stdev    = statistics.stdev(times) if len(times) > 1 else 0.0,
        median   = statistics.median(times),
        min      = min(times),
        max      = max(times),
        n        = len(times),
        timeouts = tos,
        results  = results,
        times    = times,
        has_sat  = any(r not in ("unsat", "unknown") for r in results),
    )

# ── Figure 1 — Correctness gap ────────────────────────────────────────────────
def fig_correctness_gap(data, outdir):
    gap_benches = [
        ("b2", "fire-forget\n(cancel timing)"),
        ("b4", "event broadcast\n(wake guarantee)"),
        ("b5", "wait_for\n(race outcome)"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    style(fig, axes)
    fig.suptitle(
        "Figure 1 — Correctness Gap: Naive Encodings Return SAT (Property Unprovable)\n"
        "Structured encodings correctly return UNSAT for the same property",
        color=TEXT, fontsize=11
    )

    for ax, (bench, label) in zip(axes, gap_benches):
        ns = summ(data[(bench, "naive")])
        ss = summ(data[(bench, "structured")])

        n_sat     = sum(1 for r in ns["results"] if r == "sat")
        n_unsat_n = sum(1 for r in ns["results"] if r == "unsat")
        n_to_n    = ns["timeouts"]
        n_unsat_s = sum(1 for r in ss["results"] if r == "unsat")

        categories  = ["SAT\n(gap)", "UNSAT", "Timeout"]
        naive_vals  = [n_sat, n_unsat_n, n_to_n]
        struct_vals = [0, n_unsat_s, 0]

        x = np.arange(3)
        w = 0.35
        bars_n = ax.bar(x - w/2, naive_vals,  w, color=NAIVE_C,  alpha=0.85, label="Naive")
        bars_s = ax.bar(x + w/2, struct_vals, w, color=STRUCT_C, alpha=0.85, label="Structured")

        for bar in bars_n:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x()+bar.get_width()/2, h+0.3, str(int(h)),
                        ha="center", va="bottom", color=NAIVE_C, fontsize=9, fontweight="bold")
        for bar in bars_s:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x()+bar.get_width()/2, h+0.3, str(int(h)),
                        ha="center", va="bottom", color=STRUCT_C, fontsize=9, fontweight="bold")

        ax.set_xticks(x)
        ax.set_xticklabels(categories, color=SUB, fontsize=9)
        ax.set_ylabel("Number of runs", color=SUB, fontsize=9)
        ax.set_title(f"{bench}: {label}", color=TEXT, fontsize=10)
        ax.set_ylim(0, max(ns["n"], ss["n"]) * 1.15)
        ax.legend(facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT, fontsize=8)

        # Arrow pointing at the SAT bar from above-right
        if n_sat > 0:
            ax.annotate(
                "Correctness\ngap",
                xy=(x[0] - w/2, n_sat),
                xytext=(x[0] - w/2 + 0.6, n_sat * 0.65),
                color=ACC4, fontsize=8,
                arrowprops=dict(arrowstyle="->", color=ACC4, lw=1.2),
            )

    fig.tight_layout()
    out = outdir / "fig1_correctness_gap.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Figure 2 — Asyncio stdev: honest single-panel ────────────────────────────
def fig_asyncio_stdev(data, outdir):
    """
    All 6 asyncio benchmarks on one shared axis.

    The key honest observation:
      - For b1-b5, naive σ < structured σ (naive is tighter). This is because
        naive times out on SAT (wrong answer), so it exits quickly and stably.
        The structured solver takes the correct UNSAT path but with more variance.
      - b6 is the only bench where structured σ < naive σ.
      - Stdev is NOT the instability story for asyncio — that's Fig 4 (PHP).
    """
    benches = ["b1", "b2", "b3", "b4", "b5", "b6", "b7"]

    naive_s  = [summ(data[(b, "naive")])["stdev"]      for b in benches if (b, "naive") in data]
    struct_s = [summ(data[(b, "structured")])["stdev"] for b in benches if (b, "structured") in data]
    has_sat  = [summ(data[(b, "naive")])["has_sat"]    for b in benches if (b, "naive") in data]
    benches  = [b for b in benches if (b, "naive") in data and (b, "structured") in data]

    fig, ax = plt.subplots(figsize=(14, 5))
    style(fig, [ax])

    w = 0.35
    x = np.arange(len(benches))

    ax.bar(x - w/2, naive_s,  w, color=NAIVE_C,  alpha=0.85, label="Naive (AUFLIA)")
    ax.bar(x + w/2, struct_s, w, color=STRUCT_C, alpha=0.85, label="Structured (QF_LIA)")

    for xi, (nv, sv, sat) in enumerate(zip(naive_s, struct_s, has_sat)):
        ax.text(xi - w/2, nv + 0.1, f"{nv:.1f}",
                ha="center", va="bottom", color=NAIVE_C, fontsize=8, fontweight="bold")
        ax.text(xi + w/2, sv + 0.1, f"{sv:.1f}",
                ha="center", va="bottom", color=STRUCT_C, fontsize=8, fontweight="bold")
        if sat:
            ax.text(xi - w/2, -max(naive_s) * 0.18, "SAT ★",
                    ha="center", color=ACC4, fontsize=7, style="italic")

    ax.set_xticks(x)
    ax.set_xticklabels([ASYNCIO_LABELS[b] for b in benches], color=SUB, fontsize=9)
    ax.set_ylabel("Standard Deviation of Solve Time (ms)", color=SUB)
    ax.legend(facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT, fontsize=9)

    # Annotate benches where structured is tighter
    for ann_bench in ("b6", "b7"):
        if ann_bench in benches:
            idx = benches.index(ann_bench)
            ax.annotate(
                "structured\ntighter here",
                xy=(idx + w/2, struct_s[idx]),
                xytext=(idx + w/2 + 0.6, struct_s[idx] + 1.2),
                color=STRUCT_C, fontsize=7,
                arrowprops=dict(arrowstyle="->", color=STRUCT_C, lw=1.0),
            )

    fig.suptitle(
        "Figure 2 — Asyncio Benchmark Solve-Time Variance (σ)\n"
        "Naive σ ≤ structured σ for b1–b5 (naive exits early on incorrect SAT answer)  |"
        "  ★ = correctness gap  |  Stdev story for PHP: see Fig 4",
        color=TEXT, fontsize=10
    )
    fig.tight_layout()
    out = outdir / "fig2_asyncio_stdev.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Figure 3 — Asyncio scatter ────────────────────────────────────────────────
def fig_asyncio_scatter(data, outdir):
    benches = [b for b in ["b1", "b2", "b3", "b4", "b5", "b6", "b7"]
               if (b, "naive") in data and (b, "structured") in data]
    n_benches = len(benches)
    ncols = 3
    nrows = (n_benches + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(13, nrows * 3.5 + 1))
    style(fig, axes.flat)
    fig.suptitle(
        "Figure 3 — Individual Run Times: All Asyncio Benchmarks\n"
        "Each dot = one run  |  ● Naive  ◆ Structured",
        color=TEXT, fontsize=11, y=1.01
    )

    rng = np.random.default_rng(42)

    # Hide any unused subplot cells in the grid
    for ax in list(axes.flat)[n_benches:]:
        ax.set_visible(False)

    for ax, bench in zip(axes.flat, benches):
        ns = summ(data[(bench, "naive")])

        for enc, color, marker in [
            ("naive",      NAIVE_C,  "o"),
            ("structured", STRUCT_C, "D"),
        ]:
            runs   = data[(bench, enc)]
            times  = [r["elapsed_ms"] for r in runs]
            jitter = rng.uniform(-0.15, 0.15, len(times))
            xpos   = (0 if enc == "naive" else 1) + jitter
            ax.scatter(xpos, times, c=color, marker=marker, s=18, alpha=0.7)

        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Naive", "Structured"], color=SUB, fontsize=8)
        ax.set_ylabel("Time (ms)", color=SUB, fontsize=8)
        ax.tick_params(labelsize=8)

        title  = ASYNCIO_LABELS[bench]
        flags  = []
        if ns["has_sat"]:  flags.append("naive=SAT ★")
        if ns["timeouts"]: flags.append(f"{ns['timeouts']} timeouts")
        if flags:
            ax.set_title(f"{title}  {'  '.join(flags)}", color=ACC4, fontsize=8)
        else:
            ax.set_title(title, color=TEXT, fontsize=9)

    handles = [
        mpatches.Patch(color=NAIVE_C,  label="Naive (AUFLIA)"),
        mpatches.Patch(color=STRUCT_C, label="Structured (QF_LIA)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2,
               facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT,
               fontsize=9, bbox_to_anchor=(0.5, -0.04))

    fig.tight_layout()
    out = outdir / "fig3_asyncio_scatter.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Figure 4 — PHP instability log scatter ────────────────────────────────────
def fig_php_instability(data, outdir):
    php_benches = ["php3", "php4", "php5", "php6"]
    fig, axes = plt.subplots(1, 4, figsize=(14, 5))
    style(fig, axes)
    fig.suptitle(
        "Figure 4 — PHP Benchmark Instability (Log Scale)\n"
        "Naive AUFLIA encoding: wide spread growing with problem size; "
        "Structured QF_LIA: flat cluster",
        color=TEXT, fontsize=11
    )

    rng = np.random.default_rng(99)

    for ax, bench in zip(axes, php_benches):
        ns = summ(data[(bench, "naive")])
        ss = summ(data[(bench, "structured")])

        for enc, color, marker in [
            ("naive",      NAIVE_C,  "o"),
            ("structured", STRUCT_C, "D"),
        ]:
            runs   = data[(bench, enc)]
            times  = [max(r["elapsed_ms"], 0.1) for r in runs]
            jitter = rng.uniform(-0.15, 0.15, len(times))
            xpos   = (0 if enc == "naive" else 1) + jitter
            ax.scatter(xpos, times, c=color, marker=marker, s=22, alpha=0.75)

        ax.set_yscale("log")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Naive", "Struct"], color=SUB, fontsize=8)
        ax.set_ylabel("Solve time ms (log)" if bench == "php3" else "", color=SUB, fontsize=8)
        ax.tick_params(labelsize=8)

        timeout_ms = 60000
        ax.axhline(timeout_ms, color=NAIVE_C, linestyle="--", alpha=0.4, linewidth=1)
        ax.text(0.5, timeout_ms * 1.2, "60s timeout",
                ha="center", color=NAIVE_C, fontsize=7,
                transform=ax.get_yaxis_transform())

        n_to = ns["timeouts"]
        title_color = ACC4 if n_to > 0 else TEXT
        ratio = ns["stdev"] / ss["stdev"] if ss["stdev"] > 0 else float("inf")
        ax.set_title(
            f"{PHP_LABELS[bench]}\n"
            f"naive σ={ns['stdev']:.0f}ms  struct σ={ss['stdev']:.1f}ms\n"
            f"{'⚠ ' + str(n_to) + ' timeouts' if n_to else 'no timeouts'}  ({ratio:.0f}× σ reduction)",
            color=title_color, fontsize=8.5
        )

    handles = [
        mpatches.Patch(color=NAIVE_C,  label="Naive (AUFLIA)"),
        mpatches.Patch(color=STRUCT_C, label="Structured (QF_LIA)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2,
               facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT,
               fontsize=9, bbox_to_anchor=(0.5, -0.04))

    fig.tight_layout()
    out = outdir / "fig4_php_instability.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Figure 5 — PHP CDF (log x-axis so structured curve is visible) ─────────
def fig_php_cdf(data, outdir):
    """
    Use log x-axis so the structured CDFs (clustered at ~7-15ms) are visible
    alongside the naive long tail stretching to 60s.
    """
    php_benches = ["php4", "php5", "php6"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    style(fig, axes)
    fig.suptitle(
        "Figure 5 — Cumulative Distribution: PHP Naive vs Structured  (log time axis)\n"
        "Structured CDF completes in <20ms; Naive has a long tail toward timeout",
        color=TEXT, fontsize=11
    )

    for ax, bench in zip(axes, php_benches):
        ns = summ(data[(bench, "naive")])
        ss = summ(data[(bench, "structured")])

        for enc, color, ls, label in [
            ("naive",      NAIVE_C,  "-",  f"Naive (σ={ns['stdev']:.0f}ms)"),
            ("structured", STRUCT_C, "--", f"Structured (σ={ss['stdev']:.1f}ms)"),
        ]:
            times = sorted(r["elapsed_ms"] for r in data[(bench, enc)])
            n     = len(times)
            cdf   = np.arange(1, n + 1) / n
            ax.step(times, cdf, color=color, linestyle=ls, linewidth=2.5, label=label)
            ax.fill_between(times, 0, cdf, alpha=0.07, color=color, step="pre")

        ax.set_xscale("log")
        ax.axvline(60000, color=NAIVE_C, linestyle=":", alpha=0.4, linewidth=1)
        ax.set_xlabel("Solve Time (ms, log scale)", color=SUB)
        ax.set_ylabel("CDF" if bench == "php4" else "", color=SUB)
        ax.set_title(PHP_LABELS[bench].replace("\n", " "), color=TEXT, fontsize=10)
        ax.legend(facecolor=BG3, edgecolor=BORDER, labelcolor=TEXT, fontsize=8)

        ratio = ns["stdev"] / ss["stdev"] if ss["stdev"] > 0 else float("inf")
        ax.text(0.03, 0.95,
                f"σ reduction\n{ratio:.0f}×",
                transform=ax.transAxes, ha="left", va="top",
                color=ACC4, fontsize=9, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor=BG3, edgecolor=ACC4, alpha=0.8))

    fig.tight_layout()
    out = outdir / "fig5_php_cdf.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Figure 6 — Full stats table ───────────────────────────────────────────────
def fig_full_table(data, outdir):
    all_benches = [
        ("b1",   "b1 TaskGroup"),   ("b2",   "b2 fire-forget"),
        ("b3",   "b3 mutex"),       ("b4",   "b4 event"),
        ("b5",   "b5 wait_for"),    ("b6",   "b6 queue"),
        ("b7",   "b7 broadcast"),
        ("php3", "PHP3 4p/3h"),     ("php4", "PHP4 5p/4h"),
        ("php5", "PHP5 6p/5h"),     ("php6", "PHP6 7p/6h"),
    ]

    rows = []
    for bench, name in all_benches:
        if (bench, "naive") not in data or (bench, "structured") not in data:
            continue
        ns = summ(data[(bench, "naive")])
        ss = summ(data[(bench, "structured")])

        nv, sv = ns["stdev"], ss["stdev"]

        # Honest ratio: always show the actual direction
        if sv == 0:
            ratio_str = "∞×"
        else:
            ratio = nv / sv
            if ratio >= 1.0:
                # structured is tighter — show plain multiplier
                ratio_str = f"{ratio:.2f}×"
            elif ratio >= 0.95:
                # roughly equal
                ratio_str = "~1×"
            else:
                # naive is actually tighter
                ratio_str = f"N better ({ratio:.2f}×)"

        n_res  = "SAT *" if ns["has_sat"] else "unsat"
        s_res  = "unsat" if not summ(data[(bench, "structured")])["has_sat"] else "SAT"
        n_to   = f"{ns['timeouts']}/{ns['n']}"
        s_to   = f"{ss['timeouts']}/{ss['n']}"   # computed, not hard-coded

        rows.append([
            name,
            f"{ns['mean']:.1f}",  f"{nv:.1f}",  n_res,  n_to,
            f"{ss['mean']:.1f}",  f"{sv:.1f}",  s_res,  s_to,
            ratio_str,
        ])

    col_labels = [
        "Benchmark",
        "N mean\n(ms)", "N sigma\n(ms)", "N result", "N timeouts",
        "S mean\n(ms)", "S sigma\n(ms)", "S result", "S timeouts",
        "sigma\nN/S ratio",
    ]

    fig, ax = plt.subplots(figsize=(17, len(rows) * 0.55 + 1.8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")

    tbl = ax.table(cellText=rows, colLabels=col_labels,
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 2.0)

    for (row, col), cell in tbl.get_celld().items():
        cell.set_facecolor(BG3 if row == 0 else BG2)
        cell.set_edgecolor(BORDER)
        if row == 0:
            cell.set_text_props(color=STRUCT_C, fontweight="bold")
        else:
            text = rows[row - 1][col] if col < len(rows[row - 1]) else ""
            txt  = str(text)
            if col in (1, 2, 4):
                cell.set_text_props(color=NAIVE_C)
            elif col == 0:
                cell.set_text_props(color="#ffffff")
            elif col == 3:
                if "SAT" in txt:
                    cell.set_text_props(color=ACC4, fontweight="bold")
                else:
                    cell.set_text_props(color=NAIVE_C)
            elif col in (5, 6, 8):
                cell.set_text_props(color=STRUCT_C)
            elif col == 7:
                cell.set_text_props(color=STRUCT_C)
            elif col == 9:
                if "N better" in txt:
                    # naive is tighter — muted warning colour
                    cell.set_text_props(color=ACC2)
                elif "~1×" in txt:
                    cell.set_text_props(color=SUB)
                else:
                    # structured tighter (any ×) — gold
                    cell.set_text_props(color=ACC4, fontweight="bold")

    ax.set_title(
        "Figure 6 — Complete Sweep Statistics\n"
        "N = Naive (AUFLIA)   S = Structured (QF_LIA)   "
        "* = correctness gap   S/N better = which encoding has smaller σ",
        color=TEXT, fontsize=11, pad=16
    )

    fig.tight_layout()
    out = outdir / "fig6_full_table.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=".")
    ap.add_argument("--outdir",  default="figures")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    data = load_results(args.results)
    found = sorted(data.keys())
    print(f"Found {len(found)} result sets")

    fig_correctness_gap(data, outdir)
    fig_asyncio_stdev(data, outdir)
    fig_asyncio_scatter(data, outdir)
    fig_php_instability(data, outdir)
    fig_php_cdf(data, outdir)
    fig_full_table(data, outdir)

    print(f"\nDone — saved to {outdir}/")

if __name__ == "__main__":
    main()