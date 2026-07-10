#!/usr/bin/env python3
"""
refine.py — Deconstruct the "unmediated" bucket produced by scan.py.

For every (kind, name) pair (e.g. SELF_ATTR:self._cache) within a repo, look
at ALL write_forms ever observed for that name across the whole repo's async
code (mediated or not — a write is a write regardless of whether other sites
also lock it), and classify the name into one of three buckets:

  READ_ONLY    - the name is never written (Store/subscript-write/augmented/
                 mutating-method) anywhere in the scanned async code. Every
                 access to it is trivially race-free: N readers can never
                 conflict with zero writers. This is exactly SNF-5's territory.

  COMMUTATIVE  - the name IS written, but every write observed is one of:
                   - subscript_write            (x[k] = v -- independent slot)
                   - augmented_commutative      (+=, |=, &=, ^=)
                   - mutating_method_commutative (.append/.add/.update/...)
                 i.e. every write is an operation whose effect does not depend
                 on interleaving order with other writes to the SAME name
                 (distinct keys commute; +=/|= etc. commute with each other
                 under the algebraic operation, ignoring the read-modify-write
                 non-atomicity of += itself, which is a separate, narrower
                 concern noted in limitations).

  DESTRUCTIVE  - at least one write to the name is a full_rebind (x = value,
                 unconditionally clobbers), an augmented_noncommutative op
                 (-=, *=, //=, etc.), a mutating_method_noncommutative call
                 (.pop/.remove/.clear/.insert/...), or an unresolved
                 "other_write". Two coroutines racing here CAN produce a
                 result that depends on interleaving order (a genuine
                 interference hazard) -- this is the bucket Path 2
                 (over-approximation / lock insertion) should target.

Then every individual UNMEDIATED interaction inherits its name's bucket. A
mediated interaction is left alone (already controlled; doesn't need
re-litigating), but is still used as write-evidence when computing the bucket
for its name (a write behind a lock in one function still means the name is
NOT read-only, and still tells us whether its write shape is commutative).

Caveat inherited from scan.py and worth restating: bucketing is done by
(kind, name) STRING within a repo -- e.g. two unrelated classes that both
happen to have a `self._count` attribute are folded into one bucket. This can
misclassify in both directions (a truly read-only `self._count` in class A
gets treated as written because class B's `self._count` is incremented
elsewhere). This is a real precision loss versus true per-class dataflow, and
is called out in the report.
"""
import json
from pathlib import Path
from collections import defaultdict

COMMUTATIVE_FORMS = {"subscript_write", "augmented_commutative", "mutating_method_commutative"}
DESTRUCTIVE_FORMS = {"full_rebind", "augmented_noncommutative", "mutating_method_noncommutative", "other_write"}
WRITE_FORMS = COMMUTATIVE_FORMS | DESTRUCTIVE_FORMS


def classify_name_bucket(write_forms_seen: set) -> str:
    if not write_forms_seen:
        return "READ_ONLY"
    if write_forms_seen <= COMMUTATIVE_FORMS:
        return "COMMUTATIVE"
    return "DESTRUCTIVE"


