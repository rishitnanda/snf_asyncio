#!/usr/bin/env python3
"""
corpus_pie.py — Full-corpus breakdown: complete vs. sound-but-incomplete
vs. unverified-applicability vs. open.

Reads the summary JSONs already produced by the pipeline:
    _SUMMARY.json           (scan.py: mediated / unmediated totals)
    _REFINED_SUMMARY.json   (refine.py: read-only / commutative / destructive)
    _BRANCH_SUMMARY.json    (branch_check.py: flagged-data / flagged-control
                             split of the destructive bucket, PLUS the
                             Definition 15 bounded- vs. unbounded-loop-gated
                             split within flagged-control)

and draws one pie chart of all 20,991 corpus interactions, split into the
six categories that correspond to what's actually proved vs. still open
in the paper. These six categories fall into FOUR distinct rigor tiers,
not two -- collapsing them into a single "solved" bucket (as an earlier
version of this script did) overstates the commutative slice's status
and understates the mediated/read-only slice's:

  TIER 1 -- COMPLETE (not just sound):
    Mediated                        -- controlled interference (Section 3)
    Unmediated, read-only           -- SNF-5 (Proposition 1a)
    Both are proved complete with respect to feasible traces (Prop. 4),
    not merely sound -- the main theorem's actual guarantee, stronger
    than anything else on this chart.

  TIER 2 -- SOUND, NOT COMPLETE (may false-alarm on safe code):
    Unmediated, destructive, flagged-data       -- Prop. 12
    Unmediated, destructive, flagged-control,
      bounded-path                              -- Prop. 13/13a/13b
    Both guarantee no missed bug, but a verifier built on either can
    report a false alarm on code that is in fact safe, since havoc
    injection admits models with no corresponding real execution. The
    bounded-path slice's SIZE is additionally a syntactic-proxy upper
    bound, not a verified count against Definition 15.

  TIER 3 -- UNVERIFIED APPLICABILITY (proof exists, corpus overlap unchecked):
    Unmediated, commutative         -- Prop. 10 proves a SUFFICIENT
    condition for trace-equivalence (disjoint-key writes, no aggregate
    read before completion), not a full characterization. This corpus
    bucket was identified by a syntactic proxy during scanning and has
    NEVER been re-checked against Prop. 10's precise condition -- so
    unlike Tier 2, this slice's proof isn't even known to apply to the
    interactions it's drawn around, let alone complete them.

  TIER 4 -- OPEN (no result at all):
    Unmediated, destructive, flagged-control,
      unbounded-loop-gated            -- no soundness result, no technique

Usage:
    python corpus_pie.py [--results-dir results] [--refined-dir refined]
                          [--branch-dir branch_check] [--out OUT.png]
Defaults are resolved relative to this script's own location, not the
current working directory -- so `python3 corpus-study/corpus_pie.py` works
from anywhere, as long as results/, refined/, and branch_check/ are
siblings of corpus_pie.py itself:
    <script_dir>/results/_SUMMARY.json
    <script_dir>/refined/_REFINED_SUMMARY.json
    <script_dir>/branch_check/_BRANCH_SUMMARY.json
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load(path: Path, name: str) -> dict:
    if not path.exists():
        raise SystemExit(
            f"Missing {name} at {path}. Run scan.py -> refine.py -> "
            f"branch_check.py first, or pass --results-dir/--refined-dir/"
            f"--branch-dir to point at the folders that have each _*.json file."
        )
    return json.loads(path.read_text())


def build_breakdown(summary: dict, refined: dict, branch: dict) -> dict:
    total = summary["overall"]["total_interactions"]
    mediated_total = summary["overall"]["mediated"]

    ro = refined["overall"]
    unmediated_readonly = ro["counts_by_bucket"]["READ_ONLY"] - ro["mediated_by_bucket"]["READ_ONLY"]
    unmediated_commutative = ro["counts_by_bucket"]["COMMUTATIVE"] - ro["mediated_by_bucket"]["COMMUTATIVE"]
    unmediated_destructive = ro["counts_by_bucket"]["DESTRUCTIVE"] - ro["mediated_by_bucket"]["DESTRUCTIVE"]

    b = branch["overall"]
    # branch_check's splits (flagged-data vs. flagged-control, and within
    # flagged-control, bounded-path vs. unbounded-loop-gated) were computed
    # over ALL destructive interactions (mediated + unmediated), since a
    # name's guard status doesn't depend on mediation. Apply those same
    # ratios to the UNMEDIATED-destructive count specifically, since
    # mediated-destructive is already solved via controlled interference
    # and doesn't need Prop 12/13 at all.
    flagged_control_total = b["flagged_control_bounded_interactions"] + b["flagged_control_unbounded_interactions"]
    flagged_total = b["flagged_data_interactions"] + flagged_control_total

    flagged_ratio_data = b["flagged_data_interactions"] / flagged_total
    flagged_ratio_control_bounded = b["flagged_control_bounded_interactions"] / flagged_total
    flagged_ratio_control_unbounded = b["flagged_control_unbounded_interactions"] / flagged_total

    flagged_data = round(unmediated_destructive * flagged_ratio_data)
    flagged_control_bounded = round(unmediated_destructive * flagged_ratio_control_bounded)
    # Remainder absorbs rounding so the three sub-slices sum exactly to
    # unmediated_destructive (matches the assert below).
    flagged_control_unbounded = unmediated_destructive - flagged_data - flagged_control_bounded

    breakdown = {
        "Mediated\n(controlled interference)": mediated_total,
        "Unmediated, read-only\n(SNF-5)": unmediated_readonly,
        "Unmediated, commutative\n(checker-cleared, Prop. 10\nunverified vs. this bucket)": unmediated_commutative,
        "Unmediated, destructive,\nflagged-data (Prop. 12)": flagged_data,
        "Unmediated, destructive,\nflagged-control,\nbounded-path (Prop. 13)": flagged_control_bounded,
        "Unmediated, destructive,\nflagged-control,\nunbounded-loop (OPEN)": flagged_control_unbounded,
    }
    assert sum(breakdown.values()) == total, (
        f"breakdown sums to {sum(breakdown.values())}, expected {total} -- "
        f"check that all three JSONs came from the same corpus run"
    )
    return breakdown, total


def main():
    ap = argparse.ArgumentParser()
    script_dir = Path(__file__).resolve().parent
    ap.add_argument("--results-dir", default=str(script_dir / "results"), help="folder with _SUMMARY.json (scan.py output)")
    ap.add_argument("--refined-dir", default=str(script_dir / "refined"), help="folder with _REFINED_SUMMARY.json (refine.py output)")
    ap.add_argument("--branch-dir", default=str(script_dir / "branch_check"), help="folder with _BRANCH_SUMMARY.json (branch_check.py output)")
    ap.add_argument("--out", default=str(script_dir / "corpus_breakdown_pie.png"))
    args = ap.parse_args()

    summary = load(Path(args.results_dir) / "_SUMMARY.json", "_SUMMARY.json")
    refined = load(Path(args.refined_dir) / "_REFINED_SUMMARY.json", "_REFINED_SUMMARY.json")
    branch = load(Path(args.branch_dir) / "_BRANCH_SUMMARY.json", "_BRANCH_SUMMARY.json")

    breakdown, total = build_breakdown(summary, refined, branch)
    labels = list(breakdown.keys())
    values = list(breakdown.values())

    # index: 0=mediated, 1=read-only, 2=commutative, 3=flagged-data,
    #        4=bounded-flagged-control, 5=unbounded-flagged-control
    #
    # FOUR rigor tiers, FOUR distinct color families -- not two:
    #   Tier 1 (complete):            0, 1  -- blues (strongest guarantee)
    #   Tier 2 (sound, not complete): 3, 4  -- greens (real proof, may false-alarm)
    #   Tier 3 (unverified applicability): 2 -- purple/lavender (proof exists,
    #                                            never checked against this bucket --
    #                                            visually distinct from both "solved"
    #                                            tiers so it can't be misread as one)
    #   Tier 4 (open):                 5    -- warm red, pulled out
    colors = ["#3B6FA0", "#5B8FC0", "#9B7FBF", "#5FB89C", "#8FCB9A", "#D65F4C"]
    explode = [0, 0, 0.03, 0, 0.03, 0.08]

    fig, ax = plt.subplots(figsize=(9.5, 8))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        colors=colors,
        explode=explode,
        autopct=lambda pct: f"{pct:.2f}%",
        pctdistance=0.75,
        startangle=90,
        textprops={"fontsize": 9},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontweight("bold")

    # Four-tier summary line, replacing the earlier two-tier "solved vs.
    # open" framing. That framing put the commutative slice (Tier 3: a
    # sufficient condition is proved, but never checked against this
    # specific corpus bucket) in the same "solved" category as the
    # mediated/read-only slice (Tier 1: proved COMPLETE, not just sound) --
    # overstating Tier 3's status and understating Tier 1's in the same
    # breath. Reporting all four tiers separately avoids both errors.
    complete_total = values[0] + values[1]
    sound_incomplete_total = values[3] + values[4]
    unverified_total = values[2]
    open_total = values[5]
    ax.set_title(
        f"Asyncio corpus, {total:,} shared-variable interactions across 33 repos\n"
        f"Complete: {complete_total:,} ({100 * complete_total / total:.2f}%)   |   "
        f"Sound, not complete: {sound_incomplete_total:,} ({100 * sound_incomplete_total / total:.2f}%)   |   "
        f"Unverified applicability: {unverified_total:,} ({100 * unverified_total / total:.2f}%)   |   "
        f"Open: {open_total:,} ({100 * open_total / total:.2f}%)\n"
        f"\"Sound, not complete\" may false-alarm on safe code; bounded-path/unbounded-loop split "
        f"is a syntactic proxy, not verified against Def. 15 directly; \"unverified applicability\" "
        f"means Prop. 10's sufficient condition was never re-checked against this specific bucket",
        fontsize=10.5,
        pad=30,
    )
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(args.out, dpi=200, bbox_inches="tight")
    print(f"Saved {args.out}")
    print(json.dumps({k.replace(chr(10), ' '): v for k, v in breakdown.items()}, indent=2))
    print(json.dumps({
        "complete": complete_total,
        "sound_not_complete": sound_incomplete_total,
        "unverified_applicability": unverified_total,
        "open": open_total,
        "total": total,
    }, indent=2))


if __name__ == "__main__":
    main()