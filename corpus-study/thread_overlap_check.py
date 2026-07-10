#!/usr/bin/env python3
"""
thread_overlap_check.py — Quantify how much of the DESTRUCTIVE
("flagged", unmediated) bucket sits inside functions that also use
`run_in_executor` / `ThreadPoolExecutor` / `threading.Thread`.

Why this exists: SNF-3 (yield-point atomicity) guarantees no other
*coroutine* runs during cᵢ's step, but says nothing about a concurrently
running OS thread. A function that offloads work via
`loop.run_in_executor(...)` or spins up a `ThreadPoolExecutor` /
`threading.Thread` directly is exactly the case where the theorem's
guarantees don't actually apply, GIL or no GIL (see the free-threading
note in track1_snf_formal.md, Step 2). The paper flagged this as a real,
unquantified risk concentrated in `aiohttp`/`asyncpg` core paths but never
measured the overlap. This script measures it.

METHOD (heuristic, same evidentiary tier as scan.py's own detectors):
For every async function scan.py already analyzed (same (file, func)
granularity as results/<repo>.json — this reuses scan.py's own file
walk and async-function enumeration, not a fresh one, so the two are
directly joinable), check whether that function's body contains:
  - a call to `<expr>.run_in_executor(...)`  (attribute name match), or
  - a call to `ThreadPoolExecutor(...)` (Name or Attribute ctor), or
  - a call to `threading.Thread(...)` / a bare `Thread(...)` ctor.

Then, for every DESTRUCTIVE, unmediated interaction from refine.py's
bucketing (same logic, re-derived here from results/<repo>.json so this
script has no dependency on refine.py's file outputs), check whether its
(file, func) is in the thread-offloading set.

CAVEATS (stated once, not repeated per-repo):
  - Same-function only, no call-graph analysis — scan.py's own stated
    restriction (see its docstring, point 4). A destructive interaction
    in a helper function called BY a thread-offloading function is not
    counted as overlapping. This almost certainly UNDERCOUNTS the true
    overlap.
  - `func` is the bare function name (not class-qualified), matching
    scan.py's `Interaction.func` field exactly — two same-named methods
    on different classes in the same file collide, same limitation
    scan.py/refine.py already carry.
  - `.start()` on an arbitrary object is not treated as thread evidence
    (too many false positives from unrelated `.start()` methods); only
    constructor calls and `run_in_executor` are detected. This also
    undercounts.
  - Detecting `ThreadPoolExecutor`/`Thread` by bare name match will miss
    renamed imports (`from threading import Thread as T`) unless the
    alias itself is literally named `Thread`/`ThreadPoolExecutor`் this
    is the same class of heuristic gap scan.py's lock-keyword matching
    already has and already discloses.

Net effect of all three: this reports a LOWER BOUND on the overlap, not
an exact figure. That's the right direction to err in given what it's
being used for (showing the corpus percentages are "at least this
optimistic", not claiming they're "exactly this bad").

Usage:
    python thread_overlap_check.py
Reads:
    results/<repo>.json   (scan.py output)
    repo_src/<repo>/...   (source tree, same as branch_check.py needs)
Writes:
    thread_overlap/<repo>.json
    thread_overlap/_THREAD_OVERLAP_SUMMARY.json
"""
import ast
import json
from pathlib import Path
from collections import defaultdict

from scan import iter_python_files, REPO_ASYNC_SCOPE, REPO_ASYNC_EXCLUDE
from refine import WRITE_FORMS, classify_name_bucket

THREAD_CTOR_NAMES = {"ThreadPoolExecutor", "Thread"}


class ThreadUsageCollector(ast.NodeVisitor):
    """Walk one async function's body (not descending into nested defs,
    matching scan.py's own no-double-count discipline) and report whether
    it calls run_in_executor or constructs a ThreadPoolExecutor/Thread."""

    def __init__(self):
        self.found = False

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "run_in_executor":
            self.found = True
        elif isinstance(f, ast.Attribute) and f.attr in THREAD_CTOR_NAMES:
            self.found = True
        elif isinstance(f, ast.Name) and f.id in THREAD_CTOR_NAMES:
            self.found = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return  # don't descend into nested defs

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return


def collect_thread_functions_for_file(tree):
    """Returns a set of function names (bare, matching scan.py's
    Interaction.func) that use thread-offloading anywhere in their body,
    for every AsyncFunctionDef in the file (top-level, method, or nested
    -- mirrors scan.py's walk_scopes traversal)."""
    found = set()

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                collector = ThreadUsageCollector()
                for stmt in child.body:
                    collector.visit(stmt)
                if collector.found:
                    found.add(child.name)
                walk(child)
            elif isinstance(child, ast.FunctionDef):
                walk(child)
            elif isinstance(child, ast.Lambda):
                continue
            else:
                walk(child)

    walk(tree)
    return found


