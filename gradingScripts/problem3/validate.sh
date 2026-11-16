#!/usr/bin/env bash
# Validates deliverables_<team#>/problem3/: at least MIN_RESOLUTIONS convergence_N<resolution>/
# directories holding the files in files.txt, each the advecting vortex run to the final time.
# Prints each resolution's density error against the exact solution.
# Usage: ./gradingScripts/problem3/validate.sh --input <path to deliverables_<team#>/problem3> [--files-only]

set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib.sh"

MIN_RESOLUTIONS=4

# Number of distinct time steps in a case directory's restart output.
count_steps() {
    local d=$1
    {
        find "$d/restart_data" -mindepth 1 -maxdepth 1 -regextype egrep -regex '.*/lustre_[0-9]+(\.dat)?' 2>/dev/null | sed -E 's|.*/lustre_([0-9]+).*|\1|'
        find "$d/p_all" -mindepth 2 -maxdepth 2 -type d -regextype egrep -regex '.*/p[0-9]+/[0-9]+' 2>/dev/null | sed -E 's|.*/||'
    } | sort -u | grep -c .
}

gs_parse_args "$@"
echo "Validating problem 3 deliverables in $GS_INPUT"
gs_subdirs '^convergence_N[1-9][0-9]*$'
mapfile -t dirs < <(printf '%s\n' "${GS_DIRS[@]}" | sort -t N -k2 -n)
results=()
for d in "${dirs[@]}"; do
    [ -n "$d" ] || continue
    gs_check_files "$here/files.txt" "$GS_INPUT/$d"
    gs_full || continue
    res=$(gs_option "$GS_INPUT/$d/options.txt" --resolution 2>/dev/null)
    [ "$res" = "${d#convergence_N}" ] || gs_fail "$d/options.txt: --resolution ${res:-missing}, but the directory is for ${d#convergence_N}"
    steps=$(count_steps "$GS_INPUT/$d")
    [ "$steps" -le 1 ] || gs_fail "$d: output holds $steps time steps; submit only the final one"
    [ -s "$GS_INPUT/$d/mfc_fingerprint.log" ] && gs_check_fingerprint "$GS_INPUT/$d/mfc_fingerprint.log"
    if [ -s "$GS_INPUT/$d/case.py" ]; then
        if out=$(gs_python "$here/check_solution.py" "$GS_INPUT/$d" 2>&1); then
            err=$(grep -oE 'L1 [0-9.e+-]+ +L2 [0-9.e+-]+ +Linf [0-9.e+-]+' <<< "$out")
            gs_pass "$d: vortex run to the final time; density error $err"
            results+=("${d#convergence_N} $err")
        else
            while IFS= read -r line; do [[ "$line" =~ FAIL\ (.*) ]] && [ "${BASH_REMATCH[1]}" != "" ] && gs_fail "$d: ${BASH_REMATCH[1]}"; done <<< "$out"
            grep -q 'FAIL ' <<< "$out" || gs_fail "$d: check_solution.py failed: $out"
        fi
    fi
done
n=${#dirs[@]}; [ -z "${dirs[0]:-}" ] && n=0
[ "$n" -ge "$MIN_RESOLUTIONS" ] && gs_pass "$n resolutions" || gs_fail "$n resolution(s), need at least $MIN_RESOLUTIONS"
if [ "${#results[@]}" -gt 0 ]; then
    echo
    echo "  Density error against the exact solution:"
    printf '  %6s  %s\n' N "error"
    for r in "${results[@]}"; do printf '  %6s  %s\n' "${r%% *}" "${r#* }"; done
fi
gs_finish
