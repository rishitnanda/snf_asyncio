; php3_nonsnf.smt2
; Pigeonhole Principle: 4 pigeons, 3 holes  (PHP_3)
; Theory: QF_LIA  (NON-SNF baseline -- mechanical QE, big-OR/pairwise)
; Expected: UNSAT
;
; This is the THIRD encoding point: same QF_LIA theory as the
; structured (SNF) version, but built by literally translating
; forall/exists into big-OR + pairwise clauses -- NO structural
; reduction via row-sum/column-sum symmetry. Isolates whether
; stability comes from the theory (QF_LIA easier than AUFLIA)
; or from the SNF structural derivation specifically.
;
; Clause count: 4 big-OR clauses (row coverage)
;            + 18 pairwise exclusion clauses
; vs SNF structured: 7 linear constraints total

(set-logic QF_LIA)

; 4x3 = 12 assignment variables (0/1 Int)
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

; Big-OR: each pigeon in at least one hole (mechanical exists elimination)
; forall p. exists h. InHole(p,h)  -->  OR over all holes per pigeon
(assert (or (= a00 1) (= a01 1) (= a02 1)))
(assert (or (= a10 1) (= a11 1) (= a12 1)))
(assert (or (= a20 1) (= a21 1) (= a22 1)))
(assert (or (= a30 1) (= a31 1) (= a32 1)))

; Pairwise exclusion: no two pigeons share a hole
; forall p1 p2 h. (p1!=p2 AND InHole(p1,h)) => NOT InHole(p2,h)
; --> one explicit clause per (pigeon-pair, hole) triple, NOT row/column-sum
(assert (not (and (= a00 1) (= a10 1))))
(assert (not (and (= a00 1) (= a20 1))))
(assert (not (and (= a00 1) (= a30 1))))
(assert (not (and (= a10 1) (= a20 1))))
(assert (not (and (= a10 1) (= a30 1))))
(assert (not (and (= a20 1) (= a30 1))))
(assert (not (and (= a01 1) (= a11 1))))
(assert (not (and (= a01 1) (= a21 1))))
(assert (not (and (= a01 1) (= a31 1))))
(assert (not (and (= a11 1) (= a21 1))))
(assert (not (and (= a11 1) (= a31 1))))
(assert (not (and (= a21 1) (= a31 1))))
(assert (not (and (= a02 1) (= a12 1))))
(assert (not (and (= a02 1) (= a22 1))))
(assert (not (and (= a02 1) (= a32 1))))
(assert (not (and (= a12 1) (= a22 1))))
(assert (not (and (= a12 1) (= a32 1))))
(assert (not (and (= a22 1) (= a32 1))))

; Total pairwise clauses: 18

(check-sat)
; UNSAT: same answer as SNF, but reached via full unreduced clause set
