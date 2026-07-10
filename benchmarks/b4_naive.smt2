; b4_naive.smt2  (SCALED — 12 waiters)
; Benchmark: b4_event_broadcast_scaled
; Theory: AUFLIA
; Property: len(results) = 12
; Expected: SAT  *** CORRECTNESS GAP ***
;
; Naive encoding does NOT encode that asyncio.Event.set() guarantees
; ALL waiters wake up. The forall only says: if a waiter woke, it appends.
; But waking itself is non-deterministic in the naive model.
; Solver finds model where some waiters don't wake => results_len < 12.
; Demonstrates encoding incompleteness for event broadcast semantics.

(set-logic AUFLIA)

(declare-const num_waiters Int)
(assert (= num_waiters 12))

(declare-const event_fired  Int)
(assert (= event_fired 1))

(declare-fun Woke     (Int) Bool)
(declare-fun Appended (Int) Bool)
(declare-const wakeup_queue (Array Int Bool))

; Naive: event fires but wakeup of each waiter is non-det
; Does NOT encode asyncio guarantee that event.set() wakes ALL waiters
(assert (forall ((w Int))
  (=> (and (>= w 0) (< w num_waiters) (= event_fired 1))
      (or (Woke w) (not (Woke w))))))   ; non-deterministic!

; Waiters that woke do append
(assert (forall ((w Int))
  (=> (and (>= w 0) (< w num_waiters) (Woke w))
      (Appended w))))

(declare-const results_len Int)
(assert (= results_len
  (+ (ite (Appended 0)  1 0) (ite (Appended 1)  1 0)
     (ite (Appended 2)  1 0) (ite (Appended 3)  1 0)
     (ite (Appended 4)  1 0) (ite (Appended 5)  1 0)
     (ite (Appended 6)  1 0) (ite (Appended 7)  1 0)
     (ite (Appended 8)  1 0) (ite (Appended 9)  1 0)
     (ite (Appended 10) 1 0) (ite (Appended 11) 1 0))))

; Property (negated): results_len = 12
; SAT because naive does not encode that ALL 12 waiters are guaranteed to wake
(assert (not (= results_len num_waiters)))

(check-sat)
; SAT: correctness gap — naive cannot prove all 12 waiters append
