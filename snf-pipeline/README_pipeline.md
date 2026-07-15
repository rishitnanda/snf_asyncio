# snf-pipeline

Automated source-to-SMT pipeline for the SNF-structured vs. naive
correctness-gap methodology (Section 5.2 / 5.7). Given a Python asyncio
source file, it extracts Lock/Queue/Event synchronization structure via AST
analysis, builds both a naive and an SNF-structured SMT encoding for the
relevant mutual-exclusion / broadcast-wake property, and asks Z3 whether
each is satisfiable.

**What this replaces:** hand-encoding b1–b7, PHP proxies, and the asyncpg
case study by hand. This tool derives the same class of result mechanically
from unmodified source.

**What this does NOT do:** cover the PHP pigeonhole proxies (not asyncio
code — stays a separate synthetic artifact), or resolve the flagged-control /
Prop 12 open case (it *detects and flags* the cross-function/cross-file gap,
it doesn't close it). `.smt2` export is supported (see below).
Everything the tool skips or can't resolve is surfaced explicitly (unresolved
sync-like references, generic awaits, "needs manual check" wait_for sites)
rather than silently dropped. `test_pipeline.py` has 43 regression
assertions covering every fix made so far — run it before trusting a new
sweep.

**Concurrency multiplicity — two distinct mechanisms, don't conflate them:**
- **Detected** (`spawn_multiplicity`, from source): a coroutine spawned as
  ≥2 concurrent tasks in the SAME file (`asyncio.create_task(f())` inside a
  loop/comprehension, or ≥2 separate explicit `create_task(f())` calls to
  the same `f`) is automatically modeled with that many concurrent
  instances instead of just 1 static call site. This is what recovers the
  naive/structured gap on benchmarks like b3/b4/b6, whose worker functions
  are spawned via exactly these patterns.
- **Assumed** (`--assume-public-concurrent`, opt-in, NOT derived from
  source): a coroutine whose name doesn't start with `_` (dunder methods
  like `__aenter__` count as public despite the leading underscore) is
  *assumed* callable concurrently by ≥2 unknown external callers, and that
  assumption is propagated through the same-file call chain to whichever
  inner function actually touches the sync object. This is the ONLY way
  to recover asyncpg's `Pool.acquire()` finding, since the real concurrent
  callers live in code `pool.py` never sees. **This flag changes the
  verdict and must be disclosed as an explicit modeling assumption
  wherever its results are cited** — the tool always prints which
  coroutines got multiplicity this way, separately from detected ones,
  specifically so this distinction is never lost in a results CSV.

## Setup

```bash
pip install z3-solver --break-system-packages
```

Everything else is stdlib (`ast`, `argparse`, `csv`, `re`).

## Files

| File | Purpose |
|---|---|
| `ir.py` | IR: `Program` / `Coroutine` / `Op`, `SyncKind` (LOCK/QUEUE/EVENT), `wait_for_sites`, `unresolved_refs`, `task_refs`, `spawn_multiplicity`, `assumed_concurrent`, `coro_name_collisions` |
| `extractor.py` | AST walker: finds `asyncio.Lock/Queue/LifoQueue/Event` constructor assignments (class/function-scoped, with proper closure-chain resolution for nested functions — not global-by-name), extracts ACQUIRE/RELEASE/Q_GET/Q_PUT/EV_WAIT/EV_SET ops and `wait_for(...)` sites (with multi-hop, same-file handler resolution) from any `async def` — including nested ones, each visited exactly once — in program order. Also detects same-file task-spawn multiplicity (`create_task`/`gather`/loop patterns) |
| `encoder.py` | Builds naive + structured z3 encodings per sync-object kind (site counts scaled by detected/assumed multiplicity), plus the `wait_for`/timeout-race check |
| `smt2_export.py` | Dumps naive/structured solvers to standalone `.smt2` files |
| `pipeline.py` | CLI entry point — run this. Also hosts `apply_public_concurrent_assumption`, the opt-in multiplicity heuristic |
| `sweep_corpus.sh` | Runs `pipeline.py` over every `.py` file in every repo under a corpus root (excluding real `tests/` dirs, not just paths containing "test"), parses output into a CSV + log + `.smt2` files. Set `ASSUME_PUBLIC_CONCURRENT=1` to pass `--assume-public-concurrent` through the whole sweep |
| `inspect_gaps.py` | Spot-check tool: pulls source context for every gap/flag row in a results CSV so you can manually verify findings, and flags files with multiple constructors for the same name |
| `test_pipeline.py` | Regression suite, 43 assertions, no dependencies beyond z3. Run before trusting any new sweep |
| `bench_b1_lock.py`, `bench_b3_queue.py`, `bench_b4_event.py`, `bench_b5_wait_for.py` | Synthetic validation benchmarks, one per property family |