def refine_repo(data: dict) -> dict:
    interactions = data["interactions"]
    # Pass 1: collect write_forms per (kind, name)
    writes_by_name = defaultdict(set)
    for i in interactions:
        if i["write_form"] in WRITE_FORMS:
            writes_by_name[(i["kind"], i["name"])].add(i["write_form"])

    bucket_by_name = {k: classify_name_bucket(v) for k, v in writes_by_name.items()}

    # Pass 2: classify every interaction (bucket defaults to READ_ONLY if the
    # name never appears in writes_by_name at all)
    counts = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    mediated_counts = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    unmediated_counts = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    destructive_examples = []

    for i in interactions:
        key = (i["kind"], i["name"])
        bucket = bucket_by_name.get(key, "READ_ONLY")
        counts[bucket] += 1
        if i["mediated"]:
            mediated_counts[bucket] += 1
        else:
            unmediated_counts[bucket] += 1
            if bucket == "DESTRUCTIVE" and len(destructive_examples) < 5:
                destructive_examples.append(i)

    total = len(interactions)
    unmediated_total = sum(unmediated_counts.values())
    return {
        "total_interactions": total,
        "counts_by_bucket": counts,
        "mediated_by_bucket": mediated_counts,
        "unmediated_by_bucket": unmediated_counts,
        "unmediated_total": unmediated_total,
        "unmediated_destructive_pct_of_all": round(100 * unmediated_counts["DESTRUCTIVE"] / total, 2) if total else None,
        "unmediated_destructive_pct_of_unmediated": round(100 * unmediated_counts["DESTRUCTIVE"] / unmediated_total, 2) if unmediated_total else None,
        "distinct_names_seen": len({(i["kind"], i["name"]) for i in interactions}),
        "distinct_names_destructive": sum(1 for b in bucket_by_name.values() if b == "DESTRUCTIVE"),
        "distinct_names_commutative": sum(1 for b in bucket_by_name.values() if b == "COMMUTATIVE"),
        "distinct_names_readonly": sum(1 for b in bucket_by_name.values() if b == "READ_ONLY")
                                    + sum(1 for k in {(i["kind"], i["name"]) for i in interactions} if k not in bucket_by_name),
        "destructive_examples": destructive_examples,
    }


def main():
    root = Path(__file__).parent
    results_dir = root / "results"
    refined_dir = root / "refined"
    refined_dir.mkdir(exist_ok=True)

    per_repo = {}
    agg_counts = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    agg_unmediated = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    agg_mediated = {"READ_ONLY": 0, "COMMUTATIVE": 0, "DESTRUCTIVE": 0}
    total_all = 0

    for f in sorted(results_dir.glob("*.json")):
        if f.name == "_SUMMARY.json":
            continue
        data = json.load(open(f))
        refined = refine_repo(data)
        per_repo[data["repo"]] = refined
        with open(refined_dir / f.name, "w") as out:
            json.dump(refined, out, indent=2)
        total_all += refined["total_interactions"]
        for b in agg_counts:
            agg_counts[b] += refined["counts_by_bucket"][b]
            agg_unmediated[b] += refined["unmediated_by_bucket"][b]
            agg_mediated[b] += refined["mediated_by_bucket"][b]
        print(f"{data['repo']:22s} total={refined['total_interactions']:6d}  "
              f"RO={refined['counts_by_bucket']['READ_ONLY']:6d}  "
              f"COMM={refined['counts_by_bucket']['COMMUTATIVE']:5d}  "
              f"DESTR={refined['counts_by_bucket']['DESTRUCTIVE']:6d}  "
              f"unmediated-destructive%={refined['unmediated_destructive_pct_of_all']}")

    overall = {
        "total_interactions": total_all,
        "counts_by_bucket": agg_counts,
        "mediated_by_bucket": agg_mediated,
        "unmediated_by_bucket": agg_unmediated,
        "pct_of_all_read_only": round(100 * agg_counts["READ_ONLY"] / total_all, 2),
        "pct_of_all_commutative": round(100 * agg_counts["COMMUTATIVE"] / total_all, 2),
        "pct_of_all_destructive": round(100 * agg_counts["DESTRUCTIVE"] / total_all, 2),
        "pct_unmediated_read_only_of_all": round(100 * agg_unmediated["READ_ONLY"] / total_all, 2),
        "pct_unmediated_commutative_of_all": round(100 * agg_unmediated["COMMUTATIVE"] / total_all, 2),
        "pct_unmediated_destructive_of_all": round(100 * agg_unmediated["DESTRUCTIVE"] / total_all, 2),
    }
    with open(refined_dir / "_REFINED_SUMMARY.json", "w") as out:
        json.dump({"per_repo": per_repo, "overall": overall}, out, indent=2)

    print("\n=== OVERALL (refined) ===")
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()
