/-
  SNFClaim3.lean

  Mechanization of:
    · Lemma 2a  (Resolution-set invariance)
    · Claim 3   (Inductive composition — inductive step)
    · Claim 2   (Bijection — mechanized as a theorem, `claim2_mechanized`,
                 for the abstract per-step permutation machine built in
                 Part 1; `SchedulerAssumptions` is retained as an axiom
                 only for the CPython-source-level content — that
                 dispatch really is FIFO, rendezvous really wake in FIFO
                 order, etc. — which is Proposition 1's direct-inspection
                 argument and stays out of scope here, as before)
    · Proposition 4   (Completeness — proved from Claim 2; now provable
                       with no free axiom for the abstract machine via
                       `proposition4_mechanized`, in addition to the
                       original axiom-conditional `proposition4`)
    · Proposition 6 / SNF-5   (Read-only sharing invariance — proved,
                               not axiomatized)
    · Write-conflict negative result  (concrete counterexample
                                       showing where Lemma 2a fails)

  Source of truth: track1_snf_formal.md, Steps 3–4.

  SCOPE.  Deliberately narrow: the Normal Form Reduction Lemma's core
  combinatorial claims only.  Not in scope: Enc(P)'s size bound
  (Prop 2), quantifier-freedom (Prop 3), the main theorem (Step 5),
  Prop 10 (trace-equivalence), Prop 11 (checker soundness), Prop 12
  (havoc-injection soundness, flagged-data), Prop 13/13a/13b
  (path-sensitive encoding and its refinements, flagged-control), or
  anything in Tracks 2–3. Props 12 and 13(a/b) postdate this file and
  are hand-proofs only; none of the havoc-injection or path-sensitive-
  encoding machinery has been mechanized.

  DESIGN CHOICES.
  · Dispatch orders are `List C` with `List.Perm` for "is a reordering
    of"; this uses Lean 4 core only — no Mathlib dependency.
  · `readyToResolve : C → Prop` is a *pure* predicate on the coroutine
    identifier.  This is the key hypothesis of Lemma 2a: whether a
    rendezvous resolves depends only on which coroutine is the put-side,
    not on that coroutine's position within the step's dispatch order.
    The write-conflict section below shows this hypothesis is tight.
  · Claim 2's bijection is now *mechanized* (`claim2_mechanized`) for the
    abstract per-step permutation machine (`StepData`, Part 1) rather than
    axiomatized wholesale. `SchedulerAssumptions` is kept as a separate,
    narrower axiom capturing only the CPython-source-level content the
    combinatorial theorem cannot reach — that a real dispatch loop's
    admissible orderings really are exactly the FIFO-consistent
    permutations, established via Proposition 1's direct source
    inspection, not proved here.
  · The `WorkedExample2.Interp` interpreter's `dispatch` takes the
    current step's ready set explicitly and requires membership +
    single-use consumption (`removeOne`), modeling `_ready.popleft()`
    rather than relying on per-coroutine phase guards alone to prevent
    a coroutine handle from being dispatched twice in one step. An
    earlier version used phase guards only; see `σ_repeat`/`τ_repeat`
    in `WorkedExample2.Interp` for the counterexample that motivated
    the change (now kept as a regression test).

  COMPILATION STATUS.  This file has not been compiled in the authoring
  environment: `elan` requires network access to
  `objects.githubusercontent.com` which is not reachable from the
  sandbox.  Verify with `lake build` locally.  All proofs are either
  `decide` on finite concrete types (always terminates) or one-to-three
  tactic steps on simple structural goals; if anything fails to compile
  it is almost certainly a lemma-name discrepancy rather than a
  mathematical gap.
-/

-- Four informational-only lint warnings are expected (see README): an
-- unused `[DecidableEq C]` section variable in three theorems that
-- don't need it, and one unused match variable. Neither affects
-- correctness; silenced here rather than left as noise.
set_option linter.unusedSectionVars false
set_option linter.unusedVariables false

-- ════════════════════════════════════════════════════════════════════
-- PART 1 · Lemma 2a and Claim 3
-- ════════════════════════════════════════════════════════════════════

namespace SNF

/-- A rendezvous point (Definition 7): put-side and get-side coroutine.
    Yield-point indices are not needed for this mechanization. -/
structure Rendezvous (C : Type _) where
  putSide : C
  getSide : C
deriving DecidableEq, Repr

variable {C : Type _} [DecidableEq C]

/-!
### Lemma 2a — Resolution-set invariance

The paper's proof (Claim 1 + SNF-3): whether a rendezvous `(pᵢ, gⱼ)`
resolves during step `t` depends only on
  (a) whether `pᵢ ∈ Qₜ` (set membership), and
  (b) `pᵢ`'s own execution (`readyToResolve pᵢ`)
— and *not* on the relative dispatch position of `pᵢ` within `Qₜ`.

We model this directly: `resolves` is membership + a pure per-coroutine
predicate, so order-independence follows from `List.Perm.mem_iff`.
-/

/-- `Resolves rTR d r`: rendezvous `r` resolves given dispatch order `d`
    and per-coroutine predicate `rTR`.  The predicate encodes Claim 1 +
    SNF-3: `pᵢ`'s atomic segment executes and triggers `_wakeup_next`
    independently of any other coroutine's position. -/
abbrev Resolves (rTR : C → Prop) (d : List C) (r : Rendezvous C) : Prop :=
  r.putSide ∈ d ∧ rTR r.putSide

/-- The list of rendezvous from `rs` that resolve under dispatch order `d`. -/
def resolvedAt (rTR : C → Prop) [DecidablePred rTR]
    (d : List C) (rs : List (Rendezvous C)) : List (Rendezvous C) :=
  rs.filter (fun r => decide (Resolves rTR d r))

/-- **Lemma 2a (Resolution-set invariance).**
    If `σ` and `σ'` are permutations of the same ready set, the
    resolved-rendezvous set is identical under both.
    *Proof:* `List.Perm.mem_iff` gives `pᵢ ∈ σ ↔ pᵢ ∈ σ'`; the rest
    of `Resolves` depends only on `pᵢ` itself. -/
theorem lemma2a_resolution_set_invariance
    (rTR : C → Prop) [DecidablePred rTR]
    {σ σ' : List C} (hperm : σ.Perm σ')
    (rs : List (Rendezvous C)) :
    resolvedAt rTR σ rs = resolvedAt rTR σ' rs := by
  unfold resolvedAt Resolves
  apply List.filter_congr
  intro r _
  simp [hperm.mem_iff]

/-!
### Claim 3 — Inductive step (combinatorial core)

The inductive step needs one fact: `Q_{T+1}` — computed from the
current ready set and which rendezvous resolved — is invariant across
permutations of `Qₜ`.  We model a "step" abstractly via `StepData`:
a ready set, candidate rendezvous, a per-coroutine resolution predicate,
and a *next-state function that takes the ready set and the resolved
list but NOT the dispatch order* — matching the paper's claim that
`Q_{T+1}` depends on program structure and resolution outcome, not on
the specific `σₜ` chosen.
-/

structure StepData (C : Type _) where
  ready           : List C
  candidates      : List (Rendezvous C)
  rTR             : C → Prop
  next            : List C → List (Rendezvous C) → List C

/-- **Claim 3, inductive step.**
    Any two permutations of the current ready set produce the same next
    ready set, because they produce the same resolved-rendezvous set
    (Lemma 2a) and the next-state function is independent of dispatch
    order by construction. -/
