; php3_structured.smt2
; Pigeonhole Principle: 4 pigeons, 3 holes  (PHP_3)
; Theory: QF_LIA
; Expected: UNSAT — completely stable across all seeds
;
; Structured: enumerate all 4x3=12 assignment variables explicitly.
; Use bounds (0<=x<=1) instead of OR-constraints for Simplex efficiency.
; No quantifiers. Solved by Simplex in polynomial time, deterministically.

(set-logic QF_LIA)

; 4x3 = 12 assignment variables
(declare-const a00 Int) (declare-const a01 Int) (declare-const a02 Int)
(declare-const a10 Int) (declare-const a11 Int) (declare-const a12 Int)
(declare-const a20 Int) (declare-const a21 Int) (declare-const a22 Int)
(declare-const a30 Int) (declare-const a31 Int) (declare-const a32 Int)

; Bounds: 0 <= a[p][h] <= 1
(assert (>= a00 0))(assert (<= a00 1))
(assert (>= a01 0))(assert (<= a01 1))
(assert (>= a02 0))(assert (<= a02 1))
(assert (>= a10 0))(assert (<= a10 1))
(assert (>= a11 0))(assert (<= a11 1))
(assert (>= a12 0))(assert (<= a12 1))
(assert (>= a20 0))(assert (<= a20 1))
(assert (>= a21 0))(assert (<= a21 1))
(assert (>= a22 0))(assert (<= a22 1))
(assert (>= a30 0))(assert (<= a30 1))
(assert (>= a31 0))(assert (<= a31 1))
(assert (>= a32 0))(assert (<= a32 1))

; Each pigeon in at least one hole (row sum >= 1)
(assert (>= (+ a00 a01 a02) 1))
(assert (>= (+ a10 a11 a12) 1))
(assert (>= (+ a20 a21 a22) 1))
(assert (>= (+ a30 a31 a32) 1))

; Each hole has at most one pigeon (column sum <= 1)
(assert (<= (+ a00 a10 a20 a30) 1))
(assert (<= (+ a01 a11 a21 a31) 1))
(assert (<= (+ a02 a12 a22 a32) 1))

(check-sat)
; UNSAT: stable across all seeds (QF_LIA = Simplex, no MBQI)
