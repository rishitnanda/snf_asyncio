#!/usr/bin/env python3
"""
eager_factory_check.py — How much of the corpus actually uses
`asyncio.eager_task_factory`?

Why this exists: bullet 2 of the fragility note (eager_task_factory
breaks SNF-1/2/3) has a proved sub-case (Prop 7-8), a sketched-but-
unproved sub-case (Prop 8'), and no measurement of how often the whole
question even comes up in practice. This script measures that, the
same way branch_check.py and thread_overlap_check.py measured the other
two open questions instead of leaving them qualitative.

METHOD (heuristic, same evidentiary tier as scan.py's own detectors):
For every .py file in a repo's scanned scope, look for:
  1. Any reference to the name `eager_task_factory` at all -- as an
     attribute (`asyncio.eager_task_factory`), a bare name (imported via
     `from asyncio import eager_task_factory`), or an alias target of an
     import statement. This catches both "set it as the factory" and
     "pass it explicitly to Runner(...)" usage.
  2. Any call to `.set_task_factory(...)` on any object, regardless of
     what's passed -- recorded separately, since the argument might be a
     variable or a custom factory rather than the literal
     `eager_task_factory` name, and that can't be resolved by a
     syntactic scan without dataflow analysis (out of scope here, same
     restriction scan.py/branch_check.py/thread_overlap_check.py all
     already carry). These calls are reported as "unclear" unless their
     argument expression's source text literally contains
     `eager_task_factory`.
  3. Any `asyncio.Runner(..., loop_factory=..., ...)` or similar call
     whose keyword arguments' source text contains `eager_task_factory`
     (Python 3.12+ convenience path for setting the factory at Runner
     construction time).

This is a REPO-WIDE scan, not restricted to async functions or to
scan.py's REPO_ASYNC_SCOPE -- factory setup is typically top-level
application wiring (main(), a Runner context manager, a conftest.py
fixture), not inside the coroutines scan.py already analyzed. Test
files and examples ARE included here (unlike scan.py's corpus study),
since "does this repo's test suite exercise eager_task_factory" is
itself useful signal about how live the question is, and doing so is
noted explicitly in the output.

CAVEATS:
  - A literal `eager_task_factory` reference does not prove it is
    RUNNING against corpus code the destructive-write analysis covers --
    it could be behind a version check, a feature flag, or dead code.
    This reports an UPPER bound on real usage, in contrast to the
    thread-overlap script's lower bound -- the two measurement scripts
    lean in opposite directions on purpose, and both should be read as
    approximate.
  - `set_task_factory` calls whose argument isn't literally
    `eager_task_factory` in the source text are reported as "unclear",
    not resolved further; a repo passing a custom factory that wraps or
    delegates to eager_task_factory would be missed.

Usage:
    python eager_factory_check.py
Reads:
    repo_src/<repo>/...   (source tree; same requirement as branch_check.py)
Writes:
    eager_factory/_EAGER_FACTORY_SUMMARY.json
    (no per-repo files -- this is a much smaller signal than the other
    two checks, one summary file is enough)
"""
import ast
from pathlib import Path
import json


