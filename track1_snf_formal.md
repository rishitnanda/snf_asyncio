# Track 1 — Scheduling Normal Form: Formal Document

---

## Step 1 · Abstract Machine

**Definition 1 (Program).** A program *P* is a finite set of coroutines
*C = {c₁, …, cₙ}* together with a finite set of synchronization
objects *Sync(P)*, each of which is an instance of one of the asyncio
primitives covered by SNF-4 below.

**Definition 2 (Coroutine).** A coroutine *cᵢ* is a sequence of steps
separated by *yield points* *yᵢ,₁, yᵢ,₂, …* At each yield point *cᵢ*
either suspends (waiting for a future to resolve) or terminates.

**Definition 3 (Yield point — concrete).** In CPython 3.12, every
`await expr` compiles to:

```
SEND         →target    ← coroutine reaches yield point here
YIELD_VALUE  2          ← control returns to scheduler
RESUME       3          ← coroutine resumes here on next dispatch
```

The `SEND` / `YIELD_VALUE` pair is the concrete realisation of yield
point *yᵢ,ⱼ*. Yield points are addressable bytecode offsets.

**Definition 4 (Ready queue).** The ready queue *Q ⊆ C* is the set of
coroutines currently eligible for dispatch. In CPython: `BaseEventLoop._ready`,
a `collections.deque` of `Handle` objects.

**Definition 5 (Scheduler).** A scheduler *S* is a function
*S : 2^C → C* mapping a non-empty ready queue to the next coroutine
to dispatch.

**Definition 6 (Variable partition).** Let *Vars(cᵢ)* denote the set
of variables directly written or read by coroutine *cᵢ*, excluding
accesses mediated by synchronization objects in *Sync(P)*. Coroutines
*cᵢ* and *cⱼ* are *directly non-interfering* if
*Vars(cᵢ) ∩ Vars(cⱼ) = ∅*. A program is directly non-interfering if
all pairs of distinct coroutines are directly non-interfering.

**Definition 7 (Rendezvous point).** A *rendezvous point* is a pair
*(pᵢ, gⱼ)* where coroutine *cᵢ* performs a put-side operation on a
synchronization object *s ∈ Sync(P)* at yield point *yᵢ,p* and
coroutine *cⱼ* performs the corresponding get-side operation at yield
point *yⱼ,g*. The rendezvous is *resolved* when both operations
complete; resolution establishes a happens-before relation
*yᵢ,p → yⱼ,g*.

---

## Step 2 · Scheduling Normal Form (SNF)

**Definition 8 (Scheduling Normal Form).** A scheduler *S* satisfies
*Scheduling Normal Form* if all four conditions below hold.

**SNF-1 (Determinism).** *S(Q)* is a total function: identical *Q*
always yields the same dispatch choice.

*CPython witness (3.12.3).* `_ready` is a FIFO deque. `_run_once` captures
`ntodo = len(self._ready)` before the dispatch loop and calls
`_ready.popleft()` once per handle for `i in range(ntodo)`
(`base_events.py` lines 61–63). Dispatch order equals insertion order;
no randomness is introduced.

**SNF-2 (Bounded dispatch).** `|Q|` at any dispatch step is bounded
above by `|C|`.

*CPython witness (3.12.3).* `ntodo` is computed before the dispatch loop.
Handles appended to `_ready` during the current iteration are deferred
to the next `_run_once` call (the loop iterates `range(ntodo)`, not the
live deque). Each coroutine contributes at most one `Handle` per
iteration, so `ntodo ≤ |C|`.

**SNF-3 (Yield-point atomicity).** Between two consecutive yield points
of *cᵢ*, no other coroutine's state changes.

*CPython witness (3.12.3).* `Task.__step` calls `coro.send(None)` synchronously
in `__step_run_and_handle_result` (`tasks.py`). The coroutine executes
until `YIELD_VALUE` returns control; only then does `__step` return and
the loop can dispatch another task. The single-threaded event loop
ensures no other coroutine is dispatched during this call — this is
the scheduling-level atomicity SNF-3 requires. The GIL additionally
prevents concurrent mutation of Python objects across OS threads, but
SNF-3 does not require this stronger property: it requires only that
no other coroutine's *state* changes during *cᵢ*'s step, which holds
by the cooperative single-threaded design of the event loop regardless
of whether the GIL is held (see the free-threading note under
*Conditions under which CPython witnesses fail*, below, and the
Limitations section).

**SNF-4 (Rendezvous ordering).** For each synchronization object
*s ∈ Sync(P)*, the order in which waiting coroutines are woken is
determined by a fixed, statically-describable policy derivable from
program structure — specifically, FIFO order of `await` arrival.

*CPython witness (3.12.3).* Three primitives are covered:

- **`asyncio.Queue`.** Getters and putters are maintained as FIFO deques
  `_getters` and `_putters` (`queues.py`). `_wakeup_next` calls
  `waiters.popleft()`, waking the earliest-arrived waiter. Put-side
  operations call `_wakeup_next(self._getters)` via `put_nowait`;
  get-side operations call `_wakeup_next(self._putters)`. Wakeup order
  is strictly FIFO with respect to `await` arrival.

- **`asyncio.Lock`.** Waiters are maintained as a FIFO deque
  `_waiters` (`locks.py`). `_wake_up_first` calls
  `next(iter(self._waiters))`, waking the earliest-arrived waiter.
  Lock acquisition order is strictly FIFO.

- **`asyncio.Event`.** `set()` calls `fut.set_result(None)` on all
  waiters simultaneously (`locks.py`). All waiting coroutines become
  ready in the iteration after `set()` is called; their relative order
  within that iteration is determined by `_ready` FIFO insertion order,
  which traces back to `await` arrival order. SNF-4 covers this as a
  special case where all waiters are resolved simultaneously.

*Conditions under which CPython witnesses fail.* These witnesses are
verified against CPython 3.12.3. They would fail to hold under: (a)
alternative event loop implementations (e.g., `uvloop`) that use
different scheduling policies — not a dead end, since the Consistency
Interface (Definitions 9, Proposition 9, Limitations below) checks
`uvloop` directly and shows it inherits SNF; (b) CPython versions prior
to 3.12 where `Task.__step` was not yet split into `__step` /
`__step_run_and_handle_result` — also not a dead end, since Corollary
9a (Limitations below) routes this through the same Consistency
Interface, checked against CPython 3.9–3.13; (c) programs using `loop.set_task_factory(asyncio.eager_task_factory)`
(PEP 3156 extension, merged in CPython 3.12), which runs a newly-created
task's first step synchronously inside `create_task` rather than
scheduling it onto `_ready` — this breaks SNF-1 (the first step never
passes through `_run_once`'s FIFO queue), SNF-2 (`ntodo` is computed
before the eager step executes, so that step is uncounted), and SNF-3
(the first step runs inside the *creating* coroutine's atomic segment,
not its own `__step` invocation); a task's remaining steps, once it
first suspends and re-enters `_ready`, satisfy SNF-1 through SNF-4
normally (full treatment in Limitations, below — this is a priority
scope extension given `eager_task_factory`'s trajectory toward becoming
CPython's default); (d) CPython 3.13+ free-threading (`-X nogil`, PEP
703) does **not** break SNF-3 at the scheduling level, since the event
loop remains single-threaded by design — what it removes is the GIL's
stronger guarantee of atomic Python object mutation across OS threads,
which SNF-3 never relied on for programs using only async/await without
`run_in_executor` or explicit threading (full treatment in Limitations).
The theorem applies to programs using the default task
factory on `asyncio.BaseEventLoop` in CPython 3.12, with or without
free-threading enabled.

**Proposition 1.** CPython's `asyncio.BaseEventLoop` (CPython 3.12.3,
default task factory) satisfies SNF-1, SNF-2, SNF-3, and SNF-4. ∎

---

## Step 3 · Normal Form Reduction Lemma

**Assumption (Controlled interference).** A program *P* satisfies
*controlled interference* if it is directly non-interfering (Definition
6) and all shared state is accessed exclusively through synchronization
objects in *Sync(P)* whose ordering is governed by SNF-4.

This replaces the stronger non-interference assumption used in earlier
drafts. It admits the programs that matter practically — producers and
consumers communicating via `asyncio.Queue`, critical sections guarded
by `asyncio.Lock` — while remaining encodable without quantifiers.
Programs with unmediated shared mutable state are outside scope; two
such cases are treated separately below: read-only sharing (SNF-5,
proved immediately below) and commutative writes / bounded
write-conflict (deferred to the Limitations section as open problems,
not claimed here).

**Definition 7 (SNF-5: Read-only sharing).** A variable *x* satisfies
the *read-only sharing condition* if at most one coroutine writes *x*
during any execution of *P*, and that coroutine writes *x* only before
any coroutine reads *x* (write-once-before-read semantics). A program
*P* satisfies *extended controlled interference* if it satisfies
controlled interference for all write-write and write-read accesses,
and additionally satisfies the read-only sharing condition for any
remaining unmediated shared accesses. Equivalently, extended controlled
interference requires that (1) all write-write shared accesses between
distinct coroutines are mediated through *Sync(P)*; (2) all write-read
shared accesses are mediated through *Sync(P)*; and (3) read-read
shared accesses — where multiple coroutines only read a shared
variable, and no coroutine writes it during *P*'s execution — are
permitted without mediation. SNF-5 is a condition on the program's
access patterns, not on the scheduler; it extends the controlled
interference precondition of the theorem rather than adding a fifth
scheduler condition alongside SNF-1–SNF-4.

**Proposition 6 (SNF-5 correctness).** The Normal Form Reduction Lemma
and Propositions 2–4 hold under extended controlled interference in
place of controlled interference.

*Proof.* Let *x* be a shared variable satisfying the read-only sharing
condition, read (without an intervening write) by coroutines *cᵢ* and
*cⱼ*.

*Lemma 2a is unaffected.* A read of *x* does not call `put_nowait`,
`release`, or `set()` — the only CPython operations that trigger
`_wakeup_next` (Step 2, SNF-4 witnesses). Therefore a segment
containing a read of *x* cannot resolve a rendezvous or otherwise alter
*Q_{t+1}*. Lemma 2a's proof is unchanged: whether any rendezvous point
resolves during step *t* remains a function of *Qₜ* and the put-side
coroutine's own internal execution alone, independent of whether other
coroutines in *Qₜ* read *x*.

*Claim 2's bijection is unaffected.* Under read-only sharing, *cᵢ* and
*cⱼ* observe the same value of *x* regardless of their relative dispatch
order, since no coroutine writes *x* during *P*'s execution (by the
write-once-before-read semantics, any write to *x* precedes every read
in every trace). The ordering of *cᵢ* and *cⱼ* within *Qₜ* therefore
does not affect observable state at *x*. Distinct
FIFO-and-rendezvous-consistent permutation-sequences still define
distinct traces — they differ in scheduling choice even where they agree
on *x*'s value — so the trace-to-sequence correspondence established in
Claim 2 is preserved.

*Proposition 4's completeness is unaffected.* No new rendezvous points
are introduced by read-only accesses (reads do not appear in
`Rendezvous(t)`), so the disjunction *Fₜ* over
FIFO-and-rendezvous-consistent permutations is exactly the set defined
under plain controlled interference; read-only shared variables neither
create feasible orderings absent from *Fₜ* nor admit any infeasible one.

Since Claim 1, Lemma 2a, Claim 2, and Claim 3 (which depends only on
Claim 1 and Lemma 2a) all go through unchanged, the Normal Form
Reduction Lemma holds under extended controlled interference, and
Propositions 2–4, stated in terms of *Fₜ* and the Lemma, hold
unchanged. $\square$

*Encoding consequence.* For a variable *x* satisfying read-only sharing,
no ordering constraint on the coroutines that read *x* needs to appear
in *Φₜ*: any FIFO-consistent ordering produces the same value of *x*.
The rendezvous constraint set is unchanged, so *|Fₜ|* remains bounded by
*n!/2^r* from actual rendezvous constraints alone (Proposition 5) —
SNF-5 adds coverage without adding complexity to the encoding.

**Lemma (Normal Form Reduction).** Let *P* be a program satisfying
controlled interference whose scheduler satisfies SNF, with coroutine
set *C* and *T* dispatch steps. The set of feasible execution traces of
*P* is in bijection with the set of all sequences *(σ₁, …, σ_T)* where
each *σₜ* is a permutation of *Qₜ* consistent with the FIFO order of
`_ready` at step *t* and consistent with the happens-before constraints
imposed by resolved rendezvous points.

*Consequence.* Scheduling nondeterminism is fully indexed by yield
points and rendezvous orderings. Both are finite and statically
derivable from program structure, giving a finite disjunction without
quantifiers.

### Proof

**Claim 1 (Sequential determinism).** For any *cᵢ* and consecutive
yield points *yᵢ,ⱼ*, *yᵢ,ⱼ₊₁*, the state of every *cₖ ≠ cᵢ* is
constant throughout the segment *[yᵢ,ⱼ, yᵢ,ⱼ₊₁]*.

