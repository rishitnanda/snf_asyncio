; b5_structured.smt2  (SCALED — 5 nested wait_for races)
; Theory: QF_LIA
; Property: exactly 3 of 5 services return SUCCESS
; Expected: UNSAT
;
; Each race outcome is determined by a single integer comparison.
; No scheduler, no tick quantifier. 2^5=32 branches collapse to 5 ITEs.

(set-logic QF_LIA)

; Sleep and timeout values in ms
(declare-const sleep1 Int)(assert (= sleep1 100))
(declare-const sleep2 Int)(assert (= sleep2 300))
(declare-const sleep3 Int)(assert (= sleep3  50))
(declare-const sleep4 Int)(assert (= sleep4 400))
(declare-const sleep5 Int)(assert (= sleep5  80))

(declare-const tout1 Int)(assert (= tout1 200))
(declare-const tout2 Int)(assert (= tout2 200))
(declare-const tout3 Int)(assert (= tout3 100))
(declare-const tout4 Int)(assert (= tout4 150))
(declare-const tout5 Int)(assert (= tout5 120))

; Outcomes determined by timing comparison alone
(declare-const r1 Int)(assert (= r1 (ite (< sleep1 tout1) 1 0))) ; 100<200 => 1
(declare-const r2 Int)(assert (= r2 (ite (< sleep2 tout2) 1 0))) ; 300<200 => 0
(declare-const r3 Int)(assert (= r3 (ite (< sleep3 tout3) 1 0))) ;  50<100 => 1
(declare-const r4 Int)(assert (= r4 (ite (< sleep4 tout4) 1 0))) ; 400<150 => 0
(declare-const r5 Int)(assert (= r5 (ite (< sleep5 tout5) 1 0))) ;  80<120 => 1

(declare-const successes Int)
(assert (= successes (+ r1 r2 r3 r4 r5)))

; Property (negated)
(assert (not (= successes 3)))

(check-sat)
; UNSAT: structured encoding correctly proves exactly 3 succeed
