#!/usr/bin/env python3
"""
branch_check.py — Definition 13 classifier: split refine.py's DESTRUCTIVE
("flagged") names into flagged-control vs. flagged-data.

Definition 13 (Control-flow independence), track1_snf_formal.md addendum:
a flagged variable v is control-flow-independent ("flagged-data") in
coroutine c_i if no branch condition in c_i reads v. Otherwise it's
"flagged-control", and Proposition 12's havoc-injection soundness proof
does not apply to it.

This script does NOT re-derive mediation or write-form (that's scan.py's
and refine.py's job, already done and sitting in results/*.json). It only
answers one new question per (kind, name): does this name ever appear
inside a branch-guard TEST anywhere in the repo's scanned async code?

"Branch-guard test" = the `test` of an `If`/`While`, the `test` of a
ternary `IfExp`, an operand of a `BoolOp` (and/or short-circuit), or an
`if` clause of a comprehension. A name counts as guard-reading if it's
read (Name/Load, or self.attr/cls.attr access) anywhere inside one of
these test expressions, in any async function in the same scanned scope
refine.py already used.

Caveat, inherited from scan.py's own stated scope: this is per-repo,
name-string bucketing, not per-class/per-variable dataflow, matching
refine.py's existing (kind, name) granularity exactly so the two are
directly joinable. A name guard-reading ANYWHERE in the repo is enough to
mark it flagged-control everywhere, even if the specific write/read pair
that made it DESTRUCTIVE never interacts with the specific guard found.
This is deliberately conservative in the direction Prop 12 needs: it can
only over-flag as flagged-control (safe — falls back to "still open"), never
under-flag a genuinely control-flow-dependent variable as flagged-data
(which would be the unsound direction for claiming Prop 12 applies).

Usage:
    python branch_check.py
Reads:
    results/<repo>.json        (scan.py output — needed for write_form/kind/name)
    repo_src/<repo>/...        (source tree — needed to re-walk for guard context)
Writes:
    branch_check/<repo>.json
    branch_check/_BRANCH_SUMMARY.json
"""
import ast
import json
from pathlib import Path
from collections import defaultdict

from scan import (
    ModuleScope,
    collect_local_binds,
    BUILTINS,
    iter_python_files,
    REPO_ASYNC_SCOPE,
)
from refine import COMMUTATIVE_FORMS, DESTRUCTIVE_FORMS, WRITE_FORMS, classify_name_bucket


