#!/usr/bin/env python3
"""
Reduces a problem 3 deliverable directory to what grading needs: the density of the final
time step. Run it on your copy in deliverables_<team#>/problem3/convergence_N<res>/, never on
the case directory you ran in.

  ./gradingScripts/problem3/density_only.py <deliverable directory> [--apply]

Without --apply it only prints what it would do. It removes every earlier time step and cuts
the final step's restart files down to density, the first variable in each file:
  restart_data/lustre_<n>.dat (parallel_io = "T")   truncated to its density block
  restart_data/lustre_<n>/    (file_per_process)   each rank's file truncated likewise
  p_all/p<rank>/<n>/          (parallel_io = "F")   keeps q_cons_vf1.dat and the grid files
Truncation keeps each file an exact prefix of what the simulation sealed, so the judges can
still verify it.
"""

import glob
import math
import os
import re
import shutil
import sys

import check_solution as cs

SERIAL_KEEP = {"q_cons_vf1.dat", "x_cb.dat", "y_cb.dat", "z_cb.dat"}


def _steps(paths, pattern):
    """step -> path for paths whose basename matches pattern's single integer group."""
    return {int(m.group(1)): p for p in paths if (m := re.fullmatch(pattern, os.path.basename(p)))}


def plan(case_dir):
    """[(action, path, detail)] reducing case_dir to the final step's density."""
    opts = os.path.join(case_dir, "options.txt")
    params = cs.run_case(os.path.join(case_dir, "case.py"), open(opts).read().split() if os.path.isfile(opts) else [])
    N = int(params["m"]) + 1
    actions = []

    def drop_earlier(steps):
        final = max(steps)
        actions.extend(("remove", path, "earlier time step") for n, path in steps.items() if n != final)
        return final

    def truncate(path, cells):
        keep = cells * cs.value_bytes(os.path.getsize(path), cells)
        if os.path.getsize(path) != keep:
            actions.append(("truncate", path, keep))

    restart = os.path.join(case_dir, "restart_data")
    if not cs._true(params.get("parallel_io", "F")):
        ranks = sorted(glob.glob(os.path.join(case_dir, "p_all", "p[0-9]*")))
        if not ranks:
            raise ValueError("no p_all/ output")
        for r in ranks:
            steps = _steps(glob.glob(os.path.join(r, "*")), r"(\d+)")
            final = drop_earlier(steps)
            actions.extend(("remove", f, "not density") for f in sorted(glob.glob(os.path.join(steps[final], "*"))) if os.path.basename(f) not in SERIAL_KEEP)
    elif cs._true(params.get("file_per_process", "F")):
        steps = _steps([d for d in glob.glob(os.path.join(restart, "lustre_*")) if os.path.isdir(d)], r"lustre_(\d+)")
        if not steps:
            raise ValueError("no restart_data/lustre_<n>/ output")
        final = drop_earlier(steps)
        files = {int(m.group(1)): f for f in glob.glob(os.path.join(steps[final], "*.dat")) if (m := re.search(r"_(\d{7})\.dat$", f))}
        for r, (_, shape) in enumerate(cs.decompose(N, len(files), params)):
            truncate(files[r], math.prod(shape))
    else:
        steps = _steps(glob.glob(os.path.join(restart, "lustre_*.dat")), r"lustre_(\d+)\.dat")
        if not steps:
            raise ValueError("no restart_data/lustre_<n>.dat output")
        truncate(steps[drop_earlier(steps)], N**3)
    return actions


def main():
    args = [a for a in sys.argv[1:] if a != "--apply"]
    if len(args) != 1 or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args and args[0] in ("-h", "--help") else 2
    apply = "--apply" in sys.argv[1:]
    try:
        actions = plan(args[0])
    except (OSError, ValueError, KeyError) as exc:
        print(f"density_only: {exc}")
        return 1
    for action, path, detail in actions:
        rel = os.path.relpath(path, args[0])
        if action == "truncate":
            print(f"{'truncate' if apply else 'would truncate'} {rel}: {os.path.getsize(path)} -> {detail} bytes")
            if apply:
                os.truncate(path, detail)
        else:
            print(f"{'remove' if apply else 'would remove'} {rel} ({detail})")
            if apply:
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    if not actions:
        print("already density only")
    elif not apply:
        print("dry run; pass --apply to make these changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
