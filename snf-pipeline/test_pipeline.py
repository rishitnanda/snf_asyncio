"""
Basic regression suite for snf-pipeline. No pytest dependency -- plain
asserts, run directly:

    python3 test_pipeline.py

Covers: the four sync-object families (Lock/Queue/Event correctness gap),
class-scoped symbol resolution (the conflation fix), multi-hop wait_for
resolution, unresolved-ref surfacing, and GENERIC_AWAIT auditing. Intended
to catch silent regressions if extractor.py/encoder.py are touched again --
run this before trusting any new corpus sweep.
"""

import sys
import tempfile
import os
from extractor import extract
from encoder import check_all, check_wait_for
from ir import SyncKind


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def run_source(src, functions=None):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        with open(path) as f2:
            program = extract(f2.read(), coroutine_names=functions)
    finally:
        os.unlink(path)
    return program


# ---------------------------------------------------------------- LOCK ----

def test_lock_gap():
    program = run_source("""
import asyncio
mutex = asyncio.Lock()

async def worker_1():
    async with mutex:
        pass

async def worker_2():
    async with mutex:
        pass
""")
    results = check_all(program)
    check("lock: found 1 sync object", len(program.sync_objects) == 1)
    check("lock: naive=sat", results["mutex"]["naive"] == "sat")
    check("lock: structured=unsat", results["mutex"]["structured"] == "unsat")


def test_lock_no_gap_single_acquirer():
    program = run_source("""
import asyncio
mutex = asyncio.Lock()

async def worker_1():
    async with mutex:
        pass
""")
    results = check_all(program)
    check("lock/single: naive=unsat (no contention)", results["mutex"]["naive"] == "unsat")


# --------------------------------------------------------------- QUEUE ----

def test_queue_gap():
    program = run_source("""
import asyncio
q = asyncio.Queue()

async def a():
    x = await q.get()

async def b():
    x = await q.get()

async def c():
    q.put_nowait(1)
""")
    results = check_all(program)
    check("queue: naive=sat", results["q"]["naive"] == "sat")
    check("queue: structured=unsat", results["q"]["structured"] == "unsat")


# --------------------------------------------------------------- EVENT ----

def test_event_gap():
    program = run_source("""
import asyncio
ev = asyncio.Event()

async def w1():
    await ev.wait()

async def w2():
    await ev.wait()

async def setter():
    ev.set()
""")
    results = check_all(program)
    check("event: naive=sat", results["ev"]["naive"] == "sat")
    check("event: structured=unsat", results["ev"]["structured"] == "unsat")


# --------------------------------------------------------- SCOPING FIX ----

def test_class_scoped_locks_not_conflated():
    program = run_source("""
import asyncio

class A:
    def __init__(self):
        self._lock = asyncio.Lock()
    async def m(self):
        async with self._lock:
            pass

class B:
    def __init__(self):
        self._lock = asyncio.Lock()
    async def m1(self):
        async with self._lock:
            pass
    async def m2(self):
        async with self._lock:
            pass
""")
    results = check_all(program)
    check("scoping: 2 distinct objects found (not conflated)",
          len(program.sync_objects) == 2)
    check("scoping: A._lock has no gap (1 acquirer)",
          results["A._lock"]["naive"] == "unsat")
    check("scoping: B._lock has a gap (2 acquirers)",
          results["B._lock"]["naive"] == "sat" and results["B._lock"]["structured"] == "unsat")


def test_function_scoped_locals_not_conflated():
    program = run_source("""
import asyncio

async def bench_a():
    lock = asyncio.Lock()
    async def w():
        async with lock:
            pass
    await w()

async def bench_b():
    lock = asyncio.Lock()
    async def w():
        async with lock:
            pass
    await w()
""")
    check("function-scoping: 2 distinct locals found",
          len(program.sync_objects) == 2)


# ------------------------------------------------------ WAIT_FOR CHAIN ----

def test_wait_for_handled_locally():
    program = run_source("""
import asyncio

async def op(res, timeout):
    try:
        await asyncio.wait_for(res.get(), timeout=timeout)
    except asyncio.TimeoutError:
        res.put_nowait("x")
""")
    results = check_wait_for(program)
    check("wait_for: 1 site found", len(results) == 1)
    check("wait_for: local handler -> structured=unsat", results[0]["structured"] == "unsat")