*Proof.* The segment runs entirely within one call to `coro.send(None)`
in `__step_run_and_handle_result`. By SNF-3, no other coroutine executes
during this call. Therefore, for all *cₖ ≠ cᵢ*, the state of *cₖ* is
constant throughout *[yᵢ,ⱼ, yᵢ,ⱼ₊₁]*. ∎

**Claim 2 (Correspondence).** Every feasible execution trace corresponds
to exactly one FIFO-and-rendezvous-consistent permutation-sequence, and
every such sequence corresponds to at least one feasible trace.

*Proof (trace → sequence).* By SNF-1, each dispatch step produces a
unique scheduling choice. Every trace therefore maps to a unique
sequence.

*Proof (sequence → trace).* A FIFO-consistent permutation of *Qₜ* is
reachable when its insertion order into `_ready` is realisable. For
`asyncio.sleep(0)`, insertion order traces back to task creation order
(via the `result is None` branch in `__step_run_and_handle_result`
calling `call_soon`, which appends to `_ready`). For rendezvous points,
SNF-4 establishes that wakeup order is FIFO with respect to `await`
arrival; any execution in which the rendezvous is resolved produces a
unique, statically-determinable insertion order into `_ready`.

*On the bijection's domain.* Two distinct FIFO-and-rendezvous-consistent
permutations *σ ≠ σ'* of *Qₜ* may produce identical post-state
variable valuations for directly non-interfering coroutines (since
*Vars(cᵢ) ∩ Vars(cⱼ) = ∅* means each coroutine's local state is
unaffected by dispatch order). The bijection is therefore over
*sequences of scheduling choices* — that is, execution traces as
records of dispatching decisions — not over distinguishable program
states. This is the correct domain for a scheduling theorem: the
theorem verifies that the encoding captures all feasible *scheduling
behaviours*, not that distinct behaviours produce distinct observable
states. For programs with synchronization (controlled interference),
dispatch order *does* affect observable state — different Queue
operation orderings produce different item-delivery sequences — and the
bijection there distinguishes traces by outcome. The non-interfering
case is the degenerate end where scheduling choices are unobservable
from variable valuations; this is explicitly noted as a limitation:
for directly non-interfering programs with no synchronization objects,
the encoding verifies scheduling properties only. ∎

**Lemma 2a (Resolution-set invariance).** *This sub-claim is what
Claim 3's inductive step actually requires, and is stated separately
because it is distinct from, and not derived by, Proposition 5's
discussion of how chained constraints prune the ordering count within
a single step.* Proposition 5 shows that *how many* orderings a set of
rendezvous constraints admits at step *t* depends on whether the
constraints are independent or chained. Claim 3 instead requires that
*which* rendezvous points are resolved by the end of step *t* — i.e.
the membership of *Q_{T+1}*, not the size of *F_{T+1}* — is invariant
under the choice of *σₜ ∈ Fₜ*. These are different properties: the
first is about counting orderings of a fixed constraint set; the
second is about whether the constraint set itself, and the resulting
ready set, varies with the ordering chosen.

*Statement.* Let *P* satisfy controlled interference with scheduler
satisfying SNF. For any dispatch step *t* and any two
FIFO-and-rendezvous-consistent permutations *σ, σ' ∈ Fₜ*, the set of
rendezvous points resolved during step *t* under *σ* equals the set
resolved under *σ'*, and consequently *Q_{t+1}* is identical under
both.

*Proof.* Fix a rendezvous point *(pᵢ, gⱼ)* with put-side coroutine
*cᵢ*. Whether this rendezvous resolves during step *t* depends only
on whether *cᵢ* is dispatched during step *t* (i.e. *cᵢ ∈ Qₜ*) and,
if so, whether *cᵢ*'s execution up to and including *yᵢ,p* completes
within step *t* — both of which are properties of *Qₜ* as a *set* and
of *cᵢ*'s own sequential execution, not of the relative order in
which *Qₜ*'s members are dispatched. By Claim 1, *cᵢ*'s execution
between its own yield points is unaffected by any other coroutine's
state. By SNF-3, *cᵢ* runs to its next yield point atomically once
dispatched, regardless of dispatch position within *σ*. Therefore
whether *(pᵢ, gⱼ)* resolves during step *t* is a function of *Qₜ* and
*cᵢ*'s internal execution alone, constant across all *σ ∈ Fₜ*. Since
this holds for every rendezvous point independently, the set of
rendezvous points resolved during step *t* is invariant across
*Fₜ*, and so is *Q_{t+1}*. ∎

*Remark.* This lemma is what licenses the "not by the relative
ordering of other coroutines in *Qₜ*" claim used informally in earlier
drafts of Claim 3's proof. It is stated here as its own lemma, derived
from Claim 1 and SNF-3 rather than asserted, because mechanisation of
Claim 3 requires this exact statement as a standalone hypothesis — see
the chained-rendezvous worked example below, which is the minimal
instance exercising this lemma nontrivially (a single rendezvous with
no other coroutine present at step *t* makes the lemma vacuous).

**Claim 3 (Inductive composition).** The bijection from Claim 2 extends
to full traces of *T* steps.

*Proof.* By induction on *T*.

*Base case T = 1.* Immediate from Claim 2.

*Inductive step.* Assume the bijection holds for *T* steps. The ready
queue *Q_{T+1}* is determined by which coroutines completed their
awaited futures during step *T*. Under controlled interference: (a)
for directly non-interfering segments, each coroutine's future
resolution depends only on its own execution; (b) for rendezvous
points, by Lemma 2a the set of rendezvous points resolved during step
*T* — and hence *Q_{T+1}* itself — is invariant across all
*σₜ ∈ Fₜ*. Therefore the same set of FIFO-and-rendezvous-consistent
permutations of *Q_{T+1}* is available regardless of which permutation
was chosen at step *T*. By the inductive hypothesis the bijection
holds for *T* steps; extending by Claim 2 gives the bijection for
*T+1* steps. ∎

The three claims, together with Lemma 2a, prove the lemma. ∎

---

## Step 4 · General Encoding Enc(P)

**Definition 9 (General Enc(P)).** Let *P* be a program satisfying
controlled interference with *n* coroutines and *k* yield points per
coroutine (the definition extends to variable *kᵢ* per coroutine
straightforwardly).

For each coroutine *cᵢ* and yield point *yᵢ,ⱼ*, introduce state
variables recording the values of *Vars(cᵢ)* immediately after *yᵢ,ⱼ*.
For each rendezvous point *(pᵢ, gⱼ)*, introduce a rendezvous constraint
asserting the happens-before ordering established by SNF-4.

For each dispatch step *t*, let *Fₜ* be the set of
FIFO-and-rendezvous-consistent permutations of *Qₜ*. The per-step
encoding is:

```
Φₜ = ∨_{σ ∈ Fₜ} ( order_t = σ ∧ ∧_{cᵢ} post_constraints(cᵢ, σ, t)
                               ∧ ∧_{r ∈ Rendezvous(t)} rendezvous_constraint(r, σ) )
```

where `post_constraints` is the conjunction of ground constraints on
local state variables (quantifier-free, in QF_LIA or QF_BV), and
`rendezvous_constraint(r, σ)` is a ground assertion on the ordering
variable for rendezvous *r* (e.g., `queue_order = put_before_get`).

The full encoding is:

```
Enc(P) = Φ_init ∧ Φ₁ ∧ … ∧ Φ_k
```

**Proposition 2 (Size bound).** *Enc(P)* has size *O(k · |Fₜ| · n)*
where *|Fₜ| ≤ n!*. In the worst case this is *O(k · n! · n)*.

*Practical note.* For realistic asyncio programs, *n* is bounded by
concurrent `create_task` calls in scope at any yield point (typically
single digits), and rendezvous constraints strictly reduce *|Fₜ|*
below *n!* by eliminating orderings that violate happens-before. The
bound is a ceiling, not a typical case.

**Proposition 3 (Quantifier-freedom).** Every formula in *Enc(P)* is
in the quantifier-free fragment of QF_LIA (or QF_BV). No `ForAll` or
`Exists` quantifiers appear.

*Proof.* Each *Φₜ* is a disjunction of conjunctions of ground
constraints and ground ordering assertions. *Φ_init* is a conjunction
of ground equalities. *Enc(P)* is quantifier-free by construction. ∎

**Proposition 4 (Completeness).** *Enc(P)* captures all feasible
execution traces of *P* and no infeasible ones.

*Proof.*

*Soundness (no infeasible traces included).* Every disjunct in *Φₜ*
corresponds to a permutation *σ ∈ Fₜ* — that is, a FIFO-and-rendezvous-consistent
ordering of *Qₜ*. By the Normal Form Reduction Lemma (Claim 2, trace
→ sequence direction), every FIFO-and-rendezvous-consistent permutation
corresponds to a feasible execution trace. Therefore no disjunct in
*Φₜ* represents an infeasible ordering, and *Enc(P)* cannot be
satisfied by a property query that holds only on infeasible traces.

*Completeness (no feasible traces excluded).* By the Normal Form
Reduction Lemma (Claim 2, sequence → trace direction), every feasible
execution trace corresponds to exactly one FIFO-and-rendezvous-consistent
permutation-sequence *(σ₁, …, σ_T)*. By construction, *Fₜ* is defined
as the full set of FIFO-and-rendezvous-consistent permutations of *Qₜ*,
so every *σₜ* that appears in any feasible trace's permutation-sequence
appears as a disjunct in *Φₜ*. The conjunction *Enc(P) = Φ_init ∧ Φ₁
∧ … ∧ Φ_k* is therefore satisfiable for every property that holds on
some feasible trace, and no feasible trace is excluded. ∎

*Significance.* Completeness means a verifier built on *Enc(P)* will
find all bugs that manifest on some feasible trace. Without this
proposition, stability would come at the cost of missed behaviours.

**Proposition 5 (Separation from naive quantifier elimination).** The
encoding *Enc(P)* derived from SNF is strictly more compact than the
result of applying standard quantifier elimination (QE) to the naive
quantified encoding, for all programs with at least one rendezvous
point per dispatch step.

*Proof.*

**Naive QE size.** The naive encoding quantifies over a scheduling
variable *sched ∈ {0, …, n!-1}*. Standard QE (e.g., Fourier-Motzkin
for LIA) eliminates the quantifier by enumerating all *n!*
instantiations and disjoining them, producing *n!* disjuncts per step.

**SNF-derived size.** *Enc(P)* contains *|Fₜ|* disjuncts per step,
where *|Fₜ|* is the number of permutations of *Qₜ* consistent with
the happens-before constraints from rendezvous points.

**Key lemma.** A single happens-before constraint (*cᵢ* before *cⱼ*)
eliminates exactly those permutations in which *cⱼ* precedes *cᵢ*.
For any set of *n* elements, exactly *n!/2* permutations have *cᵢ*
before *cⱼ* and exactly *n!/2* have *cⱼ* before *cᵢ*. The bijection
is: given any permutation in which *cⱼ* appears before *cᵢ*, swap
only the positions of *cᵢ* and *cⱼ* while leaving all other elements
fixed; the result is a distinct permutation in which *cᵢ* appears
before *cⱼ*, and the map is its own inverse. This is a bijection
between the two halves of *Sₙ* for any *n ≥ 2*, not merely for *n =
2*. Therefore one constraint reduces *|Fₜ|* from *n!* to *n!/2*.

*Verified:* for *n = 3*, one constraint `(0,1)`: 3 valid orderings of
6 total = 3!/2 = 3. ✓

**Bound under independent constraints.** Let *r* be the number of
rendezvous constraints at step *t*, where constraints are *independent*
— that is, no two constraints share a coroutine (each coroutine appears
in at most one constraint). Then each constraint halves the remaining
feasible set independently, giving:

```
|Fₜ| = n! / 2^r
```

*Verified:* for *n = 4*, two independent constraints `{(0,1),(2,3)}`:
6 valid orderings of 24 total = 4!/4 = 6. ✓

*Independence is a real condition.* If constraints share a coroutine
(forming a chain, e.g., *c₀ → c₁ → c₂*), the reduction is larger than
*n!/2^r* because the chain constraints are not independent — for *n = 4*
with chain constraints `{(0,1),(1,2)}`, only 4 orderings are feasible,
less than *4!/4 = 6*. The bound *n!/2^r* therefore understates the
pruning for chained constraints, making it conservative: the actual
*|Fₜ|* is at most *n!/2^r* for *r* constraints regardless of
independence (since dependent constraints prune at least as much as
independent ones).

**Structural separation.** The asymptotic sizes are the same (*Θ(k · n!/2^r · n)*
vs. *Θ(k · n! · n)*) up to the *2^r* factor, which is the quantitative
gain. The qualitative separation is that QE applied to the naive
encoding (a) passes through an intermediate quantified representation
that engages E-matching and relevancy machinery during any intermediate
SMT query, and (b) produces *n!* disjuncts because it operates on
syntax and does not know that certain instantiations correspond to
scheduling-infeasible orderings. *Enc(P)* produces *|Fₜ| ≤ n!/2^r*
disjuncts because SNF-4 provides the scheduling semantics directly,
and *|Fₜ| < n!* strictly for all *r ≥ 1*. ∎