## Usage

### Regression suite

```bash
python3 test_pipeline.py
```

Run this before trusting any new corpus sweep, especially after touching
`extractor.py`/`encoder.py`. Should print `N passed, 0 failed`.

### Single file

```bash
python3 pipeline.py <file.py> [--functions f1,f2,...] [--smt2-dir DIR] [--repo-label NAME] [--assume-public-concurrent]
```

`--functions` restricts AST extraction to the named `async def`s (useful for
pulling one function's worth of context out of a large real-world file).
Note: coroutines are currently tracked by bare name across the whole file
(not class-qualified) -- see Known Limitations #9 if two unrelated classes
define a method with the same name.

`--smt2-dir <dir>` writes a standalone `.smt2` file for every naive and
structured check performed, into `<dir>`. `--repo-label <name>` (optional)
is folded into the output filenames/headers, useful when aggregating across
a corpus sweep.

`--assume-public-concurrent` (opt-in, off by default): treats any
non-underscore-prefixed coroutine (dunder methods count as public) as
callable concurrently by ≥2 unknown external callers, propagated through
the same-file call chain to whichever inner function touches the sync
object. See the top-of-file explanation before using this — it's a stated
assumption, not a source-derived fact, and changes verdicts.

Example, on asyncpg's `pool.py` (default run, no assumption -- correctly
stays `unsat/unsat`, since the real concurrent callers of `Pool.acquire()`
live outside this file):

```bash
python3 pipeline.py pool.py --functions __aenter__,_acquire,_acquire_impl,release
```

Same file, WITH the explicit assumption (recovers the naive/structured gap,
clearly labeled as assumed in the output):

```bash
python3 pipeline.py pool.py --functions __aenter__,_acquire,_acquire_impl,release --assume-public-concurrent
```

### Corpus sweep

```bash
./sweep_corpus.sh <corpus_root_dir> [output.csv]
```

Defaults to writing `./results/results.csv`, `./results/results.log`
(full raw stdout), and `./results/smt2/*.smt2` (one naive + one structured
file per check site) if no output path is given. One CSV row per
sync-object check and per `wait_for` site, across every repo/file found.
Set `ASSUME_PUBLIC_CONCURRENT=1` in the environment to apply the opt-in
assumption across the whole sweep -- do this as a clearly labeled separate
run, never mixed silently into a "default" sweep's numbers.

### Spot-checking sweep results

```bash
python3 inspect_gaps.py <results.csv> <out.txt>
```

Run from the same working directory the sweep was run from (so relative
file paths in the CSV resolve). For every gap/flag row it dumps the source
lines mentioning that object, with context, and warns if it finds more than
one constructor call for the same object name in one file (name-conflation
risk -- see Known Limitations).

## Reading the output

```
--- KIND 'object_name' ---
  naive:      sat|unsat
  structured: sat|unsat
```
**naive=sat, structured=unsat** → correctness gap: naive encoding
incorrectly allows the violation, structured correctly rules it out. This is
the paper's primary finding, reproduced mechanically.

