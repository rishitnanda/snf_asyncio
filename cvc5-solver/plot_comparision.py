"""
plot_table.py
==================
Generates a single figure: cross-solver comparison table (Z3 vs CVC5).

Shows for every benchmark:
  - Z3 structured:   result, mean, sigma
  - CVC5 structured: result, mean, sigma

Supports the "solver-independent stability" claim:
  structured QF_LIA is stable and correct in both solvers.

Usage:
  python3 plot_table.py \
      --z3_results   results/       \
      --cvc5_results results/  \
      --outdir       figures/
"""

import argparse
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Style ────────────────────────────────────────────────────────────────────
BG      = "#0f1117"
BG2     = "#1a1d2e"
BG3     = "#242740"
BORDER  = "#2e3152"
TEXT    = "#e8eaf6"
SUB     = "#8b8fa8"
NAIVE_C = "#ff6b6b"
STRUCT_C= "#4ecdc4"
ACC4    = "#ffe66d"
Z3_C    = "#7c6aff"
CVC5_C  = "#ff9f43"


# ── Data loader ──────────────────────────────────────────────────────────────

def load_dir(results_dir: str) -> dict:
    """Load all results_*.json from a directory. Returns {label: [runs]}."""
    data = {}
    for f in Path(results_dir).glob("results_*.json"):
        if "test" in f.stem:
            continue
        label = f.stem.replace("results_", "")
        data[label] = json.loads(f.read_text())
    return data


def summ(runs: list) -> dict:
    times   = [r["elapsed_ms"] for r in runs]
    results = [r["result"]     for r in runs]
    tos     = sum(r["timed_out"] for r in runs)
    res_set = set(results)
    all_unknown = res_set == {"unknown"}
    has_sat     = any(r == "sat" for r in results)
    return dict(
        mean    = statistics.mean(times),
        stdev   = statistics.stdev(times) if len(times) > 1 else 0.0,
        n       = len(times),
        timeouts= tos,
        res_set = res_set,
        all_unknown = all_unknown,
        has_sat     = has_sat,
        result_str  = ("unknown" if all_unknown
                       else "SAT *" if has_sat
                       else "unsat"),
    )


# ── Table builder ─────────────────────────────────────────────────────────────

def build_rows(z3: dict, cvc5: dict) -> tuple[list, list, list]:
    """
    Returns (rows, col_labels, row_colors) for the matplotlib table.
    Benchmarks: b1-b6 asyncio + php3-php6.
    """
    bench_defs = [
        ("b1",   "b1 TaskGroup"),
        ("b2",   "b2 fire-forget"),
        ("b3",   "b3 mutex"),
        ("b4",   "b4 event"),
        ("b5",   "b5 wait_for"),
        ("b6",   "b6 queue"),
        ("b7",   "b7 broadcast"),
        ("php3", "PHP3 4p/3h"),
        ("php4", "PHP4 5p/4h"),
        ("php5", "PHP5 6p/5h"),
        ("php6", "PHP6 7p/6h"),
    ]

    col_labels = [
        "Benchmark",
        # Z3 structured
        "Z3-S\nresult", "Z3-S\nmean(ms)", "Z3-S\nσ(ms)",
        # CVC5 structured
        "CVC5-S\nresult", "CVC5-S\nmean(ms)", "CVC5-S\nσ(ms)",
    ]

    rows = []
    row_colors = []  # per-row colouring hints (unused beyond length check, kept for extension)

    for bench, name in bench_defs:
        z3s_key = f"{bench}_structured"
        c5s_key = f"{bench}_structured"

        if z3s_key not in z3 or c5s_key not in cvc5:
            continue

        z3s = summ(z3[z3s_key])
        c5s = summ(cvc5[c5s_key])

        row = [
            name,
            # Z3 structured
            z3s["result_str"],
            f"{z3s['mean']:.1f}",
            f"{z3s['stdev']:.1f}",
            # CVC5 structured
            c5s["result_str"],
            f"{c5s['mean']:.1f}",
            f"{c5s['stdev']:.1f}",
        ]
        rows.append(row)
        row_colors.append({})  # placeholder; extend here for per-row metadata

    return rows, col_labels, row_colors