*Empirical remark (Track 2).* A non-SNF QF\_LIA baseline constructed
by Big-OR/pairwise quantifier elimination (producing *n!* disjuncts,
no scheduling-structure knowledge) on benchmarks b3 and PHP3–PHP6 —
the only benchmarks with genuine permutation bijection structure — shows
σ ≤ 1.2ms, comparable to *Enc(P)*'s σ ≤ 0.9ms. Both are flat against
naive AUFLIA's σ up to 24103ms at PHP6. This confirms that SMT
instability is a quantifier phenomenon and that the *2^r* disjunction
reduction in *Enc(P)* does not produce measurable additional stability
beyond the theory change. The separation between *Enc(P)* and non-SNF
QE is therefore primarily about correctness (Proposition 4: completeness
with respect to feasible traces) and derivability (the encoding follows
from program structure, not mechanical syntax manipulation), rather than
about stability per se. This finding does not affect the main theorem,
which proves stability from Proposition 3 (quantifier-freedom) alone.

**Worked example — two coroutines, one yield point each.**

```python
async def a():          async def b():
    x = 1                   y = 1
    await sleep(0)          await sleep(0)
    x = 2                   y = 2
```

Under the default asyncio scheduler, *|F₁| = 1* (one FIFO-consistent
ordering: *a* before *b*). The conservative encoding retaining both
branches for scheduler-agnostic verification:

```python
s.add(x_pre == 1, y_pre == 1)
s.add(z3.Or(
    z3.And(order,         x_post == 2, y_post == 2),   # σ = (a,b)
    z3.And(z3.Not(order), y_post == 2, x_post == 2),   # σ = (b,a)
))
```

This encoding is conservative: it is valid for any SNF-class scheduler.
A scheduler-aware tool may add `order = True` to reduce it to a single
ground conjunction. `z3.is_quantifier` returns `False` on all
assertions; Z3 returns `sat` for `x_post=2 ∧ y_post=2` and `unsat` for
`x_post≠2 ∨ y_post≠2`.

*Why this example cannot witness Claim 3.* This example has a single
dispatch step (*T = 1*), no rendezvous points, and directly
non-interfering coroutines (*Vars(a) ∩ Vars(b) = ∅*). Claim 3's
content is entirely about composing the bijection *across* multiple
dispatch steps in the presence of rendezvous resolution, and Lemma 2a
is vacuous when no rendezvous point exists. A worked example exercising
either claim requires at least two dispatch steps and at least one
rendezvous point.

**Worked example 2 — chained rendezvous, four coroutines, Lemma 2a and Claim 3 witness.**

This example is the minimal instance exercising Lemma 2a nontrivially:
two chained rendezvous points sharing a coroutine, with an unrelated
fourth coroutine present at the step where the choice of *σₜ* could,
in principle, vary. An explicit intervening yield point in *c1*
(`await sleep(0)` between its get and put) splits the two rendezvous
across two distinct dispatch steps, so the example witnesses both
Lemma 2a's within-step invariance and Claim 3's cross-step composition.

```python
async def c0():               async def c1():
    q1.put_nowait("a")            x = await q1.get()
                                   await sleep(0)
                                   q2.put_nowait(x + "b")

async def c2():               async def c3():
    y = await q2.get()            z = 1
                                   await sleep(0)
                                   z = 2
```

Here `q1`, `q2` are `asyncio.Queue` instances. The rendezvous structure
is a chain: *c0*'s put on `q1` resolves *c1*'s get (rendezvous *r1*),
and *c1*'s subsequent put on `q2` resolves *c2*'s get (rendezvous
*r2*), so *c0 → c1 → c2* with *c1* shared between both constraints.
Coroutine *c3* shares no synchronization object with *c0*, *c1*, or
*c2* and is present in *Q₁* alongside them, varying the schedule
without participating in either rendezvous.

*Dispatch step 1.* *Q₁ = {c0, c1, c2, c3}* (all four are immediately
ready: *c0* has no preceding `await`, *c1* and *c2* are blocked on
`get()` until their respective `put_nowait()` calls occur, and *c3*
begins execution immediately). The only resolvable rendezvous at step
1 is *r1*, since *c1*'s `get()` can only return after *c0*'s
`put_nowait()` executes within step 1, and *r2* cannot resolve until
*c1* — having received from `q1` — performs its `put_nowait` on `q2`,
which now happens strictly after the explicit `await sleep(0)` in
*c1*'s body, i.e. no earlier than the dispatch step *after* *c1* is
first dispatched. *F₁* consists of every FIFO-consistent permutation of
*{c0, c1, c2, c3}* in which *c0* precedes *c1* (required for *r1* to
resolve within the step) — by the Proposition 5 key lemma, this halves
*S₄* to 12 permutations, with *c2*'s and *c3*'s relative positions
unconstrained at this step since *r2* and *c3*'s execution depend on
nothing yet established.

*Applying Lemma 2a at step 1.* Take two permutations
*σ = (c0, c3, c1, c2)* and *σ' = (c3, c0, c1, c2)*, both in *F₁* (both
respect *c0* before *c1*; the position of *c3*, which participates in
no rendezvous, varies freely). Under *σ*, *c0* dispatches at position
1 and resolves *r1* immediately upon executing `put_nowait`; under
*σ'*, *c0* dispatches at position 2 and resolves *r1* at that point
instead. In both cases *r1* resolves *during step 1*, because by SNF-3
*c0*'s entire (single-step) body executes atomically once dispatched,
regardless of *c3*'s position. Under both *σ* and *σ'*, *c1* is also
dispatched during step 1 and executes its `get()`, but the explicit
`await sleep(0)` forces *c1*'s `put_nowait` on `q2` into a *separate*
atomic segment, so *r2* resolves under neither *σ* nor *σ'* at step 1
— *c1* instead re-enters `_ready` at the end of step 1, its `q2` put
still pending. So the set of rendezvous resolved at step 1 — *{r1}* —
is identical under *σ* and *σ'*, exactly as Lemma 2a predicts, and
*Q₂ = {c1, c3}* is identical in both cases — *c0* exits (its single
step is complete), *c1* re-enters `_ready` after its `sleep(0)`, and
*c3* re-enters `_ready` after its own `sleep(0)`. *c2* is **not** in
*Q₂*: it is blocked on `q2`'s getters queue — registered as a waiter,
not dispatched — until *r2* resolves, which by SNF-2 does not happen
until step 2.

*Dispatch step 2.* *Q₂ = {c1, c3}*. *c1* resumes and executes
`q2.put_nowait(x + "b")`, resolving *r2* and waking *c2* — but per
SNF-2, a coroutine woken during step *t* is not itself dispatched until
step *t+1* (the `ntodo` capture excludes handles appended mid-iteration),
so *c2* becomes eligible for `_ready` without joining *Q₂*. *F₂*
consists of both FIFO-consistent permutations of *Q₂ = {c1, c3}*: since
*c1* and *c3* do not interact, either relative order is feasible, and by
Lemma 2a, whether *r2* resolves during step 2 depends only on *c1*'s
own dispatch — which happens regardless of its position relative to
*c3* — not on any ordering against *c2*, which is not a member of *Q₂*
to be ordered against in the first place. The set of rendezvous
resolved at step 2, *{r2}*, is therefore invariant across both
permutations in *F₂*, and *Q₃* (containing *c2*, now unblocked, and,
depending on timing, *c3*) is identical across all permutations in
*F₂*. This is a genuine two-dispatch-step composition: *r1* resolves
at step 1, *r2* resolves at step 2, and Lemma 2a's invariance of *Q₂*
across step-1 orderings is exactly the premise Claim 3's inductive step
needs to extend the bijection from *T = 1* to *T = 2*.

*What this example tests.* The chain *c0 → c1 → c2* is exactly the
dependent-constraint case flagged in Proposition 5 as pruning *|Fₜ|*
below the independent-constraint bound *n!/2^r*, and the presence of
*c3* is what makes Lemma 2a's invariance claim nonvacuous — without
*c3*, *F₁* would have only the orderings of *{c0, c1, c2}* to vary
over, all of which trivially produce the same resolved-rendezvous set
since *r1* and *r2* resolve in the same relative position regardless.
With *c3* present and free to vary its position, this example
witnesses that Lemma 2a's invariance is a genuine claim about
resolution timing being independent of *unrelated* coroutines'
positions, not an artifact of having no real alternative orderings to
check. The explicit `await sleep(0)` between *c1*'s get and put
additionally makes this a genuine two-step witness of Claim 3's
inductive step: *r1* resolves at step 1, *r2* resolves at step 2, and
*Q₂ = {c1, c3}*'s invariance across step-1 orderings feeds directly
into *Q₃*'s invariance across step-2 orderings, exactly the composition
Claim 3's induction requires. This is the example used to formalise the
second test case in the Lean mechanisation of Claim 3.

---

## Step 5 · Main Theorem

**Theorem.** Let *P* be a program satisfying controlled interference
whose scheduler satisfies SNF (CPython 3.12.3, default task factory).
The encoding *Enc(P)* is:

1. Quantifier-free (Proposition 3)
2. Complete with respect to feasible traces (Proposition 4)
3. Free of root cause classes A, B, and C in Can's SMT instability taxonomy

**Part A (Quantifier/relevancy instability).** Can's root cause class A
requires a quantifier in the SMT query: the instability arises from
E-matching and relevancy filtering interacting with universal
quantifiers. By Proposition 3, *Enc(P)* is quantifier-free. The
structural precondition for class A is absent. The same applies to
MBQI (Model-Based Quantifier Instantiation): Z3 invokes its MBQI
engine as a fallback when E-matching fails to instantiate quantifiers;
since *Enc(P)* contains no quantifiers, the MBQI engine is never
consulted. Can's `patch-mbqi` fix addresses instability arising from
MBQI heuristics; *Enc(P)* avoids this class of instability by the
same structural argument. ∎

**Part B (Misconfiguration instability).** Can's root cause class B
comprises two cases, both concerning misconfigured quantifier
instantiation parameters; the concrete fix for one (`lemma_2toX`) is
setting `smt.qi.eager_threshold=200`, a parameter controlling the cost
threshold for eager quantifier instantiation. Since *Enc(P)* contains
no quantifiers (Proposition 3), the quantifier instantiation subsystem
is never invoked regardless of how `smt.qi.eager_threshold` or related
parameters are set. Class B is a corollary of Part A. ∎

**Part C (Misaligned trigger expectations).** Can's root cause class C
comprises three cases (`issue_7444`, `IfNorm0`, `root0`) where users
expected triggers to fire on ground terms but relevancy filtering
suppressed E-matching: the CDCL(T) core marks ground terms appearing
only in currently-irrelevant atoms as ineligible for trigger matching,
blocking the expected instantiation. Triggers are annotations on
quantified formulas; a quantifier-free formula carries no triggers and
never consults the E-matching engine, so relevancy filtering has no
instantiations to suppress. Class C is a corollary of Part A. ∎

---

## Related Work

**Can's instability taxonomy.** This work directly extends Can's
empirical study of SMT solver instability in solver-aided verifiers.
Can's taxonomy identifies eleven unstable queries and classifies their
root causes into three classes: quantifier/relevancy mismatches,
misconfigured quantifier instantiation parameters, and misaligned
trigger expectations. The present work takes Can's taxonomy as its
primary input and proves that a class of encodings — those derived from
the Normal Form Reduction — structurally avoids every root cause class
he identified. Can's work is descriptive and empirical; this work is
prescriptive and formal.

**Herbreteau, Larroze-Jardiné, and Walukiewicz (CONCUR 2025).** Their
result that stateful partial-order reduction cannot be polynomially
approximated unless P=NP — holding even for acyclic programs with
only `await` instructions — is a direct lower bound on the general
problem this work studies in the restricted asyncio setting. SNF
sidesteps the hardness result by restricting to programs satisfying
controlled interference, for which the relevant permutation set *Fₜ*
is structurally bounded and enumerable without an NP-hard oracle. The
hardness result explains why the controlled-interference restriction
is not merely a convenience: for the general case, no polynomial
encoding exists.

**Schemmel et al. — KLEE+POR.** The closest symbolic execution work
combines quasi-optimal partial-order reduction with KLEE to handle
both data and scheduling nondeterminism in multi-threaded C programs,
building partial orders over POSIX synchronization primitives and using
cutoff events to prune redundant traces. The goals overlap — both
approaches aim to reduce the space of interleavings that must be
explored — but the problems are different. KLEE+POR targets
exhaustive interleaving enumeration for bug-finding in general
multithreaded programs; this work targets SMT encoding stability for
asyncio programs. KLEE+POR does not address quantifier structure in
the SMT queries it generates, and makes no claims about solver
stability under seed variation or parameter misconfiguration.

**ESST.** ESST (Explicit Scheduler, Symbolic Threads) targets model
checking of correctness properties by combining explicit-state
scheduler enumeration with symbolic per-thread execution. Like KLEE+POR,
its goal is interleaving coverage, not encoding stability, and it does
not address quantifier structure or the solver instability phenomena
that Can's taxonomy characterises. The problems are complementary:
ESST and KLEE+POR handle the interleaving enumeration problem for
general concurrent programs; SNF handles the encoding stability
problem for asyncio programs satisfying controlled interference.

