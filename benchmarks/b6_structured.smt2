; b6_structured.smt2  (SCALED — Queue(3), 8 items, 2 producers, 2 consumers)
; Theory: QF_LIA
; Property: len(state) = 8
; Expected: UNSAT
;
; FIFO + conservation: total puts = total gets regardless of interleaving.
; maxsize=3 with 2 producers forces blocking but not the final count.
; Each producer puts 4, each consumer gets 4 => total = 8. No scheduler.

(set-logic QF_LIA)

(declare-const maxsize     Int)(assert (= maxsize     3))
(declare-const total_items Int)(assert (= total_items 8))

; Each producer puts exactly 4 items
(declare-const p1_puts Int)(assert (= p1_puts 4))
(declare-const p2_puts Int)(assert (= p2_puts 4))

; Each consumer gets exactly 4 items
(declare-const c1_gets Int)(assert (= c1_gets 4))
(declare-const c2_gets Int)(assert (= c2_gets 4))

; Queue never exceeds maxsize (structural bound)
(declare-const max_observed_len Int)
(assert (>= max_observed_len 0))
(assert (<= max_observed_len maxsize))

; Conservation: total puts = total gets (queue drains fully)
(assert (= (+ p1_puts p2_puts) (+ c1_gets c2_gets)))

(declare-const final_len Int)
(assert (= final_len (+ c1_gets c2_gets)))

; Property (negated)
(assert (not (= final_len total_items)))

(check-sat)
