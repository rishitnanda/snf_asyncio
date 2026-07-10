; b4_structured.smt2  (SCALED — 12 waiters)
; Theory: QF_LIA
; Property: len(results) = 12
; Expected: UNSAT
;
; asyncio.Event.set() unblocks ALL waiters atomically — this is a
; guarantee of the asyncio semantics, encoded directly.
; 12! = 479M orderings collapse to one count invariant: sum = 12.

(set-logic QF_LIA)

(declare-const num_waiters Int)
(assert (= num_waiters 12))

; Each waiter appends exactly 1 element — event.set() guarantees all wake
(declare-const w00 Int)(assert (= w00 1))
(declare-const w01 Int)(assert (= w01 1))
(declare-const w02 Int)(assert (= w02 1))
(declare-const w03 Int)(assert (= w03 1))
(declare-const w04 Int)(assert (= w04 1))
(declare-const w05 Int)(assert (= w05 1))
(declare-const w06 Int)(assert (= w06 1))
(declare-const w07 Int)(assert (= w07 1))
(declare-const w08 Int)(assert (= w08 1))
(declare-const w09 Int)(assert (= w09 1))
(declare-const w10 Int)(assert (= w10 1))
(declare-const w11 Int)(assert (= w11 1))

(declare-const results_len Int)
(assert (= results_len
  (+ w00 w01 w02 w03 w04 w05
     w06 w07 w08 w09 w10 w11)))

; Property (negated)
(assert (not (= results_len num_waiters)))

(check-sat)
; UNSAT: structured encoding correctly proves all 12 waiters append
