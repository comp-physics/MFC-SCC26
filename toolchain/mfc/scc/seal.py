#!/usr/bin/env python3
"""
Seals a finished simulation's results into its case directory's fingerprint log: hashes of
the final time step's restart files, the timing files, and the run's wall time. Called by
the job script (toolchain/templates/include/helpers.mako) right after simulation succeeds.

  seal.py <case dir> --start <epoch s> --stop <epoch s> --exe <simulation binary>
"""

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "toolchain"))
from mfc.scc import core  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("case_dir")
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--exe", required=True)
    args = p.parse_args()
    if core.skipped():
        return 0

    log = os.path.join(args.case_dir, core.LOG_NAME)
    record = {
        "stage": "seal",
        "prev": core.file_sha(log),
        "start": args.start,
        "stop": args.stop,
        "exec_seconds": args.stop - args.start,
        **core.seal_record(args.case_dir, args.start),
        **core.context(),
    }
    line = core.encode_line(core.load_pubkey(ROOT), "seal", "simulation", core.file_sha(args.exe), record)
    with open(log, "a") as f:
        f.write(line)
    n = len(record["outputs"])
    print(f"Fingerprint: sealed {n} output file(s) of step {record['final_step']} and {len(record['timing'])} timing file(s).")
    for rel in record["stale_outputs"]:
        print(f"Fingerprint: warning: {rel} predates this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
