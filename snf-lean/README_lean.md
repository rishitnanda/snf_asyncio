# SNFClaim3.lean — Lean 4 mechanization

Mechanizes the combinatorial core of the Normal Form Reduction Lemma
from `track1_snf_formal.md`, Step 3, plus (as of this revision) the
general logical cores of Proposition 12 and Proposition 3.

## Status

Builds clean under Lean 4 v4.14.0 (`lake build` — **zero errors**), per
prior local verification; the file has not been re-run through `lake
build` in the authoring sandbox for this revision (no network access to
`objects.githubusercontent.com` there) — run `lake build` locally before
citing anything below as machine-checked rather than hand-checked. No
`sorry`/`admit` appears anywhere in the file. Four informational lint
warnings remain (unused `[DecidableEq C]` section variable in three
theorems that don't need it, and one unused match variable); none affect
correctness, and they can be silenced with
`set_option linter.unusedSectionVars false` / `linter.unusedVariables false`
if desired.

## Installation

```
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
cd snf-lean
lake build
```

This uses Lean 4 core only (`List.Perm`, `List.filter`, etc.) — no Mathlib
dependency — so `lake build` is fast and doesn't need a Mathlib cache.

## What is covered

| Theorem | Status | Location |
|---|---|---|
| Lemma 2a (resolution-set invariance) | ✓ proved | `SNF` namespace |
| Claim 3 inductive step | ✓ proved | `SNF` namespace |
| Claim 2 bijection, CPython-grounded direction | ✓ axiomatized as `SchedulerAssumptions` (deliberate — this is Proposition 1's direct-inspection content, not mechanizable) | `SNF.Bijection` |
| Claim 2 bijection, abstract per-step machine | ✓ proved, no free axiom (`claim2_mechanized`) | `SNF.Bijection` |
| Proposition 4 completeness, from `SchedulerAssumptions` | ✓ proved from Claim 2 | `SNF.Bijection` |
| Proposition 4 completeness, abstract machine | ✓ proved, no free axiom (`proposition4_mechanized`) | `SNF.Bijection` |
| Proposition 6 / SNF-5 read-only invariance | ✓ proved | `SNF.SNF5` |
| Write-conflict breaks Lemma 2a (negative result) | ✓ counterexample via `decide` | `SNF.WriteConflict` |
| Worked Example 1 (base case, no rendezvous) | ✓ | `WorkedExample1` |
| Worked Example 2, step 1: Lemma 2a + Claim 3 | ✓ concrete + proved | `WorkedExample2` |
| Worked Example 2, step 2: Lemma 2a cross-step | ✓ concrete + proved | `WorkedExample2` |
| Worked Example 2, all 4 schedule combinations | ✓ enc-consistent | `WorkedExample2.BijectionCheck` |
| Proposition 4 instantiated at WE2 | ✓ proved | `WorkedExample2.BijectionCheck` |
| Claim 2 proved (not axiomatized) for WE2 interpreter | ⚠ proved on `perms Q1 × perms Q2`; the ready-set closure lemmas (`removeOne_perm`, `runStep_ready_perm`, `run_step_perm_of_drained`) are now proved, giving `Qₜ.Perm σ` for any dispatch order that fully drains step `t`'s ready set — one bridge lemma (`Perm l Q → l ∈ perms Q`, i.e. that `perms` enumerates a full permutation class) remains to fully close the domain restriction | `WorkedExample2.Interp` |
| Proposition 12 soundness core (havoc-injection preserves satisfiability, both directions) | ✓ proved, in full generality — not tied to any worked example | `HavocCore` |
| Proposition 3 (`Enc(P)`'s generator never reaches a quantifier constructor) | ✓ proved (`encodeStep_isQF`), for a generator mirroring Section 4.1's actual construction | `QuantifierFreedom` |

**Not in scope** (deliberately): Enc(P)'s size bound (Prop 2), the main
theorem (Step 5), Prop 10 (trace-equivalence), Prop 11 (checker
soundness), Definition 13 (the syntactic side-condition that tells you
*when* Prop 12's mechanized hypothesis holds for a given program — the
existential-witness argument itself is mechanized in `HavocCore`, but
deciding when its hypothesis applies to a given program is not, and isn't
the kind of thing this style of mechanization can check), Prop 13 / 13a /
13b (path-sensitive encoding for flagged-control variables and its two
refinements — per-step-shared havoc variables and the yield-point-scoped
path-count bound), or Track 2 encodings.

**On Claim 2 specifically, don't conflate the two results above.** The
abstract-machine bijection (`claim2_mechanized`) is a proved theorem with
no free axiom on its combinatorial content — that's real progress over
treating all of Claim 2 as an axiom. It does **not** discharge the
CPython-grounded half of Claim 2 (that real dispatch really is a
permutation of a FIFO-popped ready set, that rendezvous really do wake in
FIFO order): that remains `SchedulerAssumptions`, an axiom, by design —
it's Proposition 1's direct-inspection argument, which describes an
external artifact's (CPython's) behavior and isn't the kind of claim this
style of mechanization can close. Say "Claim 2's combinatorial content is
mechanized" or "the abstract-machine bijection is proved," not "Claim 2 is
proved" — the latter overclaims relative to what's here.

## Design notes

- **Dispatch orders as `List C`** with `List.Perm` for permutation equivalence.
  Uses Lean 4 core only — no Mathlib dependency.
- **`readyToResolve : C → Prop` is pure** (no dispatch-order argument).
  This is Lemma 2a's key hypothesis. The `SNF.WriteConflict` section shows
  concretely what breaks when an order-dependent predicate is used instead.
- **`SchedulerAssumptions` is retained as a narrower axiom** than in
  earlier revisions of this file: it now captures only the CPython-source-
  level content (Proposition 1) that the combinatorial theorem
  (`claim2_mechanized`) cannot reach, rather than the whole of Claim 2.
- **`EncConsistent` is an inductive type** (not `List.Forall₂`) to avoid
  depending on naming stability of Init library internals.
- **`Resolves`, `writeConflictPred`, and `sd1` are `abbrev`s, not `def`s.**
  Each is used as an argument inside a `Decidable`/`DecidablePred` instance
  search (directly or via a structure projection), and Lean's typeclass
  resolution only unfolds `@[reducible]` definitions (which `abbrev` is
  sugar for) — a plain `def` there causes instance synthesis to fail
  silently and every `decide` depending on it to get stuck.
- **Q₂ = {c1, c3}** in Worked Example 2 (not {c1, c2, c3} as stated in the
  paper's Section 4.1). c2 is in `q2._getters` after step 1, not in `_ready`;
  per SNF-2, its handle is deferred to step 3. The formal document Step 3
  and this file both use the correct value.
- **`HavocCore`'s two theorems are deliberately trivial-looking**
  (`Exists.intro` and a `Classical.em` case split). That's the point: they
  make visible that Proposition 12's soundness direction adds no
  mathematical content beyond a single existential witness — all the real
  content is in Definition 13 correctly identifying which programs make
  the theorem's hypothesis true, which is not, and cannot be, checked here.
- **`QuantifierFreedom.Formula` deliberately includes quantifier
  constructors** (`forallV`/`existsV`) that a naive AUFLIA-style encoding
  would use, so that `IsQF` excluding them by construction is a genuine
  structural fact about where `encodeStep`'s output lands, not a vacuous
  truth about a type that couldn't represent a quantifier in the first
  place.

## What mechanization surfaced

1. **Worked Example 2 needed `sleep(0)`** (caught in a prior session): without it
   both rendezvous collapsed into step 1, making the example a non-witness of
   Claim 3's cross-step composition.
2. **Q₂ error in paper**: the paper's Section 4.1 says Q₂ = {c1, c2, c3}; the
   correct value per SNF-2 is Q₂ = {c1, c3}. Formalizing forced this to be
   precise.
3. **Prop 4 is structurally trivial given Claim 2**: the one-line proof
   `⟨h.claim2_fwd s, h.claim2_bwd s⟩` makes visible that Proposition 4
   adds no mathematical content beyond packaging Claim 2's two directions
   as an iff. The same observation holds one level down for
   `proposition4_mechanized`, which is literally `claim2_mechanized`
   under a different name.
4. **Lemma 2a's pure-predicate hypothesis is tight**: the `SNF.WriteConflict`
   counterexample shows directly that dropping it (allowing an order-dependent
   predicate) breaks the theorem on concrete two-coroutine data. This
   formalizes the paper's Section 6/7 claim about why write-conflict programs
   are outside scope.
5. **`we2_claim2_proved`'s domain restriction is not closable by the obvious
   induction — under the *original* interpreter design**: the file's first
   comment sketched "`runStep St.init σ ≠ none → σ.Perm Q1`, by induction
   tracking which flags `dispatch` sets, since a repeat dispatch trips an
   already-set flag." That reasoning holds for the one-shot coroutines
   (`c0`, `c2`) but not the two-phase ones (`c1`, `c3`): a repeat dispatch
   of `c1` or `c3` advances to their *next* phase rather than re-tripping a
   flag. This produced a real counterexample (`σ_repeat`/`τ_repeat`) where
   `FeasibleSchedule` held for schedules that were not permutations of
   `Q1`/`Q2` at all.
6. **Fix: `dispatch` now takes the ready set explicitly.** `dispatch` was
   redesigned to require `c` be a member of the *current step's remaining
   ready set* and to consume it single-use (`removeOne`), modeling
   `_ready.popleft()` directly instead of inferring non-repetition from
   per-coroutine phase flags. `σ_repeat`/`τ_repeat` is now a regression
   test confirming the fix: under the new `dispatch`, that schedule is
   correctly rejected. This also makes the well-formedness closure lemma
   (`FeasibleSchedule s → ∃ σ ∈ perms Q1, τ ∈ perms Q2, s = [σ,τ]`)
   *plausible* again rather than false.
7. **Ready-set closure lemmas now proved.** `removeOne_perm`
   (removing a present element and re-consing it front is a permutation
   of the original list), `dispatch_eq_some` (a successful `dispatch`
   both witnesses ready-set membership and consumes exactly via
   `removeOne`), and `runStep_ready_perm` (threading a dispatch order
   through `runStep` permutes the starting ready set into the order
   plus whatever's left over) are all proved by straightforward
   induction/case-analysis — see `SNFClaim3.lean`. Specializing the
   last to an empty leftover (`run_step_perm_of_drained`) gives exactly
   the missing half of Claim 2's well-formedness statement: any
   dispatch order that fully drains a step's ready set is a permutation
   of it. What's *not* yet closed is the one remaining bridge lemma
   `List.Perm l Q → l ∈ perms Q` connecting that fact back to membership
   in the hand-rolled `perms` generator — a separate, self-contained
   fact about `perms`/`insertions`, left for a future pass.
8. **The abstract-machine bijection generalizes past Worked Example 2.**
   `claim2_mechanized` proves the same fwd/bwd correspondence WE2 checks
   concretely, but for an arbitrary `List (StepData C)` — the WE2 result
   is now a corollary of the general theorem in content (though the file
   keeps both, since WE2's concrete instance is also a regression test
   for the interpreter-level `dispatch`/`runStep` machinery that the
   abstract theorem doesn't touch).
9. **Proposition 12's "hard part" is Definition 13, not the existential
   witness.** Formalizing `HavocCore` made this precise: the soundness
   argument itself is a one-line `Exists.intro`, so all of Proposition
   12's actual content is in correctly identifying, syntactically, which
   programs satisfy the hypothesis the witness argument needs — a claim
   about program structure that this file does not and cannot check.

## File layout

- `SNFClaim3.lean` — the mechanization.
- `lakefile.lean`, `lean-toolchain` — minimal project scaffold.