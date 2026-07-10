#!/usr/bin/env bash
# Sweep snf-pipeline/pipeline.py across every repo in the Section 5.6 corpus.
#
# Usage:
#   ./sweep_corpus.sh corpus-study/repo_src results.csv
#
# For each repo directory, runs the pipeline on every .py file found inside
# it (recursively), parses stdout, and appends one row per sync-object check
# and per wait_for site to the CSV. Also writes a full raw log
# (results.csv.log) with everything the pipeline printed, in case you need
# to go back and check a specific line.

set -u
CORPUS_ROOT="${1:?usage: sweep_corpus.sh <corpus_root_dir> [output.csv]}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_CSV="${2:-$SCRIPT_DIR/results/results.csv}"
LOG_FILE="${OUT_CSV%.csv}.log"
SMT2_DIR="$(dirname "$OUT_CSV")/smt2"
PIPELINE="$SCRIPT_DIR/pipeline.py"

mkdir -p "$(dirname "$OUT_CSV")" "$SMT2_DIR"

echo "repo,file,check_type,object_name,kind_or_line,naive,structured,gap_or_flag" > "$OUT_CSV"
: > "$LOG_FILE"

for repo_dir in "$CORPUS_ROOT"/*/; do
    repo="$(basename "$repo_dir")"
    # Only .py files; skip test/ and setup.py noise which tend to be
    # sync-object-free and just add runtime.
    find "$repo_dir" \( -path "*/tests/*" -o -path "*/test/*" -o -name "test_*.py" -o -name "*_test.py" \) -prune -o \
        -name "*.py" -not -name "setup.py" -print \
        | while read -r pyfile; do

        echo "=== repo=$repo file=$pyfile ===" >> "$LOG_FILE"
        extra_flags=""
        if [[ "${ASSUME_PUBLIC_CONCURRENT:-0}" == "1" ]]; then
            extra_flags="--assume-public-concurrent"
        fi
        output=$(python3 "$PIPELINE" "$pyfile" --smt2-dir "$SMT2_DIR" --repo-label "$repo" $extra_flags 2>>"$LOG_FILE")
        echo "$output" >> "$LOG_FILE"

        # No sync objects and no wait_for sites -> skip, nothing to report
        if ! echo "$output" | grep -qE "^--- (LOCK|QUEUE|EVENT|wait_for)"; then
            continue
        fi

        current_kind=""
        current_name=""
        while IFS= read -r line; do
            if [[ "$line" =~ ^---\ (LOCK|QUEUE|EVENT)\ \'(.+)\'\ ---$ ]]; then
                current_kind="${BASH_REMATCH[1]}"
                current_name="${BASH_REMATCH[2]}"
                naive=""
                structured=""
            elif [[ "$line" =~ naive:\ +([a-z]+) ]]; then
                naive="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ structured:\ +([a-z]+) ]]; then
                structured="${BASH_REMATCH[1]}"
                gap="no"
                [[ "$naive" == "sat" && "$structured" == "unsat" ]] && gap="yes"
                echo "$repo,$pyfile,$current_kind,$current_name,,$naive,$structured,$gap" >> "$OUT_CSV"
            elif [[ "$line" =~ ^\ \ ([A-Za-z0-9_.]+):([0-9]+)\ \ naive=([a-z]+)\ +structured=([a-z]+)\ +\((.+)\)$ ]]; then
                coro="${BASH_REMATCH[1]}"
                lineno="${BASH_REMATCH[2]}"
                naive_wf="${BASH_REMATCH[3]}"
                struct_wf="${BASH_REMATCH[4]}"
                note="${BASH_REMATCH[5]}"
                echo "$repo,$pyfile,wait_for,${coro},${lineno},$naive_wf,$struct_wf,\"$note\"" >> "$OUT_CSV"
            fi
        done <<< "$output"
    done
done

echo "Done. CSV: $OUT_CSV   Full log: $LOG_FILE   SMT2 files: $SMT2_DIR"
echo "Summary:"
echo "  total rows:        $(($(wc -l < "$OUT_CSV") - 1))"
echo "  sync-object gaps:  $(grep -c ',yes$' "$OUT_CSV" || true)"
echo "  wait_for flags:    $(grep -c ',wait_for,' "$OUT_CSV" || true)"
echo "  .smt2 files:       $(find "$SMT2_DIR" -name '*.smt2' | wc -l)"