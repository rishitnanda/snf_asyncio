; b7_naive.smt2  (NEW -- unmediated read-only broadcast, 8 readers)
; Benchmark: b7_readonly_broadcast_unmediated
; Theory: AUFLIA
; Property: all readers observe config["x"] = 42
; Expected: UNSAT (property holds -- but UNMEDIATED, no collapse axiom available)
;
; UNLIKE b4 (event_broadcast), there is NO asyncio.Event.set() primitive
; here -- no "all waiters unblock atomically" structural guarantee for the
; naive encoder to (mis)model. Readers run with NO mediating happens-before
; edge at all. The naive scheduler must quantify over ALL 8! orderings of
; reader execution with no shortcut, since nothing establishes that the
; readers are even ordered relative to each other.
;
; This tests the BOUNDARY of SNF: in b4, naive failed because it omitted
; the Event's atomicity guarantee (correctness gap, returns SAT). Here,
; there is no such guarantee available even in the GROUND TRUTH semantics
; -- readers are unordered by construction. So the question becomes: can
; the naive encoding still PROVE the property without a mediator, and if
; so, is it stable?

(set-logic AUFLIA)

(declare-const num_readers Int)
(assert (= num_readers 8))

(declare-const config_x Int)
(assert (= config_x 42))

; Scheduler: readers run in SOME order, modeled as a permutation --
; but unlike b4, there is no "Event fires, all readers see post-fire state"
; axiom. Each reader independently and non-deterministically reads at
; SOME point relative to the others (no ordering constraint at all).
(declare-const read_order (Array Int Int))
(declare-fun ReadAt   (Int) Int)   ; value read by reader r
(declare-fun ReadSlot (Int) Int)   ; scheduling slot assigned to reader r

; Each reader is scheduled at SOME slot in [0, num_readers) -- but slots
; are NOT required to be distinct or ordered (no mediator enforces this)
(assert (forall ((r Int))
  (=> (and (>= r 0) (< r num_readers))
      (and (>= (ReadSlot r) 0) (< (ReadSlot r) num_readers)))))

; Each reader reads config_x at whatever slot it is scheduled --
; since config is immutable (no writer), every reader reads the SAME
; value regardless of slot. This is the only axiom connecting ReadAt
; to config_x -- there is NO mediator-derived ordering axiom at all.
(assert (forall ((r Int))
  (=> (and (>= r 0) (< r num_readers))
      (= (ReadAt r) config_x))))

; Array consistency for read_order (models the scheduler's bookkeeping,
; unused for correctness but present because a real naive AUFLIA model
; of "the scheduler" would carry this structure regardless of whether
; it influences the read result)
(assert (forall ((slot Int))
  (=> (and (>= slot 0) (< slot num_readers))
      (and (>= (select read_order slot) 0)
           (<  (select read_order slot) num_readers)))))

; Property (negated): does there EXIST a reader r in [0,num_readers)
; such that ReadAt(r) != 42? If naive can show this is impossible
; (UNSAT), the property holds even without a mediator.
(assert (exists ((r Int))
  (and (>= r 0) (< r num_readers)
       (not (= (ReadAt r) 42)))))

(check-sat)
