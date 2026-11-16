#!/usr/bin/env bash
# Shared checks for gradingScripts/problem*/validate.sh. Source it; don't run it.

shopt -s extglob
GS_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
GS_FAILS=0

gs_pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
gs_fail() {
    printf '  \033[31mFAIL\033[0m %s\n' "$*"
    GS_FAILS=$((GS_FAILS + 1))
}
gs_note() { printf '  \033[33mNOTE\033[0m %s\n' "$*"; }

# Sets GS_INPUT to the absolute path given by --input; --files-only sets GS_FILES_ONLY, which
# limits validation to which files are present (see gs_full); --scc-connect sets GS_CONNECT and
# GS_ARGS, which validateAll.sh passes on to each problem. GS_CONNECT is also set when the input
# or its parent is an SCC Connect team's deliverables_CONNN/ (see gs_team).
gs_parse_args() {
    GS_INPUT="" GS_FILES_ONLY="" GS_CONNECT="" GS_TEAM="" GS_ARGS=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -i | --input) GS_INPUT="${2:-}"; shift 2 ;;
            --files-only) GS_FILES_ONLY=1; shift ;;
            --scc-connect) GS_CONNECT=1 GS_ARGS+=(--scc-connect); shift ;;
            -h | --help) echo "Usage: $0 --input <path to deliverables_<team#>/problemN> [--files-only] [--scc-connect]"; exit 0 ;;
            *) echo "Unknown option: $1" >&2; exit 2 ;;
        esac
    done
    [ -n "$GS_INPUT" ] || { echo "Missing --input <directory>" >&2; exit 2; }
    [ -d "$GS_INPUT" ] || { echo "Not a directory: $GS_INPUT" >&2; exit 2; }
    GS_INPUT=$(cd "$GS_INPUT" && pwd)
    gs_team "$GS_INPUT" || gs_team "$(dirname "$GS_INPUT")" || true
}

# gs_team <dir>
# False unless dir is named deliverables_<team#>, where <team#> is SCCNN (SCC team NN, 01-10) or
# CONNN (SCC Connect instance scc-connect-NN, 01-29). Sets GS_TEAM to <team#> and, for SCC
# Connect, GS_CONNECT.
GS_TEAM_HELP="SCCNN (SCC, NN = 01-10) or CONNN (SCC Connect, NN = 01-29)"
gs_team() {
    [[ "$(basename "$1")" =~ ^deliverables_(SCC(0[1-9]|10)|CON(0[1-9]|[12][0-9]))$ ]] || return 1
    GS_TEAM=${BASH_REMATCH[1]}
    [[ "$GS_TEAM" != CON* ]] || GS_CONNECT=1
}

# True unless --files-only: guards checks of file contents.
gs_full() { [ -z "$GS_FILES_ONLY" ]; }

# Python with numpy (MFC's own virtual environment once ./mfc.sh has run).
gs_python() {
    if [ -x "$GS_REPO/build/venv/bin/python" ]; then "$GS_REPO/build/venv/bin/python" "$@"; else python3 "$@"; fi
}

