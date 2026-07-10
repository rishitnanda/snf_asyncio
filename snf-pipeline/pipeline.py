"""
Generalized automated source-to-SMT pipeline.

    python3 pipeline.py <source.py> [--functions f1,f2,...]

Works on ANY Python source file, not one specific repository: extracts
asyncio Lock/Queue/Event synchronization structure via AST pattern-matching,
then runs the matching naive-vs-structured (SNF) SMT check for every sync
object found, via z3. No hand-encoding, no per-file special-casing.

Intended use for the paper: point this at each of the corpus repos
(Section 5.6) or at the b1-b7 microbenchmark sources to get sat/unsat
results mechanically instead of by hand.
"""

import argparse
from extractor import extract
from encoder import check_all, check_wait_for
from smt2_export import export_program_smt2
from ir import OpKind


def apply_public_concurrent_assumption(program):
    """OPT-IN heuristic (only applied if --assume-public-concurrent is
    passed): any coroutine whose name doesn't start with '_' (a rough
    "this is a public API method" signal) is assumed to be callable
    concurrently by >=2 unknown external callers. If that public
    coroutine doesn't itself touch a Lock/Queue/Event directly -- e.g.
    asyncpg's public `acquire()` just delegates to private `_acquire` ->
    `_acquire_impl`, which is where the actual queue op lives -- the
    assumption is propagated through the same-file call chain (depth-
    limited to 5 hops, same mechanism as the wait_for chain resolution)
    to whichever inner coroutine actually touches the sync object.

    This is NOT derived from the source file -- it's a stated assumption
    that a public method could be called concurrently by callers this
    file never sees (the asyncpg Pool.acquire() shape). Every coroutine
    given multiplicity this way is recorded in program.assumed_concurrent
    and reported separately from genuinely source-detected multiplicities,
    so it's never silently conflated with a real finding.
    """
    import ast as _ast
    SYNC_OP_KINDS = {OpKind.ACQUIRE, OpKind.Q_GET, OpKind.Q_PUT,
                     OpKind.EV_WAIT, OpKind.EV_SET}
    MAX_HOPS = 5

    def touches_sync(coro_name):
        coro = program.coroutines.get(coro_name)
        return coro is not None and any(op.kind in SYNC_OP_KINDS for op in coro.ops)

    def callees_of(coro_name):
        coro = program.coroutines.get(coro_name)
        if coro is None:
            return []
        names = set()
        for op in coro.ops:
            if op.kind == OpKind.GENERIC_AWAIT and op.note:
                # note is like ".methodname()" -- strip to bare name
                names.add(op.note.strip(".()"))
        return [n for n in names if n in program.coroutines]

    def find_sync_touching_descendant(start, seen, hops):
        if hops > MAX_HOPS or start in seen:
            return None
        seen = seen | {start}
        if touches_sync(start):
            return start
        for callee in callees_of(start):
            found = find_sync_touching_descendant(callee, seen, hops + 1)
            if found:
                return found
        return None

    def _is_public(name):
        # Dunder methods (__aenter__, __aexit__, __call__, etc.) ARE public
        # API despite the leading underscore -- only single/double leading
        # underscore WITHOUT a matching trailing dunder means "private".
        if name.startswith("__") and name.endswith("__"):
            return True
        return not name.startswith("_")

    for coro in program.coroutines.values():
        if not _is_public(coro.name):
            continue
        target = coro.name if touches_sync(coro.name) else \
            find_sync_touching_descendant(coro.name, set(), 0)
        if not target:
            continue
        existing = program.spawn_multiplicity.get(target, 1)
        if existing < 2:
            program.spawn_multiplicity[target] = 2
            program.assumed_concurrent.add(target)


