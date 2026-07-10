import json, statistics
from pathlib import Path

def summ(path):
    data = json.loads(Path(path).read_text())
    times = [r["elapsed_ms"] for r in data]
    tos = sum(r["timed_out"] for r in data)
    return dict(mean=statistics.mean(times),
                stdev=statistics.stdev(times) if len(times) > 1 else 0,
                n=len(times), tos=tos)

# Clause/var counts (from generator output)
counts = {
    "b3":   dict(nonsnf_vars=100, nonsnf_clauses=460+10, snf_clauses=12),
    "php3": dict(nonsnf_vars=12,  nonsnf_clauses=22,     snf_clauses=7),
    "php4": dict(nonsnf_vars=20,  nonsnf_clauses=45,     snf_clauses=9),
    "php5": dict(nonsnf_vars=30,  nonsnf_clauses=81,     snf_clauses=11),
    "php6": dict(nonsnf_vars=42,  nonsnf_clauses=133,    snf_clauses=13),
}

benches = ["b3", "php3", "php4", "php5", "php6"]
names   = ["b3 mutex (10!)", "PHP3 (4p/3h)", "PHP4 (5p/4h)", "PHP5 (6p/5h)", "PHP6 (7p/6h)"]

rows = []
for b, name in zip(benches, names):
    naive  = summ(f"z3-solver/results/results_{b}_naive.json")
    nonsnf = summ(f"z3-solver/results_nonsnf/results_{b}_nonsnf.json")
    struct = summ(f"z3-solver/results/results_{b}_structured.json")
    c = counts[b]
    rows.append([
        name,
        f"{naive['mean']:.1f}", f"{naive['stdev']:.1f}", f"{naive['tos']}/{naive['n']}",
        f"{c['nonsnf_clauses']}", f"{nonsnf['mean']:.1f}", f"{nonsnf['stdev']:.1f}", f"{nonsnf['tos']}/{nonsnf['n']}",
        f"{c['snf_clauses']}", f"{struct['mean']:.1f}", f"{struct['stdev']:.1f}", f"{struct['tos']}/{struct['n']}",
    ])

headers = ["Benchmark",
           "Naive\nmean(ms)", "Naive\nσ(ms)", "Naive\ntimeouts",
           "Non-SNF\nclauses", "Non-SNF\nmean(ms)", "Non-SNF\nσ(ms)", "Non-SNF\ntimeouts",
           "SNF\nclauses", "SNF\nmean(ms)", "SNF\nσ(ms)", "SNF\ntimeouts"]

# Print as markdown table for in-text use
print("| " + " | ".join(h.replace("\n"," ") for h in headers) + " |")
print("|" + "---|"*len(headers))
for r in rows:
    print("| " + " | ".join(r) + " |")