# gs_check_files <manifest> [dir]
# Each manifest pattern (an extglob; blank lines and # comments ignored; {dir} is replaced by
# the directory's name) must match exactly one entry of dir (default GS_INPUT). A pattern
# ending in / matches a non-empty directory and everything inside it; any other pattern
# matches a non-empty regular file. Every entry, hidden ones included, must be matched.
gs_check_files() {
    local manifest=$1 dir=${2:-$GS_INPUT} pattern entry hits want_dir
    local name label
    local -a patterns=() present=()
    local -A claimed=()
    name=$(basename "$dir")
    label=${dir#"$GS_INPUT"}; label=${label#/}; label=${label:+$label/}

    while IFS= read -r pattern; do
        pattern="${pattern%%#*}"
        pattern="${pattern#"${pattern%%[![:space:]]*}"}"
        pattern="${pattern%"${pattern##*[![:space:]]}"}"
        [ -n "$pattern" ] && patterns+=("${pattern//\{dir\}/$name}")
    done < "$manifest"

    while IFS= read -r -d '' entry; do
        present+=("${entry#"$dir"/}")
    done < <(find "$dir" -mindepth 1 -print0 | sort -z)

    for pattern in "${patterns[@]}"; do
        want_dir=""
        [ "${pattern%/}" != "$pattern" ] && want_dir=1 && pattern=${pattern%/}
        hits=()
        for entry in "${present[@]}"; do
            # shellcheck disable=SC2053  # unquoted on purpose: the manifest entry is a glob
            [[ "$entry" != */* && "$entry" == $pattern ]] && hits+=("$entry")
        done
        if [ "${#hits[@]}" -eq 0 ]; then
            gs_fail "${label}missing: $pattern${want_dir:+/}"
        elif [ "${#hits[@]}" -gt 1 ]; then
            gs_fail "${label}'$pattern' must match exactly one entry, found ${#hits[@]}: ${hits[*]}"
        elif [ -n "$want_dir" ]; then
            if [ ! -d "$dir/${hits[0]}" ] || [ -L "$dir/${hits[0]}" ]; then
                gs_fail "${label}${hits[0]} is not a directory"
            elif [ -z "$(ls -A "$dir/${hits[0]}")" ]; then
                gs_fail "${label}${hits[0]}/ is empty"
            else
                gs_pass "${label}found ${hits[0]}/"
            fi
        elif [ ! -f "$dir/${hits[0]}" ] || [ -L "$dir/${hits[0]}" ]; then
            gs_fail "${label}${hits[0]} is not a regular file"
        elif [ ! -s "$dir/${hits[0]}" ]; then
            gs_fail "${label}${hits[0]} is empty"
        else
            gs_pass "${label}found ${hits[0]}"
        fi
        for entry in "${hits[@]}"; do claimed["$entry"]=1; done
    done

    for entry in "${present[@]}"; do  # contents of a matched directory belong to it
        [[ "$entry" == */* ]] || [ -n "${claimed[$entry]:-}" ] || gs_fail "${label}unexpected: $entry"
    done
}

# gs_subdirs <regex>
# Sets GS_DIRS to the subdirectories of GS_INPUT whose names match regex (sorted) and fails
# every other entry of GS_INPUT.
gs_subdirs() {
    local regex=$1 entry name
    GS_DIRS=()
    while IFS= read -r -d '' entry; do
        name=$(basename "$entry")
        if [ -d "$entry" ] && [ ! -L "$entry" ] && [[ "$name" =~ $regex ]]; then
            GS_DIRS+=("$name")
        else
            gs_fail "unexpected: $name (expected directories matching $regex)"
        fi
    done < <(find "$GS_INPUT" -mindepth 1 -maxdepth 1 -print0 | sort -z)
}

# gs_check_fingerprint <log>
# Format-only check (the records are encrypted): every line is a fingerprint record sealed to
# this repository's organizer key, with at least one run record and, after the last run, the
# seal the job script writes when simulation finishes.
gs_check_fingerprint() {
    local log=$1 keyid total bad runs last label
    label=${log#"$GS_INPUT"/}
    keyid=$(base64 -d "$GS_REPO/toolchain/mfc/scc/organizer.pub" | sha256sum | cut -c1-16)
    total=$(grep -c '' "$log")
    bad=$(grep -cvE "^MFCFP1 $keyid (build|run|seal) [^ ]+ [^ ]+ [^ ]+ [A-Za-z0-9+/]+=*$" "$log")
    runs=$(grep -cE "^MFCFP1 $keyid run " "$log")
    last=$(grep -oE "^MFCFP1 $keyid (run|seal) " "$log" | tail -1 | awk '{print $3}')

    if [ "$bad" -gt 0 ]; then
        gs_fail "$label: $bad of $total line(s) are not fingerprint records for this repository's key"
    elif [ "$runs" -eq 0 ]; then
        gs_fail "$label: no run records; it must come from the case directory of an ./mfc.sh run"
    elif [ "$last" != seal ]; then
        gs_fail "$label: the last run has no seal; its simulation did not finish through the MFC job script"
    else
        gs_pass "$label: $total record(s), $runs run(s), sealed"
    fi
}

# gs_option <options.txt> <--flag>: the value recorded for --flag, or nothing.
gs_option() {
    awk -v f="$2" '$1 == f { print $2; exit }' "$1"
}

gs_finish() {
    echo
    if [ "$GS_FAILS" -eq 0 ]; then
        printf '\033[32mValidation PASSED.\033[0m\n'
        exit 0
    fi
    printf '\033[31mValidation FAILED: %d problem(s).\033[0m\n' "$GS_FAILS"
    exit 1
}