**both unsat** → property holds under both encodings, no gap (b1/b3/b6/b7-
style properties that hold universally, OR a coroutine that's genuinely
only ever invoked once with no detected/assumed concurrency).

```
--- spawn multiplicity DETECTED from source (create_task/gather/loop) ---
  coro_name: modeled as N concurrent instance(s)

--- spawn multiplicity ASSUMED (--assume-public-concurrent, NOT detected from source) ---
  coro_name: modeled as N concurrent instance(s) -- assumption, not derived from this file
```
Printed whenever multiplicity >1 was applied to any coroutine touching a
sync object. The two sections are ALWAYS kept separate -- a detected
multiplicity is a source-derived fact; an assumed one is a stated
methodological choice. Never cite an assumed-multiplicity result as if it
were detected.

```
--- wait_for / timeout race sites ---
  coro:line  naive=... structured=...  (resolution)
```
`structured=sat` flags a wait_for site where no cleanup was found for the
timeout/cancellation branch. The `(resolution)` text tells you why:
- `handled_locally` — cleanup found in the same function as the `wait_for` call
- `handled_in_callee_chain:X` — resolved by walking the call chain (up to 5
  hops, same file only, including `coro = f(); wait_for(coro, ...)` style
  indirection, and `self.attr` receivers) and finding a handler in function `X`
- `callee 'X' not in this file -- needs manual check` — cross-file/cross-module,
  genuinely out of reach for this tool
- `no handler found within same-file call chain -- needs manual check` —
  every same-file callee was checked and none had a handler; likely a real
  gap, but verify by hand
- `no callee name resolved -- needs manual check` — the awaited expression
  wasn't a call or simple variable-assigned call this tool recognizes

**Every "needs manual check" result is a triage flag, not a proof either way.**

```
--- unresolved sync-like references (NOT checked -- origin unknown) ---
  ClassName.attr = source_name  (line N) -- ...
```
A `self.attr = some_name` assignment where `attr` looks lock/queue/event-like
but isn't a recognized `asyncio.X()` constructor call — typically a lock
passed into `__init__` as a parameter. Surfaced explicitly instead of
silently vanishing from `Sync objects found`; not checked for correctness.

```
--- N generic await(s) seen but not modeled ---
  coro:line  await .method()
```
Every awaited call that isn't one of the recognized Lock/Queue/Event/
wait_for patterns, deduplicated -- including bare-name calls like
`await helper()`, which used to be silently dropped entirely. This is the
audit trail for "what did the tool silently skip" — read it before assuming
`Sync objects found` is a complete picture of a file's synchronization
surface.


## Known limitations