def run(path, functions=None, smt2_dir=None, repo_label="", assume_public_concurrent=False):
    with open(path) as f:
        source = f.read()

    program = extract(source, coroutine_names=functions)

    if assume_public_concurrent:
        apply_public_concurrent_assumption(program)

    print(f"=== {path} ===")
    print(f"Coroutines extracted: {list(program.coroutines.keys())}")
    print(f"Sync objects found: { {k: v.name for k, v in program.sync_objects.items()} }")

    detected_mult = {k: v for k, v in program.spawn_multiplicity.items()
                     if v >= 2 and k not in program.assumed_concurrent}
    if detected_mult:
        print(f"\n--- spawn multiplicity DETECTED from source (create_task/gather/loop) ---")
        for name, mult in detected_mult.items():
            print(f"  {name}: modeled as {mult} concurrent instance(s)")

    if program.assumed_concurrent:
        print(f"\n--- spawn multiplicity ASSUMED (--assume-public-concurrent, NOT detected from source) ---")
        for name in sorted(program.assumed_concurrent):
            print(f"  {name}: modeled as {program.spawn_multiplicity[name]} concurrent instance(s) "
                  f"-- assumption, not derived from this file")

    if program.coro_name_collisions:
        print(f"\n--- WARNING: bare coroutine name(s) defined in >1 class (limitation #9) ---")
        for name, scopes_list in sorted(program.coro_name_collisions.items()):
            print(f"  '{name}' defined in: {', '.join(scopes_list)}")
        print(f"  Program.coroutines is keyed by bare name -- if two classes above both touch a")
        print(f"  sync object under the same method name, their ops WILL be merged into one")
        print(f"  bucket by encoder.py's site counting, inflating or fabricating apparent")
        print(f"  contention. Verify manually before citing any gap/no-gap result involving")
        print(f"  these names. (A full fix requires reconciling class-qualified identity with")
        print(f"  every bare-name-based mechanism this tool uses -- wait_for chains, spawn-")
        print(f"  multiplicity, --assume-public-concurrent -- since `self.foo()` in the AST only")
        print(f"  ever gives the bare name; this is deferred as a larger undertaking, not fixed.)")

    if program.unresolved_refs:
        print(f"\n--- unresolved sync-like references (NOT checked -- origin unknown) ---")
        for ref in program.unresolved_refs:
            scope = ref["class_scope"] or "(module)"
            print(f"  {scope}.{ref['attr']} = {ref['source_name']}  (line {ref['line']}) "
                  f"-- {ref['reason']}")

    generic_awaits = sorted(set((coro.name, op.line, op.note) for coro in program.coroutines.values()
                      for op in coro.ops if op.kind.name == "GENERIC_AWAIT"), key=lambda t: (t[0], t[1]))
    if generic_awaits:
        print(f"\n--- {len(generic_awaits)} generic await(s) seen but not modeled ---")
        for coro_name, line, note in generic_awaits:
            print(f"  {coro_name}:{line}  await {note}")

    results = check_all(program)
    if not results:
        print("No Lock/Queue/Event objects found in scope.")

    for name, r in results.items():
        print(f"\n--- {r['kind']} '{name}' ---")
        gap = r["naive"] == "sat" and r["structured"] == "unsat"
        flag = "  <-- CORRECTNESS GAP" if gap else ""
        print(f"  naive:      {r['naive']}{flag}")
        print(f"  structured: {r['structured']}")

    wf_results = check_wait_for(program)
    if wf_results:
        print(f"\n--- wait_for / timeout race sites ---")
        for site, r in zip(program.wait_for_sites, wf_results):
            print(f"  {r['coro']}:{r['line']}  naive={r['naive']}  "
                  f"structured={r['structured']}  ({site.get('resolution', '')})")

    if smt2_dir:
        written = export_program_smt2(program, results, wf_results, smt2_dir,
                                       repo=repo_label, source_file=path)
        print(f"\n--- wrote {len(written)} .smt2 file(s) to {smt2_dir} ---")

    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--functions", default=None,
                     help="comma-separated async def names to restrict extraction to")
    ap.add_argument("--smt2-dir", default=None,
                     help="if given, write naive/structured .smt2 files for every "
                          "check site into this directory")
    ap.add_argument("--repo-label", default="",
                     help="optional repo name, used only in .smt2 filenames/headers")
    ap.add_argument("--assume-public-concurrent", action="store_true",
                     help="OPT-IN, NOT derived from source: treat any coroutine whose "
                          "name doesn't start with '_' and touches a Lock/Queue/Event "
                          "as callable concurrently by >=2 unknown external callers "
                          "(the asyncpg Pool.acquire() shape). Always reported "
                          "separately from source-detected multiplicity.")
    args = ap.parse_args()
    fns = set(args.functions.split(",")) if args.functions else None
    run(args.source, fns, smt2_dir=args.smt2_dir, repo_label=args.repo_label,
        assume_public_concurrent=args.assume_public_concurrent)