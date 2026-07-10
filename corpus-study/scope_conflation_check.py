#!/usr/bin/env python3
"""
scope_conflation_check.py — Check ALL 33 corpus repos for the same
sync/async monorepo conflation risk found (and fixed) for sqlalchemy and
elasticsearch-py.

Why this exists: REPO_ASYNC_SCOPE in scan.py currently only restricts 2
of 33 repos to their async submodules. The other 31 are scanned
unscoped. That was fine as a default when those repos are async-first
(aiohttp, asyncpg, etc.), but nothing has actually CHECKED whether any
of the other 31 also have a large sync-only volume diluting their
destructive-interaction percentage the same way sqlalchemy/
elasticsearch-py did before their scope fix.

METHOD (heuristic screen, not a fix): for every repo already in
results/<repo>.json (i.e. already scanned by scan.py), re-walk the same
source tree UNSCOPED (ignoring any existing REPO_ASYNC_SCOPE entry, to
measure what the whole repo looks like) and, per .py file actually
under scan.py's own file-walk rules (respects SKIP_DIR_NAMES, no
test dirs), check whether the file contains ANY of:
  - `async def`
  - `await `
  - `asyncio` import or attribute reference
If a file contains NONE of these, it is "sync-only" by this heuristic.
Report, per repo, the fraction of files that are sync-only. A repo with
a high sync-only fraction (comparable to sqlalchemy's pre-fix profile)
is a candidate for the same scoping treatment already applied to
sqlalchemy/elasticsearch-py.

CAVEATS:
  - This is a per-FILE async-syntax presence check, not a per-function
    or per-interaction check — a file can be "async-containing" and
    still have plenty of unrelated sync helper code inside it, so this
    UNDERSTATES how much sync-only *code* (as opposed to sync-only
    *files*) exists even in "clean" repos. It's a fast triage signal,
    not a replacement for the same manual scoped-rescan treatment given
    to sqlalchemy/elasticsearch-py.
  - Does not attempt to auto-generate a REPO_ASYNC_SCOPE entry. A high
    sync-only fraction is a flag for manual inspection (find the actual
    async submodule path), the same way the original two were found.

Usage:
    python scope_conflation_check.py
Reads:
    results/<repo>.json   (scan.py output, for the repo list)
    repo_src/<repo>/...   (source tree)
Writes:
    scope_conflation_report.json
"""
import ast
import json
import re
from pathlib import Path

from scan import iter_python_files, SKIP_DIR_NAMES  # reuse scan.py's own walk rules

ASYNC_SIGNAL_RE = re.compile(r"\basync\s+def\b|\bawait\s|\basyncio\b")


def file_has_async_signal(path: Path) -> bool:
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if ASYNC_SIGNAL_RE.search(src):
        return True
    # Fallback AST check in case of unusual formatting the regex misses
    try:
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncWith, ast.AsyncFor, ast.Await)):
            return True
    return False


def check_repo(repo_dir: Path):
    total_files = 0
    sync_only_files = 0
    sync_only_paths = []
    for f in iter_python_files(repo_dir, include_tests=False, scope_prefixes=None):
        total_files += 1
        if not file_has_async_signal(f):
            sync_only_files += 1
            if len(sync_only_paths) < 10:
                sync_only_paths.append(str(f.relative_to(repo_dir)))
    pct = round(100 * sync_only_files / total_files, 2) if total_files else None
    return {
        "total_files_scanned": total_files,
        "sync_only_files": sync_only_files,
        "pct_sync_only_files": pct,
        "sample_sync_only_paths": sync_only_paths,
    }


def main():
    root = Path(__file__).resolve().parent
    results_dir = root / "results"
    repo_src = root / "repo_src"

    already_scoped = {"sqlalchemy", "elasticsearch-py"}  # per REPO_ASYNC_SCOPE

    report = {}
    for f in sorted(results_dir.glob("*.json")):
        if f.name == "_SUMMARY.json":
            continue
        data = json.load(open(f))
        repo = data["repo"]
        repo_dir = repo_src / repo
        if not repo_dir.is_dir():
            print(f"{repo:22s} SKIPPED — repo_src/{repo} not found")
            continue
        result = check_repo(repo_dir)
        result["already_has_scope_fix"] = repo in already_scoped
        report[repo] = result
        flag = "  <-- CHECK THIS ONE" if (result["pct_sync_only_files"] or 0) > 30 and repo not in already_scoped else ""
        print(f"{repo:22s} files={result['total_files_scanned']:5d}  "
              f"sync_only={result['sync_only_files']:5d} "
              f"({result['pct_sync_only_files']}%)  "
              f"scoped_already={repo in already_scoped}{flag}")

    # Create the output directory if it doesn't already exist
    output_dir = root / "scope_conflation"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write the JSON report into the new directory
    with open(output_dir / "scope_conflation_report.json", "w") as out:
        json.dump(report, out, indent=2)

    candidates = sorted(
        (r for r, v in report.items() if not v["already_has_scope_fix"] and (v["pct_sync_only_files"] or 0) > 30),
        key=lambda r: -report[r]["pct_sync_only_files"],
    )
    print("\n=== Repos with >30% sync-only files, not yet scope-fixed ===")
    print("(candidates for the same manual scoped-rescan treatment given")
    print(" to sqlalchemy/elasticsearch-py — inspect these first)")
    for r in candidates:
        print(f"  {r}: {report[r]['pct_sync_only_files']}% sync-only "
              f"({report[r]['sync_only_files']}/{report[r]['total_files_scanned']} files)")
    if not candidates:
        print("  none found above the 30% threshold")


if __name__ == "__main__":
    main()