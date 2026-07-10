"""
Spot-check tool: for every gap/flag row in a results.csv (from
sweep_corpus.sh), pull the relevant source lines with context and write
them to a single txt file, so you can manually verify each finding instead
of trusting the CSV blind.

Checks specifically for the known risk: two distinct sync objects in the
same file sharing a variable name (the conflation issue seen in
benchmarks.py) would show up here as multiple, unrelated-looking
constructor/usage sites under one "object_name" heading.

Usage:
    python3 inspect_gaps.py results/results.csv results/inspect.txt
"""

import sys
import csv
import re
import ast

try:
    from extractor import ScopeTracker
except ImportError:
    ScopeTracker = None  # degrade gracefully if not run alongside extractor.py

CONTEXT = 2  # lines of context around each match


def _target_scope(qualified_name):
    """Inverse of _bare_name: the scope portion of a qualified display
    name, e.g. "ConnectionPool._lock" -> "ConnectionPool", or None if the
    name was never qualified (module-level)."""
    if "::" in qualified_name:
        return qualified_name.rsplit("::", 1)[0]
    if "." in qualified_name:
        return qualified_name.rsplit(".", 1)[0]
    return None


def _class_scope_by_line(filepath):
    """Parse filepath and return {lineno: class_scope_or_None} for EVERY
    line with an AST node (not just Assign statements) -- used both to
    check whether multiple constructor assignments for the same object
    name are in different classes (real conflation) or the same class
    (benign reassignment), AND to annotate every hit line in the gap
    report with which class it actually belongs to, since bare-name
    search (see _bare_name) can match occurrences from an unrelated class
    in the same file that happens to reuse the same short attribute name."""
    if ScopeTracker is None:
        return {}
    try:
        with open(filepath, errors="replace") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, FileNotFoundError, OSError):
        return {}
    scopes = ScopeTracker()
    scopes.visit(tree)
    result = {}
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            class_scope, _ = scopes.scope_of(node)
            result.setdefault(node.lineno, class_scope)
    return result


def _bare_name(qualified_name):
    """extractor.py's _display_name() produces qualified DISPLAY names for
    scoped sync objects -- "ClassName.attr" (class scope) or
    "func_name::attr" (function scope) -- but the source file itself only
    ever contains the literal bare attribute/variable name ("_lock"), never
    the qualified string ("ConnectionPool._lock") as literal text. Searching
    for the qualified name as-is matches ZERO lines in every scoped case,
    which is exactly what was happening here: every gap row with a
    class- or function-qualified object_name showed "0 occurrences",
    silently making the context dump useless. Strip back to the bare name
    before searching."""
    if "::" in qualified_name:
        return qualified_name.rsplit("::", 1)[-1]
    if "." in qualified_name:
        return qualified_name.rsplit(".", 1)[-1]
    return qualified_name


def find_object_lines(filepath, obj_name):
    """Return (lineno, text) for every line mentioning obj_name as a bare
    identifier (not a substring of a longer name)."""
    try:
        with open(filepath, errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None, []
    pattern = re.compile(r"\b" + re.escape(obj_name) + r"\b")
    hits = []
    for i, line in enumerate(lines, start=1):
        if pattern.search(line):
            hits.append((i, line.rstrip("\n")))
    return lines, hits


def dump_context(lines, lineno, out, width=CONTEXT):
    lo = max(1, lineno - width)
    hi = min(len(lines), lineno + width)
    for i in range(lo, hi + 1):
        marker = ">>" if i == lineno else "  "
        out.write(f"    {marker} {i:5d}: {lines[i-1].rstrip(chr(10))}\n")


def main(csv_path, out_path):
    rows = list(csv.DictReader(open(csv_path)))
    sync_gap_rows = [r for r in rows
                      if r["check_type"] in ("LOCK", "QUEUE", "EVENT")
                      and r["gap_or_flag"] == "yes"]
    wf_flag_rows = [r for r in rows
                    if r["check_type"] == "wait_for"
                    and "needs manual check" in r["gap_or_flag"]]

    with open(out_path, "w") as out:
        out.write(f"Spot-check report: {len(sync_gap_rows)} sync-object gaps, "
                   f"{len(wf_flag_rows)} wait_for flags\n")
        out.write("=" * 78 + "\n\n")

        out.write("### SYNC-OBJECT CORRECTNESS-GAP ROWS (LOCK/QUEUE/EVENT) ###\n\n")
        for r in sync_gap_rows:
            out.write(f"[{r['repo']}] {r['file']}\n")
            out.write(f"  kind={r['check_type']}  object_name={r['object_name']}\n")
            bare = _bare_name(r["object_name"])
            lines, hits = find_object_lines(r["file"], bare)
            if lines is None:
                out.write("  !! file not found at this path -- rerun from repo root\n\n")
                continue
            out.write(f"  {len(hits)} occurrence(s) of '{bare}' "
                      f"(searched as bare name, displayed qualified as "
                      f"'{r['object_name']}') in this file:\n")
            # Flag possible conflation: multiple constructor calls for the same name
            ctor_lines = [ln for ln, text in hits if re.search(r"=\s*asyncio\.\w+\(", text)]
            if len(ctor_lines) > 1:
                class_by_line = _class_scope_by_line(r["file"])
                ctor_classes = {class_by_line.get(ln, "?") for ln in ctor_lines}
                if len(ctor_classes) > 1:
                    out.write(f"  ** WARNING: {len(ctor_lines)} separate constructor "
                              f"assignments found for '{r['object_name']}' ACROSS "
                              f"{len(ctor_classes)} DIFFERENT classes/scopes "
                              f"({', '.join(str(c) for c in sorted(ctor_classes, key=str))}) "
                              f"-- likely real conflation of distinct objects **\n")
                else:
                    out.write(f"  (note: {len(ctor_lines)} constructor assignments for "
                              f"'{r['object_name']}', all within the same class/scope -- "
                              f"benign reassignment, e.g. __init__ + reset(), not conflation)\n")
            target_scope = _target_scope(r["object_name"])
            class_by_line = _class_scope_by_line(r["file"])
            for ln, text in hits:
                hit_scope = class_by_line.get(ln)
                if target_scope is not None and hit_scope != target_scope:
                    out.write(f"  -- line {ln} (DIFFERENT SCOPE: '{hit_scope}', "
                              f"not the target '{target_scope}' -- likely an unrelated "
                              f"object that happens to share the bare name '{bare}') --\n")
                else:
                    out.write(f"  -- line {ln} --\n")
                dump_context(lines, ln, out)
            out.write("\n")

        out.write("\n### wait_for FLAGGED SITES (no locally-visible handler) ###\n\n")
        for r in wf_flag_rows:
            out.write(f"[{r['repo']}] {r['file']}\n")
            out.write(f"  coro={r['object_name']}  line={r['kind_or_line']}\n")
            lines, _ = find_object_lines(r["file"], "wait_for")
            if lines is None:
                out.write("  !! file not found at this path -- rerun from repo root\n\n")
                continue
            try:
                lineno = int(r["kind_or_line"])
                dump_context(lines, lineno, out, width=6)
            except ValueError:
                pass
            out.write("\n")

    print(f"Wrote {out_path}")
    print(f"  sync-object gap rows: {len(sync_gap_rows)}")
    print(f"  wait_for flagged rows: {len(wf_flag_rows)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python3 inspect_gaps.py <results.csv> <out.txt>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])