def test_wait_for_one_hop_resolution():
    program = run_source("""
import asyncio

async def outer(res, timeout):
    await asyncio.wait_for(inner(res), timeout=timeout)

async def inner(res):
    try:
        await res.get()
    except asyncio.CancelledError:
        res.put_nowait("x")
""")
    site = program.wait_for_sites[0]
    check("wait_for/1-hop: resolved via callee",
          site["handled_locally"] and "inner" in site["resolution"])


def test_wait_for_multi_hop_resolution():
    program = run_source("""
import asyncio

async def outer(res, timeout):
    await asyncio.wait_for(middle(res), timeout=timeout)

async def middle(res):
    await inner(res)

async def inner(res):
    try:
        await res.get()
    except asyncio.CancelledError:
        res.put_nowait("x")
""")
    site = program.wait_for_sites[0]
    check("wait_for/multi-hop: resolved through 2 hops",
          site["handled_locally"] and "inner" in site["resolution"])


def test_wait_for_genuinely_unhandled():
    program = run_source("""
import asyncio

async def op(res, timeout):
    await asyncio.wait_for(res.get(), timeout=timeout)
""")
    results = check_wait_for(program)
    check("wait_for/unhandled: structured=sat (flags the gap)",
          results[0]["structured"] == "sat")


# ------------------------------------------------------ UNRESOLVED REFS --

def test_unresolved_passed_in_lock_is_surfaced():
    program = run_source("""
import asyncio

class Worker:
    def __init__(self, lock):
        self.lock = lock
    async def run(self):
        async with self.lock:
            pass
""")
    check("unresolved: passed-in lock surfaced, not silently dropped",
          len(program.unresolved_refs) == 1 and
          program.unresolved_refs[0]["attr"] == "lock")


# ------------------------------------------------------ GENERIC_AWAIT ----

def test_generic_await_captured():
    program = run_source("""
import asyncio

async def f():
    await asyncio.sleep(1)
""")
    from ir import OpKind
    generic = [op for coro in program.coroutines.values() for op in coro.ops
               if op.kind == OpKind.GENERIC_AWAIT]
    check("generic_await: sleep() captured, not silently ignored", len(generic) == 1)


def test_wait_for_indirect_variable_resolution():
    program = run_source("""
import asyncio

async def outer(res, timeout):
    coro = inner(res)
    await asyncio.wait_for(coro, timeout=timeout)

async def inner(res):
    try:
        await res.get()
    except asyncio.CancelledError:
        res.put_nowait("x")
""")
    site = program.wait_for_sites[0]
    check("wait_for/indirect-var: resolved via variable assignment",
          site["handled_locally"] and "inner" in site["resolution"])


def test_condition_wait_for_not_treated_as_timeout_race():
    """asyncio.Condition.wait_for(predicate) is a completely different
    primitive from asyncio.wait_for(coro, timeout=...) -- must not be
    misdetected as a timeout-race site (the redis-py connection.py false
    match)."""
    program = run_source("""
import asyncio

class Pool:
    def __init__(self):
        self._condition = asyncio.Lock()

    async def get_connection(self):
        async with self._condition:
            await self._condition.wait_for(self.can_get_connection)

    def can_get_connection(self):
        return True
""")
    check("condition.wait_for: NOT recorded as a wait_for race site",
          len(program.wait_for_sites) == 0)


def test_wait_for_self_attr_task_resolution():
    """wait_for(self._drainer, ...) should resolve back to whatever
    function created self._drainer (typically assigned in __init__, a
    different function than the one containing the wait_for call) -- the
    consumer.py / quart request.py real-world shape."""
    program = run_source("""
import asyncio

class Consumer:
    def __init__(self):
        self._drainer = self._drain()

    async def _drain(self):
        try:
            await self._queue.get()
        except asyncio.CancelledError:
            self._queue.put_nowait("x")

    async def stop(self):
        await asyncio.wait_for(self._drainer, timeout=1.0)
""")
    site = program.wait_for_sites[0]
    check("wait_for/self.attr: resolved via task_refs",
          site["handled_locally"] and "_drain" in site["resolution"])


def test_smt2_export_matches_python_verdict():
    """The exported .smt2 files must independently reproduce the same
    sat/unsat verdict when run through z3, not just when called via the
    python API -- this is the whole point of exporting them."""
    import subprocess
    import shutil
    import tempfile as tf
    from encoder import check_all
    from smt2_export import export_program_smt2

    if shutil.which("z3") is None:
        check("smt2: z3 CLI not available, skipping", True)
        return

    program = run_source("""
import asyncio
mutex = asyncio.Lock()

async def worker_1():
    async with mutex:
        pass

async def worker_2():
    async with mutex:
        pass
""")
    results = check_all(program)
    with tf.TemporaryDirectory() as d:
        written = export_program_smt2(program, results, [], d, repo="t", source_file="t.py")
        check("smt2: files written", len(written) == 2)
        for path in written:
            out = subprocess.run(["z3", path], capture_output=True, text=True).stdout.strip()
            expected = "sat" if path.endswith("naive.smt2") else "unsat"
            check(f"smt2: {os.path.basename(path)} verdict matches ({expected})",
                  out == expected)


