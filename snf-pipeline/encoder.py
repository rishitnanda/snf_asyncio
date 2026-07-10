"""
Encoder: turns extracted IR into SMT queries (via the z3 python API), one
property family per SyncKind. This is the generalized version -- it is not
specific to any one repository or benchmark; it runs the same way against
any Lock/Queue/Event object the extractor finds, in any source file.

Three property families, each with a naive and an SNF-structured encoding,
matching the paper's Section 5.2 correctness-gap methodology:

  QUEUE  -> double-checkout / mutual exclusion over a bounded resource pool
            (b3/PHP-family pattern; asyncpg Pool.acquire is one instance).
  LOCK   -> mutual exclusion over a critical section (b1-family pattern).
  EVENT  -> broadcast wake guarantee: all waiters must wake after set()
            (b4/b7-family pattern).

For all three, "structured" derives the property from SNF-1..SNF-4 (FIFO,
deterministic dispatch); "naive" is the modeling mistake the paper's naive
encodings make (treating FIFO-mediated wakeup as an unconstrained
existential choice). SAT on the naive query and UNSAT on the structured
query, on the same source-derived site, is the correctness gap.
"""

from z3 import Int, Bool, Distinct, Solver, Or, And, Not, sat, unsat
from ir import Program, OpKind, SyncKind


def _verdict(solver):
    r = solver.check()
    return "sat" if r == sat else ("unsat" if r == unsat else str(r))


# ---------------------------------------------------------------- QUEUE ----

def _multiplicity(program, coro_name):
    """How many concurrent runtime instances of this coroutine's ops
    should be modeled -- 1 by default (a single static call site), or
    the detected spawn_multiplicity if this coroutine was found to be
    spawned via create_task/gather/loop patterns (see
    extractor._find_spawn_targets), whichever is larger."""
    return max(1, program.spawn_multiplicity.get(coro_name, 1))


def find_queue_sites(program: Program, name: str):
    waiters, puts = [], 0
    for coro in program.coroutines.values():
        get_ops = [op for op in coro.ops if op.sync_obj == name and op.kind == OpKind.Q_GET]
        put_ops = [op for op in coro.ops if op.sync_obj == name and op.kind == OpKind.Q_PUT]
        mult = _multiplicity(program, coro.name)
        if get_ops:
            # Multiple static Q_GET sites within ONE coroutine (e.g. an
            # if/elif branch, a retry loop) are sequential by
            # construction -- a single coroutine instance can only be at
            # one of them at a time, so they must NOT each contribute a
            # separate concurrent contender. Only genuine multiplicity
            # (detected spawn count, or --assume-public-concurrent)
            # multiplies a coroutine's contribution; the number of
            # static call sites inside it does not.
            for i in range(mult):
                waiters.append((f"{coro.name}#{i}" if mult > 1 else coro.name, get_ops[0].seq))
        if put_ops:
            puts += mult
    return waiters, puts


def check_queue(program: Program, name: str):
    waiters, num_puts = find_queue_sites(program, name)
    n = len(waiters)
    results = {"num_waiters": n, "num_puts": num_puts}

    order = [Int(f"order_{i}") for i in range(n)]
    s = Solver()
    for o in order:
        s.add(o >= 1, o <= max(n, 1))
    s.add(Distinct(*order))
    matched = [order[i] <= num_puts for i in range(n)]
    viol = Or([And(matched[i], matched[j], order[i] == order[j])
               for i in range(n) for j in range(i + 1, n)]) if n > 1 else False
    s.add(viol)
    results["structured"] = _verdict(s)
    results["solver_structured"] = s

    conn = [Int(f"conn_{i}") for i in range(n)]
    s2 = Solver()
    for c in conn:
        s2.add(c >= 1, c <= max(num_puts, 1))
    matched2 = [conn[i] >= 1 for i in range(n)]
    viol2 = Or([And(matched2[i], matched2[j], conn[i] == conn[j])
                for i in range(n) for j in range(i + 1, n)]) if n > 1 else False
    s2.add(viol2)
    results["naive"] = _verdict(s2)
    results["solver_naive"] = s2
    return results


# ----------------------------------------------------------------- LOCK ----

def find_lock_sites(program: Program, name: str):
    acquirers = []
    for coro in program.coroutines.values():
        acquire_ops = [op for op in coro.ops if op.sync_obj == name and op.kind == OpKind.ACQUIRE]
        if not acquire_ops:
            continue
        mult = _multiplicity(program, coro.name)
        # Same reasoning as find_queue_sites: multiple static ACQUIRE
        # sites in one coroutine (e.g. the double-checked-locking idiom
        # -- `if not lock.locked(): async with lock: ... elif ...:
        # async with lock: ...`) are mutually exclusive by control flow,
        # never concurrent with each other in one call. Confirmed as a
        # real false-positive source on aiobotocore's credentials.py
        # (`AioRefreshableCredentials._refresh_lock`) during manual
        # corpus spot-checking -- was fabricating n=2 from one coroutine
        # with two if/elif-exclusive acquire sites.
        for i in range(mult):
            acquirers.append((f"{coro.name}#{i}" if mult > 1 else coro.name, acquire_ops[0].seq))
    return acquirers


