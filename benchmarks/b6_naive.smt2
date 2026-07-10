; b6_naive.smt2  (SCALED — Queue(3), 8 items, 2 producers, 2 consumers)
; Benchmark: b6_producer_consumer_queue_scaled
; Theory: AUFLIA
; Property: len(state) = 8
; Expected: UNSAT
;
; 2 producers (4 items each) + 2 consumers (4 items each).
; Queue maxsize=3 creates blocking that interleaves all 4 tasks.
; Naive: forall over steps with exists for task selection at each step.
; forall/exists nesting forces real MBQI instantiation.

(set-logic AUFLIA)

(declare-const maxsize     Int)(assert (= maxsize     3))
(declare-const total_items Int)(assert (= total_items 8))

; Op stream with task selection at each step
(declare-const op_stream (Array Int Int))
(declare-fun   TaskAt    (Int) Int)   ; task at step: 0=p1,1=p2,2=c1,3=c2
(declare-fun   OpAt      (Int) Int)   ; op: 0=put, 1=get
(declare-fun   QueueLen  (Int) Int)   ; queue length after step

; Naive: at every step, ANY of 4 tasks could run (forall/exists)
(assert (forall ((step Int))
  (=> (>= step 0)
      (exists ((tid Int))
        (and (>= tid 0) (< tid 4)
             (= (TaskAt step) tid))))))

(assert (forall ((step Int))
  (=> (>= step 0)
      (and (>= (TaskAt step) 0) (< (TaskAt step) 4)))))

(assert (forall ((step Int))
  (=> (>= step 0)
      (or (= (OpAt step) 0) (= (OpAt step) 1)))))

; Queue bounded by maxsize
(assert (forall ((step Int))
  (=> (>= step 0)
      (and (>= (QueueLen step) 0)
           (<= (QueueLen step) maxsize)))))

; Put increases queue length
(assert (forall ((step Int))
  (=> (and (>= step 0) (= (OpAt step) 0))
      (= (QueueLen (+ step 1)) (+ (QueueLen step) 1)))))

; Get decreases queue length
(assert (forall ((step Int))
  (=> (and (>= step 0) (= (OpAt step) 1))
      (= (QueueLen (+ step 1)) (- (QueueLen step) 1)))))

; Each producer puts exactly 4 items
(declare-fun PutCount (Int) Int)
(assert (forall ((tid Int))
  (=> (and (>= tid 0) (< tid 2))
      (= (PutCount tid) 4))))

; Each consumer gets exactly 4 items
(declare-fun GetCount (Int) Int)
(assert (forall ((tid Int))
  (=> (and (>= tid 2) (< tid 4))
      (= (GetCount tid) 4))))

(declare-const final_len Int)
(assert (= final_len (+ (GetCount 2) (GetCount 3))))

; Property (negated)
(assert (not (= final_len total_items)))

(check-sat)
