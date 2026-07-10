"""
cpython_version_diff.py — check I-1 through I-4 witness patterns across
CPython tagged releases, per Corollary 9a (track1_snf_formal.md).

Fetches base_events.py, tasks.py, locks.py, and queues.py from each
tagged release and greps for the specific structural patterns the
Step 2 / Consistency Interface witnesses depend on, flagging any
version where a pattern is absent so it can be inspected by hand.

Usage:
    python cpython_version_diff.py

Requires internet access to raw.githubusercontent.com.

IMPORTANT: a "MISSING" result does NOT by itself mean the version fails
I-1-I-4. CPython renames identifiers across versions (e.g. the 3.12
split of Task.__step into __step / __step_run_and_handle_result did not
exist under those names in earlier versions). A MISSING result is a
signal to open that version's file and check the structurally
equivalent pattern by hand, not an automatic failure verdict.
"""
import urllib.request

VERSIONS = ["v3.9.19", "v3.10.14", "v3.11.9", "v3.12.3", "v3.13.0"]

FILES = {
    "base_events.py": "Lib/asyncio/base_events.py",
    "tasks.py": "Lib/asyncio/tasks.py",
    "locks.py": "Lib/asyncio/locks.py",
    "queues.py": "Lib/asyncio/queues.py",
}

# (condition label, substrings to search for — ALL must be present to pass)
CHECKS = {
    "base_events.py": [
        ("I-1/SNF-1 (FIFO ntodo snapshot)", ["ntodo = len(self._ready)", "popleft()"]),
        ("I-2/SNF-2 (bounded dispatch)", ["for i in range(ntodo)"]),
    ],
    "tasks.py": [
        ("I-3/SNF-3 (synchronous step)", ["coro.send", "coro.throw"]),
    ],
    "queues.py": [
        ("I-4/SNF-4 (FIFO getters/putters)", ["_getters", "_putters", "popleft()"]),
    ],
    "locks.py": [
        ("I-4/SNF-4 (FIFO lock waiters)", ["_waiters", "next(iter(self._waiters))"]),
    ],
}

RAW_URL = "https://raw.githubusercontent.com/python/cpython/{tag}/{path}"


def fetch(tag, path):
    url = RAW_URL.format(tag=tag, path=path)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"__FETCH_ERROR__: {e}"


def main():
    report = {}
    for tag in VERSIONS:
        report[tag] = {}
        for fname, path in FILES.items():
            content = fetch(tag, path)
            for check_name, needles in CHECKS.get(fname, []):
                if content.startswith("__FETCH_ERROR__"):
                    report[tag][check_name] = f"FETCH FAILED ({content})"
                    continue
                missing = [n for n in needles if n not in content]
                report[tag][check_name] = "OK" if not missing else f"MISSING: {missing}"

    any_missing = False
    for tag, checks in report.items():
        print(f"\n=== {tag} ===")
        for check_name, status in checks.items():
            marker = "OK " if status == "OK" else "!! "
            if status != "OK":
                any_missing = True
            print(f"  [{marker}] {check_name}: {status}")

    print("\n" + "=" * 60)
    if any_missing:
        print("Some checks show MISSING or FETCH FAILED. Inspect those")
        print("version/file combinations by hand for the structurally")
        print("equivalent pattern under a possibly different name before")
        print("concluding I-1-I-4 fails for that version.")
    else:
        print("All checked versions show all witness patterns present")
        print("under their 3.12-era names. (Still verify by hand for any")
        print("version where identifiers may have shifted silently.)")


if __name__ == "__main__":
    main()