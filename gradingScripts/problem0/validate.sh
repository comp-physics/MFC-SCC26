#!/usr/bin/env bash
# Validates deliverables_<team#>/problem0/: one configuration<#>/ directory per configuration
# of required disclosures, each holding the files in files.txt. No directories means nothing
# needed disclosing.
# Usage: ./gradingScripts/problem0/validate.sh --input <path to deliverables_<team#>/problem0> [--files-only]

set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib.sh"

# Only the skipped count is checked: CPU and GPU runs differ in passed and total (GPU runs drop
# the IGR Gauss-Seidel cases without counting them as skipped), but a full run on either skips
# just the convergence tests (39: the "Convergence" lines of ./mfc.sh test -l), plus one MUSCL
# case under nvfortran in Docker. More means --only, --percent, --shard, --no-chemistry or no MPI.
MAX_SKIPPED=40

# check_tests <log> <gpu|cpu>: a complete ./mfc.sh test run on the right hardware with no failures.
check_tests() {
    local log=$1 hw=$2 label=${1#"$GS_INPUT"/} passed failed skipped
    passed=$(grep -oE '^[^0-9A-Za-z]*[0-9]+ passed' "$log" | tail -1 | grep -oE '[0-9]+')
    failed=$(grep -oE '^[^0-9A-Za-z]*[0-9]+ failed' "$log" | tail -1 | grep -oE '[0-9]+')
    skipped=$(grep -oE '^[^0-9A-Za-z]*[0-9]+ skipped' "$log" | tail -1 | grep -oE '[0-9]+')
    if [ -z "$passed" ] || [ -z "$failed" ]; then
        gs_fail "$label: no test summary found; the log must cover a complete ./mfc.sh test run"
    elif [ "$failed" -ne 0 ] || [ "$passed" -eq 0 ]; then
        gs_fail "$label: $passed passed, $failed failed"
    elif [ "${skipped:-0}" -gt "$MAX_SKIPPED" ]; then
        gs_fail "$label: $skipped tests skipped; run the full suite with MPI (no --only, --percent or --shard)"
    else
        gs_pass "$label: $passed passed, 0 failed"
    fi
    if [ "$hw" = gpu ]; then
        grep -qE -- '--(acc|mp)-gpu' "$log" || gs_fail "$label: not a GPU test run (no --gpu acc/mp in the header)"
    else
        grep -q -- '--no-gpu' "$log" || gs_fail "$label: not a CPU test run (no --no-gpu in the header)"
    fi
}

gs_parse_args "$@"
echo "Validating problem 0 deliverables in $GS_INPUT"
gs_subdirs '^configuration[0-9]+$'
[ "${#GS_DIRS[@]}" -eq 0 ] && gs_note "no configuration<#>/ directories: declaring that no changes needed disclosure"
for d in "${GS_DIRS[@]}"; do
    gs_check_files "$here/files.txt" "$GS_INPUT/$d"
    gs_full || continue
    diff="$GS_INPUT/$d/$d.diff"
    [ -s "$diff" ] && { grep -q '^diff --git ' "$diff" && gs_pass "$d/$d.diff is a git diff" || gs_fail "$d/$d.diff is not git diff output"; }
    [ -s "$GS_INPUT/$d/${d}_gpu.log" ] && check_tests "$GS_INPUT/$d/${d}_gpu.log" gpu
    [ -s "$GS_INPUT/$d/${d}_cpu.log" ] && check_tests "$GS_INPUT/$d/${d}_cpu.log" cpu
done
gs_finish