class GuardNameCollector(ast.NodeVisitor):
    """Walk one async function body. Tracks a guard-depth counter that is
    nonzero exactly while visiting the TEST subtree of an If/While/IfExp,
    a BoolOp, or a comprehension's `if` clauses. Any self/cls-attr or
    resolvable Name read while guard-depth > 0 is recorded as
    control-flow-relevant for that (kind, name).

    Definition 15 (Bounded-Path Assumption) split: guard reads are further
    bucketed into `while_guard_names` (read in the TEST of a `While` node
    — an unbounded-iteration guard, which Definition 15 excludes) versus
    `bounded_guard_names` (read only in If/IfExp/BoolOp/comprehension
    tests — candidates for Proposition 13's finite-path construction).
    A name that appears in a While test anywhere is always treated as
    while-guarded even if it also appears in a bounded test elsewhere,
    matching this script's existing conservative-in-the-safe-direction
    policy: over-flag as the harder (still-open) case, never under-flag."""

    def __init__(self, module_scope: ModuleScope, locals_: set, enclosing_locals_stack):
        self.module_scope = module_scope
        self.locals = locals_
        self.enclosing_locals_stack = enclosing_locals_stack
        self.guard_depth = 0
        self.while_depth = 0
        self.guard_names = set()  # {(kind, name)}  -- any guard, kept for backward compat
        self.while_guard_names = set()   # {(kind, name)}  -- read in a While test
        self.bounded_guard_names = set()  # {(kind, name)} -- read only in If/IfExp/BoolOp/comprehension tests

    # -- name resolution, mirrors scan.py's FunctionAnalyzer._classify_name --
    def _classify_name(self, name):
        if name in self.locals:
            return None
        if name in BUILTINS or name in ("self", "cls", "True", "False", "None"):
            return None
        if name in self.module_scope.import_names:
            return None
        for outer_locals in reversed(self.enclosing_locals_stack):
            if name in outer_locals:
                return "CLOSURE"
        if name in self.module_scope.names:
            return "GLOBAL"
        return None

    def _record_if_guarded(self, kind, name):
        if self.guard_depth > 0:
            self.guard_names.add((kind, name))
            if self.while_depth > 0:
                self.while_guard_names.add((kind, name))
            else:
                self.bounded_guard_names.add((kind, name))

    # -- expression visitors --
    def visit_Attribute(self, node):
        base = node.value
        if isinstance(base, ast.Name) and base.id in ("self", "cls"):
            self._record_if_guarded("SELF_ATTR", f"self.{node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node):
        cls = self._classify_name(node.id)
        if cls:
            self._record_if_guarded(cls, node.id)
        self.generic_visit(node)

    # -- guard-context trackers --
    def _visit_guarded(self, test_nodes, rest_visit, is_while=False):
        for t in test_nodes:
            self.guard_depth += 1
            if is_while:
                self.while_depth += 1
            self.visit(t)
            if is_while:
                self.while_depth -= 1
            self.guard_depth -= 1
        rest_visit()

    def visit_If(self, node):
        self._visit_guarded([node.test], lambda: self._walk_list(node.body + node.orelse))

    def visit_While(self, node):
        self._visit_guarded([node.test], lambda: self._walk_list(node.body + node.orelse), is_while=True)

    def visit_IfExp(self, node):
        self._visit_guarded([node.test], lambda: (self.visit(node.body), self.visit(node.orelse)))

    def visit_BoolOp(self, node):
        # and/or short-circuit: every operand is a condition in the sense
        # that matters here (whether it's *evaluated* can depend on a prior
        # operand's value, and the overall expression's truth value gates
        # whatever consumes it). Inherits the enclosing while_depth, so a
        # BoolOp inside a While's test is correctly counted as while-guarded.
        self._visit_guarded(node.values, lambda: None, is_while=(self.while_depth > 0))

    def visit_comprehension(self, node):
        self.visit(node.iter)
        self._visit_guarded(node.ifs, lambda: None)

    def _walk_list(self, stmts):
        for s in stmts:
            self.visit(s)

    # Don't descend into nested function/lambda bodies here; walk_scopes-
    # style top-level driver (below) visits every AsyncFunctionDef
    # independently, matching scan.py's own no-double-count discipline.
    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return


def collect_guard_names_for_file(tree, mod_scope, relpath):
    """Mirrors scan.py's walk_scopes: visit every AsyncFunctionDef anywhere
    in the file (top-level, method, nested) with the correct enclosing-
    locals stack, and union their guard_names. Returns a
    (guard_names, while_guard_names, bounded_guard_names) triple."""
    found = set()
    found_while = set()
    found_bounded = set()

    def walk(node, enclosing_locals_stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                locals_ = collect_local_binds(child)
                collector = GuardNameCollector(mod_scope, locals_, list(enclosing_locals_stack))
                for stmt in child.body:
                    collector.visit(stmt)
                found.update(collector.guard_names)
                found_while.update(collector.while_guard_names)
                found_bounded.update(collector.bounded_guard_names)
                walk(child, enclosing_locals_stack + [locals_])
            elif isinstance(child, ast.FunctionDef):
                locals_ = collect_local_binds(child)
                walk(child, enclosing_locals_stack + [locals_])
            elif isinstance(child, ast.Lambda):
                continue
            else:
                walk(child, enclosing_locals_stack)

    walk(tree, [])
    return found, found_while, found_bounded


def collect_guard_names_for_repo(repo_dir: Path, scope_prefixes=None):
    guard_names = set()
    while_guard_names = set()
    bounded_guard_names = set()
    for f in iter_python_files(repo_dir, include_tests=False, scope_prefixes=scope_prefixes):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(f))
        except (SyntaxError, ValueError):
            continue
        mod_scope = ModuleScope(tree)
        relpath = str(f.relative_to(repo_dir))
        g, gw, gb = collect_guard_names_for_file(tree, mod_scope, relpath)
        guard_names |= g
        while_guard_names |= gw
        bounded_guard_names |= gb
    # Conservative priority (Definition 15): a name that EVER appears in a
    # While test anywhere is while-guarded, even if it also appears in a
    # bounded test elsewhere — over-flag as the harder, still-open case.
    bounded_guard_names -= while_guard_names
    return guard_names, while_guard_names, bounded_guard_names


def bucket_by_name_from_scan_json(data: dict) -> dict:
    """Same logic as refine.classify_name_bucket, but returns the
    per-(kind,name) bucket dict directly instead of aggregate counts."""
    writes_by_name = defaultdict(set)
    for i in data["interactions"]:
        if i["write_form"] in WRITE_FORMS:
            writes_by_name[(i["kind"], i["name"])].add(i["write_form"])
    return {k: classify_name_bucket(v) for k, v in writes_by_name.items()}


def main():
    root = Path(__file__).parent
    results_dir = root / "results"
    repo_src = root / "repo_src"
    out_dir = root / "branch_check"
    out_dir.mkdir(exist_ok=True)

    per_repo = {}
    agg = {"flagged_control_bounded": 0, "flagged_control_unbounded": 0, "flagged_data": 0}
    agg_names = {"flagged_control_bounded": 0, "flagged_control_unbounded": 0, "flagged_data": 0}

    for f in sorted(results_dir.glob("*.json")):
        if f.name == "_SUMMARY.json":
            continue
        data = json.load(open(f))
        repo = data["repo"]
        repo_dir = repo_src / repo
        if not repo_dir.is_dir():
            print(f"{repo:22s} SKIPPED — repo_src/{repo} not found (need cloned source, not just results JSON)")
            continue

        bucket_by_name = bucket_by_name_from_scan_json(data)
        destructive_names = {k for k, v in bucket_by_name.items() if v == "DESTRUCTIVE"}
        if not destructive_names:
            continue

        scope = REPO_ASYNC_SCOPE.get(repo)
        guard_names, while_guard_names, bounded_guard_names = collect_guard_names_for_repo(
            repo_dir, scope_prefixes=scope
        )

        flagged_control_names = destructive_names & guard_names
        flagged_data_names = destructive_names - guard_names

        # Definition 15 split of flagged-control: while_guard_names always
        # wins (conservative — over-flag as the still-open unbounded case)
        # even if a name also appears in a bounded test elsewhere.
        flagged_control_unbounded_names = flagged_control_names & while_guard_names
        flagged_control_bounded_names = flagged_control_names - flagged_control_unbounded_names

        # Interaction-level counts: every DESTRUCTIVE interaction inherits
        # its name's split, same inheritance rule refine.py uses for buckets.
        # Only UNMEDIATED interactions count here -- an already-mediated
        # destructive interaction is already safe via Proposition 1a and
        # does not belong in the "needs Prop 12/13 havoc-injection
        # treatment" denominator. refine.py itself makes this distinction
        # explicitly (mediated_counts vs unmediated_counts); this filter
        # brings branch_check.py's own counting in line with it -- without
        # it, this script's own denominator (all destructive interactions,
        # mediated or not) silently diverged from corpus_pie.py's, which
        # correctly used only the unmediated subset.
        control_bounded_interactions = 0
        control_unbounded_interactions = 0
        data_interactions = 0
        for i in data["interactions"]:
            if i["mediated"]:
                continue
            key = (i["kind"], i["name"])
            if bucket_by_name.get(key) != "DESTRUCTIVE":
                continue
            if key in flagged_control_unbounded_names:
                control_unbounded_interactions += 1
            elif key in flagged_control_bounded_names:
                control_bounded_interactions += 1
            else:
                data_interactions += 1

        repo_result = {
            "repo": repo,
            "destructive_names_total": len(destructive_names),
            "flagged_control_bounded_names": sorted(f"{k[0]}:{k[1]}" for k in flagged_control_bounded_names),
            "flagged_control_unbounded_names": sorted(f"{k[0]}:{k[1]}" for k in flagged_control_unbounded_names),
            "flagged_data_names": sorted(f"{k[0]}:{k[1]}" for k in flagged_data_names),
            "flagged_control_bounded_interactions": control_bounded_interactions,
            "flagged_control_unbounded_interactions": control_unbounded_interactions,
            "flagged_data_interactions": data_interactions,
        }
        per_repo[repo] = repo_result
        with open(out_dir / f"{repo}.json", "w") as out:
            json.dump(repo_result, out, indent=2)

        agg["flagged_control_bounded"] += control_bounded_interactions
        agg["flagged_control_unbounded"] += control_unbounded_interactions
        agg["flagged_data"] += data_interactions
        agg_names["flagged_control_bounded"] += len(flagged_control_bounded_names)
        agg_names["flagged_control_unbounded"] += len(flagged_control_unbounded_names)
        agg_names["flagged_data"] += len(flagged_data_names)

        print(f"{repo:22s} destructive_names={len(destructive_names):4d}  "
              f"flagged_control_bounded={len(flagged_control_bounded_names):4d}  "
              f"flagged_control_unbounded={len(flagged_control_unbounded_names):4d}  "
              f"flagged_data_names={len(flagged_data_names):4d}  "
              f"bounded_interactions={control_bounded_interactions:5d}  "
              f"unbounded_interactions={control_unbounded_interactions:5d}  "
              f"data_interactions={data_interactions:5d}")

    total_interactions = agg["flagged_control_bounded"] + agg["flagged_control_unbounded"] + agg["flagged_data"]
    total_flagged_control = agg["flagged_control_bounded"] + agg["flagged_control_unbounded"]
    overall = {
        "flagged_control_bounded_interactions": agg["flagged_control_bounded"],
        "flagged_control_unbounded_interactions": agg["flagged_control_unbounded"],
        "flagged_data_interactions": agg["flagged_data"],
        "pct_flagged_data_of_flagged": round(100 * agg["flagged_data"] / total_interactions, 2) if total_interactions else None,
        "pct_flagged_control_of_flagged": round(100 * total_flagged_control / total_interactions, 2) if total_interactions else None,
        "pct_bounded_of_flagged_control": round(100 * agg["flagged_control_bounded"] / total_flagged_control, 2) if total_flagged_control else None,
        "pct_unbounded_of_flagged_control": round(100 * agg["flagged_control_unbounded"] / total_flagged_control, 2) if total_flagged_control else None,
        "flagged_control_bounded_distinct_names": agg_names["flagged_control_bounded"],
        "flagged_control_unbounded_distinct_names": agg_names["flagged_control_unbounded"],
        "flagged_data_distinct_names": agg_names["flagged_data"],
    }
    with open(out_dir / "_BRANCH_SUMMARY.json", "w") as out:
        json.dump({"per_repo": per_repo, "overall": overall}, out, indent=2)

    print("\n=== OVERALL (Definition 13 + Definition 15 split of the DESTRUCTIVE/flagged bucket) ===")
    print(json.dumps(overall, indent=2))
    print("\npct_flagged_data_of_flagged: share of the destructive-write bucket")
    print("Proposition 12's soundness proof already covers, for free.")
    print("\npct_bounded_of_flagged_control: share of the REMAINING flagged-control")
    print("bucket that satisfies the Bounded-Path Assumption (Definition 15) and is")
    print("therefore now covered by Proposition 13's path-sensitive over-approximation.")
    print("\npct_unbounded_of_flagged_control: share that is gated by an unbounded")
    print("`while` loop somewhere — Definition 15 excludes this case explicitly, and")
    print("it remains genuinely open; no construction in this document covers it.")
    print("\nNote: this classifier is conservative in the safe direction — a name")
    print("appearing in ANY While-test anywhere in the repo is always counted as")
    print("unbounded, even if it also appears in a bounded If/IfExp/BoolOp test")
    print("elsewhere. This can only under-count the bounded-path share, never")
    print("over-claim Proposition 13 applies where it might not.")


if __name__ == "__main__":
    main()