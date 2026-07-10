import z3, time, statistics, math
TIMEOUT_MS = 10000

def structured_encoding(n):
    x = z3.Int('x')
    disjuncts = [x == i for i in range(n)]
    return z3.Or(*disjuncts), len(disjuncts)

def time_solve(n, runs=5):
    times = []
    result = None
    for seed in range(runs):
        s = z3.Solver()
        s.set("random_seed", seed)
        s.set("timeout", TIMEOUT_MS)
        enc, size = structured_encoding(n)
        s.add(enc)
        x = z3.Int('x')
        s.add(z3.Or(x < 0, x >= n))
        t0 = time.time()
        r = s.check()
        t1 = time.time()
        times.append((t1 - t0) * 1000)
        result = r
    return result, times, size

print(f"{'n':>4} | {'n!':>18} | {'disjuncts':>10} | {'result':>9} | {'mean ms':>10} | {'sigma':>8}")
for n in [2,4,6,8,10,15,20,30,50,100]:
    r, times, size = time_solve(n)
    mean = statistics.mean(times); sigma = statistics.pstdev(times)
    nfact = math.factorial(n) if n <= 20 else float('inf')
    print(f"{n:>4} | {nfact!s:>18} | {size:>10} | {str(r):>9} | {mean:>10.3f} | {sigma:>8.3f}")