; b3_naive.smt2  (SCALED — 10 tasks)
; Benchmark: b3_mutex_contention_scaled
; Theory: AUFLIA
; Property: shared_resource = 10
; Expected: UNSAT
;
; 10 tasks race for asyncio.Lock(). 10! = 3,628,800 possible orderings.
; Naive: forall over task pairs enforcing mutual exclusion +
; forall/exists for surjective lock queue assignment.
; MBQI must instantiate the surjection axiom for all 10 slots.

(set-logic AUFLIA)

(declare-const num_tasks Int)
(assert (= num_tasks 10))

(declare-const lock_queue (Array Int Int))
(declare-fun AcquireSlot (Int) Int)
(declare-fun Holds       (Int) Bool)
(declare-fun Increment   (Int) Int)

; Mutual exclusion: no two tasks hold lock simultaneously
(assert (forall ((t1 Int) (t2 Int))
  (=> (and (Holds t1) (Holds t2) (not (= t1 t2)))
      false)))

; AcquireSlot is injective over [0,10)
(assert (forall ((t Int))
  (=> (and (>= t 0) (< t num_tasks))
      (and (>= (AcquireSlot t) 0)
           (<  (AcquireSlot t) num_tasks)))))

(assert (forall ((t1 Int) (t2 Int))
  (=> (and (not (= t1 t2))
           (>= t1 0) (< t1 num_tasks)
           (>= t2 0) (< t2 num_tasks))
      (not (= (AcquireSlot t1) (AcquireSlot t2))))))

; Surjection: every slot is occupied (forall/exists nesting)
(assert (forall ((pos Int))
  (=> (and (>= pos 0) (< pos num_tasks))
      (exists ((t Int))
        (and (>= t 0) (< t num_tasks)
             (= (AcquireSlot t) pos))))))

; Array encodes lock queue
(assert (forall ((pos Int))
  (=> (and (>= pos 0) (< pos num_tasks))
      (and (>= (select lock_queue pos) 0)
           (<  (select lock_queue pos) num_tasks)))))

; Each task increments exactly once
(assert (forall ((t Int))
  (=> (and (>= t 0) (< t num_tasks))
      (= (Increment t) 1))))

(declare-const shared_resource Int)
(assert (= shared_resource
  (+ (Increment 0) (Increment 1) (Increment 2) (Increment 3)
     (Increment 4) (Increment 5) (Increment 6) (Increment 7)
     (Increment 8) (Increment 9))))

; Property (negated)
(assert (not (= shared_resource num_tasks)))

(check-sat)