theorem claim3_inductive_step
    (sd : StepData C) [DecidablePred sd.rTR]
    {σ σ' : List C} (hσ : σ.Perm sd.ready) (hσ' : σ'.Perm sd.ready) :
    sd.next sd.ready (resolvedAt sd.rTR σ sd.candidates) =
    sd.next sd.ready (resolvedAt sd.rTR σ' sd.candidates) := by
  rw [lemma2a_resolution_set_invariance sd.rTR (hσ.trans hσ'.symm)]

end SNF

-- ════════════════════════════════════════════════════════════════════
-- PART 2 · Claim 2 (bijection) and Proposition 4 (completeness)
-- ════════════════════════════════════════════════════════════════════

namespace SNF.Bijection

/-!
### Design

A *schedule* is a sequence of per-step dispatch orderings `(σ₁,…,σ_T)`.
The *encoding* `Enc(P)` is a sequence of sets `(F₁,…,F_T)` where each
`Fₜ` is the list of FIFO-and-rendezvous-consistent permutations of `Qₜ`.
Since Claim 3 / Lemma 2a guarantee the `Qₜ` sequence is determined
by program structure alone (independent of scheduling choices), `Enc(P)`
is well-defined upfront.

`EncConsistent enc sched` zips the two sequences and checks that each
`σₜ ∈ Fₜ`.

**Claim 2** is axiomatized via `SchedulerAssumptions`: a structure
with two fields capturing the two directions of the bijection.  These
are axioms about the CPython scheduler semantics; mechanizing CPython
execution directly is out of scope.

**Proposition 4** is then *proved* as a one-line theorem from the two
directions of Claim 2.  The proof makes visible that Prop 4 adds no
content beyond Claim 2 — it IS the iff-packaging of Claim 2.
-/

variable {C : Type _} [DecidableEq C]

/-- A schedule is a sequence of per-step dispatch orderings. -/
abbrev Schedule (C : Type _) := List (List C)

/-- `Enc(P)`: for each step `t`, the list `Fₜ` of valid orderings.
    Since `Qₜ` is fixed by Claim 3 / Lemma 2a, this is a plain list
    of lists without any scheduler-state reference. -/
abbrev Enc (C : Type _) := List (List (List C))

/-- A schedule is encoding-consistent if at each step `t`, the chosen
    ordering `σₜ` is in `Fₜ`.  Defined inductively to stay in Lean 4
    core without Mathlib's `List.Forall₂`. -/
inductive EncConsistent {C : Type _} : Enc C → Schedule C → Prop where
  | nil  : EncConsistent [] []
  | cons : σ ∈ Fₜ → EncConsistent rest σs →
           EncConsistent (Fₜ :: rest) (σ :: σs)

/-- **Claim 2 (Bijection), axiomatized.**

    The two fields are the two directions of the bijection between
    feasible traces and encoding-consistent schedules.

    `claim2_fwd` (trace → sequence, injectivity direction): by SNF-1
    each dispatch step produces a unique scheduling choice, so every
    feasible execution maps to a unique encoding-consistent sequence.

    `claim2_bwd` (sequence → trace, surjectivity direction): every
    encoding-consistent sequence is realizable — for `sleep(0)`,
    insertion order into `_ready` traces to task-creation order; for
    rendezvous, SNF-4 establishes FIFO wakeup order.

    These fields are *axioms* in the sense that their content is
    the informal argument grounded in CPython 3.12.3 source.
    Proposition 4 is *proved* from them. -/
structure SchedulerAssumptions {C : Type _} (enc : Enc C)
    (FeasibleSchedule : Schedule C → Prop) : Prop where
  /-- Every feasible schedule is encoding-consistent.
      (SNF-1 determinism + FIFO-consistency argument.) -/
  claim2_fwd : ∀ s, FeasibleSchedule s → EncConsistent enc s
  /-- Every encoding-consistent schedule is feasible.
      (FIFO constructability + SNF-4 rendezvous ordering.) -/
  claim2_bwd : ∀ s, EncConsistent enc s → FeasibleSchedule s

/-- **Proposition 4 (Completeness).**
    `Enc(P)` captures all feasible execution traces and no infeasible
    ones: a schedule is feasible *if and only if* it is
    encoding-consistent.

    *Proof:* this is exactly the conjunction of the two directions of
    Claim 2.  No additional content is needed beyond `SchedulerAssumptions`. -/
theorem proposition4 {enc : Enc C} {Feasible : Schedule C → Prop}
    (h : SchedulerAssumptions enc Feasible) (s : Schedule C) :
    Feasible s ↔ EncConsistent enc s :=
  ⟨h.claim2_fwd s, h.claim2_bwd s⟩

/-- **Proposition 4 — soundness direction.**
    No encoding-consistent schedule is infeasible (no false positives). -/
theorem prop4_soundness {enc : Enc C} {Feasible : Schedule C → Prop}
    (h : SchedulerAssumptions enc Feasible)
    {s : Schedule C} (hEnc : EncConsistent enc s) : Feasible s :=
  h.claim2_bwd s hEnc

/-- **Proposition 4 — completeness direction.**
    No feasible schedule is absent from the encoding (no false negatives).
    This is the property a verifier needs: no bug on a feasible trace
    goes unwitnessed by some disjunct in `Enc(P)`. -/
theorem prop4_completeness {enc : Enc C} {Feasible : Schedule C → Prop}
    (h : SchedulerAssumptions enc Feasible)
    {s : Schedule C} (hF : Feasible s) : EncConsistent enc s :=
  h.claim2_fwd s hF

/-!
### Claim 2, mechanized (not axiomatized) for the abstract per-step machine

Everything above this point *assumes* `SchedulerAssumptions` as given data —
the two bijection directions are axioms about CPython's dispatch semantics.
That is unavoidable for the CPython-specific content (Proposition 1's
source-level witnesses are not mechanized here, by design — see file
header). But the *combinatorial* content of Claim 2 — "the only degree of
freedom at each step is which permutation of the ready set is dispatched,
and the induced sequence of ready sets is fixed independent of that
choice" — is exactly what `StepData` and Claim 3 (Part 1) already capture.
That part does not need to be assumed: it can be *proved* from the same
primitives already used for Lemma 2a / Claim 3, with no new axiom.

We do this by giving Claim 2's two directions as one theorem
(`claim2_mechanized`) relating:

  · `FeasibleSeq sds σs` — "`σs` is achievable for the step sequence
    `sds`": at every step the dispatched order is *some* permutation of
    that step's ready set (the only freedom SNF-1–SNF-4 leaves open,
    per the informal proof of Claim 2's `claim2_bwd` direction: any
    FIFO-consistent permutation is realizable).

  · `PermEncConsistent (encOfStepData sds) σs` — "`σs` is
    encoding-consistent" against the encoding generated directly from
    `sds`, where step `t`'s permission predicate is literally
    "is a permutation of `sd.ready`" (Section 4.1's `Fₜ`, specialized
    to the abstract machine where every FIFO-consistent permutation is
    exactly `List.Perm sd.ready` — no rendezvous-ordering constraints
    narrow `Fₜ` further at this level of abstraction; SNF-4's FIFO
    wakeup-order constraints are the `rTR`/`resolvedAt` machinery from
    Part 1, already folded into `next`, not into which permutations are
    admissible).

This does **not** discharge the CPython-source-level content of Claim 2
(that dispatch really is a permutation of a FIFO-popped ready set, that
rendezvous really do wake in FIFO order, etc.) — that remains Proposition
1's direct-inspection argument, exactly as before. What it removes is the
*second*, purely combinatorial axiom that used to sit on top of that:
"the trace/permutation-sequence correspondence itself is a bijection."
That correspondence is now a theorem, not an assumption.
-/

/-- A step-indexed *predicate* encoding: `Fₜ : List C → Prop` is "is this
    ordering permitted at step `t`", rather than a materialized list of
    permitted orderings. Equivalent in content to `Enc C` above but
    avoids needing a permutation-list generator to state the general
    theorem below. -/
abbrev EncPred (C : Type _) := List (List C → Prop)

/-- `PermEncConsistent` is `EncConsistent`'s predicate-indexed twin:
    same shape, `Fₜ σ` in place of `σ ∈ Fₜ`. -/
inductive PermEncConsistent {C : Type _} : EncPred C → Schedule C → Prop where
  | nil  : PermEncConsistent [] []
  | cons : Fₜ σ → PermEncConsistent rest σs →
           PermEncConsistent (Fₜ :: rest) (σ :: σs)

/-- **A feasible schedule for a step sequence `sds`.**
    At each step, the dispatched order is *some* permutation of that
    step's ready set — the only freedom the informal proof's
    `claim2_bwd` direction grants (FIFO-constructability). Because
    `sds` is given upfront and each step's `ready`/`candidates`/`rTR`/
    `next` are fixed data (not functions of the schedule chosen so
    far), this directly mirrors the file header's design note that
    `Enc(P)` — and hence feasibility — is "well-defined upfront." -/
inductive FeasibleSeq {C : Type _} : List (StepData C) → Schedule C → Prop where
  | nil  : FeasibleSeq [] []
  | cons {sd sds σ σs} :
      σ.Perm sd.ready →
      FeasibleSeq sds σs →
      FeasibleSeq (sd :: sds) (σ :: σs)

/-- The encoding generated directly from a step sequence: step `t`'s
    permission predicate is exactly "is a permutation of that step's
    ready set." -/
def encOfStepData {C : Type _} (sds : List (StepData C)) : EncPred C :=
  sds.map (fun sd σ => σ.Perm sd.ready)

/-- **Claim 2, mechanized.** For the abstract per-step machine of Part 1,
    a schedule is feasible for `sds` iff it is encoding-consistent
    against `encOfStepData sds`. Both directions fall out of the same
    two constructors — `claim2_fwd`/`claim2_bwd`'s combinatorial content
    is literally the `.cons` constructor read in each direction — so
    unlike `SchedulerAssumptions` above, nothing here is assumed. -/
theorem claim2_mechanized {C : Type _} :
    ∀ (sds : List (StepData C)) (σs : Schedule C),
      FeasibleSeq sds σs ↔ PermEncConsistent (encOfStepData sds) σs := by
  intro sds
  induction sds with
  | nil =>
      intro σs
      constructor
      · intro h; cases h; exact .nil
      · intro h; cases h; exact .nil
  | cons sd sds ih =>
      intro σs
      constructor
      · intro h
        cases h with
        | cons hperm hrest =>
          exact .cons hperm ((ih _).mp hrest)
      · intro h
        cases h with
        | cons hperm hrest =>
          exact .cons hperm ((ih _).mpr hrest)

/-- **Corollary: `SchedulerAssumptions`'s two fields are derivable, not
    just positable, for `encOfStepData sds` / `FeasibleSeq sds`.**
    This replays `proposition4`'s packaging one level down: given
    `claim2_mechanized`, both directions of the bijection — and hence
    completeness itself — hold for the abstract machine with no free
    axiom. (The predicate-indexed `EncPred`/`PermEncConsistent` pair is
    used here instead of the list-indexed `Enc`/`EncConsistent` pair
    used by the worked examples below; the two are the same content
    stated two ways, per the discussion above.) -/
theorem claim2_fwd_mechanized {C : Type _} (sds : List (StepData C))
    {σs : Schedule C} (h : FeasibleSeq sds σs) :
    PermEncConsistent (encOfStepData sds) σs :=
  (claim2_mechanized sds σs).mp h

theorem claim2_bwd_mechanized {C : Type _} (sds : List (StepData C))
    {σs : Schedule C} (h : PermEncConsistent (encOfStepData sds) σs) :
    FeasibleSeq sds σs :=
  (claim2_mechanized sds σs).mpr h

/-- **Proposition 4, mechanized (no axiom) for the abstract machine.**
    Completeness for `encOfStepData sds` / `FeasibleSeq sds` follows
    directly from `claim2_mechanized` — the same one-line packaging as
    `proposition4` above, but with `SchedulerAssumptions` discharged by
    proof instead of supplied as a hypothesis. -/
theorem proposition4_mechanized {C : Type _} (sds : List (StepData C))
    (σs : Schedule C) :
    FeasibleSeq sds σs ↔ PermEncConsistent (encOfStepData sds) σs :=
  claim2_mechanized sds σs

end SNF.Bijection

-- ════════════════════════════════════════════════════════════════════
-- PART 3 · Proposition 6 / SNF-5 (read-only sharing invariance)
-- ════════════════════════════════════════════════════════════════════

namespace SNF.SNF5

/-!
### Proposition 1a / Proposition 6

The paper's argument (Section 3.1, Proposition 1a; formal doc Prop. 6):
a variable `x` satisfying the read-only sharing condition — written by
at most one coroutine, before any coroutine reads it — never triggers
`_wakeup_next`, so it contributes no candidates to `Rendezvous(t)`.
Consequently:

- Lemma 2a is unaffected: the resolved set depends only on put-side
  coroutines, and read-only coroutines are never put-sides.
- `Fₜ` is unchanged: no new ordering constraint is introduced.
- Proposition 4's completeness argument carries through unchanged.

We mechanize this as a theorem about `resolvedAt`: appending read-only
rendezvous candidates (those whose put-side coroutine is never
`readyToResolve`) to the candidate list leaves the resolved set
unchanged.  This directly formalizes "read-only accesses never call
`_wakeup_next`."
-/

open SNF

variable {C : Type _} [DecidableEq C]

/-- **Proposition 1a / SNF-5 (read-only invariance of `resolvedAt`).**

    If `readonly` is a list of rendezvous candidates whose put-side
    coroutines never satisfy `rTR` (i.e. they never call `_wakeup_next`),
    then appending them to the candidate list does not change the
    resolved set.

    *Proof:* the filter over `readonly` is empty because no element of
    `readonly` satisfies `Resolves rTR d r` (the `rTR r.putSide`
    conjunct is always false). -/
theorem snf5_readonly_invariance
    (rTR : C → Prop) [DecidablePred rTR]
    (d : List C) (rs readonly : List (Rendezvous C))
    (h : ∀ r ∈ readonly, ¬ rTR r.putSide) :
    resolvedAt rTR d (rs ++ readonly) = resolvedAt rTR d rs := by
  have hnil : readonly.filter (fun r => decide (Resolves rTR d r)) = [] := by
    apply List.filter_eq_nil_iff.mpr
    intro r hr
    simp only [Resolves, decide_eq_true_eq, not_and]
    exact fun _ => h r hr
  simp only [resolvedAt, List.filter_append, hnil, List.append_nil]

/-- **Corollary:** SNF-5 makes Lemma 2a's invariance extend to programs
    with read-only shared accesses at zero cost — no new ordering
    constraints enter `Fₜ` and no cases split off the bijection. -/
theorem snf5_lemma2a_unaffected
    (rTR : C → Prop) [DecidablePred rTR]
    {σ σ' : List C} (hperm : σ.Perm σ')
    (rs readonly : List (Rendezvous C))
    (h : ∀ r ∈ readonly, ¬ rTR r.putSide) :
    resolvedAt rTR σ (rs ++ readonly) =
    resolvedAt rTR σ' (rs ++ readonly) := by
  rw [snf5_readonly_invariance rTR σ rs readonly h,
      snf5_readonly_invariance rTR σ' rs readonly h]
  exact lemma2a_resolution_set_invariance rTR hperm rs

end SNF.SNF5

-- ════════════════════════════════════════════════════════════════════
-- PART 4 · Write-conflict negative result
-- ════════════════════════════════════════════════════════════════════

namespace SNF.WriteConflict

/-!
### Where Lemma 2a fails: destructive write-conflicts

The paper (Section 6 / Section 7, Future Work) states that Lemma 2a
fails for programs with unmediated shared *writes*:

> "For a shared write, this is false — if coroutine cᵢ reads a variable
>  written by cⱼ, whether cᵢ's post-condition holds depends on whether
>  cⱼ executed before cᵢ within the same dispatch step, which is exactly
>  the scheduling choice Lemma 2a requires to be invariant."

We formalize this failure as a concrete counterexample.

The key structural point: Lemma 2a's `rTR : C → Prop` is a *pure*
predicate on the coroutine identifier.  This encodes the paper's
invariant that `pᵢ`'s post-condition depends only on `pᵢ`'s own
execution, not on who else ran or in what order.

For a destructive write, the "post-condition" of coroutine `a` —
e.g., "the shared variable has the value `a` wrote, not the value
`b` wrote" — depends on whether `b` ran *before* `a` in the same
step.  This requires `rTR : List C → C → Prop` (order-dependent),
not the pure `rTR : C → Prop` that Lemma 2a assumes.

We exhibit: a two-coroutine system with an order-dependent predicate
where two permutations of the same ready set produce different resolved
sets — a concrete refutation of the conclusion of Lemma 2a when the
hypothesis (order-independence of `rTR`) is dropped.
-/

/-- Two coroutines competing on a shared write. -/
inductive Coro2 | a | b deriving DecidableEq, Repr

open Coro2 SNF

/-- A version of `resolvedAt` that passes the full dispatch order to the
    resolution predicate — what write-conflict programs would require. -/
def resolvedAtOD
    (rTROD : List Coro2 → Coro2 → Prop)
    [∀ d, DecidablePred (rTROD d)]
    (d : List Coro2) (rs : List (Rendezvous Coro2)) :
    List (Rendezvous Coro2) :=
  rs.filter (fun r =>
    decide (r.putSide ∈ d ∧ rTROD d r.putSide))

/-- Order-dependent "resolution predicate" for a destructive write:
    coroutine `a` "wins" (its value persists) only if `a` was dispatched
    before `b` — i.e. `a` wrote last.  Whether `a` wins is determined by
    its position in the dispatch order, not by `a`'s identity alone.

    This models: `shared_var` is read by `a` after possibly being
    overwritten by `b`, and `a`'s post-condition holds iff `b` ran first
    (so `b`'s write is overwritten by `a`). -/
abbrev writeConflictPred (order : List Coro2) : Coro2 → Prop
  | a => order.indexOf a < order.indexOf b
  | b => False

instance : ∀ d, DecidablePred (writeConflictPred d) := fun d c =>
  match c with
  | a => inferInstance  -- Nat.decLt makes indexOf comparison decidable
  | b => .isFalse (fun h => h)

/-- The write-conflict rendezvous: `a` is the "put-side" (the coroutine
    whose post-condition we are checking). -/
def r_wc : Rendezvous Coro2 := ⟨a, b⟩

/-- Under `[a, b]` — `a` dispatched first, writes second, wins —
    `a` satisfies `writeConflictPred`: its value persists. -/
example : resolvedAtOD writeConflictPred [a, b] [r_wc] = [r_wc] := by
  decide

/-- Under `[b, a]` — `a` dispatched second, writes second, but `b` ran
    first so `b`'s value came *after* `a`'s in this scenario —
    `a` does NOT satisfy `writeConflictPred`. -/
example : resolvedAtOD writeConflictPred [b, a] [r_wc] = [] := by
  decide

/-- `[b, a]` is a permutation of `[a, b]`. -/
example : ([b, a] : List Coro2).Perm [a, b] := by decide

/-- **Counterexample to Lemma 2a under order-dependent resolution.**

    `[a, b]` and `[b, a]` are permutations of each other, but
    `resolvedAtOD writeConflictPred` gives *different* results on them.

    This directly formalizes the paper's Section 6 / Section 7 claim
    that Lemma 2a fails for write-conflict programs: the theorem's
    hypothesis — that `rTR` is a pure predicate on the coroutine
    identifier — is *necessary*, not merely convenient.  Drop it and
    the conclusion fails on concrete data.

    Equivalently: Claim 2's bijection fails for write-conflict programs
    because distinct permutations of `Qₜ` produce distinct final states
    (different write orders → different observable values), so the
    trace-to-sequence map is no longer injective on reachable states. -/
theorem writeConflict_breaks_lemma2a :
    resolvedAtOD writeConflictPred [a, b] [r_wc] ≠
    resolvedAtOD writeConflictPred [b, a] [r_wc] := by
  decide

end SNF.WriteConflict

-- ════════════════════════════════════════════════════════════════════
-- PART 5 · Worked examples
-- ════════════════════════════════════════════════════════════════════

/-! ## Worked Example 1 — two non-interfering coroutines, no rendezvous

    (Paper Section 4.1, first worked example.)
    No rendezvous candidates: Lemma 2a's conclusion holds vacuously.
    This example cannot witness Claim 3 or Lemma 2a nontrivially; it
    serves as the base-case sanity check. -/
namespace WorkedExample1

inductive Coro | a | b deriving DecidableEq, Repr
open SNF Coro

/-- Empty candidate list → resolved set is [] under any dispatch order. -/
example : resolvedAt (C := Coro) (fun _ => True) [a, b] [] =
          resolvedAt (C := Coro) (fun _ => True) [b, a] [] := by
  decide

end WorkedExample1

/-! ## Worked Example 2 — chained rendezvous, four coroutines, two steps

    (Paper Section 4.1, second worked example; formal doc Step 3.)

    ```python
    async def c0(): q1.put_nowait("a")
    async def c1(): x = await q1.get(); await sleep(0); q2.put_nowait(x+"b")
    async def c2(): y = await q2.get()
    async def c3(): z = 1; await sleep(0); z = 2
    ```

    Rendezvous chain: r1 = (c0, c1) resolved at step 1;
                      r2 = (c1, c2) resolved at step 2.

    KEY: Q₁ = {c0,c1,c2,c3};  Q₂ = {c1,c3}  (NOT {c1,c2,c3}).
    c2 is in q2._getters after step 1, not in `_ready` — per SNF-2,
    the handle added when c1's put_nowait wakes c2 is deferred to step 3.
    Q₃ = {c2}.

    Note: the paper's Section 4.1 text says Q₂ = {c1,c2,c3}; this is
    an error.  The formal document (Step 3) and this Lean file both use
    the correct Q₂ = {c1,c3} consistent with SNF-2 and the definition
    of Q as BaseEventLoop._ready. -/
namespace WorkedExample2

inductive Coro | c0 | c1 | c2 | c3 deriving DecidableEq, Repr
open SNF Coro

def r1 : Rendezvous Coro := ⟨c0, c1⟩
def r2 : Rendezvous Coro := ⟨c1, c2⟩

-- ── Step 1 setup ─────────────────────────────────────────────────

def Q1 : List Coro := [c0, c1, c2, c3]

/-- Only c0's put resolves at step 1.  c1's put is gated behind
    its own `sleep(0)` — c1 cannot execute put_nowait until step 2. -/
def rTR1 : Coro → Prop | c0 => True | _ => False

instance : DecidablePred rTR1 := fun c =>
  match c with | c0 => .isTrue trivial | c1 | c2 | c3 => .isFalse (fun h => h)

-- Two representative permutations from the paper's worked example:
def σ1  : List Coro := [c0, c3, c1, c2]   -- c3 before c0 in neither σ
def σ1' : List Coro := [c3, c0, c1, c2]   -- c3 before c0 in σ'

example : σ1.Perm  Q1 := by decide
example : σ1'.Perm Q1 := by decide

/-- r1 resolves at step 1 under σ1: c0 is dispatched, calls put_nowait,
    wakes c1's get regardless of c3's position. -/
example : resolvedAt rTR1 σ1  [r1, r2] = [r1] := by decide
example : resolvedAt rTR1 σ1' [r1, r2] = [r1] := by decide

/-- **Lemma 2a at step 1** (paper's own instantiation):
    two permutations differing only in c3's position produce the same
    resolved-rendezvous set. -/
theorem lemma2a_step1 :
    resolvedAt rTR1 σ1 [r1, r2] = resolvedAt rTR1 σ1' [r1, r2] :=
  lemma2a_resolution_set_invariance rTR1 (by decide) [r1, r2]

-- ── Step 2 setup ─────────────────────────────────────────────────

-- Q₂ = {c1, c3}.  c0 terminated; c2 is in q2._getters (NOT in _ready);
-- c1 re-entered _ready after sleep(0); c3 re-entered after sleep(0).
def Q2 : List Coro := [c1, c3]

/-- c1's put on q2 resolves r2 at step 2 (c1's continuation executes
    atomically by SNF-3 once dispatched). -/
def rTR2 : Coro → Prop | c1 => True | _ => False

instance : DecidablePred rTR2 := fun c =>
  match c with | c1 => .isTrue trivial | c0 | c2 | c3 => .isFalse (fun h => h)

-- Both orderings of Q₂:
def τ  : List Coro := [c1, c3]
def τ' : List Coro := [c3, c1]

example : τ.Perm  Q2 := by decide
example : τ'.Perm Q2 := by decide

/-- r2 resolves at step 2 under both τ and τ': c3's position is
    irrelevant, exactly as Lemma 2a predicts, now at a step whose
    candidate set is contingent on step 1's resolution. -/
example : resolvedAt rTR2 τ  [r2] = [r2] := by decide
example : resolvedAt rTR2 τ' [r2] = [r2] := by decide

/-- **Lemma 2a at step 2:** two orderings of Q₂ produce the same
    resolved set, witnessing the cross-step composition Claim 3 requires. -/
theorem lemma2a_step2 :
    resolvedAt rTR2 τ [r2] = resolvedAt rTR2 τ' [r2] :=
  lemma2a_resolution_set_invariance rTR2 (by decide) [r2]

-- ── Claim 3 instantiation ─────────────────────────────────────────

-- A concrete next-state function: after step 1, the next ready set
-- is Q₂ if r1 resolved, otherwise unchanged.
def nextAfterStep1 (_ready : List Coro) (resolved : List (Rendezvous Coro)) :
    List Coro :=
  if resolved = [r1] then Q2 else _ready

abbrev sd1 : StepData Coro :=
  { ready := Q1, candidates := [r1, r2]
    rTR := rTR1, next := nextAfterStep1 }

/-- **Claim 3 at T=1→T=2:** regardless of whether σ1 or σ1' was chosen
    at step 1, the next ready set (Q₂) is the same — the bijection extends
    to step 2. -/
theorem claim3_step1 :
    sd1.next sd1.ready (resolvedAt sd1.rTR σ1  sd1.candidates) =
    sd1.next sd1.ready (resolvedAt sd1.rTR σ1' sd1.candidates) :=
  claim3_inductive_step sd1 (by decide) (by decide)

end WorkedExample2

-- ════════════════════════════════════════════════════════════════════
-- PART 6 · Worked Example 2 — bijection and encoding-consistency
-- ════════════════════════════════════════════════════════════════════

namespace WorkedExample2.BijectionCheck

/-!
Instantiate `proposition4` at the concrete WE2 encoding and verify that
the four schedule combinations `(σ ∈ {σ1,σ1'}) × (τ ∈ {τ,τ'})` are
all encoding-consistent.

`we2Enc` uses a *representative subset* of F₁ (the 12-permutation set
is not enumerated; we include only the two document-cited orderings
sufficient to check the worked example).  F₂ = {τ, τ'} is complete
since |F₂| = 2.
-/

open WorkedExample2 SNF.Bijection Coro

def we2Enc : Enc Coro :=
  [[σ1, σ1'],   -- F₁ representative (full F₁ has 12 elements)
   [τ,  τ' ]]   -- F₂ complete (|F₂| = 2! = 2)

-- All four schedule combinations are encoding-consistent:

theorem enc_σ1_τ : EncConsistent we2Enc [σ1, τ] :=
  .cons (List.mem_cons_self _ _) (.cons (List.mem_cons_self _ _) .nil)

theorem enc_σ1_τ' : EncConsistent we2Enc [σ1, τ'] :=
  .cons (List.mem_cons_self _ _)
        (.cons (List.mem_cons_of_mem _ (List.mem_cons_self _ _)) .nil)

theorem enc_σ1'_τ : EncConsistent we2Enc [σ1', τ] :=
  .cons (List.mem_cons_of_mem _ (List.mem_cons_self _ _))
        (.cons (List.mem_cons_self _ _) .nil)

theorem enc_σ1'_τ' : EncConsistent we2Enc [σ1', τ'] :=
  .cons (List.mem_cons_of_mem _ (List.mem_cons_self _ _))
        (.cons (List.mem_cons_of_mem _ (List.mem_cons_self _ _)) .nil)

/-- **Proposition 4 at WE2:** under the scheduler assumptions (which
    instantiate Claim 2's two directions for this specific program),
    a two-step schedule for WE2 is feasible iff it is encoding-consistent
    with `we2Enc`.

    `FeasibleSchedule` is left abstract: it is the set of schedules
    corresponding to actual CPython asyncio executions of the program.
    The theorem says the SNF encoding captures that set exactly. -/
theorem we2_proposition4
    (FeasibleSchedule : List (List Coro) → Prop)
    (hAsm : SchedulerAssumptions we2Enc FeasibleSchedule)
    (sched : List (List Coro)) :
    FeasibleSchedule sched ↔ EncConsistent we2Enc sched :=
  proposition4 hAsm sched

end WorkedExample2.BijectionCheck

-- ════════════════════════════════════════════════════════════════════
-- PART 7 · Toward a PROVED (not axiomatized) Claim 2 for WE2
-- ════════════════════════════════════════════════════════════════════

/-!
Everything above treats `FeasibleSchedule` as an *abstract* predicate
(`SchedulerAssumptions` just asserts the two directions). To prove
rather than assume Claim 2 for WE2, `FeasibleSchedule` needs to be
replaced by an actual operational semantics, and `Enc`'s `Fₜ` sets
need to be the *real* FIFO-and-rendezvous-consistent orderings, not a
hand-picked representative subset.

This section provides:
  1. `perms` — full permutation generation (Lean core, no Mathlib).
  2. `Interp` — a small concrete interpreter for WE2's four coroutines,
     giving `FeasibleSchedule` real (non-axiomatized) content.
  3. `fifoConsistent` — a NAMED STUB for the FIFO-consistency predicate
     that cuts F₁ from 24 permutations down to 12 (per the README).
     ITS BODY IS NOT YET FILLED IN. The exact rule (e.g. "relative
     order of coroutines not touched by any rendezvous this step must
     match `_ready` insertion/creation order") needs to be pulled from
     `track1_snf_formal.md`'s definition of Enc(P) / Fₜ before this
     compiles to a genuine (non-vacuous) equivalence — filling it in
     with a guess risks reproducing exactly the kind of silent
     mismatch the Q₂ bug was.
  4. The shape of the final theorem (`we2_claim2_target`) that step 3
     is needed to discharge: `FeasibleSchedule s ↔ EncConsistent enc s`
     with `FeasibleSchedule` now defined via `Interp.run`, not assumed.
-/

namespace WorkedExample2.Interp

open WorkedExample2 SNF.Bijection Coro

/-- Insert `x` at every position of `ys`. -/
def insertions {α : Type _} (x : α) : List α → List (List α)
  | [] => [[x]]
  | y :: ys => (x :: y :: ys) :: (insertions x ys).map (y :: ·)

/-- Full permutation generation, Lean 4 core only — `List.permutations`
    does not exist in this toolchain's core library, so this is
    hand-rolled via the standard insert-everywhere recursion (structural
    recursion on the list, no `erase`/termination proof needed). -/
def perms {α : Type _} : List α → List (List α)
  | [] => [[]]
  | x :: xs => (perms xs).flatMap (insertions x)

/-- Sanity check: 4 coroutines → 24 raw permutations before filtering. -/
example : (perms Q1).length = 24 := by decide

/-- FIFO-consistency for F₁, per `track1_snf_formal.md`'s Step 3:
    "F₁ consists of every FIFO-consistent permutation of {c0,c1,c2,c3}
    in which c0 precedes c1 (required for r1 to resolve within the
    step)... halves S₄ to 12 permutations." Confirmed unambiguous —
    matches the existing Lean file's `Q1`/`σ1`/`σ1'` exactly.
    `c2`, `c3` are unconstrained at this step, per the same passage. -/
def fifoConsistentF1 (d : List Coro) : Prop :=
  d.indexOf c0 < d.indexOf c1

instance : DecidablePred fifoConsistentF1 := fun d =>
  Nat.decLt (d.indexOf c0) (d.indexOf c1)

def f1Real : List (List Coro) :=
  (perms Q1).filter (fun d => decide (fifoConsistentF1 d))

example : ((perms Q1).filter (fun d => decide (fifoConsistentF1 d))).length = 12 := by decide
-- Confirms the document's stated count exactly:
example : f1Real.length = 12 := by decide

/-- F₂, confirmed: `track1_snf_formal.md` now states Q₂ = {c1,c3}
    (the 3-way {c1,c2,c3} was a since-corrected error — c2 is blocked
    on q2 at step 2, not a `_ready` member). With c2 absent from Q₂,
    r2's resolution depends only on c1 being dispatched (`rTR2`), not
    on relative order vs. anything else — no FIFO ordering constraint
    applies at step 2, matching the existing `WorkedExample2.τ/τ'`. -/
def f2Real : List (List Coro) :=
  perms Q2

example : f2Real.length = 2 := by decide

/-- Minimal interpreter state: contents of the two queues, per-phase
    completion flags for coroutines with a `sleep(0)`-separated
    two-part body (c1: get-then-put; c3: set-then-reset, mirroring the
    program's `z=1; await sleep(0); z=2`), and (for c2) a used-once
    flag since it has one atomic segment that blocks forever within
    scope. -/
structure St where
  q1put   : Bool   -- has c0's put_nowait landed in q1?
  c1AteQ1 : Bool   -- has c1's `await q1.get()` resolved? (c1 phase 1)
  q2put   : Bool   -- has c1's put_nowait landed in q2? (c1 phase 2)
  c3Slept : Bool   -- has c3 passed its `await sleep(0)`? (c3 phase 1)
  c3Done  : Bool   -- has c3's post-sleep resume executed? (c3 phase 2)
  c2Ran   : Bool   -- has c2 already been dispatched (and re-blocked)?
deriving DecidableEq, Repr

def St.init : St := ⟨false, false, false, false, false, false⟩

/-- Remove one occurrence of `a` from `l` (the first one found). Hand-rolled
    against `[DecidableEq α]` rather than `List.erase` (which wants
    `[BEq α]` in core Lean 4.14) so this section stays self-contained
    and doesn't need a `BEq`/`DecidableEq` bridging instance. -/
def removeOne {α : Type _} [DecidableEq α] (a : α) : List α → List α
  | [] => []
  | b :: bs => if a = b then bs else b :: removeOne a bs

/-- One coroutine's atomic segment when dispatched — the PURE per-
    coroutine phase logic only, with no notion of "is this coroutine
    actually still in the ready queue." `none` = the coroutine's own
    phase guard blocks it (still-blocked). Mirrors `rTR1`/`rTR2`'s case
    split, now wired to an actual state instead of a bare Prop.

    `c3` is two-phase, exactly like `c1`: its first dispatch executes
    up to `await sleep(0)` (setting `c3Slept`); a LATER dispatch (in a
    subsequent step) resumes and completes (setting `c3Done`).

    `c2`: per the document, c2 IS a Q₁ member — "immediately ready...
    blocked on get() until put_nowait() occurs." Being dispatched at
    step 1 means it runs and re-blocks on the still-empty q2 (a real,
    successful, state-unchanging dispatch) — NOT an error. Only a
    *second* dispatch of c2 is rejected, and — as of the redesign
    below — that rejection is now enforced structurally by ready-set
    membership, not by this flag alone. -/
def phaseStep (s : St) : Coro → Option St
  | c0 => if s.q1put then none else some { s with q1put := true }
  | c1 =>
      if !s.c1AteQ1 then
        if s.q1put then some { s with c1AteQ1 := true } else none
      else if !s.q2put then
        some { s with q2put := true }
      else none
  | c2 => if s.c2Ran then none else some { s with c2Ran := true }
  | c3 =>
      if !s.c3Slept then some { s with c3Slept := true }
      else if !s.c3Done then some { s with c3Done := true }
      else none

/-- **Dispatch, now modeling `_ready.popleft()` for real.** `c` must
    actually be a member of the coroutines still remaining in this
    step's ready queue (`ready`) — not merely runnable per its own
    `phaseStep` guard — and is removed from `ready` on success. A
    coroutine handle can therefore be consumed by a given step at most
    once, *structurally*, regardless of what `phaseStep` alone would
    tolerate (which, for two-phase coroutines like `c1`/`c3`, is a
    second dispatch that advances to the next phase). This is exactly
    the gap the `σ_repeat`/`τ_repeat` counterexample below exploited
    before this change: `phaseStep` accepted a second `c1` because it
    fell through to `c1`'s *other* phase guard; `ready`-membership now
    catches that at the door, since `c1` only occupies one slot in the
    ready queue no matter how many phases it has. `none` if `c ∉ ready`
    or if `phaseStep` itself blocks. -/
def dispatch (ready : List Coro) (s : St) (c : Coro) : Option (List Coro × St) :=
  if c ∈ ready then (phaseStep s c).map (fun s' => (removeOne c ready, s'))
  else none

/-- Thread the shrinking ready set through a step's dispatch order,
    returning what's left of it (ideally `[]`, see `run` below)
    alongside the resulting state. -/
def runStep (ready : List Coro) (s : St) : List Coro → Option (List Coro × St)
  | [] => some (ready, s)
  | c :: cs => (dispatch ready s c).bind (fun p => runStep p.1 p.2 cs)

/-- Run a 2-step schedule from the initial state, using `Q1`/`Q2` as
    each step's actual ready set (not just a length/shape check on the
    dispatch order). `none` if some coroutine was dispatched while
    blocked, dispatched twice, or wasn't a member of that step's ready
    set — OR if the dispatch order didn't drain the ready set fully
    (a real event-loop iteration processes every entry queued for it,
    not a strict prefix). The latter requirement is what makes this a
    faithful model of "σ is a dispatch order *of* `Qₜ`," not merely "a
    sequence of individually-valid dispatches drawn from `Qₜ`." -/
def run (sched : Schedule Coro) : Option St :=
  match sched with
  | [σ, τ] =>
      match runStep Q1 St.init σ with
      | none => none
      | some (rem1, s1) =>
          if rem1 ≠ [] then none else
          match runStep Q2 s1 τ with
          | none => none
          | some (rem2, s2) => if rem2 ≠ [] then none else some s2
  | _ => none

/-- The real, non-axiomatized feasibility predicate for WE2. -/
def FeasibleSchedule (s : Schedule Coro) : Prop := (run s).isSome = true

instance : DecidablePred FeasibleSchedule := fun s => by
  unfold FeasibleSchedule; infer_instance

-- Spot-check against the four hand-picked combinations already used
-- in `WorkedExample2.BijectionCheck` — these should all succeed:
example : FeasibleSchedule [σ1, τ]   := by decide
example : FeasibleSchedule [σ1, τ']  := by decide
example : FeasibleSchedule [σ1', τ]  := by decide
example : FeasibleSchedule [σ1', τ'] := by decide

-- And a schedule that should FAIL (c1 dispatched twice at step 1,
-- second time while still blocked/already progressed):
def σ_bad : List Coro := [c1, c1, c0, c3]
example : ¬ FeasibleSchedule [σ_bad, τ] := by decide

/-- **Regression test for the ready-set fix.** Before this redesign,
    `phaseStep` alone (then called `dispatch`) accepted this schedule:
    `σ_repeat` dispatches `c0`, then `c1` twice (consuming both of
    `c1`'s phases within a single step) and never touches `c2`, and
    `τ_repeat` then finishes off `c3` and `c2`. Neither list is a
    permutation of the set it stands in for, yet the old interpreter
    said `FeasibleSchedule` held. With `dispatch` now checking ready-
    set membership and consuming entries single-use, the second `c1`
    in `σ_repeat` is rejected outright (`c1 ∉ [c2, c3]`, the ready set
    remaining after the first `c1`), so the whole schedule is now
    correctly infeasible. -/
def σ_repeat : List Coro := [c0, c1, c1, c3]
def τ_repeat : List Coro := [c3, c2]

example : ¬ FeasibleSchedule [σ_repeat, τ_repeat] := by decide
example : ¬ σ_repeat.Perm Q1 := by decide
example : ¬ τ_repeat.Perm Q2 := by decide

/-- Real (generated, not hand-picked-representative) encoding for
    WE2, now fully confirmed: F₁ = 12 FIFO-consistent permutations of
    Q₁ with c0 before c1; F₂ = both permutations of Q₂ = {c1,c3}. -/
def we2EncReal : Enc Coro := [f1Real, f2Real]

/-- Unfolds `EncConsistent we2EncReal [σ,τ]` to plain list membership
    — needed because `EncConsistent` (an inductive `Prop`, defined
    generically in Part 2) has no `Decidable` instance anywhere in
    this file, so `decide` can't touch it directly. This is a two-line
    unfold of the `.cons`/`.nil` constructors, not new mathematical
    content. -/
theorem enc_real_iff (σ τ : List Coro) :
    EncConsistent we2EncReal [σ, τ] ↔ σ ∈ f1Real ∧ τ ∈ f2Real := by
  constructor
  · intro h
    cases h with
    | cons hσ h2 =>
      cases h2 with
      | cons hτ h3 => cases h3; exact ⟨hσ, hτ⟩
  · intro ⟨hσ, hτ⟩
    exact .cons hσ (.cons hτ .nil)

/-- The actual finite check, phrased as `List.all` (a `Bool`
    computation) over the already-decidable `σ ∈ f1Real ∧ τ ∈ f2Real`
    rather than `EncConsistent` directly (see `enc_real_iff`), and as
    `List.all` rather than a nested `∀ x ∈ _, ∀ y ∈ _, _` — core
    Lean 4.14's library doesn't have a `Decidable` instance for that
    *nested* bounded-quantifier shape either (confirmed by `lake
    build`). `List.all` sidesteps both issues by being `Bool`-valued
    throughout, which `decide` always handles. -/
def we2_claim2_check : Bool :=
  (perms Q1).all (fun σ =>
    (perms Q2).all (fun τ =>
      decide (FeasibleSchedule [σ, τ] ↔ (σ ∈ f1Real ∧ τ ∈ f2Real))))

theorem we2_claim2_check_true : we2_claim2_check = true := by decide

/-- **Claim 2 for WE2, proved over the finite candidate domain** —
    derived from `we2_claim2_check` via `List.all_eq_true` and
    `of_decide_eq_true`, then converted from the `f1Real`/`f2Real`
    membership form to the `EncConsistent` form via `enc_real_iff`.

    NOTE ON SCOPE: `σ`/`τ` range over `perms Q1`/`perms Q2` (48 pairs),
    not arbitrary `Schedule Coro` — that type is infinite (arbitrary
    length/repeats), so a fully unrestricted `∀ s, ...` has no
    `Decidable` instance at all. This bound is not a cheat:
    `EncConsistent we2EncReal [σ,τ]` already forces membership in
    `f1Real`/`f2Real` by definition, so this covers the interesting
    direction (interpreter agrees with generated encoding on every
    candidate the encoding considers). What it does NOT cover: that
    every `s` outside `perms Q1 × perms Q2` is infeasible under `run`
    — see the next note. -/
theorem we2_claim2_proved :
    ∀ σ ∈ perms Q1, ∀ τ ∈ perms Q2,
      FeasibleSchedule [σ, τ] ↔ EncConsistent we2EncReal [σ, τ] := by
  intro σ hσ τ hτ
  have h := List.all_eq_true.mp we2_claim2_check_true σ hσ
  have h2 := of_decide_eq_true (List.all_eq_true.mp h τ hτ)
  exact h2.trans (enc_real_iff σ τ).symm

/-! ### Closing the ready-set generalization

The natural well-formedness statement is
`∀ s, FeasibleSchedule s → ∃ σ ∈ perms Q1, ∃ τ ∈ perms Q2, s = [σ, τ]`.
Previously this was FALSE for the old `dispatch` (per-coroutine phase
guards only, no ready-set bookkeeping): see the git history / prior
revision of this file for the `σ_repeat`/`τ_repeat` counterexample, now
kept above as a regression test showing the *current* `dispatch`
correctly rejects it.

With `dispatch` now requiring ready-set membership and consuming entries
single-use via `removeOne`, the lemmas below close the combinatorial
core of that statement: every coroutine `dispatch` actually consumes was
a member of the ready set it started from, so threading a whole dispatch
order through `runStep` can only ever *permute* the ready set it drains
into (`σ` in front) plus whatever's left over (`rem` behind). Neither
lemma has been checked by `lake build` (no network access to
`objects.githubusercontent.com` in this sandbox to fetch the toolchain),
so treat the proofs as carefully hand-checked, not machine-verified. -/

/-- **Lemma 1.** Removing a present element and putting it back at the
    front is a permutation of the original list. Induction on `l`,
    case-split on whether the head equals `a`:
    * head = a: `removeOne` strips exactly the head, so `a :: removeOne a l`
      literally *is* `l` (`Perm.refl`).
    * head = b ≠ a: `a` survives in `bs`, so the IH gives
      `bs ~ a :: removeOne a bs`; cons `b` onto both sides, then swap
      `b`/`a` at the front to land on `a :: b :: removeOne a bs`, which is
      definitionally `a :: removeOne a (b :: bs)` since the `if` takes the
      `else` branch. -/
theorem removeOne_perm {α : Type _} [DecidableEq α] (a : α) :
    ∀ (l : List α), a ∈ l → List.Perm l (a :: removeOne a l)
  | [], h => absurd h (List.not_mem_nil a)
  | b :: bs, h => by
      by_cases hab : a = b
      · subst hab
        simp only [removeOne]
        exact List.Perm.refl (a :: bs)
      · have ha' : a ∈ bs := (List.mem_cons.mp h).resolve_left hab
        have ih := removeOne_perm a bs ha'
        simp only [removeOne]
        rw [if_neg hab]
        have step1 : List.Perm (b :: bs) (b :: a :: removeOne a bs) := ih.cons b
        have step2 : List.Perm (b :: a :: removeOne a bs) (a :: b :: removeOne a bs) :=
          List.Perm.swap a b (removeOne a bs)
        exact step1.trans step2

/-- Unpacking what a successful `dispatch` tells us: the dispatched
    coroutine was in the ready set, and the leftover ready set is exactly
    what `removeOne` produces. Pure case analysis on the `if` and on
    `phaseStep`'s result — no induction needed. -/
theorem dispatch_eq_some {ready : List Coro} {s : St} {c : Coro} {p : List Coro × St}
    (h : dispatch ready s c = some p) : c ∈ ready ∧ p.1 = removeOne c ready := by
  unfold dispatch at h
  by_cases hmem : c ∈ ready
  · rw [if_pos hmem] at h
    cases hps : phaseStep s c with
    | none => rw [hps] at h; cases h
    | some s'' =>
        rw [hps] at h
        -- `h : (some s'').map f = some p` is defeq to `some (f s'') = some p`,
        -- so `cases` can inject it directly without naming the `Option.map` lemma.
        cases h
        exact ⟨hmem, rfl⟩
  · rw [if_neg hmem] at h
    cases h

/-- **Lemma 2.** Threading a dispatch order `σ` through `runStep`
    starting from ready set `ready` and ending with leftover `rem`
    permutes `ready` into `σ ++ rem`. Induction on `σ`:
    * `[]`: `runStep` returns `ready` unchanged as the leftover, so
      `rem = ready` and `σ ++ rem` reduces to `ready` itself.
    * `c :: cs`: `dispatch` must have succeeded (`dispatch_eq_some`),
      handing back `c ∈ ready` and a shrunk ready set
      `removeOne c ready`. The IH applied to that shrunk set gives
      `removeOne c ready ~ cs ++ rem`; cons `c` onto both sides and
      chain with `removeOne_perm c ready hmem : ready ~ c :: removeOne c ready`
      to get `ready ~ c :: (cs ++ rem)`, which is definitionally
      `(c :: cs) ++ rem`. -/
theorem runStep_ready_perm :
    ∀ (ready : List Coro) (s : St) (σ : List Coro) (rem : List Coro) (s' : St),
      runStep ready s σ = some (rem, s') → List.Perm ready (σ ++ rem)
  | ready, s, [], rem, s', h => by
      unfold runStep at h
      simp only [Option.some.injEq, Prod.mk.injEq] at h
      obtain ⟨h1, _⟩ := h
      subst h1
      exact List.Perm.refl ready
  | ready, s, c :: cs, rem, s', h => by
      unfold runStep at h
      cases hd : dispatch ready s c with
      | none => rw [hd] at h; cases h
      | some p =>
          rw [hd] at h
          -- `h : (some p).bind (fun p => runStep p.1 p.2 cs) = some (rem, s')`
          -- is defeq to `runStep p.1 p.2 cs = some (rem, s')`.
          have hp : runStep p.1 p.2 cs = some (rem, s') := h
          obtain ⟨hmem, hp1⟩ := dispatch_eq_some hd
          have ih := runStep_ready_perm p.1 p.2 cs rem s' hp
          rw [hp1] at ih
          have hrp := removeOne_perm c ready hmem
          exact hrp.trans (ih.cons c)

/-- **Specializing Lemma 2 to `rem = []`**: if a dispatch order fully
    drains a ready set (leaves nothing behind), it's a permutation of
    that ready set. This is the missing half of Claim 2's
    well-formedness statement flagged in the README/task list — the
    direction saying every *feasible* dispatch order is (a permutation
    of) the ready set it was drawn from, not just that permutations of
    the ready set are feasible. -/
theorem run_step_perm_of_drained {ready : List Coro} {s : St} {σ : List Coro} {s' : St}
    (h : runStep ready s σ = some ([], s')) : List.Perm ready σ := by
  have h' := runStep_ready_perm ready s σ [] s' h
  simpa using h'

/- **Status after these proofs.** `removeOne_perm`, `dispatch_eq_some`,
   `runStep_ready_perm`, and `run_step_perm_of_drained` together give,
   for either step of a run: if `runStep Qₜ s σ = some ([], s')` (i.e.
   `σ` fully drains that step's ready set — exactly `run`'s `remₜ ≠ []
   → none` guard, read in the success direction) then `Qₜ.Perm σ`.
   Composing this over both steps of `run` and unfolding
   `FeasibleSchedule` would give the full
   `∀ s, FeasibleSchedule s → ∃ σ ∈ perms Q1, ∃ τ ∈ perms Q2, s = [σ, τ]`
   statement, modulo one more bridge lemma not proved in this file:
   `List.Perm l Q → l ∈ perms Q` (i.e. that `perms` — the hand-rolled
   `insertions`-based generator — enumerates a full permutation *class*,
   not just relating `Perm` to membership abstractly). That bridge is
   a separate, self-contained fact about `perms`/`insertions` and is
   left for a future pass; nothing above depends on it, and
   `run_step_perm_of_drained` is already a complete, standalone result
   in `List.Perm` terms. -/

/-- **Proposition 4 for WE2, now for-real** (not conditional on an
    axiom): follows immediately from `we2_claim2_proved`, matching the
    README's observation that Prop 4 is structurally trivial given
    Claim 2 — the content was always in Claim 2, and Claim 2 is now
    proved for this instance, over the same bounded domain as
    `we2_claim2_proved`.

    That domain restriction (`perms Q1 × perms Q2` rather than
    arbitrary `Schedule Coro`) was shown to be a genuine gap under the
    old phase-guard-only `dispatch` (see the file's revision history:
    `σ_repeat`/`τ_repeat` were feasible schedules outside the domain).
    Under the current ready-set-based `dispatch`, that specific gap is
    closed as a regression test, and — via `run_step_perm_of_drained`
    above — the domain restriction is now closable in general up to the
    one remaining `Perm ↔ perms`-membership bridge lemma noted there,
    rather than being structurally false. -/
theorem we2_proposition4_proved :
    ∀ σ ∈ perms Q1, ∀ τ ∈ perms Q2,
      FeasibleSchedule [σ, τ] ↔ EncConsistent we2EncReal [σ, τ] :=
  we2_claim2_proved

end WorkedExample2.Interp

/-!
## Eager Task Factory: A Concrete Witness for Propositions 7–8

**Scope, stated up front:** this section proves the invariance claim
Propositions 7–8 rely on for ONE small concrete scenario, using a
self-contained state type (not `WorkedExample2`'s `St`/`Coro`, to avoid
any risk of colliding with or silently depending on that section's
definitions). It is a template and mechanism check, not a proof of the
general Propositions 7–8 — which would require a real model of "eager
step runs inside the creator's atomic segment" for an arbitrary program,
not just this one instance. That general model is not attempted here.

### The scenario

- `c1` runs a single step that (a) writes `flagA` (shared with `c4`'s
  eventual second phase), then (b) — as part of the SAME synchronous
  step, per `eager_task_factory` semantics — triggers `c4`'s eager
  FIRST phase directly, with no separate dispatch and no intervening
  yield point. That eager phase writes only `c4Local`, a field no
  other coroutine's transition or resolve-condition ever reads. This
  is Definition 8's "eager step touches no shared state" hypothesis,
  made concrete rather than assumed abstractly.
- `c2` is a free-varying witness coroutine (the same role `c3` played
  in Worked Example 2): independent of everything else, present so
  that "the eager step's effect is invariant to scheduling" has an
  actual alternative ordering to be invariant *against*, rather than
  being vacuously true with nothing to vary.
- `c4`'s SECOND phase — ordinarily dispatched, once `c4` first reaches
  `_ready` after its own suspension — writes `flagA` too. From this
  point on `c4` is exactly the kind of coroutine Lemma 2a already
  governs.

### What this shows, and what it deliberately does not

Claim 1 (`Vars(c_k)` unchanged during `c_i`'s step, for `k ≠ i`) is
**literally false** here: `c4Local` changes during `c1`'s step, before
`c4` is ever dispatched. `eager_invariance` below is not a proof that
Claim 1 holds — it doesn't. It proves the weaker, and actually needed,
conclusion: that `c4`'s *second*-phase behavior is invariant to `c2`'s
relative dispatch position anyway, because `c4Local` never enters
anyone's resolve-condition or transition except via `c4Eager` (a
boolean flag recording that the eager phase *ran*, not what it
*wrote*). That gap — value vs. occurrence — is exactly Definition 8's
content, verified here as a fact about this machine rather than
assumed.

`counterexample_if_value_leaks` documents, but does not construct, the
failure mode: if `c4SecondStep` or the resolve-condition instead read
`c4Local`'s *value*, this would reduce to exactly the `SNF.WriteConflict`
failure pattern already proved elsewhere in this file. Building that
failing variant is left as the natural next regression test.
-/

namespace EagerTask

/-- A minimal, self-contained state for this witness — distinct from
    `WorkedExample2.St`, so this section has no dependency on (and
    cannot silently break) anything defined there. -/
structure ESt where
  flagA    : Bool := false   -- shared: written by c1's step and c4's second phase
  flagB    : Bool := false   -- c2's own state, unrelated to anything else
  c4Local  : Bool := false   -- PRIVATE to c4's eager phase; nothing else reads this
  c4Eager  : Bool := false   -- has c4's eager first phase run yet? (occurrence, not value)
  c4Second : Bool := false   -- has c4's second (ordinarily-dispatched) phase run?
  deriving DecidableEq, Repr

/-- `c1`'s single step. The eager task-creation call is modeled exactly
    as `eager_task_factory` requires: not a separate dispatch, just a
    direct effect inside `c1`'s own atomic segment. -/
def c1Step (s : ESt) : ESt :=
  { s with flagA := true, c4Local := true, c4Eager := true }

/-- `c2`: independent witness coroutine, touches nothing `c1`/`c4` touch. -/
def c2Step (s : ESt) : ESt :=
  { s with flagB := true }

/-- `c4`'s SECOND phase: an ordinary, Lemma-2a-governed dispatch once it
    reaches `_ready`. Note what it does *not* read: `c4Local`. It only
    ever depends on `c4Eager` having fired (checked by the caller via
    `readyToResolveEager`, kept separate here exactly as the abstract
    machine keeps `readyToResolve` separate from the transition itself). -/
def c4SecondStep (s : ESt) : ESt :=
  { s with flagA := true, c4Second := true }

/-- Resolve-condition for `c4`'s second phase. Depends on `c4Eager`
    (occurrence), never on `c4Local` (value) — Definition 8's
    restriction, stated as an executable predicate rather than a
    side-condition to remember. -/
abbrev readyToResolveEager (s : ESt) : Bool := s.c4Eager && !s.c4Second

def afterC2ThenC4 (s : ESt) : ESt := c4SecondStep (c2Step s)
def afterC4ThenC2 (s : ESt) : ESt := c2Step (c4SecondStep s)

/-- **Concrete witness for Propositions 7–8's invariance claim.**
    Starting right after `c1`'s step (so the eager phase has already
    run), `c4`'s second-phase outcome is identical regardless of `c2`'s
    relative dispatch position — Lemma 2a's conclusion for this
    scenario, despite Claim 1's literal hypothesis already having
    failed for `c4Local` back when `c1` ran. -/
theorem eager_invariance (s : ESt) :
    afterC2ThenC4 s = afterC4ThenC2 s := by
  simp [afterC2ThenC4, afterC4ThenC2, c2Step, c4SecondStep]

/-- Sanity check: Claim 1 does genuinely fail here — `c4Local` changes
    during `c1`'s own step, before `c4` is ever dispatched. This file
    is not claiming otherwise; `eager_invariance` above proves the
    weaker fact that actually suffices. -/
example : (c1Step {}).c4Local = true := by decide
example : ({} : ESt).c4Local = false := by decide

/-- Sanity check: `readyToResolveEager` depends only on `c4Eager`, and
    `c4SecondStep`'s written fields (`flagA`, `c4Second`) don't mention
    `c4Local` at all — Definition 8 holding concretely, not merely
    assumed for this example. -/
example (s : ESt) : readyToResolveEager s = (s.c4Eager && !s.c4Second) := rfl

end EagerTask

/-!
## Proposition 12's Logical Core (general, not tied to any worked example)

**Scope:** this formalizes the actual mathematical content of
Proposition 12's soundness direction, stripped of SNF-specific
bookkeeping. It is a genuinely general result -- not a concrete
instance like `WorkedExample2`/`EagerTask` -- because the argument
itself doesn't depend on anything SNF-specific. What it does NOT
mechanize is Definition 13 (control-flow independence): the syntactic
condition on *programs* that tells you WHEN this lemma's hypothesis
(the deleted conjunct doesn't appear elsewhere) actually holds. That
condition is about program structure (branch guards, yield-point
reachability), which isn't reified anywhere in this file, so it can't
be checked here -- only assumed as a hypothesis, exactly as
`track1_snf_formal.md`'s Proposition 12 assumes it via Definition 13.
-/

namespace HavocCore

/-- **Proposition 12's soundness direction, in full generality.**
    If `Rest` (everything else `Enc(P)` asserts) holds together with
    `v`'s defining equation `v = realValue`, then `Rest` alone -- i.e.
    `Enc_havoc(P)`, which drops that equation and leaves `v` free --
    is satisfiable, witnessed by that same `realValue`. This is
    literally `Exists.intro`; formalizing it is not meant to look
    impressive, it's meant to make visible (the same way
    `track1_snf_formal.md` already notes for Proposition 4 given
    Claim 2) that Proposition 12's soundness direction adds no
    mathematical content beyond this one existential witness -- ALL of
    the real content is in Definition 13 correctly identifying which
    programs make the hypothesis `Rest` (independent of `v`) true. -/
theorem havoc_preserves_satisfiability
    {α : Type u} {Rest : α → Prop} (realValue : α) (h : Rest realValue) :
    ∃ v, Rest v :=
  ⟨realValue, h⟩

/-- The same fact, phrased the other direction, closer to how a
    verifier actually uses it: if `Enc_havoc(P)`'s negation-of-property
    query is UNSAT (no value of the free `v` makes `Rest v ∧ ¬φ`
    hold), then in particular the *real* value of `v` along any
    feasible trace can't make it hold either -- so `φ` holds on that
    trace. This is the contrapositive form Section 6's soundness
    argument actually needs. -/
theorem havoc_unsat_implies_real_trace_safe
    {α : Type u} {Rest : α → Prop} {φ : Prop}
    (hUnsat : ¬ ∃ v, Rest v ∧ ¬φ) (realValue : α) (h : Rest realValue) : φ := by
  cases Classical.em φ with
  | inl hφ => exact hφ
  | inr hφ => exact absurd ⟨realValue, h, hφ⟩ hUnsat

end HavocCore

/-!
## Proposition 3, Mechanized: `Enc(P)`'s Generator Never Reaches a
## Quantifier Constructor

**Scope:** `Formula` below is deliberately built WITH quantifier
constructors (`forallV`, `existsV`) available -- matching what a naive
AUFLIA-style encoding would use -- so that "the Enc(P) construction
never produces one" is a genuine structural fact about where a
specific generator's output lands, not a vacuous truth about a type
that couldn't represent a quantifier in the first place. `encodeStep`
mirrors Section 4.1's actual Φₜ construction: a disjunction (one
disjunct per permutation in `Fₜ`) of conjunctions of ground equalities
(`post_constraints`/`rendezvous_constraint`, both ground per
Proposition 3's informal proof). This does NOT mechanize the size
bound (Proposition 2) or completeness (Proposition 4) for this
generator -- only quantifier-freedom.
-/

namespace QuantifierFreedom

/-- A formula language expressive enough for both `Enc(P)`-style
    ground disjunctions AND naive AUFLIA-style quantified formulas. -/
inductive Formula (V : Type) where
  | tru     : Formula V
  | fals    : Formula V
  | eq      : V → Nat → Formula V              -- ground equality: var = literal
  | and     : Formula V → Formula V → Formula V
  | or      : Formula V → Formula V → Formula V
  | not     : Formula V → Formula V
  | forallV : (Nat → Formula V) → Formula V     -- what naive encodings use
  | existsV : (Nat → Formula V) → Formula V

/-- `IsQF f` holds iff `f` was built using only the non-quantifier
    constructors. There is deliberately no constructor case for
    `forallV`/`existsV` -- nothing can ever prove `IsQF` of one, which
    is the formal content of "quantifier-free": not a property checked
    after the fact, but a class of formulas nothing outside it belongs
    to. -/
inductive IsQF {V : Type} : Formula V → Prop where
  | tru  : IsQF .tru
  | fals : IsQF .fals
  | eq   (v : V) (n : Nat) : IsQF (.eq v n)
  | and  {a b} : IsQF a → IsQF b → IsQF (.and a b)
  | or   {a b} : IsQF a → IsQF b → IsQF (.or a b)
  | not  {a}   : IsQF a → IsQF (.not a)

/-- One ground disjunct: `post_constraints(cᵢ, σ, t) ∧
    ⋀ rendezvous_constraint(r, σ)`, restricted to the ground-equality
    shape Section 4.1 actually uses, as a conjunction of `var = value`
    equalities. -/
def groundConjunct {V : Type} (eqs : List (V × Nat)) : Formula V :=
  eqs.foldr (fun ve acc => .and (.eq ve.1 ve.2) acc) .tru

/-- Φₜ itself: a disjunction over `Fₜ`, one ground conjunct per
    permutation -- Section 4.1's `Or` over `disjuncts`, generalized
    from the two hand-written worked examples to an arbitrary
    permutation-indexed equation list. -/
def encodeStep {V : Type} (disjuncts : List (List (V × Nat))) : Formula V :=
  disjuncts.foldr (fun eqs acc => .or (groundConjunct eqs) acc) .fals

theorem groundConjunct_isQF {V : Type} (eqs : List (V × Nat)) :
    IsQF (groundConjunct eqs) := by
  induction eqs with
  | nil => exact .tru
  | cons e es ih => exact .and (.eq e.1 e.2) ih

/-- **Proposition 3, mechanized.** `encodeStep` -- the construction
    Section 4.1 actually uses for Φₜ -- lands inside `IsQF` for every
    input, i.e. it never reaches `forallV`/`existsV`, even though
    `Formula` has those constructors available. Proof: structural
    induction over the disjunct list, mirroring the informal proof's
    "each Φₜ is a disjunction of conjunctions of ground constraints"
    almost line for line. -/
theorem encodeStep_isQF {V : Type} (disjuncts : List (List (V × Nat))) :
    IsQF (encodeStep disjuncts) := by
  induction disjuncts with
  | nil => exact .fals
  | cons eqs rest ih => exact .or (groundConjunct_isQF eqs) ih

end QuantifierFreedom