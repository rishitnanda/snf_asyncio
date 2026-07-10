"""
mutate_sweep_v4.py
==================
Mariposa-style mutation sweep for SMT-LIB files.

Fixes from v3:
  - warmup run added to eliminate cold-start JIT/OS cache noise

Fixes from v2:
  - declare-fun names now included in rename map (was causing unknown constant errors)
  - domain bound asserts excluded from shuffle (was causing ordering errors)
  - unique tmp file per run using label+run index (was causing file contamination)
  - summary JSON removed (per project requirements)

Mutations (semantics-preserving):
  1. Seed injection   -- (set-option :random-seed N)
  2. Variable rename  -- randomises ALL declared names (const + fun)
  3. Assert shuffle   -- reorders non-bound asserts only

Usage:
  python3 mutate_sweep_v4.py --smt final_benchmarks/b1_naive.smt2 \
                              --label b1_naive --n 50 --timeout 60
"""

import argparse, json, random, re, statistics, time
from pathlib import Path
import z3


# ── 1. Parenthesis-aware tokenizer ───────────────────────────────────────────

def split_top_level(text: str) -> list[str]:
    """Split SMT-LIB text into top-level tokens, handling multi-line assertions."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == ';':
            j = text.find('\n', i)
            j = j + 1 if j != -1 else n
            tokens.append(text[i:j])
            i = j
        elif text[i] in ' \t\n\r':
            j = i + 1
            while j < n and text[j] in ' \t\n\r':
                j += 1
            tokens.append(text[i:j])
            i = j
        elif text[i] == '(':
            depth = 0
            j = i
            while j < n:
                if   text[j] == '(': depth += 1
                elif text[j] == ')':
                    depth -= 1
                    if depth == 0:
                        tokens.append(text[i:j+1])
                        i = j + 1
                        break
                elif text[j] == ';':
                    k = text.find('\n', j)
                    j = k if k != -1 else n - 1
                j += 1
            else:
                tokens.append(text[i:])
                i = n
        else:
            j = i + 1
            while j < n and text[j] not in ' \t\n\r(;':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def classify(tok: str) -> str:
    s = tok.strip()
    if not s or s.startswith(';'):        return 'ws_or_comment'
    if re.match(r'^\(set-logic\b',    s): return 'set-logic'
    if re.match(r'^\(set-option\b',   s): return 'set-option'
    if re.match(r'^\(declare-const\b', s): return 'declare-const'
    if re.match(r'^\(declare-fun\b',   s): return 'declare-fun'
    if re.match(r'^\(assert\b',        s): return 'assert'
    if re.match(r'^\(check-sat\b',     s): return 'check-sat'
    if re.match(r'^\(get-model\b',     s): return 'get-model'
    return 'other'


def parse_declare_const(tok: str):
    m = re.match(r'\(declare-const\s+(\S+)\s+(.*)\)\s*$', tok.strip(), re.DOTALL)
    return (m.group(1), m.group(2).strip()) if m else None


def parse_declare_fun(tok: str):
    m = re.match(r'\(declare-fun\s+(\S+)\s+(.*)\)\s*$', tok.strip(), re.DOTALL)
    return (m.group(1), m.group(2).strip()) if m else None


# ── 2. Name generator ────────────────────────────────────────────────────────

ADJ  = ["alpha","bravo","delta","echo","foxtrot","golf","hotel","india",
        "juliet","kilo","lima","mike","november","oscar","papa","quebec",
        "romeo","sierra","tango","uniform","victor","whisky","xray",
        "yankee","zulu"]
NOUN = ["task","sched","worker","queue","lock","state","flag","event",
        "timer","count","result","value","handle","item","node","edge",
        "phase","step","tick","slot"]

def fresh_name(rng: random.Random, used: set) -> str:
    for _ in range(500):
        n = f"{rng.choice(ADJ)}_{rng.choice(NOUN)}_{rng.randint(0,999):03d}"
        if n not in used:
            used.add(n)
            return n
    return f"v_{rng.randint(0, 999999)}"


# ── 3. Mutator ───────────────────────────────────────────────────────────────

def is_domain_bound(tok: str) -> bool:
    """
    Returns True for simple domain-bound asserts that must stay in order.
    e.g. (assert (>= a00 0))  (assert (<= a00 1))  (assert (= x 5))
    These must not be shuffled before their declare-const.
    """
    s = tok.strip()
    return bool(re.match(
        r'^\(assert\s+\('
        r'(>=|<=|=)\s+\S+\s+-?\d+\)\)$'
        r'|^\(assert\s+\(or\s+\(=\s+\S+\s+\d+\)\s+\(=\s+\S+\s+\d+\)\)\)$',
        s
    ))


def mutate(original_text: str, seed: int, rng: random.Random,
           do_rename: bool, do_shuffle: bool) -> str:
    tokens = split_top_level(original_text)

    # FIX 1: build rename map for ALL declared names (const AND fun)
    name_map = {}
    if do_rename:
        used = set()
        for tok in tokens:
            c = classify(tok)
            if c == 'declare-const':
                r = parse_declare_const(tok)
                if r: used.add(r[0])
            elif c == 'declare-fun':
                r = parse_declare_fun(tok)
                if r: used.add(r[0])
        for tok in tokens:
            c = classify(tok)
            if c == 'declare-const':
                r = parse_declare_const(tok)
                if r and r[0] not in name_map:
                    name_map[r[0]] = fresh_name(rng, used)
            elif c == 'declare-fun':
                r = parse_declare_fun(tok)
                if r and r[0] not in name_map:
                    name_map[r[0]] = fresh_name(rng, used)

    def apply_rename(s: str) -> str:
        for orig, repl in name_map.items():
            s = re.sub(r'(?<![a-zA-Z0-9_])' + re.escape(orig) +
                       r'(?![a-zA-Z0-9_])', repl, s)
        return s

    # FIX 2: only shuffle non-bound asserts
    assert_indices = [i for i, t in enumerate(tokens) if classify(t) == 'assert']
    if do_shuffle and len(assert_indices) > 1:
        shuffleable = [i for i in assert_indices
                       if not is_domain_bound(tokens[i])]
        if len(shuffleable) > 1:
            shuffled = [tokens[i] for i in shuffleable]
            rng.shuffle(shuffled)
            for idx, new_tok in zip(shuffleable, shuffled):
                tokens[idx] = new_tok

    # Rebuild: header → decls → asserts → footer
    header_parts, decl_parts, assert_parts, footer_parts = [], [], [], []
    seed_injected = False

    for tok in tokens:
        c = classify(tok)
        if c == 'ws_or_comment':
            continue
        elif c == 'set-logic':
            header_parts.append(tok)
            if not seed_injected:
                header_parts.append(f"(set-option :random-seed {seed})")
                seed_injected = True
        elif c == 'set-option':
            if ':random-seed' in tok:
                if not seed_injected:
                    header_parts.append(f"(set-option :random-seed {seed})")
                    seed_injected = True
            else:
                header_parts.append(tok)
        elif c in ('declare-const', 'declare-fun'):
            decl_parts.append(apply_rename(tok))
        elif c == 'assert':
            assert_parts.append(apply_rename(tok))
        elif c in ('check-sat', 'get-model'):
            footer_parts.append(tok)
        else:
            decl_parts.append(apply_rename(tok))

    return "\n".join(header_parts + decl_parts + assert_parts + footer_parts) + "\n"


# ── 4. In-process Z3 runner ──────────────────────────────────────────────────

def run_z3(smt_text: str, timeout_sec: float, tmp_path: Path) -> dict:
    """
    FIX 3: unique tmp_path per run — prevents file contamination
    between back-to-back sweep runs.
    """
    tmp_path.write_text(smt_text)
    solver = z3.Solver()
    solver.set("timeout", int(timeout_sec * 1000))
    start = time.perf_counter()
    try:
        solver.from_file(str(tmp_path))
        res       = solver.check()
        elapsed   = time.perf_counter() - start
        res_str   = str(res)
        timed_out = (res_str == "unknown") or (elapsed >= timeout_sec)
        return dict(elapsed_ms=round(elapsed * 1000, 3),
                    result=res_str, timed_out=timed_out)
    except z3.Z3Exception as e:
        elapsed = time.perf_counter() - start
        return dict(elapsed_ms=round(elapsed * 1000, 3),
                    result=f"error:{e}", timed_out=False)
    finally:
        # Clean up tmp file after each run
        try: tmp_path.unlink()
        except: pass


# ── 5. Sweep ─────────────────────────────────────────────────────────────────

def sweep(smt_path: str, label: str, n: int, timeout: float,
          output_dir: str = "results") -> list:

    original_text = Path(smt_path).read_text()
    results       = []
    master_rng    = random.Random(42)
    out_dir       = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Unique tmp dir per sweep label — no contamination between runs
    tmp_dir = Path("/tmp") / f"sweep_v4_{label}"
    tmp_dir.mkdir(exist_ok=True)

    print(f"\n{'='*68}")
    print(f"  {label}")
    print(f"  smt    : {smt_path}")
    print(f"  n={n}   timeout={timeout}s   outdir={output_dir}")
    print(f"{'='*68}")
    print(f"  {'#':>3}  {'seed':>12}  {'ren':>5}  {'shuf':>5}  "
          f"{'time(ms)':>10}  result")
    print(f"  {'-'*55}")

    # Warmup: solve once to prime Z3's JIT and OS caches
    # This prevents the first 1-2 real runs being inflated by cold-start overhead
    _warmup_tmp = tmp_dir / "warmup.smt2"
    _warmup_rng = random.Random(0)
    _warmup_text = mutate(original_text, 0, _warmup_rng, False, False)
    run_z3(_warmup_text, timeout, _warmup_tmp)

    error_count = 0

    for i in range(n):
        seed       = master_rng.randint(0, 2**31 - 1)
        rng        = random.Random(seed)
        mode       = i % 3
        do_rename  = mode in (1, 2)
        do_shuffle = mode in (0, 2)

        # Unique tmp file per run
        tmp_path = tmp_dir / f"run_{i+1:03d}.smt2"

        mutated = mutate(original_text, seed, rng, do_rename, do_shuffle)
        r       = run_z3(mutated, timeout, tmp_path)

        if r["result"].startswith("error:"):
            error_count += 1

        tag = "TIMEOUT" if r["timed_out"] else \
              "ERROR"   if r["result"].startswith("error:") else \
              r["result"].upper()

        bar = "█" * min(int(r["elapsed_ms"] / (timeout * 1000) * 30), 30)
        print(f"  [{i+1:02d}]  {seed:>12d}  {str(do_rename):>5}  "
              f"{str(do_shuffle):>5}  {r['elapsed_ms']:>10.2f}  "
              f"[{tag:<7}]  {bar}")

        results.append(dict(
            run        = i + 1,
            seed       = seed,
            do_rename  = do_rename,
            do_shuffle = do_shuffle,
            elapsed_ms = r["elapsed_ms"],
            result     = r["result"],
            timed_out  = r["timed_out"],
            label      = label,
        ))

    # Cleanup tmp dir
    try: tmp_dir.rmdir()
    except: pass

    # Save results JSON only (no summary file)
    runs_file = out_dir / f"results_{label}.json"
    runs_file.write_text(json.dumps(results, indent=2))

    # Print summary to terminal
    times   = [r["elapsed_ms"] for r in results]
    n_to    = sum(r["timed_out"] for r in results)
    res_set = list(set(r["result"] for r in results
                       if not r["result"].startswith("error:")))
    has_sat = any(r not in ("unsat", "unknown") for r in res_set)
    mean_t  = statistics.mean(times)
    stdev_t = statistics.stdev(times) if len(times) > 1 else 0.0

    print(f"\n  {'─'*55}")
    print(f"  Saved  → {runs_file}")
    print(f"  mean={mean_t:.2f}ms  stdev={stdev_t:.2f}ms  "
          f"timeouts={n_to}/{n}  errors={error_count}/{n}")
    if error_count > 0:
        print(f"  *** {error_count} ERROR runs detected ***")
    if has_sat:
        print(f"  *** CORRECTNESS GAP: naive returns SAT ***")

    return results


# ── 6. Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Mariposa-style mutation sweep for SMT-LIB files"
    )
    ap.add_argument("--smt",     required=True)
    ap.add_argument("--label",   required=True)
    ap.add_argument("--n",       type=int,   default=50)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--outdir",  default="results")
    args = ap.parse_args()
    sweep(args.smt, args.label, args.n, args.timeout, args.outdir)