def scan_file(path: Path):
    """Returns a dict of findings for one file, or None if nothing relevant."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, ValueError):
        return None

    eager_refs = []
    set_factory_calls = []

    class Visitor(ast.NodeVisitor):
        def visit_Attribute(self, node):
            if node.attr == "eager_task_factory":
                eager_refs.append(node.lineno)
            self.generic_visit(node)

        def visit_Name(self, node):
            if node.id == "eager_task_factory":
                eager_refs.append(node.lineno)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                if alias.name == "eager_task_factory":
                    eager_refs.append(node.lineno)
            self.generic_visit(node)

        def visit_Call(self, node):
            f = node.func
            is_set_task_factory = isinstance(f, ast.Attribute) and f.attr == "set_task_factory"
            if is_set_task_factory:
                arg_src = ""
                if node.args:
                    try:
                        arg_src = ast.unparse(node.args[0])
                    except Exception:
                        arg_src = "<unparsable>"
                set_factory_calls.append({
                    "lineno": node.lineno,
                    "arg_source": arg_src,
                    "is_eager": "eager_task_factory" in arg_src,
                })
            self.generic_visit(node)

    Visitor().visit(tree)

    if not eager_refs and not set_factory_calls:
        return None
    return {
        "file": str(path),
        "eager_task_factory_references": sorted(set(eager_refs)),
        "set_task_factory_calls": set_factory_calls,
    }


def scan_repo(repo_dir: Path):
    findings = []
    for f in sorted(repo_dir.rglob("*.py")):
        result = scan_file(f)
        if result:
            result["file"] = str(f.relative_to(repo_dir))
            findings.append(result)
    return findings


def main():
    root = Path(__file__).resolve().parent
    repo_src = root / "repo_src"
    out_dir = root / "eager_factory"
    out_dir.mkdir(exist_ok=True)

    per_repo = {}
    repos_scanned = 0
    repos_with_eager_reference = 0
    repos_with_unclear_set_factory_only = 0
    total_eager_refs = 0
    total_set_factory_calls = 0

    for repo_dir in sorted(repo_src.iterdir()):
        if not repo_dir.is_dir():
            continue
        repos_scanned += 1
        findings = scan_repo(repo_dir)

        eager_ref_count = sum(len(f["eager_task_factory_references"]) for f in findings)
        set_factory_count = sum(len(f["set_task_factory_calls"]) for f in findings)
        has_eager = eager_ref_count > 0 or any(
            call["is_eager"] for f in findings for call in f["set_task_factory_calls"]
        )
        has_unclear_only = (not has_eager) and set_factory_count > 0

        if has_eager:
            repos_with_eager_reference += 1
        if has_unclear_only:
            repos_with_unclear_set_factory_only += 1

        total_eager_refs += eager_ref_count
        total_set_factory_calls += set_factory_count

        if findings:
            per_repo[repo_dir.name] = {
                "uses_eager_task_factory": has_eager,
                "unclear_set_task_factory_only": has_unclear_only,
                "eager_task_factory_reference_count": eager_ref_count,
                "set_task_factory_call_count": set_factory_count,
                "findings": findings,
            }
            print(f"{repo_dir.name:22s} eager_refs={eager_ref_count:3d}  "
                  f"set_task_factory_calls={set_factory_count:3d}  "
                  f"uses_eager={has_eager}  unclear_only={has_unclear_only}")

    overall = {
        "repos_scanned": repos_scanned,
        "repos_with_eager_task_factory_reference": repos_with_eager_reference,
        "pct_repos_using_eager_task_factory": round(
            100 * repos_with_eager_reference / repos_scanned, 2
        ) if repos_scanned else None,
        "repos_with_unclear_set_task_factory_only": repos_with_unclear_set_factory_only,
        "total_eager_task_factory_references": total_eager_refs,
        "total_set_task_factory_calls": total_set_factory_calls,
        "note": "Upper bound: a literal reference doesn't prove the eager path "
                "actually executes against scanned code (could be behind a "
                "version check, feature flag, or dead code). set_task_factory "
                "calls whose argument isn't literally 'eager_task_factory' in "
                "source text are reported separately as unclear, not resolved.",
    }
    with open(out_dir / "_EAGER_FACTORY_SUMMARY.json", "w") as out:
        json.dump({"per_repo": per_repo, "overall": overall}, out, indent=2)

    print("\n=== OVERALL (upper bound on eager_task_factory usage) ===")
    print(json.dumps(overall, indent=2))
    print("\nThis answers: how live is the eager_task_factory gap in practice?")
    print("If pct_repos_using_eager_task_factory is near zero, Prop 8' is a")
    print("correctness question worth having answered but a low-incidence one")
    print("today. If it's non-trivial, or 'unclear' set_task_factory calls are")
    print("common, that changes the urgency -- those calls warrant a manual look.")


if __name__ == "__main__":
    main()