def test_nested_async_functions_not_double_counted():
    """Real bug found on benchmarks.py b6: producer/consumer are nested
    async defs inside the outer benchmark function. The top-level
    ast.walk driver used to visit them AGAIN independently, on top of
    the parent's own body traversal reaching them -- doubling every op
    inside a nested async function. Must be visited exactly once."""
    program = run_source("""
import asyncio

async def outer():
    queue = asyncio.Queue()

    async def producer():
        for i in range(4):
            await queue.put(i)

    async def consumer():
        while True:
            await queue.get()

    await producer()
    await consumer()
""", functions={"outer", "producer", "consumer"})
    put_ops = [op for op in program.coroutines["producer"].ops]
    get_ops = [op for op in program.coroutines["consumer"].ops]
    check("nested-async: producer has exactly 1 Q_PUT op (not 2)", len(put_ops) == 1)
    check("nested-async: consumer has exactly 1 Q_GET op (not 2)", len(get_ops) == 1)


def test_spawn_multiplicity_comprehension_detected():
    """[create_task(f(i)) for i in range(N)] -- a single AST call site
    representing N runtime instances -- must be detected as multiplicity
    >=2, recovering the naive/structured gap that a naive per-site count
    of 1 would miss."""
    program = run_source("""
import asyncio
event = asyncio.Event()

async def waiter(i):
    await event.wait()

async def runner():
    tasks = [asyncio.create_task(waiter(i)) for i in range(12)]
    event.set()
    await asyncio.gather(*tasks)
""")
    check("spawn-mult/comprehension: waiter multiplicity >= 2",
          program.spawn_multiplicity.get("waiter", 1) >= 2)
    results = check_all(program)
    check("spawn-mult/comprehension: gap recovered (naive=sat)",
          results["event"]["naive"] == "sat" and results["event"]["structured"] == "unsat")


def test_spawn_multiplicity_multiple_explicit_calls_detected():
    """Two separate create_task(f(...)) call sites to the SAME function
    (b6's p1/p2 shape) must sum to multiplicity 2, not stay at 1."""
    program = run_source("""
import asyncio
queue = asyncio.Queue()

async def producer(n):
    await queue.put(n)

async def runner():
    p1 = asyncio.create_task(producer(1))
    p2 = asyncio.create_task(producer(2))
    await asyncio.gather(p1, p2)
    x = await queue.get()
    y = await queue.get()
""")
    check("spawn-mult/explicit-calls: producer multiplicity == 2",
          program.spawn_multiplicity.get("producer") == 2)


def test_spawn_multiplicity_not_applied_to_single_direct_await():
    """A function that's just directly awaited once (no create_task at
    all) must stay at multiplicity 1 -- no false inflation."""
    program = run_source("""
import asyncio
lock = asyncio.Lock()

async def critical():
    async with lock:
        pass

async def runner():
    await critical()
""")
    check("spawn-mult/no-spawn: stays at multiplicity 1",
          program.spawn_multiplicity.get("critical", 1) == 1)
    results = check_all(program)
    check("spawn-mult/no-spawn: correctly no gap (naive=unsat)",
          results["lock"]["naive"] == "unsat")


def test_assume_public_concurrent_opt_in_and_propagation():
    """The --assume-public-concurrent flag (applied via
    pipeline.apply_public_concurrent_assumption) must: (1) do nothing by
    default: a private helper touching the sync object stays at
    multiplicity 1 unless explicitly requested; (2) when requested,
    propagate through a same-file call chain from a public entrypoint
    (mirroring asyncpg's public `__aenter__` -> private `_acquire` ->
    private `_acquire_impl` shape) to whichever inner function actually
    touches the sync object; (3) record the assumption separately in
    program.assumed_concurrent, never silently conflated with a
    source-detected finding."""
    import pipeline as pipeline_mod

    program = run_source("""
import asyncio
queue = asyncio.Queue()

async def _acquire_impl():
    x = await queue.get()

async def _acquire():
    await _acquire_impl()

async def public_entry():
    await _acquire()
""")
    check("assume-public: default OFF, stays at multiplicity 1",
          program.spawn_multiplicity.get("_acquire_impl", 1) == 1)

    pipeline_mod.apply_public_concurrent_assumption(program)
    check("assume-public: propagated through chain to _acquire_impl",
          program.spawn_multiplicity.get("_acquire_impl") == 2)
    check("assume-public: recorded in assumed_concurrent, not silently applied",
          "_acquire_impl" in program.assumed_concurrent)

    results = check_all(program)
    check("assume-public: gap now visible with assumption applied",
          results["queue"]["naive"] == "sat" and results["queue"]["structured"] == "unsat")


