; php4_structured.smt2
; Pigeonhole Principle: 5 pigeons, 4 holes  (PHP_4)
; Theory: QF_LIA
; Expected: UNSAT — completely stable across all seeds
;
; Structured: enumerate all 5x4=20 assignment variables explicitly.
; Use bounds (0<=x<=1) instead of OR-constraints for Simplex efficiency.
; No quantifiers. Solved by Simplex in polynomial time, deterministically.

(set-logic QF_LIA)

; 5x4 = 20 assignment variables
(declare-const a00 Int) (declare-const a01 Int) (declare-const a02 Int) (declare-const a03 Int)
(declare-const a10 Int) (declare-const a11 Int) (declare-const a12 Int) (declare-const a13 Int)
(declare-const a20 Int) (declare-const a21 Int) (declare-const a22 Int) (declare-const a23 Int)
(declare-const a30 Int) (declare-const a31 Int) (declare-const a32 Int) (declare-const a33 Int)
(declare-const a40 Int) (declare-const a41 Int) (declare-const a42 Int) (declare-const a43 Int)

; Bounds: 0 <= a[p][h] <= 1
(assert (>= a00 0))(assert (<= a00 1))
(assert (>= a01 0))(assert (<= a01 1))
(assert (>= a02 0))(assert (<= a02 1))
(assert (>= a03 0))(assert (<= a03 1))
(assert (>= a10 0))(assert (<= a10 1))
(assert (>= a11 0))(assert (<= a11 1))
(assert (>= a12 0))(assert (<= a12 1))
(assert (>= a13 0))(assert (<= a13 1))
(assert (>= a20 0))(assert (<= a20 1))
(assert (>= a21 0))(assert (<= a21 1))
(assert (>= a22 0))(assert (<= a22 1))
(assert (>= a23 0))(assert (<= a23 1))
(assert (>= a30 0))(assert (<= a30 1))
(assert (>= a31 0))(assert (<= a31 1))
(assert (>= a32 0))(assert (<= a32 1))
(assert (>= a33 0))(assert (<= a33 1))
(assert (>= a40 0))(assert (<= a40 1))
(assert (>= a41 0))(assert (<= a41 1))
(assert (>= a42 0))(assert (<= a42 1))
(assert (>= a43 0))(assert (<= a43 1))

; Each pigeon in at least one hole (row sum >= 1)
(assert (>= (+ a00 a01 a02 a03) 1))
(assert (>= (+ a10 a11 a12 a13) 1))
(assert (>= (+ a20 a21 a22 a23) 1))
(assert (>= (+ a30 a31 a32 a33) 1))
(assert (>= (+ a40 a41 a42 a43) 1))

; Each hole has at most one pigeon (column sum <= 1)
(assert (<= (+ a00 a10 a20 a30 a40) 1))
(assert (<= (+ a01 a11 a21 a31 a41) 1))
(assert (<= (+ a02 a12 a22 a32 a42) 1))
(assert (<= (+ a03 a13 a23 a33 a43) 1))

(check-sat)
; UNSAT: stable across all seeds (QF_LIA = Simplex, no MBQI)
