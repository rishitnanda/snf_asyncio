#!/usr/bin/env python3
"""
scope_contamination_check.py — For each repo, directly measure whether
sync-only files are actually poisoning refine.py's (kind, name) write-form
buckets, rather than inferring contamination from sync-file percentage alone.

Two things can be true independently:
  (a) A repo has many sync-only files (no `async def` anywhere) -- by
      construction these contribute ZERO interaction records to scan.py's
      output, since interactions are only extracted from async function
      bodies. High sync-file % alone does NOT imply contamination.
  (b) A sync-only file assigns/mutates a name (e.g. `self._cache = {}`)
      that ALSO appears as an attribute name in async code elsewhere in
      the repo. Because refine.py buckets by (kind, name) STRING within
      a repo (not per-class), this sync-side write can flip an unrelated
      async-side READ_ONLY name to DESTRUCTIVE/COMMUTATIVE even though
      the sync file contributes zero interaction records itself.

This script measures (b) directly: for every repo, it walks ALL files
(sync and async) collecting every `self.<attr>` / module-global name that
is WRITTEN anywhere in a sync-only file (no enclosing `async def`), then
cross-references that name set against the (kind, name) pairs that
scan.py's async-side interactions actually reference. Any overlap is a
concrete, named instance of the collision mechanism -- not a percentage
proxy for it.

Usage:
    python scope_contamination_check.py
Reads:
    results/<repo>.json   (scan.py output)
    repo_src/<repo>/...   (source tree)
Writes:
    scope_contamination/<repo>.json
    scope_contamination/_CONTAMINATION_SUMMARY.json
"""
import ast
import json
from pathlib import Path
from collections import defaultdict

from scan import iter_python_files, REPO_ASYNC_SCOPE, REPO_ASYNC_EXCLUDE


def file_has_async_def(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            return True
    return False


def collect_written_names_in_tree(tree) -> set:
    """Collect (kind, name) pairs written ANYWHERE in this file (no
    scoping to async/sync -- used only on files already confirmed
    sync-only by the caller)."""
    written = set()
    for node in ast.walk(tree):
        # self.<attr> = ... / self.<attr> += ... etc.
        target_nodes = []
        if isinstance(node, ast.Assign):
            target_nodes = node.targets
        elif isinstance(node, ast.AugAssign):
            target_nodes = [node.target]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target_nodes = [node.target]
        for t in target_nodes:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                written.add(("SELF_ATTR", f"self.{t.attr}"))
            elif isinstance(t, ast.Name):
                written.add(("MODULE_GLOBAL", t.id))
        # mutating method calls: x.append(...), x.pop(...), etc. on self.<attr>
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "self":
                written.add(("SELF_ATTR", f"self.{base.attr}"))
    return written


def analyze_repo(repo: str, repo_dir: Path, scan_data: dict):
    scope = REPO_ASYNC_SCOPE.get(repo)
    exclude = REPO_ASYNC_EXCLUDE.get(repo)

    sync_only_written_names = set()
    n_sync_files, n_async_files = 0, 0

    for f in iter_python_files(repo_dir, include_tests=False, scope_prefixes=scope, exclude_prefixes=exclude):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(f))
        except (SyntaxError, ValueError):
            continue
        if file_has_async_def(tree):
            n_async_files += 1
            continue
        n_sync_files += 1
        sync_only_written_names |= collect_written_names_in_tree(tree)

    # Names actually referenced by scan.py's recorded async-side interactions
    async_side_names = {(i["kind"], i["name"]) for i in scan_data["interactions"]}
    # Of those, which were previously READ_ONLY-eligible (never written on
    # the async side itself) -- these are the ones at risk of being flipped
    # purely by sync-side write evidence.
    async_side_written = {
        (i["kind"], i["name"]) for i in scan_data["interactions"]
        if i["write_form"] not in (None, "", "read")
    }
    async_side_read_only_candidates = async_side_names - async_side_written

    collision_names = sync_only_written_names & async_side_read_only_candidates

    return {
        "repo": repo,
        "n_sync_only_files": n_sync_files,
        "n_async_files": n_async_files,
        "sync_only_written_name_count": len(sync_only_written_names),
        "async_side_read_only_candidate_count": len(async_side_read_only_candidates),
        "collision_count": len(collision_names),
        "collision_names": sorted(f"{k}:{n}" for k, n in collision_names)[:50],
        "verdict": "CONTAMINATION LIKELY -- rescope recommended" if collision_names
                   else "no direct collision found -- high sync-file% likely benign here",
    }


def main():
    root = Path(__file__).resolve().parent
    results_dir = root / "results"
    repo_src = root / "repo_src"
    out_dir = root / "scope_contamination"
    out_dir.mkdir(exist_ok=True)

    per_repo = {}
    for f in sorted(results_dir.glob("*.json")):
        if f.name == "_SUMMARY.json":
            continue
        data = json.load(open(f))
        repo = data["repo"]
        repo_dir = repo_src / repo
        if not repo_dir.is_dir():
            print(f"{repo:22s} SKIPPED -- repo_src/{repo} not found")
            continue
        result = analyze_repo(repo, repo_dir, data)
        per_repo[repo] = result
        with open(out_dir / f"{repo}.json", "w") as out:
            json.dump(result, out, indent=2)
        flag = "!!!" if result["collision_count"] else "   "
        print(f"{flag} {repo:22s} sync_files={result['n_sync_only_files']:5d}  "
              f"collisions={result['collision_count']:4d}  {result['verdict']}")

    flagged = {r: v for r, v in per_repo.items() if v["collision_count"] > 0}
    with open(out_dir / "_CONTAMINATION_SUMMARY.json", "w") as out:
        json.dump({"per_repo": per_repo, "flagged_for_rescope": sorted(flagged.keys())}, out, indent=2)

    print(f"\n=== {len(flagged)} of {len(per_repo)} repos show a direct name collision ===")
    print("These, not the raw sync-file percentage, are the actual rescope priority list:")
    for r in sorted(flagged):
        print(f"  {r}: {flagged[r]['collision_count']} colliding names")


if __name__ == "__main__":
    main()