def test_bare_name_await_call_recorded_not_silently_dropped():
    """`await some_function()` (bare Name call target, not an attribute)
    used to be silently dropped entirely -- not even GENERIC_AWAIT. Must
    now be recorded, both for audit-trail completeness and because the
    public-concurrent chain-walk depends on it."""
    program = run_source("""
import asyncio

async def helper():
    await asyncio.sleep(0.1)

async def caller():
    await helper()
""")
    from ir import OpKind
    generic = [op for op in program.coroutines["caller"].ops if op.kind == OpKind.GENERIC_AWAIT]
    check("bare-name-await: recorded as GENERIC_AWAIT, not dropped",
          len(generic) == 1 and "helper" in generic[0].note)


def test_coro_name_collision_detected():
    """Limitation #9: two different classes defining a method with the
    same name are NOT fixed (Program.coroutines still merges them by bare
    name), but the collision must be DETECTED and surfaced when it's
    actually relevant (touches a sync object)."""
    program = run_source("""
import asyncio

class A:
    def __init__(self):
        self._lock = asyncio.Lock()
    async def acquire(self):
        async with self._lock:
            pass

class B:
    async def acquire(self):
        pass
""")
    check("coro-collision: detected for 'acquire' across A and B",
          "acquire" in program.coro_name_collisions and
          len(program.coro_name_collisions["acquire"]) == 2)


def test_coro_name_collision_not_flagged_for_unique_names():
    program = run_source("""
import asyncio

class A:
    async def acquire(self):
        pass

class B:
    async def release(self):
        pass
""")
    check("coro-collision: no false positive for distinct names",
          len(program.coro_name_collisions) == 0)


def test_coro_name_collision_dunder_noise_filtered():
    """__init__ (and other dunders with no sync-relevant ops) colliding
    across classes is near-universal and NOT actionable -- must be
    filtered out, not reported as a risk."""
    program = run_source("""
import asyncio

class A:
    def __init__(self):
        self.x = 1

class B:
    def __init__(self):
        self.y = 2
""")
    check("coro-collision: __init__ collision (no sync ops) filtered as noise",
          "__init__" not in program.coro_name_collisions)


def test_broadened_cleanup_verb_detected():
    """Limitation #4: verbs added beyond the original small list (e.g.
    'rollback', 'shutdown', 'unlock') must now be recognized as exact
    cleanup handlers, not just the original put_nowait/put/release/etc."""
    program = run_source("""
import asyncio

async def op(res, timeout):
    try:
        await asyncio.wait_for(res.get(), timeout=timeout)
    except asyncio.TimeoutError:
        res.rollback()
""")
    site = program.wait_for_sites[0]
    check("cleanup-broadened: 'rollback()' recognized as exact handler",
          site["handled_locally"])


def test_fuzzy_cleanup_hint_surfaced_not_silently_dropped():
    """A call that's cleanup-SHAPED (contains a fuzzy stem like 'teardown')
    but isn't an exact CLEANUP_CALL_NAMES match must NOT be silently
    treated as unhandled with no further signal -- it should surface as an
    explicit hint in the resolution text for manual review."""
    program = run_source("""
import asyncio

async def op(res, timeout):
    await asyncio.wait_for(res.get(), timeout=timeout)
    res.custom_teardown_hook()
""")
    site = program.wait_for_sites[0]
    check("cleanup-fuzzy: NOT marked handled (too imprecise to auto-confirm)",
          not site["handled_locally"])
    check("cleanup-fuzzy: hint surfaced in resolution text",
          "possible handler hint" in site["resolution"] and "custom_teardown_hook" in site["resolution"])


