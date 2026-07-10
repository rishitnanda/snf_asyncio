; b2_naive.smt2
; Benchmark: b2_fire_and_forget
; Theory: AUFLIA
; Property: if fail_trigger=1 then processed=0
; Expected: SAT  *** CORRECTNESS GAP ***
;
; Naive encoding lacks the timing constraint that cancel arrives at 0.1s
; while bg_job needs 0.2s. Solver freely sets bg_completed=1 even when
; fail_trigger=1. This is a modeling incompleteness, not just instability.
; bg_completed is non-deterministic — solver picks whichever satisfies it.

(set-logic AUFLIA)

(declare-const event_stream (Array Int Int))
(declare-fun   EventAt      (Int) Int)

(assert (forall ((t Int))
  (= (EventAt t) (select event_stream t))))

(assert (forall ((t Int))
  (or (= (EventAt t) 0) (= (EventAt t) 1))))

(declare-const fail_trigger  Int)
(declare-const bg_completed  Int)
(declare-const processed     Int)

; No cancel: bg_job always completes
(assert (=> (= fail_trigger 0) (= bg_completed 1)))

; With cancel: naive encoding has NO timing constraint
; => solver can freely pick bg_completed=0 OR bg_completed=1
(assert (=> (= fail_trigger 1)
  (or (= bg_completed 0) (= bg_completed 1))))

(assert (= processed bg_completed))
(assert (or (= fail_trigger 0) (= fail_trigger 1)))
(assert (or (= bg_completed 0) (= bg_completed 1)))

; Property (negated): fail_trigger=1 => processed=0
; SAT because naive encoding allows bg_completed=1 when fail_trigger=1
(assert (not (=> (= fail_trigger 1) (= processed 0))))

(check-sat)
; SAT demonstrates correctness gap: naive cannot prove this property
