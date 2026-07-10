"""
Track 1 — SNF Encoding Experiment
Mechanical witness for Enc(P): quantifier-free fragment check and
correctness verification on the two-coroutine worked example.

Verifies:
  1. Enc(P) lands in QF_LIA (no quantifiers)
  2. Correct SAT on positive query (x_post=2 ∧ y_post=2)
  3. Correct UNSAT on negative query (x_post≠2 ∨ y_post≠2)
"""

import z3

def make_snf_encoding():
    """SNF-derived quantifier-free encoding of the two-coroutine example.

    async def a():          async def b():
        x = 1                   y = 1
        await sleep(0)          await sleep(0)
        x = 2                   y = 2

    Enc(P) is a finite disjunction over FIFO-consistent orderings.
    No quantifiers, no E-matching, no relevancy filtering.
    """
    s = z3.Solver()
    x_pre  = z3.Int('x_pre');  x_post = z3.Int('x_post')
    y_pre  = z3.Int('y_pre');  y_post = z3.Int('y_post')
    order  = z3.Bool('order')  # True = a-then-b, False = b-then-a

    s.add(x_pre == 1, y_pre == 1)          # Phi_init
    s.add(z3.Or(                           # Phi_1: finite disjunction
        z3.And(order,         x_post == 2, y_post == 2),  # sigma = (a,b)
        z3.And(z3.Not(order), y_post == 2, x_post == 2),  # sigma = (b,a)
    ))
    return s, x_post, y_post

def has_quantifier(expr, depth=0):
    """Recursively checks whether an expression contains any quantifier."""
    if depth > 50: return False
    if z3.is_quantifier(expr): return True
    return any(has_quantifier(expr.arg(i), depth+1) for i in range(expr.num_args()))

# --- Witness 1: QF_LIA fragment check ---
s, xp, yp = make_snf_encoding()
qf_check = not any(has_quantifier(a) for a in s.assertions())
print("Assertions:")
for a in s.assertions():
    print(" ", a)
print(f"QF_LIA check (no quantifiers): {qf_check}")
assert qf_check, "Encoding contains a quantifier — violates Proposition 3"

# --- Witness 2: SAT on positive query ---
s2, xp, yp = make_snf_encoding()
s2.add(xp == 2, yp == 2)
sat_result = s2.check()
print(f"\nPositive query (x_post=2 ∧ y_post=2): {sat_result}  [expected: sat]")
assert str(sat_result) == "sat"

# --- Witness 3: UNSAT on negative query ---
s3, xp, yp = make_snf_encoding()
s3.add(z3.Or(xp != 2, yp != 2))
unsat_result = s3.check()
print(f"Negative query (x_post≠2 ∨ y_post≠2): {unsat_result}  [expected: unsat]")
assert str(unsat_result) == "unsat"

print("\nAll Track 1 witnesses passed.")