#!/usr/bin/env bash
# Checks that deliverables_<team#>/ holds every required file for all problems and nothing
# else, without checking file contents or results: report/report_<team#>.pdf plus each
# problem's files via gradingScripts/problem<N>/validate.sh --files-only (run those without
# it for the full checks). <team#> is SCCNN (SCC, NN = 01-10) or CONNN (SCC Connect, NN = 01-29);
# CONNN implies --scc-connect.
# Usage: ./gradingScripts/validateAll.sh --input <path to deliverables_<team#>> [--scc-connect]

set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/lib.sh"

PROBLEMS=(problem0 problem1 problem2 problem3)
OPTIONAL=(problem0)  # absent when nothing needed disclosing

gs_parse_args "$@"
echo "Checking deliverables in $GS_INPUT (files only)"
failed=()

# The report, named after the team number in deliverables_<team#>/.
echo
if gs_team "$GS_INPUT"; then
    report="report_$GS_TEAM.pdf"
else
    gs_fail "the input directory must be named deliverables_<team#>, with <team#> $GS_TEAM_HELP"
    report="report_*.pdf"
fi
if [ -d "$GS_INPUT/report" ] && [ ! -L "$GS_INPUT/report" ]; then
    gs_check_files <(echo "$report") "$GS_INPUT/report"
else
    gs_fail "missing: report/$report"
fi
[ "$GS_FAILS" -eq 0 ] || failed+=(report)
for p in "${PROBLEMS[@]}"; do
    echo
    if [ ! -d "$GS_INPUT/$p" ]; then
        if [[ " ${OPTIONAL[*]} " == *" $p "* ]]; then
            gs_note "no $p/: declaring that no changes needed disclosure"
        else
            gs_fail "missing: $p/"
            failed+=("$p")
        fi
        continue
    fi
    "$here/$p/validate.sh" --files-only ${GS_ARGS[@]+"${GS_ARGS[@]}"} --input "$GS_INPUT/$p" || failed+=("$p")
done

echo
extra=0
while IFS= read -r -d '' entry; do
    name=$(basename "$entry")
    [[ " ${PROBLEMS[*]} report " == *" $name "* ]] && [ -d "$entry" ] && [ ! -L "$entry" ] && continue
    gs_fail "unexpected: $name"
    extra=1
done < <(find "$GS_INPUT" -mindepth 1 -maxdepth 1 -print0 | sort -z)
[ "$extra" -eq 0 ] || failed+=(deliverables_root)

echo
if [ "${#failed[@]}" -eq 0 ]; then
    printf '\033[32mAll deliverables present.\033[0m\n'
    exit 0
fi
printf '\033[31mMissing or unexpected files in: %s\033[0m\n' "${failed[*]}"
exit 1
