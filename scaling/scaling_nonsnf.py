import z3, time, itertools, statistics

TIMEOUT_MS = 15000

def non_snf_encoding(n):
    x = z3.Int('x')
    disjuncts = []
    for perm in itertools.permutations(range(n)):
        disjuncts.append(x == perm[-1])
    return z3.Or(*disjuncts), len(disjuncts)

def time_solve(n, runs=3):
    times = []
    result = None
    enc, size = non_snf_encoding(n)  # build once, this is the expensive part for large n
    for seed in range(runs):
        s = z3.Solver()
        s.set("random_seed", seed)
        s.set("timeout", TIMEOUT_MS)
        s.add(enc)
        x = z3.Int('x')
        s.add(z3.Or(x < 0, x >= n))
        t0 = time.time()
        r = s.check()
        t1 = time.time()
        times.append((t1 - t0) * 1000)
        result = r
    return result, times, size

print(f"{'n':>3} | {'raw disjuncts (n!)':>18} | {'result':>9} | {'mean ms':>10} | {'sigma':>8}")
for n in [2,4,6,7,8,9]:
    t_build0 = time.time()
    r, times, size = time_solve(n)
    t_build1 = time.time()
    mean = statistics.mean(times); sigma = statistics.pstdev(times)
    print(f"{n:>3} | {size:>18} | {str(r):>9} | {mean:>10.2f} | {sigma:>8.2f}   (build+solve wall: {t_build1-t_build0:.1f}s)")