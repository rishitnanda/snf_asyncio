; php6_naive.smt2
; Pigeonhole Principle: 7 pigeons, 6 holes  (PHP_6)
; Theory: AUFLIA
; Expected: UNSAT (but seed-dependent timing instability grows with n)
;
; PHP(n): n+1 pigeons must fit into n holes with no hole holding 2 pigeons.
; Canonical MBQI stress test. Instability escalates with n:
;   PHP3: low instability, PHP4: moderate, PHP5/6: severe timeouts.

(set-logic AUFLIA)

(declare-const assign (Array Int (Array Int Int)))
(declare-fun InHole (Int Int) Bool)

; Each pigeon (0 to 7-1) in at least one hole (0 to 6-1)
(assert (forall ((p Int))
  (=> (and (>= p 0) (< p 7))
      (exists ((h Int))
        (and (>= h 0) (< h 6) (InHole p h))))))

; No two pigeons share a hole
(assert (forall ((p1 Int) (p2 Int) (h Int))
  (=> (and (>= p1 0) (< p1 7)
           (>= p2 0) (< p2 7)
           (>= h  0) (< h  6)
           (not (= p1 p2))
           (InHole p1 h))
      (not (InHole p2 h)))))

; Array consistency
(assert (forall ((p Int) (h Int))
  (= (InHole p h)
     (= (select (select assign p) h) 1))))

(check-sat)