**Current corpus numbers** (Section 5.6 corpus, `corpus-study/repo_src/`,
after all fixes in items 1-2, 4, 9-11 below): 114 total check rows (70
sync-object checks, 44 `wait_for` sites). 22 gaps, 44 no-gap, 4 both-sat
(flagged). `wait_for`: 9 handled locally, 1 via call-chain, 23 cross-file,
8 in-file-no-handler, 3 unresolvable callee. 0 sync-object conflation
warnings from `inspect_gaps.py`. 12 actionable coroutine-name-collision
warnings (see #9) after filtering out dunder-method noise. These are the
numbers to cite -- confirmed stable across a rerun after the #4/#9 fixes
below, and the two bug fixes (items 10-11) are already reflected in them.

1. **Name conflation across unrelated sync objects: FIXED and verified.**
   Symbol resolution is class/function-scoped, not global-by-name, with
   proper closure-chain lookup (a nested function can resolve its
   enclosing function's locals, matching real Python scoping). 0
   conflation warnings from `inspect_gaps.py` on the real corpus as of the
   confirmed on the current, fully-fixed sweep (previously 4/35 gap rows were confirmed
   conflated). Regression-covered in `test_pipeline.py`.

2. **`asyncio.Condition.wait_for(predicate)` false-match: FIXED.**
   Was being misdetected as an `asyncio.wait_for(coro, timeout=...)`
   timeout-race site because the method name matches -- these are
   completely different primitives. Now excluded by requiring the
   receiver to be a bare module-style name (`asyncio`/`compat`), not an
   arbitrary attribute chain.

3. **`wait_for` handler resolution: same-file only, depth-limited to 5
   hops, handles direct calls, multi-hop call chains, indirect local
   variables, AND `self.attr` receivers** (resolved via a class-scoped
   `task_refs` map built from any `self.attr = some_call()` assignment,
   typically in `__init__`). Categories of unresolved sites, of 44 total
   (9 handled locally, 1 via call-chain, 34 unresolved):
   - 23 cross-file/cross-module (hard limit -- needs whole-program import
     resolution to fix properly, out of scope for a pattern-based tool)
   - 8 in-file with no handler found in any same-file callee -- **the
     closest thing to genuine findings this tool can surface; worth
     manually verifying each one**
   - 3 callee name unresolvable (e.g. a function *parameter*, not
     something assigned inside the calling function -- can't be resolved
     without caller-side context)

   **Every unresolved/flagged site is a triage flag, not a confirmed
   finding.**

4. **Cleanup-handler detection: BROADENED.** Recognizes `put_nowait`/`put`/
   `release`/`cancel`/`close`/`discard`/`set`/`clear`/`reset`/`disconnect`/
   `abort`/`rollback`/`shutdown`/`terminate`/`requeue`/`unlock`/`free`/
   `dispose`/`giveback`/`recycle` calls in an except/finally (recursively,
   including nested try blocks), and `contextlib.suppress(...)` as a
   handler idiom. Confirmed as a real improvement, not just theoretical: on
   the real corpus, `asyncpg`'s `pool.py:release()` at line 228 went from
   flagged-unresolved to correctly recognized as handled once `terminate`
   was added, since its `except` block calls `self._con.terminate()`.
   Anything outside this list (a custom cleanup method, a state flag
   instead of a call, a `raise` that's caught further up) still won't be
   recognized by exact match -- but a separate, clearly-labeled LOW-
   CONFIDENCE fuzzy check (`CLEANUP_FUZZY_STEMS`: `clean`, `teardown`,
   `revert`, `restore`, `invalidate`, `expire`) surfaces a hint in the
   `wait_for` site's resolution text when a call *looks* cleanup-shaped but
   isn't an exact match, rather than silently reporting nothing relevant
   was found. The fuzzy check never auto-confirms a handler by itself --
   it only adds "verify manually" context.

5. **No true cross-file/cross-module resolution**, for either sync objects
   or `wait_for` handlers. A `Lock()` constructed in one file and imported
   into another is invisible to that second file's analysis. This needs
   whole-program import resolution to fix properly -- documented as a hard
   limit, not silently ignored.

6. **PHP pigeonhole benchmarks are out of scope.** Not asyncio Python; this
   pipeline has no path for them.

7. **Passed-in / externally-built sync objects are surfaced, not analyzed.**
   `self.lock = lock` (a constructor parameter) is reported under
   "unresolved sync-like references" instead of silently vanishing, but its
   correctness is not checked.

8. **`.smt2` export: DONE.** Every check site (Lock/Queue/Event naive+
   structured, and every wait_for site's naive+structured) can be dumped as
   a standalone SMT-LIB2 script via `--smt2-dir` (single file) or
   automatically during `sweep_corpus.sh` (whole corpus, written to
   `results/smt2/`). Verified independently: running the exported files
   through the real `z3` command-line binary (not just the Python API)
   reproduces the exact same sat/unsat verdicts this pipeline prints.
   Regression-tested in `test_pipeline.py` (skipped gracefully if the `z3`
   CLI isn't installed, only the Python package).

9. **Coroutines are tracked by bare name across the WHOLE file, not
   class-qualified -- DETECTED, not fixed.** Unlike sync objects (fixed in
   #1), `Program.coroutines` is keyed only by function name. Two unrelated
   classes each defining a method with the same name would have their ops
   merged into one bucket. A full fix (class-qualifying the dict key)
   turned out to directly conflict with `--assume-public-concurrent`'s
   call-chain propagation and spawn-multiplicity detection, both of which
   must resolve callees by bare name (`self.foo()` in the AST never
   reveals which class `self` is -- that requires real points-to
   analysis, not just scope tracking). Rather than risk breaking that
   working machinery, this is DETECTED instead: `program.coro_name_
   collisions` + a printed warning, filtered to only surface collisions
   where the colliding name actually touches a Lock/Queue/Event or
   contains a `wait_for` site -- an unfiltered first version flagged 579
   file-hits across the corpus, almost entirely `__init__` and other
   dunders colliding across any multi-class file (near-universal, not
   actionable); after filtering, 12 real, individually-inspectable
   collisions remain corpus-wide. Confirmed on real `pool.py`: 8 raw
   collisions (including the `acquire`/`acquire` case that originally
   caused confusion earlier in this project) filtered down to 1 actually
   relevant one (`release`, which does touch a sync object).

10. **FIXED: nested async functions were double-visited, doubling every op
    inside them.** All of b1/b3/b4/b6/b7's worker functions (and asyncpg's
    `_acquire_impl`) are nested one level inside their outer function. The
    top-level extraction driver used to visit nested `async def`s both via
    their parent's own body traversal AND independently when the nested
    name matched `--functions` -- silently doubling every Q_GET/Q_PUT/
    ACQUIRE/etc. inside them. This was NOT a cosmetic bug: it fabricated an
    apparent 2-waiter contention out of what was actually 1 static call
    site counted twice, producing a false "gap reproduced" result on both
    a synthetic benchmark and asyncpg's `pool.py` before it was caught.
    Fixed via node-identity deduplication; regression-tested.

11. **FIXED: nested-function scope resolution was flattened, breaking
    closure variable lookup.** `ScopeTracker` used to compute a nested
    function's scope via a flat, single-pass `ast.walk`, which silently
    attributed ALL descendants (regardless of true nesting depth) to only
    the outermost function's scope. This coincidentally worked for the
    common case (a nested worker reading its outer function's local lock/
    queue/event) but broke the OUTER function's own direct statements
    (e.g. `event.set()` called directly in the function that declared
    `event = asyncio.Event()` would fail to resolve, since the function
    itself was assigned scope=None instead of its own name). Fixed with a
    proper recursive rewrite plus explicit closure-chain lookup (try the
    innermost scope, then walk up enclosing scopes, mirroring real Python
    closure semantics) in `_resolve_sync`. Regression-tested.

12. **Task-spawn multiplicity: two distinct mechanisms, see the top-of-file
    explanation.** `spawn_multiplicity` (detected from `create_task`/
    `gather`/loop patterns in the same file) is a source-derived fact.
    `--assume-public-concurrent` (opt-in) is a stated methodological
    assumption used ONLY to recover findings like asyncpg's, where the
    real concurrent callers are external to the file. The two are never
    merged silently -- `program.assumed_concurrent` always tracks which
    coroutines got their multiplicity from the assumption rather than from
    source, and the pipeline's printed output reports them in separate,
    clearly labeled sections.

13. **Pattern extractor, not points-to analysis.** Handles the common
    `asyncio.Lock/Queue/Event` idioms (module-level or `self.attr`
    constructor assignment, `async with`, `.acquire()/.release()`,
    `.get()/.put()/.put_nowait()`, `.wait()/.set()`, `wait_for(...)` as a
    bare await, inside a `return`, via simple variable assignment, or via
    `self.attr`). Locks stored in containers (lists/dicts) or built via a
    factory function are not tracked and won't appear anywhere in the
    output, including the GENERIC_AWAIT audit.