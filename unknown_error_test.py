import os
import json

FOLDER = "results/"

VALID_RESULTS = {"unsat", "sat", "unknown"}

for filename in sorted(os.listdir(FOLDER)):
    if not filename.endswith(".json"):
        continue

    filepath = os.path.join(FOLDER, filename)

    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Could not read {filename}: {e}")
        continue

    bad_entries = [
        entry for entry in data
        if entry.get("result") not in VALID_RESULTS
    ]

    if bad_entries:
        print(f"\n=== {filename} ===")
        for entry in bad_entries:
            print(json.dumps(entry, indent=2))