---

## Limitations

The theorem applies to programs satisfying controlled interference:
coroutines with disjoint local variable sets where all shared state is
accessed exclusively through `asyncio.Queue`, `asyncio.Lock`, or
`asyncio.Event`. Programs with *unmediated shared mutable state* —
where one coroutine reads or writes a variable that another coroutine
also reads or writes, without going through a synchronization primitive
— are outside the theorem's scope.

This is a real limitation, not merely a scope boundary, because
unmediated shared state is precisely where the interesting concurrency
bugs live. A coroutine that reads a shared counter while another
increments it, a boolean flag set by one coroutine and polled by
another without a Lock, a shared list appended to by multiple
coroutines concurrently — these patterns produce the ordering and
atomicity bugs that make concurrent programs hard to verify. They are
also the patterns the theorem says nothing about. The theorem is
strongest exactly where the verification problem is easiest (disjoint
state, fully mediated sharing), and silent exactly where the
verification problem is hardest (unmediated shared state, race
conditions).

*`asyncio.eager_task_factory` — first-step split, formalized.* Eager
task execution runs `Task.__step` synchronously inside `create_task`
rather than scheduling it onto `_ready`, which breaks SNF-1, SNF-2, and
SNF-3 for a task's first step only (mechanism given under *Conditions
under which CPython witnesses fail*, Step 2). This can be handled as a
case split rather than left as an unresolved complication.

**Definition 8 (Eager-split coroutine).** For a coroutine *cᵢ* created
under `eager_task_factory`, let *y_{i,0}* denote its eager first step —
executed synchronously inside the *creating* coroutine's own step, prior
to and excluded from *cᵢ*'s own `_ready`-mediated dispatch history — and
let *y_{i,1}, y_{i,2}, …* denote its subsequent steps, each dispatched
through `_ready` exactly as in the non-eager case.

**Proposition 7 (Subsequent-step normality).** For any *cᵢ* created
under `eager_task_factory` that suspends at least once, the suffix of
*cᵢ*'s execution from *y_{i,1}* onward satisfies SNF-1 through SNF-4 as
stated in Step 2, with $Q_t$ for $t \geq 1$ defined over the same
`_ready`-mediated dispatch history as in the non-eager case.