def test_same_coroutine_multiple_static_acquires_not_double_counted():
    """Real false-positive found via manual corpus spot-check: aiobotocore's
    credentials.py has a double-checked-locking idiom -- one function with
    TWO textually-distinct `async with self._refresh_lock:` blocks in
    mutually-exclusive if/elif branches. At most one executes per call;
    they are never concurrent with each other. Must NOT be counted as 2
    independent contenders (which would fabricate naive=sat/structured=unsat
    from a single, safe coroutine)."""
    program = run_source("""
import asyncio

class Credentials:
    def __init__(self):
        self._refresh_lock = asyncio.Lock()

    async def _refresh(self):
        if not self._refresh_lock.locked():
            async with self._refresh_lock:
                pass
        elif True:
            async with self._refresh_lock:
                pass
""")
    results = check_all(program)
    check("same-coro/dedup: only 1 real contender, no fabricated gap",
          results["Credentials._refresh_lock"]["naive"] == "unsat")


def test_same_coroutine_multiple_acquires_still_scaled_by_real_multiplicity():
    """The dedup fix must not suppress GENUINE multi-contender gaps when
    the coroutine really is spawned multiple times (detected or assumed)
    -- only the "multiple static ops in one coroutine, no real
    multiplicity" case should collapse to 1."""
    program = run_source("""
import asyncio
lock = asyncio.Lock()

async def worker():
    if True:
        async with lock:
            pass
    else:
        async with lock:
            pass

async def runner():
    tasks = [asyncio.create_task(worker()) for _ in range(4)]
""")
    results = check_all(program)
    check("same-coro/real-multiplicity: gap still detected when actually spawned N times",
          results["lock"]["naive"] == "sat" and results["lock"]["structured"] == "unsat")


def test_non_asyncio_constructors_excluded():
    """Real methodological issue found via manual corpus spot-check:
    websockets/trio/connection.py uses trio.Event(), and the extractor
    was matching it purely by short class name ("Event"), analyzing it
    as if it were asyncio.Event() and applying SNF's asyncio-scheduler-
    specific structured encoding to a primitive this pipeline was never
    validated against. Also caught threading.Lock() (seen in aioredis's
    connection.py: `self._fork_lock = threading.Lock()`) via the same
    bug. Only asyncio/compat-prefixed (or bare, unprefixed) constructor
    calls should be recognized."""
    program = run_source("""
import trio
import threading
import asyncio

class Connection:
    def __init__(self):
        self.send_in_progress = trio.Event()
        self._fork_lock = threading.Lock()
        self._real_lock = asyncio.Lock()

    async def m(self):
        async with self._real_lock:
            pass
""")
    check("trio/threading excluded: only the real asyncio.Lock recognized",
          list(program.sync_objects.keys()) == ["Connection._real_lock"])


def test_sync_def_set_release_put_nowait_detected():
    """Real false-negative found via manual corpus spot-check: Event.set()/
    Lock.release()/Queue.put_nowait() are all SYNCHRONOUS asyncio methods,
    and it's normal for them to be called from a plain `def`, most
    commonly asyncio Protocol callbacks (data_received, pause_writing,
    etc.) which asyncio always calls synchronously. The old async-only
    traversal never visited plain `def`s at all, undercounting num_sets/
    num_puts to 0 and leaving the naive/structured divergence
    unconstrained -- producing a spurious both-sat result on real code
    (aiosonic's Http2Handler._window_updated, sanic's SanicProtocol's
    write-pause/data-received callbacks)."""
    program = run_source("""
import asyncio

class Handler:
    def __init__(self):
        self._updated = asyncio.Event()

    async def wait_for_it(self):
        self._updated.clear()
        await self._updated.wait()

    def on_updated(self) -> None:
        self._updated.set()
""")
    results = check_all(program)
    check("sync-def/EV_SET: detected from plain def, gap correctly resolved",
          results["Handler._updated"]["naive"] == "sat" and
          results["Handler._updated"]["structured"] == "unsat")


def test_sync_def_does_not_emit_await_requiring_ops():
    """ACQUIRE/Q_GET/EV_WAIT/wait_for genuinely require `await`, which is
    a SyntaxError outside `async def` -- a plain def must never emit
    these even if (erroneously) written to call e.g. `.acquire()` without
    awaiting it, since that discards the coroutine object without ever
    running it (a bug in the target code, not real synchronization)."""
    program = run_source("""
import asyncio

class Handler:
    def __init__(self):
        self._lock = asyncio.Lock()

    def broken_sync_method(self):
        self._lock.acquire()  # bug in target code: never awaited
""")
    from ir import OpKind
    ops = program.coroutines["broken_sync_method"].ops
    check("sync-def: no ACQUIRE emitted from a plain def",
          not any(op.kind == OpKind.ACQUIRE for op in ops))


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()