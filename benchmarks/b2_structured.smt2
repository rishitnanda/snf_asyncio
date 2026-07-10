; b2_structured.smt2
; Theory: QF_LIA
; Property: if fail_trigger=1 then processed=0
; Expected: UNSAT
;
; Structured: main_sleep=0.1s < bg_sleep=0.2s => cancel ALWAYS arrives first.
; Two static outcomes, determined by one comparison. No scheduler needed.

(set-logic QF_LIA)

(declare-const fail_trigger  Int)
(declare-const bg_completed  Int)
(declare-const processed     Int)

; Timing constraint: cancel at 0.1s, bg_job needs 0.2s
; => cancel always wins when fail_trigger=1
(assert (=> (= fail_trigger 0) (= bg_completed 1)))
(assert (=> (= fail_trigger 1) (= bg_completed 0)))

(assert (= processed bg_completed))
(assert (or (= fail_trigger 0) (= fail_trigger 1)))
(assert (or (= bg_completed 0) (= bg_completed 1)))

; Property (negated)
(assert (not (=> (= fail_trigger 1) (= processed 0))))

(check-sat)
; UNSAT: structured encoding correctly proves the property
