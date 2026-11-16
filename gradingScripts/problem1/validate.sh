#!/usr/bin/env bash
# Validates deliverables_<team#>/problem1/. The required files are listed in files.txt.
# Usage: ./gradingScripts/problem1/validate.sh --input <path to deliverables_<team#>/problem1> [--files-only]

set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib.sh"

gs_parse_args "$@"
echo "Validating problem 1 deliverables in $GS_INPUT"
gs_check_files "$here/files.txt"
gs_full && [ -f "$GS_INPUT/mfc_fingerprint.log" ] && gs_check_fingerprint "$GS_INPUT/mfc_fingerprint.log"
gs_finish
