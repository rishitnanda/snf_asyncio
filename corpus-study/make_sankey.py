"""
Generate the corpus-triage Sankey diagram from _REFINED_SUMMARY.json.

Usage:
    pip install plotly kaleido --break-system-packages
    python make_sankey.py _REFINED_SUMMARY.json corpus_sankey.png

Produces a two-node-column Sankey:
    Total corpus interactions -> {Mediated, Read-only, Commutative, Destructive}
colored by proof status (proved / partial / open).
"""

import json
import sys
import os
import plotly.graph_objects as go

# Proof-status color coding
COLOR_PROVED = "rgba(29, 158, 117, 0.75)"      # teal  -- mediated, read-only
COLOR_PARTIAL = "rgba(186, 117, 23, 0.75)"     # amber -- commutative
COLOR_OPEN = "rgba(216, 90, 48, 0.75)"         # coral -- destructive
COLOR_ROOT = "rgba(136, 135, 128, 0.9)"        # gray  -- root node


def load_overall(json_path):
    with open(json_path) as f:
        data = json.load(f)
    o = data["overall"]
    total = o["total_interactions"]
    mediated = total - o["unmediated_by_bucket"]["READ_ONLY"] \
                     - o["unmediated_by_bucket"]["COMMUTATIVE"] \
                     - o["unmediated_by_bucket"]["DESTRUCTIVE"]
    read_only = o["unmediated_by_bucket"]["READ_ONLY"]
    commutative = o["unmediated_by_bucket"]["COMMUTATIVE"]
    destructive = o["unmediated_by_bucket"]["DESTRUCTIVE"]
    
    assert mediated + read_only + commutative + destructive == total, (
        "bucket counts do not sum to total_interactions -- check the JSON"
    )
    return total, mediated, read_only, commutative, destructive


def build_sankey(total, mediated, read_only, commutative, destructive, out_path):
    def pct(n):
        return f"{n / total * 100:.2f}%"

    labels = [
        "Total corpus interactions",
        f"Mediated -- {pct(mediated)}",
        f"Read-only (SNF-5) -- {pct(read_only)}",
        f"Commutative writes -- {pct(commutative)}",
        f"Destructive writes -- {pct(destructive)}",
    ]
    node_colors = [COLOR_ROOT, COLOR_PROVED, COLOR_PROVED, COLOR_PARTIAL, COLOR_OPEN]

    # single source (index 0) fanning out to four targets (indices 1-4)
    source = [0, 0, 0, 0]
    target = [1, 2, 3, 4]
    value = [mediated, read_only, commutative, destructive]
    link_colors = [COLOR_PROVED, COLOR_PROVED, COLOR_PARTIAL, COLOR_OPEN]

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                    pad=24,
                    thickness=18,
                    line=dict(color="rgba(0,0,0,0)", width=0),
                    label=labels,
                    color=node_colors,
                ),
                link=dict(
                    source=source,
                    target=target,
                    value=value,
                    color=link_colors,
                ),
            )
        ]
    )

    fig.update_layout(
        title_text=(
            f"Asyncio corpus triage: {total:,} shared-variable interactions "
            "across 33 repositories"
        ),
        font=dict(size=13, family="Arial, sans-serif"),
        width=900,
        height=480,
        margin=dict(l=20, r=160, t=60, b=20),
    )

    # Force absolute path in the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    final_path = os.path.join(script_dir, os.path.basename(out_path))

    # Ensure .png extension
    if not final_path.lower().endswith(".png"):
        final_path = os.path.splitext(final_path)[0] + ".png"

    # Export to PNG
    try:
        fig.write_image(final_path, format="png")
        print(f"Successfully wrote PNG to: {final_path}")
    except Exception as e:
        print(f"Static export failed: {e}. Ensure 'kaleido' is installed.")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "corpus-study/refined/_REFINED_SUMMARY.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "corpus_sankey.png"
    
    total, mediated, read_only, commutative, destructive = load_overall(json_path)
    build_sankey(total, mediated, read_only, commutative, destructive, out_path)