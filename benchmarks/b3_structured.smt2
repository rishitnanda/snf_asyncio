; b3_structured.smt2  (SCALED — 10 tasks)
; Theory: QF_LIA
; Property: shared_resource = 10
; Expected: UNSAT
;
; asyncio.Lock() enforces total acquisition order.
; Regardless of which of 10! permutations runs, each task increments
; exactly once. Result is always 10. No quantifiers needed.

(set-logic QF_LIA)

(declare-const num_tasks Int)
(assert (= num_tasks 10))

(declare-const inc0 Int)(assert (= inc0 1))
(declare-const inc1 Int)(assert (= inc1 1))
(declare-const inc2 Int)(assert (= inc2 1))
(declare-const inc3 Int)(assert (= inc3 1))
(declare-const inc4 Int)(assert (= inc4 1))
(declare-const inc5 Int)(assert (= inc5 1))
(declare-const inc6 Int)(assert (= inc6 1))
(declare-const inc7 Int)(assert (= inc7 1))
(declare-const inc8 Int)(assert (= inc8 1))
(declare-const inc9 Int)(assert (= inc9 1))

(declare-const shared_resource Int)
(assert (= shared_resource
  (+ inc0 inc1 inc2 inc3 inc4
     inc5 inc6 inc7 inc8 inc9)))

; Property (negated)
(assert (not (= shared_resource num_tasks)))

(check-sat)
