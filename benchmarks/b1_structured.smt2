; b1_structured.smt2  (SCALED — 8 workers)
; Theory: QF_LIA
; Property: if fail_trigger=1 then shared_count=0
; Expected: UNSAT
;
; Structured insight: delay_w(k) = k*0.1s so w1 < w2 < ... < w8 always.
; Exactly ONE schedule exists. Worker 1 fails => TaskGroup cancels all others.
; No quantifiers. No arrays. One variable per worker.

(set-logic QF_LIA)

(declare-const fail_trigger  Int)
(declare-const w1_raised     Int)
(declare-const w2_cancelled  Int)
(declare-const w3_cancelled  Int)
(declare-const w4_cancelled  Int)
(declare-const w5_cancelled  Int)
(declare-const w6_cancelled  Int)
(declare-const w7_cancelled  Int)
(declare-const w8_cancelled  Int)
(declare-const inc2 Int) (declare-const inc3 Int) (declare-const inc4 Int)
(declare-const inc5 Int) (declare-const inc6 Int) (declare-const inc7 Int)
(declare-const inc8 Int)
(declare-const shared_count Int)

; Timing: w(k).delay = k*0.1 => w1 always first
(assert (= w1_raised    fail_trigger))
(assert (= w2_cancelled w1_raised))
(assert (= w3_cancelled w1_raised))
(assert (= w4_cancelled w1_raised))
(assert (= w5_cancelled w1_raised))
(assert (= w6_cancelled w1_raised))
(assert (= w7_cancelled w1_raised))
(assert (= w8_cancelled w1_raised))

; w1 never increments; workers 2-8 increment iff not cancelled
(assert (= inc2 (ite (= w2_cancelled 1) 0 1)))
(assert (= inc3 (ite (= w3_cancelled 1) 0 1)))
(assert (= inc4 (ite (= w4_cancelled 1) 0 1)))
(assert (= inc5 (ite (= w5_cancelled 1) 0 1)))
(assert (= inc6 (ite (= w6_cancelled 1) 0 1)))
(assert (= inc7 (ite (= w7_cancelled 1) 0 1)))
(assert (= inc8 (ite (= w8_cancelled 1) 0 1)))

(assert (= shared_count (+ inc2 inc3 inc4 inc5 inc6 inc7 inc8)))
(assert (or (= fail_trigger 0) (= fail_trigger 1)))

; Property (negated)
(assert (not (=> (= fail_trigger 1) (= shared_count 0))))

(check-sat)