# ── Figure ────────────────────────────────────────────────────────────────────

def fig_table(z3: dict, cvc5: dict, outdir: Path):
    rows, col_labels, row_colors = build_rows(z3, cvc5)

    n_rows = len(rows)
    fig_h  = max(5.0, n_rows * 0.62 + 2.0)
    fig, ax = plt.subplots(figsize=(18, fig_h))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")

    tbl = ax.table(
        cellText  = rows,
        colLabels = col_labels,
        loc       = "center",
        cellLoc   = "center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 2.1)

    # Column index groupings (7 columns total: 0=bench, 1-3=Z3-S, 4-6=CVC5-S)
    Z3S_COLS  = (1, 2, 3)
    C5S_COLS  = (4, 5, 6)

    for (row_idx, col_idx), cell in tbl.get_celld().items():
        cell.set_facecolor(BG3 if row_idx == 0 else BG2)
        cell.set_edgecolor(BORDER)

        if row_idx == 0:
            # Header row — colour by solver group
            if col_idx == 0:
                cell.set_text_props(color=TEXT, fontweight="bold")
            elif col_idx in Z3S_COLS:
                cell.set_facecolor("#1a2a2e")
                cell.set_text_props(color=STRUCT_C, fontweight="bold")
            elif col_idx in C5S_COLS:
                cell.set_facecolor("#182a20")
                cell.set_text_props(color=ACC4, fontweight="bold")

        else:
            data_row = row_idx - 1
            if data_row >= len(rows):
                continue

            if col_idx == 0:
                cell.set_text_props(color=TEXT)
            elif col_idx in Z3S_COLS:
                cell.set_facecolor("#151e20")
                cell.set_text_props(color=STRUCT_C)
            elif col_idx in C5S_COLS:
                cell.set_facecolor("#15201a")
                cell.set_text_props(color=ACC4)

    # Group header bands — aligned to the two actual column groups
    ax.text(0.43, 0.985, "Z3 — Structured (QF_LIA)",
            transform=ax.transAxes, ha="center", va="bottom",
            color=STRUCT_C, fontsize=9, fontweight="bold")
    ax.text(0.78, 0.985, "CVC5 — Structured (QF_LIA)",
            transform=ax.transAxes, ha="center", va="bottom",
            color=ACC4, fontsize=9, fontweight="bold")

    ax.set_title(
        "Figure 7 — Cross-Solver Comparison: Z3 vs CVC5\n"
        "Structured QF_LIA encodings are correct and stable in both solvers  |  "
        "* = correctness gap  |  grey = solver gave up (unknown)",
        color=TEXT, fontsize=11, pad=28
    )

    fig.tight_layout()
    out = outdir / "fig7_comparison_table.png"
    fig.savefig(out, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Generate CVC5 vs Z3 cross-solver comparison table"
    )
    ap.add_argument("--z3_results",   default="z3-solver/results",
                    help="Directory with Z3 results_*.json files")
    ap.add_argument("--cvc5_results", default="cvc5-solver/results",
                    help="Directory with CVC5 results_*.json files")
    ap.add_argument("--outdir",       default="cvc5-solver/figures",
                    help="Output directory for PNG")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Loading Z3 results from:   {args.z3_results}")
    z3   = load_dir(args.z3_results)
    print(f"Loading CVC5 results from: {args.cvc5_results}")
    cvc5 = load_dir(args.cvc5_results)

    print(f"\nZ3 keys:   {sorted(z3.keys())}")
    print(f"CVC5 keys: {sorted(cvc5.keys())}")

    print("\nGenerating figure...")
    fig_table(z3, cvc5, outdir)
    print("Done.")


if __name__ == "__main__":
    main()