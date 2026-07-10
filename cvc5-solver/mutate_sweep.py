"""
mutate_sweep_cvc5.py
====================
CVC5 variant of mutate_sweep_v4.py.
Intended for structured (QF_LIA) benchmarks only.

Key differences from v4:
  - Uses CVC5 Python API instead of Z3
  - Seed injection uses (set-option :seed N) not :random-seed
  - Naive AUFLIA benchmarks return 'unknown' immediately in CVC5
    (CVC5 cannot handle AUFLIA quantifiers) — run structured only
  - Same mutations: seed injection, variable rename, assert shuffle

Usage:
  # Structured benchmarks only:
  python3 mutate_sweep_cvc5.py --smt final_benchmarks/b1_structured.smt2 \
                                --label b1_structured_cvc5 --n 50 --timeout 60

  # Do NOT run on naive files — CVC5 returns unknown instantly for AUFLIA
"""

import argparse, json, random, re, statistics, time
from pathlib import Path
import cvc5


# ── 1. Tokenizer (identical to v4) ───────────────────────────────────────────

def split_top_level(text: str) -> list[str]:
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
    s = tok.strip()
    return bool(re.match(
        r'^\(assert\s+\((>=|<=|=)\s+\S+\s+-?\d+\)\)$'
        r'|^\(assert\s+\(or\s+\(=\s+\S+\s+\d+\)\s+\(=\s+\S+\s+\d+\)\)\)$',
        s
    ))


def mutate(original_text: str, seed: int, rng: random.Random,
           do_rename: bool, do_shuffle: bool) -> str:
    tokens = split_top_level(original_text)

    # Build rename map for ALL declared names
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

    # Shuffle non-bound asserts only
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
    # KEY DIFFERENCE: inject (set-option :seed N) not :random-seed
    header_parts, decl_parts, assert_parts, footer_parts = [], [], [], []
    seed_injected = False

    for tok in tokens:
        c = classify(tok)
        if c == 'ws_or_comment':
            continue
        elif c == 'set-logic':
            header_parts.append(tok)
            if not seed_injected:
                header_parts.append(f"(set-option :seed {seed})")
                seed_injected = True
        elif c == 'set-option':
            # Strip both Z3 :random-seed and CVC5 :seed if present
            if ':random-seed' in tok or ':seed' in tok:
                if not seed_injected:
                    header_parts.append(f"(set-option :seed {seed})")
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


# ── 4. CVC5 runner ───────────────────────────────────────────────────────────

def run_cvc5(smt_text: str, timeout_sec: float, tmp_path: Path) -> dict:
    """
    Solve using CVC5 Python API.
    Uses unique tmp_path per run to avoid file contamination.
    CVC5 timeout is set via tlimit option (milliseconds).
    """
    tmp_path.write_text(smt_text)

    solver = cvc5.Solver()
    solver.setOption('tlimit', str(int(timeout_sec * 1000)))

    parser = cvc5.InputParser(solver)
    # Read from file for reliability
    parser.setStringInput(
        cvc5.InputLanguage.SMT_LIB_2_6,
        tmp_path.read_text(),
        str(tmp_path)
    )
    sm = parser.getSymbolManager()

    result = 'unknown'
    start = time.perf_counter()
    try:
        while True:
            cmd = parser.nextCommand()
            if cmd.isNull():
                break
            out = cmd.invoke(solver, sm)
            if out and out.strip() in ('sat', 'unsat', 'unknown'):
                result = out.strip()
    except Exception as e:
        result = f"error:{e}"

    elapsed = time.perf_counter() - start
    timed_out = (result == 'unknown') or (elapsed >= timeout_sec)

    try: tmp_path.unlink()
    except: pass

    return dict(
        elapsed_ms = round(elapsed * 1000, 3),
        result     = result,
        timed_out  = timed_out,
    )


# ── 5. Sweep ─────────────────────────────────────────────────────────────────

def sweep(smt_path: str, label: str, n: int, timeout: float,
          output_dir: str = "cvc5-solver/results") -> list:

    # Warn if running naive file
    if 'naive' in smt_path.lower():
        print(f"\n  WARNING: {smt_path} appears to be a naive AUFLIA file.")
        print(f"  CVC5 returns 'unknown' instantly for AUFLIA quantifiers.")
        print(f"  Run structured files only with this script.\n")

    original_text = Path(smt_path).read_text()
    results       = []
    master_rng    = random.Random(42)
    out_dir       = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path("/tmp") / f"sweep_cvc5_{label}"
    tmp_dir.mkdir(exist_ok=True)

    print(f"\n{'='*68}")
    print(f"  {label}  [CVC5 v{cvc5.__version__}]")
    print(f"  smt    : {smt_path}")
    print(f"  n={n}   timeout={timeout}s   outdir={output_dir}")
    print(f"{'='*68}")
    print(f"  {'#':>3}  {'seed':>12}  {'ren':>5}  {'shuf':>5}  "
          f"{'time(ms)':>10}  result")
    print(f"  {'-'*55}")

    # Warmup — prime CVC5 JIT and OS caches
    _warmup_rng  = random.Random(0)
    _warmup_text = mutate(original_text, 0, _warmup_rng, False, False)
    _warmup_tmp  = tmp_dir / "warmup.smt2"
    run_cvc5(_warmup_text, timeout, _warmup_tmp)

    error_count = 0

    for i in range(n):
        seed       = master_rng.randint(0, 2**31 - 1)
        rng        = random.Random(seed)
        mode       = i % 3
        do_rename  = mode in (1, 2)
        do_shuffle = mode in (0, 2)

        tmp_path = tmp_dir / f"run_{i+1:03d}.smt2"
        mutated  = mutate(original_text, seed, rng, do_rename, do_shuffle)
        r        = run_cvc5(mutated, timeout, tmp_path)

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
            solver     = "cvc5",
        ))

    try: tmp_dir.rmdir()
    except: pass

    # Save results
    runs_file = out_dir / f"results_{label}.json"
    runs_file.write_text(json.dumps(results, indent=2))

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
        print(f"  *** CORRECTNESS GAP: returns SAT ***")
    if n_to == n:
        print(f"  *** ALL UNKNOWN — likely a naive AUFLIA file ***")

    return results


# ── 6. Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="CVC5 mutation sweep — structured (QF_LIA) benchmarks only"
    )
    ap.add_argument("--smt",     required=True,
                    help="Path to .smt2 file (structured/QF_LIA only)")
    ap.add_argument("--label",   required=True,
                    help="Label for output file (e.g. php5_structured_cvc5)")
    ap.add_argument("--n",       type=int,   default=50,
                    help="Number of mutations (default: 50)")
    ap.add_argument("--timeout", type=float, default=60.0,
                    help="Per-run timeout seconds (default: 60)")
    ap.add_argument("--outdir",  default="results",
                    help="Output directory (default: cvc5-solver/results)")
    args = ap.parse_args()

    sweep(args.smt, args.label, args.n, args.timeout, args.outdir)