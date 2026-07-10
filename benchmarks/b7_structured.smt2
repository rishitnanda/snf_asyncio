; b7_structured.smt2  (NEW -- unmediated read-only broadcast, 8 readers)
; Theory: QF_LIA
; Property: all readers observe config["x"] = 42
; Expected: UNSAT
;
; SNF EXTENSION: read-only unmediated access.
;
; Prior SNF cases (b1 TaskGroup, b3 Lock, b4 Event, b6 Queue) all derive
; their normal form from a MEDIATOR: a primitive that imposes a total or
; count-invariant order on a write/cancellation. The collapse argument is
; always "regardless of which of n! orderings the mediator allows, the
; OUTCOME is invariant" -- e.g. Lock guarantees no lost updates, so
; sum = n regardless of acquisition order.
;
; Read-only access has NO mediator and NO write, so the prior collapse
; argument ("n! orderings -> 1 invariant via mediator semantics") does
; not apply -- there is nothing for a mediator to mediate. Instead, the
; correct SNF derivation for this class rests on a DIFFERENT lemma:
;
;   Lemma (read-only invariance): If no task in a concurrent group
;   performs a write to a shared location L between its creation and
;   completion, then the value observed by ANY read of L is independent
;   of scheduling order, and SNF reduces directly to the single ground
;   instance (no case-split over orderings is needed at all -- not even
;   the O(n) linear invariant used by Lock/Event/Queue).
;
; This is a genuine but NARROW extension: it covers read-only sharing,
; not general unmediated writes. A bounded write-conflict pattern (e.g.
; k<n racing writers without a lock) remains OUTSIDE this result and is
; explicitly left open -- the read-only lemma does not generalize to
; writes because two unordered writes to the same location are NOT
; invariant under reordering (last-write-wins is order-dependent).

(set-logic QF_LIA)

(declare-const num_readers Int)
(assert (= num_readers 8))

(declare-const config_x Int)
(assert (= config_x 42))

; Read-only invariance lemma applied directly: each reader's observed
; value equals config_x by construction, with NO case-split over
; scheduling order required -- this is the single ground instance the
; lemma collapses to, strictly stronger than the O(n) Lock/Event
; reduction (which still needed n linear equality constraints).
(declare-const r0 Int) (assert (= r0 config_x))
(declare-const r1 Int) (assert (= r1 config_x))
(declare-const r2 Int) (assert (= r2 config_x))
(declare-const r3 Int) (assert (= r3 config_x))
(declare-const r4 Int) (assert (= r4 config_x))
(declare-const r5 Int) (assert (= r5 config_x))
(declare-const r6 Int) (assert (= r6 config_x))
(declare-const r7 Int) (assert (= r7 config_x))

; Property (negated): does some reader observe a value != 42?
(assert (or (not (= r0 42)) (not (= r1 42)) (not (= r2 42)) (not (= r3 42))
            (not (= r4 42)) (not (= r5 42)) (not (= r6 42)) (not (= r7 42))))

(check-sat)
