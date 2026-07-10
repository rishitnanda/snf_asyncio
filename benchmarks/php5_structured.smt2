; php5_structured.smt2
; Pigeonhole Principle: 6 pigeons, 5 holes  (PHP_5)
; Theory: QF_LIA
; Expected: UNSAT — completely stable across all seeds
;
; Structured: enumerate all 6x5=30 assignment variables explicitly.
; Use bounds (0<=x<=1) instead of OR-constraints for Simplex efficiency.
; No quantifiers. Solved by Simplex in polynomial time, deterministically.

(set-logic QF_LIA)

; 6x5 = 30 assignment variables
(declare-const a00 Int) (declare-const a01 Int) (declare-const a02 Int) (declare-const a03 Int) (declare-const a04 Int)
(declare-const a10 Int) (declare-const a11 Int) (declare-const a12 Int) (declare-const a13 Int) (declare-const a14 Int)
(declare-const a20 Int) (declare-const a21 Int) (declare-const a22 Int) (declare-const a23 Int) (declare-const a24 Int)
(declare-const a30 Int) (declare-const a31 Int) (declare-const a32 Int) (declare-const a33 Int) (declare-const a34 Int)
(declare-const a40 Int) (declare-const a41 Int) (declare-const a42 Int) (declare-const a43 Int) (declare-const a44 Int)
(declare-const a50 Int) (declare-const a51 Int) (declare-const a52 Int) (declare-const a53 Int) (declare-const a54 Int)

; Bounds: 0 <= a[p][h] <= 1
(assert (>= a00 0))(assert (<= a00 1))
(assert (>= a01 0))(assert (<= a01 1))
(assert (>= a02 0))(assert (<= a02 1))
(assert (>= a03 0))(assert (<= a03 1))
(assert (>= a04 0))(assert (<= a04 1))
(assert (>= a10 0))(assert (<= a10 1))
(assert (>= a11 0))(assert (<= a11 1))
(assert (>= a12 0))(assert (<= a12 1))
(assert (>= a13 0))(assert (<= a13 1))
(assert (>= a14 0))(assert (<= a14 1))
(assert (>= a20 0))(assert (<= a20 1))
(assert (>= a21 0))(assert (<= a21 1))
(assert (>= a22 0))(assert (<= a22 1))
(assert (>= a23 0))(assert (<= a23 1))
(assert (>= a24 0))(assert (<= a24 1))
(assert (>= a30 0))(assert (<= a30 1))
(assert (>= a31 0))(assert (<= a31 1))
(assert (>= a32 0))(assert (<= a32 1))
(assert (>= a33 0))(assert (<= a33 1))
(assert (>= a34 0))(assert (<= a34 1))
(assert (>= a40 0))(assert (<= a40 1))
(assert (>= a41 0))(assert (<= a41 1))
(assert (>= a42 0))(assert (<= a42 1))
(assert (>= a43 0))(assert (<= a43 1))
(assert (>= a44 0))(assert (<= a44 1))
(assert (>= a50 0))(assert (<= a50 1))
(assert (>= a51 0))(assert (<= a51 1))
(assert (>= a52 0))(assert (<= a52 1))
(assert (>= a53 0))(assert (<= a53 1))
(assert (>= a54 0))(assert (<= a54 1))

; Each pigeon in at least one hole (row sum >= 1)
(assert (>= (+ a00 a01 a02 a03 a04) 1))
(assert (>= (+ a10 a11 a12 a13 a14) 1))
(assert (>= (+ a20 a21 a22 a23 a24) 1))
(assert (>= (+ a30 a31 a32 a33 a34) 1))
(assert (>= (+ a40 a41 a42 a43 a44) 1))
(assert (>= (+ a50 a51 a52 a53 a54) 1))

; Each hole has at most one pigeon (column sum <= 1)
(assert (<= (+ a00 a10 a20 a30 a40 a50) 1))
(assert (<= (+ a01 a11 a21 a31 a41 a51) 1))
(assert (<= (+ a02 a12 a22 a32 a42 a52) 1))
(assert (<= (+ a03 a13 a23 a33 a43 a53) 1))
(assert (<= (+ a04 a14 a24 a34 a44 a54) 1))

(check-sat)
; UNSAT: stable across all seeds (QF_LIA = Simplex, no MBQI)
