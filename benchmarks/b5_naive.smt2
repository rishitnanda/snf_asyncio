; b5_naive.smt2  (SCALED — 5 nested wait_for races)
; Benchmark: b5_race_and_timeout_scaled
; Theory: AUFLIA
; Property: exactly 3 of 5 services return SUCCESS
; Expected: SAT  *** CORRECTNESS GAP + INSTABILITY ***
;
; 5 races, each with 2 outcomes = 2^5 = 32 possible outcome vectors.
; Naive: tick-level scheduler quantified over all 5 races independently.
; No timing constraints => solver picks outcomes freely.
; Returns SAT (correctness gap) AND shows high timing variance (instability).
;
; Races: s1(100ms<200ms)=SUCCESS, s2(300ms>200ms)=TIMEOUT,
;        s3(50ms<100ms)=SUCCESS,  s4(400ms>150ms)=TIMEOUT,
;        s5(80ms<120ms)=SUCCESS  => total successes=3

(set-logic AUFLIA)

(declare-const tq1 (Array Int Int))(declare-const tq2 (Array Int Int))
(declare-const tq3 (Array Int Int))(declare-const tq4 (Array Int Int))
(declare-const tq5 (Array Int Int))

(declare-fun Fires1 (Int) Bool)(declare-fun Fires2 (Int) Bool)
(declare-fun Fires3 (Int) Bool)(declare-fun Fires4 (Int) Bool)
(declare-fun Fires5 (Int) Bool)

; Tautological forall forces MBQI instantiation over tick domain
(assert (forall ((t Int)) (or (Fires1 t) (not (Fires1 t)))))
(assert (forall ((t Int)) (or (Fires2 t) (not (Fires2 t)))))
(assert (forall ((t Int)) (or (Fires3 t) (not (Fires3 t)))))
(assert (forall ((t Int)) (or (Fires4 t) (not (Fires4 t)))))
(assert (forall ((t Int)) (or (Fires5 t) (not (Fires5 t)))))

; Array consistency
(assert (forall ((t Int))
  (and (or (= (select tq1 t) 0)(= (select tq1 t) 1))
       (or (= (select tq2 t) 0)(= (select tq2 t) 1))
       (or (= (select tq3 t) 0)(= (select tq3 t) 1))
       (or (= (select tq4 t) 0)(= (select tq4 t) 1))
       (or (= (select tq5 t) 0)(= (select tq5 t) 1)))))

; Outcomes: 1=SUCCESS, 0=TIMEOUT — naive has NO timing constraints
(declare-const r1 Int)(declare-const r2 Int)(declare-const r3 Int)
(declare-const r4 Int)(declare-const r5 Int)

(assert (or (= r1 0)(= r1 1)))
(assert (or (= r2 0)(= r2 1)))
(assert (or (= r3 0)(= r3 1)))
(assert (or (= r4 0)(= r4 1)))
(assert (or (= r5 0)(= r5 1)))

(declare-const successes Int)
(assert (= successes (+ r1 r2 r3 r4 r5)))

; Property (negated): successes=3
; SAT because naive has no timing info — solver freely picks successes!=3
(assert (not (= successes 3)))

(check-sat)
; SAT: correctness gap — naive cannot determine which races complete