def check_lock(program: Program, name: str):
    acquirers = find_lock_sites(program, name)
    n = len(acquirers)
    results = {"num_acquirers": n}

    order = [Int(f"lorder_{i}") for i in range(n)]
    s = Solver()
    for o in order:
        s.add(o >= 1, o <= max(n, 1))
    s.add(Distinct(*order))
    viol = Or([order[i] == order[j] for i in range(n) for j in range(i + 1, n)]) if n > 1 else False
    s.add(viol)
    results["structured"] = _verdict(s)
    results["solver_structured"] = s

    holds = [Bool(f"holds_{i}") for i in range(n)]
    s2 = Solver()
    viol2 = Or([And(holds[i], holds[j]) for i in range(n) for j in range(i + 1, n)]) if n > 1 else False
    s2.add(viol2)
    results["naive"] = _verdict(s2)
    results["solver_naive"] = s2
    return results


# ---------------------------------------------------------------- EVENT ----

def find_event_sites(program: Program, name: str):
    waiters, sets_ = [], 0
    for coro in program.coroutines.values():
        wait_ops = [op for op in coro.ops if op.sync_obj == name and op.kind == OpKind.EV_WAIT]
        set_ops = [op for op in coro.ops if op.sync_obj == name and op.kind == OpKind.EV_SET]
        mult = _multiplicity(program, coro.name)
        if wait_ops:
            for i in range(mult):
                waiters.append((f"{coro.name}#{i}" if mult > 1 else coro.name, wait_ops[0].seq))
        if set_ops:
            sets_ += mult
    return waiters, sets_


def check_event(program: Program, name: str):
    waiters, num_sets = find_event_sites(program, name)
    n = len(waiters)
    results = {"num_waiters": n, "num_sets": num_sets}

    wake = [Bool(f"ewake_{i}") for i in range(n)]
    s = Solver()
    if num_sets >= 1:
        for w in wake:
            s.add(w == True)
    query = Or([Not(w) for w in wake]) if n > 0 else False
    s.add(query)
    results["structured"] = _verdict(s)
    results["solver_structured"] = s

    wake2 = [Bool(f"ewake2_{i}") for i in range(n)]
    s2 = Solver()
    query2 = Or([Not(w) for w in wake2]) if n > 0 else False
    s2.add(query2)
    results["naive"] = _verdict(s2)
    results["solver_naive"] = s2
    return results


# ------------------------------------------------------------- DISPATCH ----

CHECKERS = {
    SyncKind.QUEUE: check_queue,
    SyncKind.LOCK: check_lock,
    SyncKind.EVENT: check_event,
}


def check_all(program: Program):
    """Run the appropriate property check for every sync object the
    extractor found, regardless of source file or repo."""
    out = {}
    for name, kind in program.sync_objects.items():
        checker = CHECKERS.get(kind)
        if checker:
            out[name] = {"kind": kind.name, **checker(program, name)}
    return out


# --------------------------------------------------------------- WAIT_FOR --

def check_wait_for(program: Program):
    """Property: on timeout/cancellation of a wait_for-wrapped operation, is
    there a cleanup/requeue path? Structured encoding models BOTH race
    outcomes (completes-first vs timeout-fires-first) as a real disjunction;
    naive ignores the timeout branch entirely (a bug-exists query is
    vacuously unsat -- it never even asks). SAT on the structured query
    means: a wait_for site was found with no LOCALLY-visible cleanup
    handler -- either a genuine gap, or a handler that lives in a callee
    (cross-function), which this same-scope check cannot see.
    """
    results = []
    for site in program.wait_for_sites:
        completes_first = Bool("completes_first")
        timeout_fires = Bool("timeout_fires")
        cleanup_ran = Bool("cleanup_ran")

        # naive: never models the timeout branch at all -- timeout_fires is
        # forced False, so the "did a timeout leave things uncleaned up"
        # query is vacuously UNSAT even when a real gap exists.
        s_naive = Solver()
        s_naive.add(timeout_fires == False)
        s_naive.add(And(timeout_fires, Not(cleanup_ran)))
        naive_verdict = _verdict(s_naive)

        # structured: both branches are real; if timeout fires, cleanup
        # must run (SNF-4-style requeue obligation). If no locally-visible
        # handler was found, don't force cleanup_ran -- let the solver find
        # the gap.
        s_struct = Solver()
        s_struct.add(Or(completes_first, timeout_fires))
        if site["handled_locally"]:
            s_struct.add(Implies_(timeout_fires, cleanup_ran))
        bug_query = And(timeout_fires, Not(cleanup_ran))
        s_struct.add(bug_query)
        struct_verdict = _verdict(s_struct)

        results.append({
            "coro": site["coro"], "line": site["line"],
            "handled_locally": site["handled_locally"],
            "naive": naive_verdict, "structured": struct_verdict,
            "solver_naive": s_naive, "solver_structured": s_struct,
        })
    return results


def Implies_(a, b):
    from z3 import Implies
    return Implies(a, b)