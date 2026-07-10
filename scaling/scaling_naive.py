import z3, time, statistics

TIMEOUT_MS = 8000

def naive_auflia_encoding(n):
    Order = z3.Function('order', z3.IntSort(), z3.IntSort())
    x = z3.Int('x')
    i = z3.Int('i')
    is_last = z3.ForAll([i], z3.Implies(
        z3.And(i >= 0, i < n, i != x),
        Order(x) > Order(i)
    ))
    perm_constraint = z3.And([z3.And(Order(k) >= 0, Order(k) < n) for k in range(n)] +
                              [z3.Distinct([Order(k) for k in range(n)])])
    return z3.And(perm_constraint, is_last)

print(f"{'n':>3} | {'result':>9} | {'mean ms':>10} | {'sigma':>8} | timeouts")
for n in [2, 3, 4, 5, 6, 7, 8, 9, 10]:
    times = []
    result = None
    timeouts = 0
    for seed in range(3):
        s = z3.Solver()
        s.set("random_seed", seed)
        s.set("timeout", TIMEOUT_MS)
        s.add(naive_auflia_encoding(n))
        x = z3.Int('x')
        s.add(z3.Or(x < 0, x >= n))
        t0 = time.time()
        r = s.check()
        t1 = time.time()
        times.append((t1-t0)*1000)
        result = r
        if str(r) == 'unknown':
            timeouts += 1
    mean = statistics.mean(times); sigma = statistics.pstdev(times)
    print(f"{n:>3} | {str(result):>9} | {mean:>10.2f} | {sigma:>8.2f} | {timeouts}")