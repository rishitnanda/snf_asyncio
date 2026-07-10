; b1_naive.smt2  (SCALED — 8 workers)
; Benchmark: b1_structured_task_group_scaled
; Theory: AUFLIA
; Property: if fail_trigger=1 then shared_count=0
; Expected: UNSAT
;
; 8 workers with delays 0.1..0.8s. Worker 1 raises on fail_trigger.
; TaskGroup cancels all siblings. Naive scheduler: universal quantifier
; over all task ids. MBQI must instantiate for all 8 workers.
; 8! = 40320 possible orderings the solver must reason about.

(set-logic AUFLIA)

(declare-const fail_trigger Int)
(declare-const loop_queue (Array Int Bool))
(declare-fun Ready       (Int) Bool)
(declare-fun TrySchedule (Int) Bool)
(declare-fun Selected    (Int) Bool)
(declare-fun Completed   (Int) Bool)
(declare-fun Cancelled   (Int) Bool)

; Naive scheduler axioms — universally quantified
(assert (forall ((t Int))
  (=> (Ready t) (TrySchedule t))))

(assert (forall ((t1 Int) (t2 Int))
  (=> (and (Selected t1) (Selected t2) (not (= t1 t2)))
      false)))

(assert (forall ((t Int))
  (= (Ready t) (select loop_queue t))))

; Each worker either completes or is cancelled
(assert (forall ((t Int))
  (=> (and (>= t 1) (<= t 8))
      (or (Completed t) (Cancelled t)))))

(assert (forall ((t Int))
  (not (and (Completed t) (Cancelled t)))))

; Worker 1 raises iff fail_trigger=1
(declare-const w1_raised Int)
(assert (= w1_raised fail_trigger))

; TaskGroup cancels ALL siblings when any worker raises
(declare-fun worker_cancelled (Int) Int)
(assert (forall ((t Int))
  (=> (and (>= t 2) (<= t 8))
      (= (worker_cancelled t) w1_raised))))

; Worker 1 never increments (raises before sleep)
(declare-fun worker_increment (Int) Int)
(assert (= (worker_increment 1) 0))

; Workers 2-8 increment only if not cancelled
(assert (forall ((t Int))
  (=> (and (>= t 2) (<= t 8))
      (= (worker_increment t)
         (ite (= (worker_cancelled t) 1) 0 1)))))

(declare-const shared_count Int)
(assert (= shared_count
  (+ (worker_increment 1) (worker_increment 2)
     (worker_increment 3) (worker_increment 4)
     (worker_increment 5) (worker_increment 6)
     (worker_increment 7) (worker_increment 8))))

(assert (or (= fail_trigger 0) (= fail_trigger 1)))

; Property (negated): fail_trigger=1 AND shared_count!=0 => UNSAT
(assert (not (=> (= fail_trigger 1) (= shared_count 0))))

(check-sat)