def collect_thread_functions_for_repo(repo_dir: Path, scope_prefixes=None, exclude_prefixes=None):
    thread_funcs = set()
    for f in iter_python_files(repo_dir, include_tests=False, scope_prefixes=scope_prefixes, exclude_prefixes=exclude_prefixes):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(f))
        except (SyntaxError, ValueError):
            continue
        thread_funcs |= collect_thread_functions_for_file(tree)
    return thread_funcs


def bucket_by_name_from_scan_json(data: dict) -> dict:
    writes_by_name = defaultdict(set)
    for i in data["interactions"]:
        if i["write_form"] in WRITE_FORMS:
            writes_by_name[(i["kind"], i["name"])].add(i["write_form"])
    return {k: classify_name_bucket(v) for k, v in writes_by_name.items()}


def main():
    root = Path(__file__).resolve().parent
    results_dir = root / "results"
    repo_src = root / "repo_src"
    out_dir = root / "thread_overlap"
    out_dir.mkdir(exist_ok=True)

    per_repo = {}
    agg_destructive_unmediated = 0
    agg_overlap = 0
    repos_with_thread_usage = 0

    for f in sorted(results_dir.glob("*.json")):
        if f.name == "_SUMMARY.json":
            continue
        data = json.load(open(f))
        repo = data["repo"]
        repo_dir = repo_src / repo
        if not repo_dir.is_dir():
            print(f"{repo:22s} SKIPPED — repo_src/{repo} not found")
            continue

        bucket_by_name = bucket_by_name_from_scan_json(data)
        scope = REPO_ASYNC_SCOPE.get(repo)
        exclude = REPO_ASYNC_EXCLUDE.get(repo)
        thread_funcs = collect_thread_functions_for_repo(repo_dir, scope_prefixes=scope, exclude_prefixes=exclude)

        destructive_unmediated = 0
        overlap = 0
        overlap_examples = []
        for i in data["interactions"]:
            key = (i["kind"], i["name"])
            if bucket_by_name.get(key) != "DESTRUCTIVE" or i["mediated"]:
                continue
            destructive_unmediated += 1
            if i["func"] in thread_funcs:
                overlap += 1
                if len(overlap_examples) < 5:
                    overlap_examples.append(i)

        pct = round(100 * overlap / destructive_unmediated, 2) if destructive_unmediated else None
        repo_result = {
            "repo": repo,
            "thread_offloading_functions": sorted(thread_funcs),
            "destructive_unmediated_interactions": destructive_unmediated,
            "overlap_interactions": overlap,
            "pct_destructive_unmediated_in_thread_functions": pct,
            "overlap_examples": overlap_examples,
        }
        per_repo[repo] = repo_result
        with open(out_dir / f"{repo}.json", "w") as out:
            json.dump(repo_result, out, indent=2)

        agg_destructive_unmediated += destructive_unmediated
        agg_overlap += overlap
        if thread_funcs:
            repos_with_thread_usage += 1

        print(f"{repo:22s} thread_functions={len(thread_funcs):3d}  "
              f"destructive_unmediated={destructive_unmediated:5d}  "
              f"overlap={overlap:5d}  pct={pct}")

    overall = {
        "destructive_unmediated_total": agg_destructive_unmediated,
        "overlap_total": agg_overlap,
        "pct_destructive_unmediated_in_thread_functions": round(
            100 * agg_overlap / agg_destructive_unmediated, 2
        ) if agg_destructive_unmediated else None,
        "repos_with_thread_usage": repos_with_thread_usage,
        "note": "Lower bound: same-function only, no call-graph analysis, "
                "constructor/run_in_executor detection only (no .start()-based "
                "detection). True overlap is >= this figure.",
    }
    with open(out_dir / "_THREAD_OVERLAP_SUMMARY.json", "w") as out:
        json.dump({"per_repo": per_repo, "overall": overall}, out, indent=2)

    print("\n=== OVERALL (lower bound on run_in_executor/threading overlap) ===")
    print(json.dumps(overall, indent=2))
    print("\nThis is the number that answers: 'how optimistic are the corpus")
    print("percentages for repos that also do thread offloading?' It is a")
    print("lower bound, not an exact figure -- see the note field and the")
    print("CAVEATS section in this file's docstring.")


if __name__ == "__main__":
    main()