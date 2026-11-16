#!/usr/bin/env bash
# Validates deliverables_<team#>/problem2/: at least MIN_POINTS (weak|strong)_N<ranks>_(cpu|gpu)/
# directories for each scaling mode and hardware, plus peak_cpu/ and peak_gpu/, each holding
# the files in files.txt.
# SCC Connect teams (deliverables_CONNN/, or --scc-connect) need only MIN_POINTS_CONNECT_GPU points per GPU scaling mode.
# Usage: ./gradingScripts/problem2/validate.sh --input <path to deliverables_<team#>/problem2> [--files-only] [--scc-connect]

set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib.sh"

MIN_POINTS=4    # data points per scaling mode and hardware
MIN_POINTS_CONNECT_GPU=2
PEAK_CPU_N=400  # peak_cpu must be a strong-scaling 400^3 run
STEPS=100       # time steps every run must show

# check_run <dir> <scaling or ""> <cpu|gpu> <ranks or "">
check_run() {
    local d=$1 scaling=$2 hw=$3 ranks=$4 opts log steps last avg np
    opts="$GS_INPUT/$d/options.txt" log="$GS_INPUT/$d/mfc_log.txt"
    if [ -s "$opts" ]; then
        local got_scaling got_res
        got_scaling=$(gs_option "$opts" --scaling) got_res=$(gs_option "$opts" --resolution)
        if [ -z "$got_scaling" ] || [ -z "$got_res" ]; then
            gs_fail "$d/options.txt does not record --resolution and --scaling"
        elif [ -n "$scaling" ] && [ "$got_scaling" != "$scaling" ]; then
            gs_fail "$d/options.txt: --scaling $got_scaling, but the directory is for $scaling scaling"
        fi
        if [ "$d" = peak_cpu ] && { [ "$got_scaling" != strong ] || [ "$got_res" != "$PEAK_CPU_N" ]; }; then
            gs_fail "peak_cpu must be a strong-scaling ${PEAK_CPU_N}^3 run (--resolution $PEAK_CPU_N --scaling strong), got --resolution $got_res --scaling $got_scaling"
        fi
        [ "$(gs_option "$opts" --serial-io)" = True ] && gs_note "$d was run with --serial-io"
    fi
    [ -s "$log" ] || return 0

    if [ "$hw" = gpu ]; then
        grep -qE -- '--(acc|mp)-gpu' "$log" || gs_fail "$d/mfc_log.txt: not a GPU run (no --gpu acc/mp in the header)"
    else
        grep -q -- '--no-gpu' "$log" || gs_fail "$d/mfc_log.txt: not a CPU run (no --no-gpu in the header)"
    fi
    grep -qE -- '--(single|mixed)( |$)' "$log" && gs_fail "$d/mfc_log.txt: built with --single or --mixed; results must be double precision"
    # Time-step lines only: the "Saving" lines that follow also print (t_step N) and an (avg 0) placeholder
    steps=$(grep -E '\] step [0-9]+ of [0-9]+ \(t_step [0-9]+\)' "$log")
    last=$(grep -oE '\(t_step [0-9]+\)' <<< "$steps" | grep -oE '[0-9]+' | sort -n | tail -1)
    avg=$(grep -oE '\(avg +[0-9.E+-]+s\)' <<< "$steps" | tail -1 | grep -oE '[0-9.]+E[+-][0-9]+')
    if [ -z "$avg" ] || [ "${last:--1}" -ne $((STEPS - 1)) ]; then
        gs_fail "$d/mfc_log.txt must show all $STEPS time steps (last t_step $((STEPS - 1)), found ${last:-none})"
    elif ! grep -qE 'Exit Code: +0\b' "$log"; then
        gs_fail "$d/mfc_log.txt: the run did not finish with exit code 0"
    else
        gs_pass "$d/mfc_log.txt: $STEPS steps, avg ${avg}s per step"
    fi
    if [ -n "$ranks" ]; then
        np=$(grep -E '^\+ .*/bin/simulation' "$log" | grep -oE -- '(-np|--np|-n|--ntasks)[ =][0-9]+' | head -1 | grep -oE '[0-9]+$')
        if [ -z "$np" ]; then
            gs_note "$d: could not read the rank count from the launch line; check it by hand"
        elif [ "$np" != "$ranks" ]; then
            gs_note "$d: the launch line shows $np ranks (per node with -N > 1?); the directory says $ranks"
        fi
    fi
    gs_check_fingerprint "$GS_INPUT/$d/mfc_fingerprint.log"
}

gs_parse_args "$@"
echo "Validating problem 2 deliverables in $GS_INPUT"
gs_subdirs '^((weak|strong)_N[1-9][0-9]*_(cpu|gpu)|peak_(cpu|gpu))$'
declare -A count=()
for d in "${GS_DIRS[@]}"; do
    gs_check_files "$here/files.txt" "$GS_INPUT/$d"
    if [[ "$d" =~ ^(weak|strong)_N([0-9]+)_(cpu|gpu)$ ]]; then
        count[${BASH_REMATCH[1]}_${BASH_REMATCH[3]}]=$((${count[${BASH_REMATCH[1]}_${BASH_REMATCH[3]}]:-0} + 1))
        gs_full && check_run "$d" "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]}" "${BASH_REMATCH[2]}"
    else
        gs_full && check_run "$d" "" "${d#peak_}" ""
    fi
done
for group in weak_cpu weak_gpu strong_cpu strong_gpu; do
    n=${count[$group]:-0} need=$MIN_POINTS
    [ -n "$GS_CONNECT" ] && [[ "$group" == *_gpu ]] && need=$MIN_POINTS_CONNECT_GPU
    [ "$n" -ge "$need" ] && gs_pass "$group: $n data points" || gs_fail "$group: $n data point(s), need at least $need"
done
for d in peak_cpu peak_gpu; do
    [ -d "$GS_INPUT/$d" ] || gs_fail "missing: $d/"
done
gs_finish