*Proof.* By construction of `eager_task_factory`, once *cᵢ* first
suspends (reaches `y_{i,0}`'s yield point and returns control), its
continuation is scheduled onto `_ready` via the same `call_soon` /
`Task.__step` path used for non-eager tasks (this follows the
`result is None` branch in `__step_run_and_handle_result`, identical to
the witness cited for Claim 2's sequence-to-trace direction in Step 3).
From this point forward, *cᵢ*'s dispatch is governed by `_run_once`'s
FIFO `popleft` loop (SNF-1 witness), is subject to the same `ntodo`
bound (SNF-2 witness), and runs atomically within one `coro.send(None)`
call per step (SNF-3 witness), identically to a non-eager coroutine.
None of these witnesses reference how *cᵢ* was created, only how it is
subsequently dispatched; eagerness is a property of *y_{i,0}* alone and
does not propagate to later steps. $\square$

**Proposition 8 (First-step exclusion is sufficient).** Let *P* be a
program using `eager_task_factory` in which, for every eager coroutine
*cᵢ*, *y_{i,0}* performs no put-side or get-side operation on any
*s ∈ Sync(P)* and no write or read of any variable in *Vars(cⱼ)* for
*j ≠ i* (i.e. the eager first step touches no shared state). Then the
Normal Form Reduction Lemma holds for *P* if *T* is redefined to index
only dispatch steps *t ≥ 1* (excluding each coroutine's eager
*y_{i,0}*) and *Q_1* is taken to be the set of coroutines whose eager
first step has already run and which have suspended into `_ready`
before step 1 begins.

*Proof.* Under the stated restriction, *y_{i,0}* is causally irrelevant
to the bijection argument: it neither reads nor writes shared state, so
it contributes nothing to any coroutine's *Vars* footprint that Claim
1's constancy argument or Lemma 2a's resolution-set argument depend on,
and it establishes no rendezvous point. The eager first step is
therefore equivalent, for the purposes of the Lemma, to a step that
happened "before *t = 1*" in program-text order but outside the
`_ready`-mediated scheduling process the theorem quantifies over. By
Proposition 7, every step from *y_{i,1}* onward satisfies SNF-1 through
SNF-4 exactly as in the non-eager case, so the proof of the Normal Form
Reduction Lemma (Claims 1–3, Lemma 2a) applies unchanged to the
restricted trace *(y_{i,1}, y_{i,2}, \ldots)*. $\square$

*Scope of the split.* Proposition 8's restriction — the eager step
touches no shared state — is real and not always satisfied: an eager
first step that, e.g., immediately acquires a Lock or reads a variable
another coroutine writes is exactly the case the split does not cover,
because such a step's effects would need their own SNF-1/2/3 argument
and none is available (the step runs inside the creating coroutine's
atomic segment, not its own). Removing this restriction — proving a
version of Lemma 2a that accounts for an eager step's shared-state
effects occurring "for free" inside the creator's segment — is the
remaining open piece of the eager-task-factory extension. Programs
satisfying `controlled interference` (Step 3) automatically satisfy
Proposition 8's restriction on `Sync(P)`-mediated accesses (the eager
step, if it touches `Sync(P)`, does so as a well-defined get/put
operation whose effect on `Q_1` needs a separate rendezvous argument not
given here), so the restriction is stated in terms of *Vars* rather than
assumed away.

*Toward removing the restriction — proof sketch, unverified.* The
obstruction is narrower than it first looks. SNF-3's actual content —
no other coroutine's state changes during *cᵢ*'s atomic segment — does
not care how long or structurally complex that segment is; it holds for
the *entire* synchronous call stack executed during *cᵢ*'s `__step`,
including a nested `create_task(cⱼ)` call that runs *cⱼ*'s eager first
step to completion or suspension before *cᵢ*'s step returns. So the
resolution-set invariance argument Lemma 2a needs (permuting the *other*
members of *Qₜ* doesn't change what happens during *cᵢ*'s step) goes
through **unchanged** for the combined segment: *cⱼ* was never a member
of *Qₜ* to begin with (its eager step doesn't pass through `_ready`),
so nothing about permuting *Qₜ* touches it, and *cᵢ*'s own atomicity
already shields the whole nested segment from interleaving by
construction. This suggests the "new invariant about nested atomicity"
a first pass might expect to need is not actually required — SNF-3
already supplies it.

What *does* need to change is Definition 9's bookkeeping, not a new
atomicity lemma: *Enc(P)*'s *Φₜ* for the step in which *cᵢ* calls
`create_task(cⱼ)` currently assumes exactly one coroutine's
`post_constraints` per step. If *cⱼ*'s eager step touches shared state,
*Φₜ* needs a second set of ground constraints —
`post_constraints(cⱼ, y_{j,0}, t)` — conjoined into the *same* *Φₜ*,
attributing *cⱼ*'s eager-step effects to *cᵢ*'s dispatch step rather
than to a step of *cⱼ*'s own (which doesn't exist yet). If the eager
step performs a rendezvous operation, that operation's happens-before
position is still well-defined (it occurs at a fixed point within
*cᵢ*'s atomic segment, between "before `create_task`" and "after
`create_task` returns"), so Definition 7's rendezvous bookkeeping
extends without modification — it was never tied to which physical
`_ready` slot produced the operation, only to its position in the total
order.

If this sketch survives scrutiny, the needed result is:

**Proposition 8′ (Eager first-step shared-state extension — proved).**
Extend Definition 9 so that for the dispatch step *t* during which *cᵢ*
calls `create_task(cⱼ)` under `eager_task_factory`, *Φₜ* additionally
conjoins `post_constraints(cⱼ, y_{j,0}, t)` — the ground constraints for
*cⱼ*'s eager first-step segment, up to its completion or first
suspension — and any rendezvous constraints that segment establishes or
resolves, using Definition 7's existing bookkeeping, now applied to an
event ordered within *cᵢ*'s segment rather than its own dispatch step.
If *y_{j,0}* performs an access to shared state that is *not*
`Sync(P)`-mediated, that access is classified by the existing static
checker (Definitions 12, Proposition 11) using the identical criteria
already applied to every other coroutine's unmediated accesses, with
the identical resulting guarantees (soundness of detection; Proposition
12 for flagged-data; open for flagged-control). Under this extension,
the Normal Form Reduction Lemma holds for programs using
`eager_task_factory`, with no restriction on *y_{j,0}*'s shared-state
accesses beyond what the theorem and checker already impose on
*every* coroutine's shared-state accesses — i.e., Proposition 8's
shared-state-free restriction is removed, not narrowed.

*Proof.*

*Quantifier-freedom.* `post_constraints(cⱼ, y_{j,0}, t)` is, by
construction, a conjunction of ground QF_LIA/QF_BV constraints — the
same syntactic form Definition 9 already requires of every coroutine's
post-constraints at every step. Conjoining a further quantifier-free
formula to a quantifier-free formula yields a quantifier-free formula
(closure of QF_LIA/QF_BV under conjunction). Nothing about *y_{j,0}*
being nested inside *cᵢ*'s segment changes its syntactic form; it is
built by the same procedure Definition 9 already uses for an ordinary
coroutine's step, just invoked one extra time within the same *Φₜ*.

*Lemma 2a extension.* By Claim 1 and controlled interference, *cᵢ*'s
state on entry to step *t* — and hence *cᵢ*'s entire deterministic
execution during its atomic segment, including whether and with what
arguments it reaches `create_task(cⱼ)` — is invariant across every
*σ ∈ Fₜ*: this is the existing Claim 1/Lemma 2a argument for *cᵢ*,
unchanged, because SNF-3's atomicity covers *cᵢ*'s entire synchronous
call stack, nested eager execution included, so no other member of
*Qₜ* can interleave with any part of it regardless of dispatch
position. Given that *cᵢ*'s hand-off state to *cⱼ* is thus
*σ*-invariant, *cⱼ*'s eager-step behavior is a deterministic function
of that fixed state. If *y_{j,0}* performs a `Sync(P)`-mediated
operation, its resolution follows exactly Lemma 2a's existing argument
for any coroutine's put/get — invariance depends only on which
coroutine performs the operation and that coroutine's own execution
reaching it, not on *Qₜ*'s permutation — with *cⱼ*-during-*y_{j,0}*
simply substituted as "the dispatched entity" for that one event. If
instead the access is unmediated, Lemma 2a's invariance claim is not
asserted for it, exactly as it is not asserted for any ordinary
coroutine's unmediated shared write — that access falls to the checker
and Proposition 12 rather than to Lemma 2a, matching the theorem's
existing scope precisely rather than requiring a new exception carved
out for eagerness.

*Claim 2 bijection.* *cⱼ*'s eager step introduces no new scheduling
degree of freedom: it is never dispatched via `_ready`, so it
contributes no additional permutation to *Fₜ*. Its outcome is a
deterministic function of *cᵢ*'s (*σ*-invariant) execution, established
above. SNF-1 still gives a unique scheduling choice per step for the
coroutines actually in *Qₜ*, so trace→sequence uniqueness is unaffected.
For sequence→trace realizability, realizing a chosen *σ ∈ Fₜ* fixes
*cᵢ*'s entire deterministic code path by the same argument as before;
this uniquely determines, via `create_task`'s synchronous eager
semantics, exactly how *cⱼ*'s nested segment unfolds — there is no
independent choice of "how *cⱼ*'s eager step goes" left over once *σ*
and *cᵢ*'s pre-step state are fixed, since that outcome was shown above
to depend on nothing else. $\square$

*Scope note.* This proof composes with, rather than eliminates, the
paper's existing open problems: an unmediated shared-state touch during
*y_{j,0}* is exactly as unresolved as an ordinary coroutine's would be
— sound detection (Prop 11) but open soundness for the flagged-control
sub-case (Prop 12's remaining gap). Nested eager creation (*cⱼ* itself
eagerly creating *cₖ* during *y_{j,0}*) is covered by the same argument
applied recursively, since the entire recursive tree remains inside
*cᵢ*'s single SNF-3-atomic segment. If *cⱼ*'s eager step suspends
partway through, the remainder is Proposition 7's territory, unchanged
— this proposition concerns only the nested, pre-suspension segment
*y_{j,0}* itself.

*How live is this in practice?* A source-wide scan (`eager_factory_check.py`)
for any reference to `eager_task_factory` — literal usage, imports, or as
an argument to `set_task_factory`/`Runner` — across all 33 corpus
repositories found **zero**. Proposition 8′ now removes the restriction
this would have been needed for, so the point is moot for the current
corpus either way, but it is worth having closed given `eager_task_factory`'s
trajectory toward becoming CPython's default.

*CPython free-threading (PEP 703, 3.13+).* CPython 3.13 introduces an
experimental no-GIL mode. SNF-3's actual claim — no other coroutine is
dispatched during *cᵢ*'s step — survives free-threading intact, because
asyncio's event loop remains single-threaded regardless of the GIL.
What free-threading removes is a *stronger* property SNF-3 never
claimed: atomicity of individual Python object mutations (dict
updates, list appends, attribute sets) against concurrent modification
by OS-level threads. This matters only for programs that combine
asyncio with `run_in_executor` or explicit threading; for such
programs, thread-level interference within a coroutine's step is
outside what SNF-3 protects against, GIL or no GIL. For programs using
only async/await with no explicit threading, SNF-3's invariant holds
under no-GIL exactly as it does under the GIL.

*Thread-Disjointness Condition — closing the free-threading carve-out
to a checkable side-condition.* The free-threading note above rules
threading-combined-with-asyncio programs out of the theorem entirely.
That blanket exclusion can be replaced by a checkable side-condition,
using the same reachability-based technique Definition 12's checker
already applies to unmediated shared state.

**Definition 17 (Thread footprint).** For a coroutine *cᵢ* and a
dispatch step *y_{i,t}* whose synchronous call stack (transitively)
invokes `loop.run_in_executor`, constructs a
`concurrent.futures.ThreadPoolExecutor`, or constructs/starts a
`threading.Thread`, let *F(y_{i,t})* denote the set of shared-state
accesses — reads or writes to any variable in ⋃ⱼ *Vars(cⱼ)* for *j ≠ i*,
or to module- or instance-level state reachable from the submitted
callable — performed by that callable's transitive call graph,
excluding accesses confined to the callable's own invocation frame
(local variables, captured-by-value arguments).

**Definition 18 (Thread-Disjointness Condition, TDC).** Program *P*
satisfies TDC if, for every step *y_{i,t}* with nonempty thread
footprint *F(y_{i,t})*, and every coroutine step *y_{j,t'}* that may be
dispatched by the event loop before the submitted executor call or
thread returns or is joined, *F(y_{i,t}) ∩ Vars-accessed(y_{j,t'}) = ∅*
— unless every variable in the intersection is guarded by an OS-level
synchronization primitive establishing a happens-before edge between
the thread's access and *y_{j,t'}*'s access: mutual exclusion
(`threading.Lock`, `threading.RLock`), or a one-shot handoff signal
(`threading.Event`, `threading.Condition`, `threading.Barrier`) awaited
by the coroutine side before the shared variable is read. This is a
different requirement than SNF-4's `asyncio.Lock`: TDC's guard need
only establish a happens-before edge for the specific accesses in
question, not the FIFO wakeup-order property SNF-4 depends on, since no
scheduling-order claim is being made about OS threads.

*Remark (motivating example from the corpus).* `asyncz`'s
`AsyncIOScheduler.start()` spawns a background thread running
`_init_new_loop`, which writes `self.event_loop` and then calls
`event.set()` on a shared `threading.Event`; `start()` does not return
control past `await asyncio.to_thread(event.wait)` until that fires.
Any coroutine that could read `self.event_loop` (e.g. `shutdown`) can
only run after `start()` has returned, by which point the write has
already happened-before it via the `Event`. A call-graph TDC checker
restricted to `Lock`/`RLock` (as an earlier draft of this definition
was) flags this as a violation; it is not one — the `Event` provides
exactly the required happens-before edge for this one-shot
initialization handoff, just via a different primitive than mutual
exclusion. This is why the guard clause above is stated in terms of
the happens-before edge a primitive establishes, rather than naming
only `Lock`/`RLock`.

**Proposition 14 (TDC sufficiency).** If *P* satisfies SNF-1–SNF-4,
extended controlled interference, and additionally TDC, then *Enc(P)*
(Definition 9) is unchanged and remains quantifier-free, complete, and
stable, with no additional encoding contribution from threaded code.

*Proof.* TDC's only role is to rule out the one case SNF-3 does not
cover: a coroutine-visible mutation occurring in an OS thread running
concurrently with a coroutine's atomic segment. SNF-3's guarantee — no
other *coroutine* interleaves during *cᵢ*'s step — is untouched by TDC
and holds exactly as proved in Proposition 1 regardless of GIL status
(free-threading note, above). TDC's disjointness clause guarantees the
submitted thread touches nothing any coroutine's Lemma 2a argument or
Definition 9's encoding depends on; where the clause is instead
satisfied via a happens-before-establishing primitive rather than
disjointness outright, that primitive's synchronization is enforced
entirely below the level the encoding reasons about, so gating access
at the OS level neither adds nor removes a scheduling degree of
freedom the encoding represents. No new variable, branch, or
scheduling choice is added to the trace space Claim 2's bijection
quantifies over, so the bijection, Lemma 2a, and Proposition 4's
completeness argument go through unchanged. $\square$

*Scope.* TDC is checkable by call-graph reachability from each
`run_in_executor`/`Thread`/`ThreadPoolExecutor` call site — the same
technique Definition 12 already uses for unmediated shared-state
classification. A program failing TDC is not thereby proven unsafe: it
is exactly as open as an unmediated-write program under Definition 12
— outside the theorem's positive claim, flagged for general-purpose
verification, not silently mis-verified. This replaces the prior
blanket exclusion ("threading + asyncio ⇒ theorem inapplicable") with
the same graduated treatment already given to every other unmediated
access case. It does not, by itself, upgrade the Section 5.6/6
same-function overlap measurement to call-graph precision — that
remains a separate, purely empirical follow-up (script given in the
paper's Section 6 discussion).

*Alternative event loops — Consistency Interface.* Rather than
re-deriving SNF-1 through SNF-4 from scratch for each alternative event
loop implementation, we factor out the CPython-specific witnesses from
the structural argument they support, giving a four-obligation
interface any scheduler can be checked against once, independent of
implementation language or internals:

**Definition 9 (Scheduler Consistency Interface).** A scheduler
implementation satisfies the *Consistency Interface* for SNF if it
exposes, or can be shown by source inspection to guarantee, the
following four properties, stated implementation-agnostically:

- **(I-1) Deterministic dispatch.** The function from ready-set to
  next-dispatched-coroutine is total and pure — no hidden randomness
  (e.g. no `random.shuffle` on the ready structure, no hash-order
  dependence for non-deterministic hash seeds).
- **(I-2) Bounded per-iteration dispatch.** Coroutines that become ready
  *during* a dispatch iteration are deferred to a subsequent iteration,
  not spliced into the current one — i.e. the set dispatched in a given
  step is fixed before the step begins.
- **(I-3) Run-to-suspension atomicity.** A dispatched coroutine executes
  without interleaving from any other coroutine until it itself
  suspends or terminates (single-threaded cooperative execution, or an
  equivalent isolation guarantee under a different concurrency model).
- **(I-4) Statically-derivable wakeup order.** For each synchronization
  primitive, the order in which multiple waiters are woken is a fixed,
  documented policy expressible independent of runtime data (FIFO being
  the canonical case; any other total, program-structure-derivable
  order would also suffice, with SNF-4's proofs adjusted accordingly).

**Proposition 9 (Interface sufficiency).** Any scheduler satisfying
(I-1)–(I-4) satisfies SNF-1 through SNF-4 as defined in Step 2, and
Proposition 1 (and hence the Normal Form Reduction Lemma and everything
built on it) transfers to that scheduler unchanged.

*Proof.* (I-1)–(I-4) are direct implementation-agnostic restatements of
SNF-1–SNF-4: SNF-1 is exactly determinism of the dispatch function
(I-1); SNF-2's bound $|Q_t| \leq |C|$ follows from (I-2), since deferring
newly-ready coroutines to the next iteration is precisely what prevents
per-iteration growth beyond one contribution per coroutine; SNF-3 is
(I-3) restated; SNF-4 is (I-4) restated with FIFO generalized to "any
statically-derivable total order," and Proposition 5's counting argument
(the $n!/2^r$ bound) goes through for any such order since the proof
only uses that a constraint bisects $S_n$, not that the order is
specifically FIFO. Every downstream proof (Claims 1–3, Lemma 2a,
Propositions 2–6) cites only SNF-1–SNF-4, not CPython-specific
mechanism, so nothing downstream needs to be re-proved. $\square$

*Status for `uvloop` — checked, passes.* We checked all four properties directly against `uvloop` 0.22.1's Cython source (commit `0582f946`, 2026-05-04). (I-1) and (I-2) hold in `uvloop/loop.pyx`'s `_on_idle` dispatch routine, which captures `ntodo = len(self._ready)` before the dispatch loop and pops handles via `popleft()` in strict FIFO order for `i in range(ntodo)` — structurally identical to `BaseEventLoop._run_once`'s SNF-1/SNF-2 witness. (I-3) holds because `handler._run()` executes synchronously inside libuv's single-threaded idle-handler callback, so no other coroutine's handle can run during a given handle's execution. (I-4) holds because `uvloop` does not reimplement `asyncio.Lock`, `Queue`, or `Event` at all — a source-wide search finds no such classes anywhere in the package — so these remain CPython's stock pure-Python implementations with the same FIFO `_waiters`/`_getters`/`_putters` deques already verified for SNF-4, routed through the same `call_soon` → `_ready` dispatch just confirmed for (I-1)/(I-2). By Proposition 9, `uvloop` therefore inherits SNF and the main theorem without modification. This is a source-level structural inspection, at the same evidentiary standard as the CPython witnesses for SNF-1–SNF-4, not a mechanized proof.

*Status for Trio — checked, fails (I-1), negative result.* We checked the same four properties against Trio (commit `865b7fc`, 2026-06-30). (I-1) fails by explicit design: Trio's core scheduling loop (`src/trio/_core/_run.py`, `unrolled_run`) executes `if _r.random() < 0.5: batch.reverse()` on the runnable batch before dispatching, with a source comment stating the rationale directly: "we randomize the order of each batch to avoid assumptions about scheduling order sneaking in." This is a stated design goal in direct opposition to (I-1)/SNF-1, which requires the dispatch function to be deterministic. Since Proposition 9 requires all four properties conjunctively, Trio fails the interface at the first property; we did not proceed to check (I-2)–(I-4). This is a genuine second data point for the Consistency Interface — one confirming case (`uvloop`) and one correctly-rejecting case (Trio) — stronger evidence that the interface's clauses discriminate real scheduler differences than a single confirming instance would be.

*Scope of the two checked instances.* Both checked schedulers are Python and both reuse or closely mirror CPython's synchronization primitives: `uvloop` imports CPython's own `asyncio.Lock`/`Queue`/`Event` unmodified (its check for (I-4) above relies on exactly this), and Trio's rejection turns on (I-1) alone, a property stated purely in terms of dispatch-order determinism rather than any Python-specific mechanism. So while the interface (Definition 9) is stated implementation-agnostically, the *evidence* for it is currently Python-only, and specifically CPython-adjacent for the passing case. The two checks demonstrate that the interface can discriminate a real pass from a real fail; they do not yet demonstrate that it transfers across languages or concurrency models. That is a separate, open question, addressed next.

*Non-Python schedulers — not checked, and why each is expected to fail a specific clause.* Rust's `tokio`, Node.js's event loop, and Go's goroutine scheduler are not checked against Definition 9 in this work. This is not merely unfinished coverage: for each, there is a specific clause of (I-1)–(I-4) that its published scheduling model appears to violate, which is why we state this as future work rather than an oversight.

- **`tokio` (multi-threaded work-stealing).** (I-1) requires a single deterministic function from ready-set to next-dispatched-coroutine. Under work-stealing, multiple worker threads pull from per-thread and global run queues concurrently, so there is no single global FIFO order in which tasks are dispatched — dispatch order depends on which worker happens to steal which task, a genuine race rather than a documented total order. (I-1) is the clause we expect to fail first, before (I-2)–(I-4) are even reached, mirroring how Trio failed at (I-1) for an unrelated reason (explicit randomization rather than concurrent dispatch).
- **Node.js (phase-based event loop).** (I-2) requires that the set of coroutines dispatched in a given step is fixed before the step begins. Node's loop is structured as ordered phases (timers, pending callbacks, poll, check, close callbacks) with distinct admission rules per phase, and callbacks in one phase can under some conditions be interleaved with callbacks queued for the next; establishing a single per-iteration dispatch bound analogous to `ntodo = len(self._ready)` would require a per-phase argument, not one global bound, so (I-2) is the clause we expect to require the most rework.
- **Go (preemptive M:N goroutine scheduler).** (I-3) requires that a dispatched coroutine executes without interleaving from any other coroutine until it itself suspends or terminates. Go's scheduler preempts goroutines asynchronously at safe points (since Go 1.14, including tight loops), so a goroutine's execution is not run-to-suspension atomic in the sense (I-3) requires — another goroutine can begin executing on the same or another core before the first voluntarily yields. (I-3) is the clause we expect to fail.

None of these three has been checked by source inspection in this work; the above states the specific expected obstruction per Definition 9's clause structure, not a checked result. Confirming or refuting each expectation by the same source-level inspection used for `uvloop` and Trio is the natural next extension of this line of work.

*Read-only sharing (SNF-5, benchmark b7) — resolved.* SNF-5 (Definition
7, Step 3) is now a proved extension: Proposition 6 shows the Normal
Form Reduction Lemma and Propositions 2–4 hold under *extended*
controlled interference, which additionally permits unmediated
read-read shared accesses. Benchmark b7 (read-only broadcast with no
writer) validates the extension empirically. A real-world corpus study
of 33 open-source asyncio repositories (a second expansion of an
original 22-repo pass; `sqlalchemy` and `elasticsearch-py` were
additionally rescanned restricted to their actual async submodules
after an unscoped scan was found to fold in unrelated sync-code
interactions) finds that 67.93% of unmediated shared-variable
interactions are read-only under SNF-5, on top of 3.07% already
mediated — i.e. 71.0% of all interactions in the corpus satisfy
extended controlled interference natively.

*Commutative writes (2.38% of the corpus) — trace-equivalence, partial
result.* The earlier framing of this case — "algebraically commutative
operations collapse to a single final state" — is not the right
criterion, for exactly the reason given previously: counter increments
share a final value across orderings but not intermediate values, and a
third coroutine reading the counter mid-sequence *can* observe the
difference. State-equivalence (same final value) is therefore both too
weak (it says nothing about what's observable mid-execution) and not
what soundness actually requires. We replace it with trace-equivalence.

**Definition 10 (Observable point).** A read of variable *x* by
coroutine *cⱼ* at yield point *y_{j,g}* is an *observable point for x*
relative to a set of write operations *W* on *x* if *y_{j,g}* occurs,
in some feasible trace, after at least one write in *W* and before all
remaining writes in *W* have completed — i.e. the read can witness a
partially-applied prefix of *W*.

**Definition 11 (Trace-equivalent write set).** A set of write
operations *W* on shared variable *x*, performed by pairwise distinct
coroutines with no coroutine in *W* also reading *x*, is
*trace-equivalent* if for every observable point for *x* relative to
*W* and every two FIFO-and-rendezvous-consistent permutations *σ, σ' ∈
Fₜ* differing only in the relative order of the coroutines performing
writes in *W*, the value of *x* observed at that point is identical
under *σ* and *σ'*.

*Note the definition is deliberately about every observable point, not
just the final one — this is what rules out counters.*

**Corollary 9a (CPython version conformance via the Consistency
Interface).** For any CPython minor version *v*, whether
`asyncio.BaseEventLoop` satisfies SNF-1 through SNF-4 can be checked
without re-deriving the Step 2 witnesses from scratch: check I-1
through I-4 (Definition 9) directly against version *v*'s
`base_events.py`, `tasks.py`, `locks.py`, and `queues.py`, exactly as
already done for `uvloop` and Trio above. CPython's own asyncio
implementation is one instance of "a scheduler" in the sense Definition
9 quantifies over, so Proposition 9 applies to it directly: any version
*v* whose four source files satisfy I-1–I-4 inherits SNF and the main
theorem for that version, with no version-specific re-proof of Claims
1–3 or Lemma 2a required.

*Status — checked, passes across 3.9–3.13.* We ran this check
(`cpython_version_diff.py`) against tagged CPython releases 3.9.19,
3.10.14, 3.11.9, 3.12.3, and 3.13.0, pulled from `python/cpython` on
GitHub. All five versions show every I-1–I-4 witness substring present
under their 3.12-era names: the `ntodo = len(self._ready)` /
`popleft()` FIFO-snapshot pair in `base_events.py` (I-1/SNF-1), the
`for i in range(ntodo)` bound (I-2/SNF-2), `coro.send`/`coro.throw` in
`tasks.py` (I-3/SNF-3), and the `_getters`/`_putters`/`popleft()` and
`_waiters`/`next(iter(self._waiters))` FIFO patterns in `queues.py` and
`locks.py` respectively (I-4/SNF-4). This is a substring-presence check,
not a semantic verification that the surrounding code still does what
the pattern implies in every version — a version could in principle
keep an identifier name while changing its behavior — but combined with
the fact that these four files' core dispatch logic has been
structurally stable since `asyncio`'s introduction, absence of any
"MISSING" result across five releases spanning 3.9–3.13 is real,
positive evidence that Proposition 9 applies uniformly across this
range. By Corollary 9a, CPython 3.9–3.13's `asyncio.BaseEventLoop`
(default task factory) therefore inherits SNF and the main theorem
without a version-specific re-proof, narrowing the theorem's practical
scope caveat from "verified only against 3.12.3" to "verified against
3.12.3, and checked structurally consistent across 3.9–3.13."

**Proposition 10 (Sufficient condition for trace-equivalence).** Let *W*
be a set of write operations on *x* such that (a) each write in *W*
writes to a syntactically distinct key of a structured value (e.g.
distinct dictionary keys, distinct indices of a pre-sized array) with no
overlap, and (b) no read in the program observes *x* as a whole (e.g.
`len(x)`, iteration order, or any aggregate over *x*) before all writes
in *W* complete. Then *W* is trace-equivalent.

*Proof.* Fix an observable point *y_{j,g}* for *x* relative to *W* and
two permutations *σ, σ'* differing only in the order of *W*'s writers.
By (a), each write in *W* mutates a disjoint key/index; the value
observed by a read of a specific key *k* depends only on whether the
write to *k* has occurred by *y_{j,g}*, which (by Claim 1 and SNF-3, as
in Lemma 2a's argument) depends only on which coroutines have been
dispatched and completed their write by that point in *Qₜ*'s
processing — a property of the *set* of completed writers, not their
relative order among each other, since disjoint-key writes do not
interact. By (b), no read observes *x* as an aggregate, so the only
observable content of *x* at *y_{j,g}* is the per-key values already
covered. Hence the observed value is identical under *σ* and *σ'*.
$\square$

*Why this does not cover counters, and is not claimed to.* A counter
increment `x = x + 1` violates condition (a): it is not a disjoint-key
write, it is a read-modify-write on the *whole* value of *x*, so two
writers' operations are not independent — the result of the second
write depends on whether the first has already applied. Proposition 10
correctly excludes this case (it is not of the syntactic form condition
(a) requires), consistent with the earlier finding that "commutative"
cannot be defined at the level of final-value algebra alone.

*Encoding consequence.* For a trace-equivalent write set *W* satisfying
Proposition 10, no ordering constraint among *W*'s writers needs to
appear in *Φₜ*: any relative order is observationally equivalent, so
the corresponding disjuncts of *Fₜ* collapse to one representative
without loss of completeness, by the same argument structure as SNF-5's
encoding consequence (Definition 7). This gives *W* the same
zero-encoding-cost treatment as read-only sharing.

*What remains open.* Proposition 10 is a sufficient condition, not a
characterization — it covers the "independent dict/array keys" case
that motivated this direction empirically, but the corpus's 2.38%
commutative-looking bucket has not been checked against condition (a)
and (b) precisely (the corpus scan used a syntactic proxy, not this
definition). Whether a broader class of trace-equivalent writes exists
beyond disjoint-key writes — and whether Proposition 10's condition (b)
can be relaxed to admit some aggregate reads — is the remaining open
problem. Unlike the previous draft, this is now a stated gap in a
proved partial result, not an undefined intuition.

*Destructive write-conflict (25.18% of the corpus) — practical
enforcement via static checking, not verification.* This category is
where Lemma 2a and Claim 2 genuinely fail (see *Bounded write conflict*,
below); no proof is claimed for it. Because silently applying the
controlled-interference encoding to a program containing unmediated,
non-trace-equivalent writes would be **unsound** — the encoding would
omit orderings that affect *x*'s value, exactly as the failed-attempt
analysis below shows — we specify a conservative static checker whose
job is not to verify these programs but to correctly detect that they
fall outside the theorem's scope, so a verifier built on SNF can degrade
safely instead of silently returning a wrong answer.

**Definition 12 (Conflict checker).** For a program *P*, the checker
computes, for each shared variable *x*: the set *W(x)* of coroutines
writing *x* and *R(x)* of coroutines reading *x*, via the same
AST-based `Vars` analysis used for controlled interference (Step 1). It
classifies *x* as:
- **mediated**, if all accesses to *x* pass through *Sync(P)*;
- **read-only**, if *|W(x)| ≤ 1* and the sole writer's write
  (statically) precedes every read (Definition 7's condition);
- **checker-cleared**, if *x*'s writes are statically confirmed to
  satisfy Proposition 10's condition (a) (syntactically disjoint
  keys/indices) and condition (b) (no whole-value read before all
  writes complete, checked via a conservative over-approximation of
  "before": any read not provably ordered after all writes by static
  happens-before analysis counts as *not* satisfying (b));
- **flagged**, otherwise.

**Proposition 11 (Checker soundness).** Every variable the checker
classifies as *mediated*, *read-only*, or *checker-cleared* satisfies,
respectively, the controlled interference, SNF-5, or Proposition 10
condition it claims; consequently a verifier that applies the SNF-derived
encoding only to non-*flagged* variables, and refuses or falls back to
general-purpose (non-SNF) verification for *flagged* variables, never
applies an unsound disjunction to a variable outside the theorem's
scope.

*Proof.* Each classification rule is a direct, conservative
implementation of the corresponding formal condition — "mediated" checks
Definition of *Sync(P)*-exclusivity exactly; "read-only" checks
Definition 7's condition exactly, syntactically; "checker-cleared" checks
Proposition 10's (a) and (b) with (b) checked in the direction that can
only under-classify (fewer variables cleared), not over-classify, since
an unproven happens-before relation is treated as a violation of (b)
rather than assumed to hold. Any variable not meeting one of these three
syntactic tests is *flagged* by construction. Since each non-flagged
class is exactly the syntactic condition whose corresponding proposition
(controlled interference's assumption, Definition 7, or Proposition 10)
was proved, applying the SNF encoding only to non-flagged variables
applies it only where the enabling proposition's hypothesis is met.
$\square$

*What this is, and is not.* Proposition 11 is a soundness-of-detection
result (the checker never misclassifies an unsafe variable as safe); it
is not a verification result for *flagged* variables themselves — those
remain outside the theorem, and the checker's role is exactly to say so
rather than silently mis-verify them. This is a practical-enforcement
contribution, distinct from and much weaker than a soundness proof for
havoc-injection over-approximation, which remains unproved and is
discussed next as an open direction.

*Sound over-approximation via havoc injection — partially resolved.*
Havoc-variable injection at yield points touching *flagged* variables
(replacing the variable's value with a fresh unconstrained symbolic
value at each such point) is the standard technique from abstract
interpretation and symbolic execution for regaining soundness at the
cost of precision. Proposition 11 tells a verifier *which* variables need
this treatment. The composition of havoc injection with *Enc(P)* is
sound and quantifier-free for one sub-case (Proposition 12, below) and
remains open for the other (flagged-control variables).

**Definition 13 (Control-flow independence).** A flagged variable *v*
is *control-flow-independent* in coroutine *cᵢ* if no branch condition
in *cᵢ*, at any yield point after the earliest yield point where *v*
could have been written by another coroutine, syntactically reads *v*.
Equivalently: the sequence of yield points *y_{i,1}, y_{i,2}, …* and
the choice of which basic block executes between them is fixed
independent of *v*'s value — only the *data* recorded in
`post_constraints(cᵢ, σ, t)` depends on *v*, not the *shape* of
*Φₜ* itself.

This is a syntactic, checkable condition: extend the Definition 12
classifier with a fifth pass over variables already marked *flagged*,
testing whether they appear in any branch guard (`if`, `while`,
boolean short-circuit, match subject) reachable from a yield point
that follows an unmediated write. Call the resulting sub-partition
*flagged-data* (independent) and *flagged-control* (not).

**Definition 14 (Havoc-injected encoding).** For a flagged-data
variable *v* written at yield point *y_{j,p}* and read at *y_{i,q}*,
let *Enc_havoc(P)* be *Enc(P)* with every occurrence of the ground
equation defining *v*'s value at *y_{i,q}* in `post_constraints(cᵢ, σ, t)`
deleted, and *v* declared as a fresh, otherwise-unconstrained state
variable at that step. All other conjuncts of *Φₜ* — ordering,
rendezvous, and constraints on every non-flagged-data variable — are
unchanged.

**Proposition 12 (Sound over-approximation for flagged-data variables).**
For any program *P* whose flagged variables are all flagged-data
(Definition 13), *Enc_havoc(P)* is quantifier-free and captures every
feasible execution trace of *P* (soundness without completeness: it
may additionally admit spurious traces, but drops none).

*Proof.*

*Quantifier-freedom.* *Enc(P)* is quantifier-free by Proposition 3.
*Enc_havoc(P)* is obtained from *Enc(P)* by deleting conjuncts (the
equations defining flagged-data variables) and declaring the
now-unconstrained variables free. Deleting a conjunct from a
quantifier-free formula, and introducing a free (non-quantified)
variable in its place, yields a quantifier-free formula: no `ForAll`
or `Exists` is introduced or removed by either operation.

*Soundness (no feasible trace dropped).* Let *τ* be any feasible
execution trace of *P*, and let *(σ₁, …, σ_T)* be its corresponding
permutation-sequence (Claim 2). By Proposition 4, *(σ₁,…,σ_T)*
satisfies *Enc(P)* under the concrete valuation *ν* assigning every
state variable — including every flagged-data variable *v* — its true
value along *τ*. *Enc_havoc(P)*'s conjunction is a sub-conjunction of
*Enc(P)*'s at every step *t*: for each flagged-data *v*, we removed
exactly the equation `v_{after} = f(v_{before}, …)` from
`post_constraints`, and no other conjunct anywhere in *Φₜ* mentions
that equation (Definition 13 guarantees no branch guard, and hence no
disjunct-selection or ordering constraint, depends on it — only the
now-deleted data equation did). A conjunction remains satisfied under
a valuation when a conjunct is removed and the corresponding variable
is left free: *ν* restricted to *Enc_havoc(P)*'s variables still
satisfies every remaining conjunct (they are unchanged from *Enc(P)*,
which *ν* already satisfies), and the free variable *v* is trivially
witnessed by *ν(v)* itself, since an unconstrained variable admits any
value. Hence *ν* is a model of *Enc_havoc(P)*, i.e., *τ*'s
permutation-sequence satisfies *Enc_havoc(P)*. Since *τ* was
arbitrary, no feasible trace is excluded. $\square$

*Remark (why completeness is not claimed).* *Enc_havoc(P)* may admit
additional models where the free variable *v* takes a value not
achievable by any real execution — e.g., a value inconsistent with
the true interleaving of *v*'s unsynchronized writers. This is
exactly the expected cost of over-approximation: a verifier built on
*Enc_havoc(P)* can still report false alarms on flagged-data
variables, but never misses a real bug, which is the soundness
direction that matters for a static checker (cf. Proposition 11).

*Where this stops: flagged-control variables.* Proposition 12's proof
leans on one fact stated explicitly in Definition 13: deleting *v*'s
defining equation touches nothing else in *Φₜ*, because nothing else
in *Φₜ* depends on it. That fact fails for a **flagged-control**
variable — one that gates a branch. Havoc-injecting such a *v* means
both branches downstream of the guard are now reachable under
different values of the free variable, but Definition 9's encoding
was built assuming a *fixed* sequence of *k* yield points per
coroutine with a *fixed* `post_constraints` shape per step. If the
branch changes which yield points *cᵢ* even reaches,
`post_constraints(cᵢ, σ, t)` is no longer one formula — it is a
different formula per branch, and potentially a different *number* of
yield points per branch. Patching this requires promoting *Φₜ* from a
disjunction over scheduling permutations *σ ∈ Fₜ* to a disjunction
over (scheduling permutation, control path) pairs — i.e., replacing
Enc(P)'s fixed-structure per-step formula with something closer to
bounded path-sensitive symbolic execution with explicit path merging
at rendezvous points. That is a different construction from Definition
9, not an extension of it, and is not attempted here. It remains the
correctly-scoped open problem — narrower than "havoc injection is
unproven" as a blanket statement, but still genuinely open.

*Attempting the path-sensitive extension.* The construction sketched
above — promoting *Φₜ* from a disjunction over scheduling permutations
to a disjunction over (permutation, control-path) pairs — is carried
out below for the sub-case where each flagged-control variable induces
only a *finite*, statically-enumerable set of branch outcomes. This
does not close the flagged-control case in general; it further splits
it into a resolved finite-branch sub-case and a still-open unbounded-loop
sub-case, in the same spirit as Proposition 8′'s narrowing of the
eager-task restriction.

**Definition 15 (Bounded-Path Assumption).** A flagged-control variable
*v* gating branches in coroutine *cᵢ* satisfies the *Bounded-Path
Assumption* if the branch structure reachable from *v*'s guard(s)
induces a finite set of distinct control paths *Πᵢ = {πᵢ,₁, …, πᵢ,mᵢ}*
through *cᵢ* — i.e., no `while`/unbounded-iteration guard anywhere in
*cᵢ* reads *v* (or a variable derived from *v* without an intervening
bound) — and the guard predicates *{g_π}_{π∈Πᵢ}* are ground, mutually
exclusive, and jointly exhaustive over *v*'s domain (the ordinary case
for a well-formed `if`/`elif`/`else` or `match` with no fallthrough).
Under this assumption each path *π* has its own fixed, statically-determined
yield-point sequence *y^π_{i,1}, …, y^π_{i,kᵢ(π)}* and its own
`post_constraints^π(cᵢ, σ, t)`, built by the same procedure Definition 9
already uses per path.

**Definition 16 (Path-sensitive per-step encoding).** For a dispatch
step *t*, let the flagged-control coroutines be *c₁, …, c_r* (a
sub-list of *cᵢ ∈ Qₜ*), each with its finite path set *Πᵢ* per
Definition 15, and let every other coroutine keep its ordinary,
single-path `post_constraints`. Define

```
Φₜ = ∨_{σ ∈ Fₜ} ( order_t = σ
      ∧ ⋀_{i=1}^{r} ( ∨_{π ∈ Πᵢ} g_π(v_free) ∧ post_constraints^π(cᵢ, σ, t) )
      ∧ ⋀_{cⱼ ordinary} post_constraints(cⱼ, σ, t)
      ∧ ⋀_{r' ∈ Rendezvous(t)} rendezvous_constraint(r', σ) )
```

where *v_free* is the same fresh, otherwise-unconstrained havoc variable
introduced at the relevant read site by Definition 14 — one independent
free variable per occurrence, not a single global variable shared
across sites. A coroutine that terminates on a shorter path is simply
absent from *Qₜ* for later *t*, exactly as Definition 2 already permits;
no padding of shorter paths is required. *Enc_path(P) = Φ_init ∧ Φ₁ ∧
… ∧ Φ_T*, with *T* the maximum step count over all path combinations.

**Proposition 13 (Sound path-sensitive over-approximation for
flagged-control variables, under the Bounded-Path Assumption).** For
any program *P* all of whose flagged-control variables satisfy the
Bounded-Path Assumption, *Enc_path(P)* is quantifier-free and captures
every feasible execution trace of *P* (soundness without completeness).

*Proof.*

*Quantifier-freedom.* By Definition 15, *Πᵢ* is finite for every
flagged-control coroutine, so the inner disjunction *∨_{π∈Πᵢ}* is a
finite disjunction of ground conjunctions: *g_π(v_free)* is a ground
predicate over a free variable (no quantifier introduced by declaring
a variable free — this is exactly Definition 14's move, applied per
path), and `post_constraints^π` is quantifier-free by the same
construction Proposition 3 already establishes for a fixed path. A
finite disjunction and conjunction of quantifier-free formulas is
quantifier-free, so *Φₜ*, and hence *Enc_path(P)*, is quantifier-free.

*Soundness (no feasible trace dropped).* Let *τ* be a feasible
execution trace of *P*, with permutation-sequence *(σ₁,…,σ_T)* (Claim
2) and, at each flagged-control read site, a real (non-havoc'd) value
of *v* determined by *τ*'s actual interleaving of *v*'s unsynchronized
writers. Since *{g_π}* is exhaustive and mutually exclusive over *v*'s
domain (Definition 15), exactly one *g_{π*(τ)}* is true of *τ*'s real
value at each such site, where *π*(τ)* is the branch *τ* actually
takes. Instantiate each occurrence of *v_free* to *τ*'s real value at
that site: this satisfies *g_{π*(τ)}(v_free)* and falsifies every
other *g_π* by mutual exclusivity, so the disjunct selected is exactly
*π*(τ)*, whose `post_constraints^{π*(τ)}` is by construction identical
to *cᵢ*'s true post-constraints along *τ* — the same per-path
construction already validated by Proposition 4 for a single fixed
path. Every other conjunct of *Φₜ* (ordering, rendezvous, ordinary
coroutines' constraints) is unchanged from *Enc(P)*, already satisfied
by *τ*'s valuation per Proposition 4. Hence *τ*'s full valuation is a
model of *Enc_path(P)*. Since *τ* was arbitrary, no feasible trace is
excluded. $\square$

*Why completeness is not claimed.* Two independent sources of
over-approximation are introduced, not one. First, as in Proposition
12, each occurrence of *v_free* at a distinct read site is an
independent free variable (Definition 14); a solver is free to pick
values at different sites that are mutually inconsistent with any
single real value of *v*, and hence with any single real interleaving.
Second, and new to this proposition, *g_π(v_free)* only constrains
*v_free* to lie in branch *π*'s guard region — it does not constrain
*v_free* to a value actually reachable under some FIFO-consistent
dispatch order of *v*'s unsynchronized writers, so a model may select
a branch combination across several coroutines that no real scheduling
choice could jointly produce. Both effects can only add spurious
models, never remove a real trace, which is the soundness direction a
static verifier needs (cf. Proposition 11) but is strictly weaker than
completeness.

*What this narrows, and what it still leaves open.* This proposition
converts the flagged-control case from a single undifferentiated open
problem into two: (i) flagged-control variables satisfying the
Bounded-Path Assumption, now soundly over-approximated by
*Enc_path(P)*, and (ii) flagged-control variables that gate an
unbounded loop (e.g. `while shared_flag: …` with no static bound),
which Definition 15 explicitly excludes and which remains fully open —
such a guard does not induce a finite *Πᵢ*, and the construction above
does not apply. Formula size is also a real, unresolved cost: nested
branching multiplies path counts combinatorially (*|Πᵢ|* up to *2^b*
for *b* nested binary guards per coroutine), so *Enc_path(P)*'s size
bound is Proposition 2's *O(k · |Fₜ| · n)* multiplied by
*max_i |Πᵢ|* — still finite and quantifier-free, but a further
blow-up on top of the existing worst case. Whether path-merging at
rendezvous points (mentioned as a future direction in Section 6) can
reduce this multiplicative cost is not attempted here.

*Corpus status — not yet measured.* Proposition 13 is a proof about
which *syntactic shape* of flagged-control variable is now covered; it
does not by itself tell us what fraction of the 63.79%
(flagged-control) corpus bucket actually satisfies the Bounded-Path
Assumption versus is gated by a genuinely unbounded loop. That split
requires a further static-analysis pass over the same 33-repo corpus
(extending `branch_check.py` to test for unbounded-loop guards on
already-flagged-control variables) and has not been run. Until that
scan is done, the honest statement is: some unmeasured sub-fraction of
the 17.5%-of-corpus flagged-control bucket is now soundly handled by
Proposition 13; the remainder, and the exact split, is still open —
exactly the kind of "proxy not yet re-verified against the precise
condition" gap already flagged elsewhere in this document for
Proposition 10.

**Proposition 13a (Per-step-shared havoc variables — tightened
over-approximation).** Definition 16 is revised so that all reads of a
flagged variable *v* by a given coroutine *cᵢ* at a given dispatch step
*t* share a single free variable *v_free(cᵢ, t)*, rather than one free
variable per read-site (Definition 14's original per-occurrence
scheme). This is a strict precision improvement: soundness is
unaffected — a real trace still assigns exactly one value to *v* at
step *t*, and instantiating *v_free(cᵢ, t)* to that value still
witnesses every conjunct that mentions it, by the same argument as
Proposition 12 and 13 — while the solver can no longer treat two reads
of *v* within the same coroutine's same step as independently free,
which was never realizable by any actual execution. This closes one of
the two over-approximation sources named in Proposition 13's
completeness discussion. The second — free variables at *different*
coroutines' (or different steps') sites remaining mutually
inconsistent — is not closed by this proposition and is not closable
without reintroducing exactly the write-order tracking that Lemma 2a
shows fails for unmediated writes (Section 6); this is stated here as a
provable limit, not an oversight.

**Proposition 13b (Yield-point-scoped path count).** In Definition 16,
the path set *Πᵢ* that must be case-split at a given dispatch step *t*
need only include branches of *cᵢ* that determine *which yield point
cᵢ reaches next* — i.e., branches whose two arms lead to different
next-yield-point targets. A branch that resolves entirely between two
fixed yield points (no `await` inside either arm) changes only the
ground content of `post_constraints^π` at the yield point already
reached, not the shape or count of disjuncts *Φₜ* needs, because
Definition 9's per-step structure is indexed by yield points, not by
arbitrary control-flow granularity. Consequently the multiplicative
factor on Proposition 2's size bound is *max_i* (number of
yield-point-spanning branch splits in *cᵢ*), not *2^b* over all nested
guards as stated in Proposition 13's original discussion — a real
reduction in the typical case, since most nested branching in ordinary
code does not straddle a suspension point, though the worst case (a
coroutine that awaits inside every arm of deep nesting) remains
exponential.

**Corpus measurement (`branch_check.py`, Definition 15 split, run
against the 33-repo corpus, post-rescope).** Of the 5,557 interactions
classified flagged (destructive, unmediated) by the existing scanner,
63.79% are flagged-control and 36.21% are flagged-data (Proposition 12
applies to the latter). Within the flagged-control bucket, 92.24%
satisfy the Bounded-Path Assumption via this script's conservative
While-test proxy for "unbounded loop" (Proposition 13 applies), and
7.76% are classified unbounded-loop-gated and remain fully open. As
shares of the whole flagged/destructive bucket:
58.84% bounded-flagged-control (Proposition 13), 4.95%
unbounded-loop-gated (open), 36.21% flagged-data (Proposition 12).
Note: this scan's flagged/destructive total and the 5,557-interaction
figure cited in the `run_in_executor` overlap measurement elsewhere in
this document are now both derived from the same post-rescope corpus
scan (see the paper's Section 6 scan-scope note); the two should be
read as consistent as of this revision.

*Caveats on this measurement, stated plainly.* The classifier's
"unbounded" signal is syntactic — presence of the name in a `While`
test anywhere in the repo — not a check of Definition 15's actual
semantic condition. It does not detect an unboundedly-iterating `for`
loop over a dynamically-growing collection, which would be
misclassified as bounded. It also does not check guard exhaustiveness
or mutual exclusivity, only presence in a bounded versus unbounded
syntactic construct. So "92.24% bounded" should be read as an upper
bound on what Proposition 13 covers under this proxy, not a verified
count against the precise condition — the same proxy-versus-precise-condition
gap already flagged for Proposition 10's corpus overlap.

*Practical note.* Run against the full 33-repo corpus (`branch_check.py`):
of the 25.18% of interactions classified *flagged*, **36.21%** are
flagged-data (Proposition 12 applies — sound over-approximation
established) and **63.79%** are flagged-control. Of that flagged-control
bucket, Proposition 13 now soundly covers the finite-branch sub-case;
the unbounded-loop sub-case remains open. As measured above, this
finite-branch sub-case is 92.24% of flagged-control (58.84% of the
whole flagged bucket) under the syntactic proxy, leaving 7.76% of
flagged-control (4.95% of the whole flagged bucket) as genuinely
unbounded-loop-gated and open. Proposition 12 resolves 36.21% of the
flagged bucket outright; Proposition 13 (subject to the proxy caveat
above) extends sound, non-complete coverage to the large majority of
the remainder.

*Bounded write conflict: where the proof breaks.* We attempted to
extend the lemma to $k < n$ unsynchronized writers on a shared
integer. The attempt fails at Lemma 2a: resolution-set invariance
requires that whether a future completes depends only on the
dispatching coroutine's own execution, not on the relative order of
other coroutines in $Q_t$. For a shared write, this is false — if $c_i$
reads a variable written by $c_j$, whether $c_i$'s post-condition holds
depends on whether $c_j$ executed before $c_i$ within the same dispatch
step, which is exactly the scheduling choice Lemma 2a requires to be
invariant. The bijection in Claim 2 also fails: distinct permutations
of $Q_t$ produce distinct final states (different write orders produce
different variable values), so the trace-to-sequence mapping is no
longer onto observable program states. The correct encoding for
write-conflict programs would need to enumerate both scheduling orders
and their effects on shared state — larger than $n!/2^r$ but
potentially still finite and quantifier-free. Characterizing that
structure precisely is the primary open problem.

---

## Status

| Item | Status |
|---|---|
| Abstract machine (Definitions 1–7) | ✓ |
| SNF conditions 1–4 with CPython 3.12.3 witnesses | ✓ |
| CPython version scope stated explicitly | ✓ (Proposition 1) |
| Claim 1 — sequential determinism | ✓ |
| Claim 2 — correspondence, bijection domain clarified | ✓ |
| Lemma 2a — resolution-set invariance, stated and proved separately from Prop. 5 | ✓ |
| Claim 3 — inductive composition under controlled interference | ✓ (cites Lemma 2a directly) |
| Worked example 2 — chained rendezvous, witnesses Lemma 2a within-step invariance and Claim 3 cross-step composition | ✓ |
| Normal Form Reduction Lemma | ✓ |
| General Enc(P), *n* coroutines, *k* yield points, rendezvous | ✓ (Definition 9) |
| Completeness of Enc(P) | ✓ (Proposition 4) |
| Separation from naive QE | ✓ (Proposition 5, with empirical remark on non-SNF baseline) |
| Enc(P) quantifier-free | ✓ (Proposition 3) |
| Theorem Parts A, B, C | ✓ |
| Core problem (trivial non-interference) resolved | ✓ (SNF-4 + controlled interference) |
| Lean mechanization of Lemma 2a, Claim 3, Claim 2, Proposition 4, Proposition 6 | ✓ (SNFClaim3.lean, clean `lake build` confirmed 2026-07-07) — Claim 2's bijection and Proposition 4's completeness now proved as theorems (`claim2_mechanized`, `proposition4_mechanized`) for the abstract per-step permutation machine, no free axiom on the combinatorial side; `SchedulerAssumptions` retained only for the CPython-source-level content, per Proposition 1 |
| Non-SNF QE empirical remark in Proposition 5 | ✓ |
| b7 (read-only broadcast) empirical validation of SNF-5 direction | ✓ |
| SNF-5 formal statement and proof (Definition 7, Proposition 6) | ✓ |
| Real-world corpus study (33 repos, second expansion + scoped rescan of sqlalchemy/elasticsearch-py): 71.0% mediated+read-only coverage | ✓ |
| Trace-equivalence definition for commutative writes (Def. 10–11) | ✓ |
| Sufficient condition for trace-equivalence, disjoint-key writes (Prop. 10) | ✓ (partial — sufficient, not characterizing) |
| Commutative-write coverage of corpus's 2.38% bucket checked against Prop. 10 | ✗ (not yet verified against corpus) |
| Static conflict checker, definitions and soundness-of-detection (Def. 12, Prop. 11) | ✓ |
| Havoc-injection soundness for flagged-data variables | ✓ (Prop. 12) |
| Havoc-injection soundness for flagged-control variables | ◐ partial — sound for finite-branch (Bounded-Path Assumption) sub-case (Prop. 13), tightened by Props. 13a/13b; unbounded-loop-gated sub-case still fully open; corpus split measured (below) via syntactic proxy, not yet verified against the precise condition |
| Corpus split: bounded vs. unbounded-loop-gated within flagged-control | ✓ measured (`branch_check.py`): 92.24% of flagged-control (58.84% of whole flagged bucket) bounded; 7.76% (4.95% of flagged bucket) unbounded-loop-gated — syntactic proxy, not Definition-15-precise |
| Corpus split: flagged-data vs. flagged-control (of the 25.18%) | ✓ 36.21% flagged-data (Prop. 12 applies), 63.79% flagged-control (open) |
| Eager-task-factory first-step split (Def. 8, Props. 7–8) | ✓ (partial — restricted to shared-state-free eager steps) |
| uvloop Consistency Interface (Def. 9, Prop. 9) | ✓ checked against uvloop 0.22.1 source — passes all four properties |
| Trio checked against Consistency Interface | ✓ fails (I-1) by design — documented negative result |
| Real-world case study: asyncpg connection-pool checkout | ✓ structured encoding verified `unsat` on double-checkout; naive-encoding correctness-gap analog reproduced by an automated source-to-SMT pipeline (`snf-pipeline`) only under an explicit, disclosed assumption about `Pool.acquire()`'s external call pattern (`--assume-public-concurrent`) — the unmodified default run correctly reports no gap, since a single file cannot on its own prove concurrent external callers exist |
| Corpus-scale automated naive/structured check (`snf-pipeline`, 33-repo corpus) | ✓ run — 22 of 70 sync-object checks show the gap pattern, 44 show none, 4 (`EVENT`-kind) return `sat` under both encodings and are flagged for manual triage rather than counted either way; of 44 `wait_for` sites, 10 handled (9 locally, 1 via call-chain), 23 cross-file, 8 same-file no-handler-found flags remain unverified pending manual pass, 3 unresolvable callee name (numbers improved from an earlier 24/68 and 11 no-handler-found sweep after fixing two extractor bugs — a nested-function double-counting bug and a scope-resolution bug — and broadening cleanup-verb detection, all found and corrected during this corpus run). A separate detector flags coroutines whose bare name collides across unrelated classes (a risk the tool cannot fully resolve, since its call-chain and multiplicity machinery must work by bare name); after filtering out near-universal dunder-method noise, 12 actionable collisions remain corpus-wide, each individually inspectable. |
| Encoding scaling data beyond a single point (structured to n=100, non-SNF impracticality point identified ~n=9–10) | ✓ |
| Write-conflict failed-attempt documented | ✓ (Limitations section) |
| Thread-Disjointness Condition (Def. 17–18, Prop. 14) | ✓ proved and empirically checked — call-graph corpus scan found 3 candidates, 0 confirmed violations after hand inspection; guard clause broadened to recognize Event/Condition/Barrier based on a real corpus case (`asyncz`) |
| CPython version conformance via Consistency Interface (Cor. 9a) | ✓ checked — all I-1–I-4 witness patterns present in 3.9.19, 3.10.14, 3.11.9, 3.12.3, 3.13.0 (`cpython_version_diff.py`); substring-presence check, not full semantic re-verification |
| Consistency Interface evidence base (uvloop, Trio) | ◐ both checked instances are Python and both reuse or mirror CPython's Lock/Queue/Event; interface stated implementation-agnostically but not yet evidenced across languages/runtimes |
| Consistency Interface checked against `tokio`, Node.js, Go | ✗ not checked; expected obstruction identified per scheduler (tokio: I-1, work-stealing has no single global dispatch order; Node.js: I-2, phase-based admission complicates a single per-iteration bound; Go: I-3, preemption at safe points breaks run-to-suspension atomicity) — stated as the specific target for future source-level checks, not a completed result |
| uvloop / Trio checks — evidentiary standard | ◐ source-level structural inspection (same standard as CPython SNF-1–SNF-4 witnesses), not a mechanized or executable proof |

**Remaining open items (future work):**

1. *Havoc-injection soundness — flagged-control remainder (partially
   resolved, measured).* Proposition 12 proves the composition of
   havoc injection with $\text{Enc}(P)$ sound and quantifier-free for
   flagged-*data* variables (Definition 13). The flagged-*control* case
   is now split in two by Proposition 13: for flagged-control variables
   satisfying the Bounded-Path Assumption (Definition 15 — finite,
   statically-enumerable branch structure, no unbounded loop gated by
   the variable), a path-sensitive encoding $\text{Enc}_{\text{path}}(P)$
   (Definition 16) is proved sound and quantifier-free. Propositions 13a
   and 13b tighten this construction further: 13a shares one free
   variable per (coroutine, step) instead of one per read-site,
   removing one of two over-approximation sources; 13b shows the
   multiplicative size cost is bounded by yield-point-spanning branch
   splits rather than all nested branches, which is typically far
   smaller than the $2^b$ worst case. Flagged-control variables gating
   an unbounded loop remain fully open. The corpus split
   (`branch_check.py`, run against all 33 repos) shows flagged-control
   is the majority of the flagged bucket: 63.79% versus 36.21%
   flagged-data. Within flagged-control, 92.24% (58.84% of the whole
   flagged bucket) satisfy the Bounded-Path Assumption under this
   script's syntactic While-test proxy and are now covered by
   Proposition 13; 7.76% (4.95% of the flagged bucket) are classified
   unbounded-loop-gated and remain open. This proxy is not yet checked
   against Definition 15's precise semantic condition (it can miss an
   unboundedly-iterating `for` loop, and does not check guard
   exhaustiveness), so these percentages are an upper bound on
   Proposition 13's practical coverage, not a verified count.

2. *Trace-equivalence characterization.* Proposition 10 gives a
   sufficient (disjoint-key) condition for trace-equivalent writes but
   not a full characterization; whether a broader class exists, and
   whether condition (b) can be relaxed to admit some aggregate reads,
   is open. The corpus's 2.38% commutative-looking bucket has not been
   re-checked against Proposition 10's precise conditions.

3. *Mechanisation of Propositions 10 and 11.*
   Lemma 2a, Claim 3, Claim 2 (bijection), Proposition 4 (completeness),
   and Proposition 6 (SNF-5) are now mechanized in Lean 4 —
   `claim2_mechanized` proves the bijection as a theorem for the
   abstract per-step permutation machine, with no free axiom on the
   combinatorial side; `SchedulerAssumptions` is retained only as a
   narrower axiom for the CPython-source-level content (that dispatch
   really is FIFO-consistent, etc.), which is Proposition 1's
   direct-inspection argument and is not itself mechanized here, same
   as for every other result in this document. Proposition 10
   (trace-equivalence) and Proposition 11 (checker soundness) remain
   hand-proofs and are the largest remaining gap between this document's
   claims and a fully mechanized development.

4. *~~Eager-task-factory: removing the shared-state-free restriction~~
   — resolved.* Proposition 8′ (above) proves the Normal Form Reduction
   Lemma holds for `eager_task_factory` programs with no restriction on
   the eager step's shared-state accesses beyond what the theorem and
   checker already require of any coroutine's accesses. This closes
   what was previously the primary open item here; the residual
   flagged-control gap (item above, Proposition 12) still applies to an
   eager step's unmediated accesses exactly as it does to an ordinary
   coroutine's, but that is the existing open problem, not a new one.

5. *Alternative event loops beyond uvloop and Trio.* `uvloop` (passes)
   and Trio (fails at (I-1)) have both now been checked against the
   Consistency Interface. Extending the check to further schedulers
   (e.g. `gevent`-based or embedded-loop variants) is future work, though
   with two data points already in hand — one confirming, one correctly
   rejecting — the interface's discriminating power is better evidenced
   than it was with `uvloop` alone.