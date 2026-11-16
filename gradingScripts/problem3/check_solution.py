#!/usr/bin/env python3
"""
Problem 3 checker: the case must be the advecting vortex run to exactly T_END, and its
final density is compared with the exact solution. No simulation is rerun.

  ./gradingScripts/problem3/check_solution.py <case directory> [-- <case.py options>]

The case directory needs case.py and the simulation output at T_END, in whichever layout
the case's I/O settings produce, either complete or reduced to density by density_only.py:
  parallel_io = "T"                            restart_data/lustre_<n>.dat
  parallel_io = "T", file_per_process = "T"    restart_data/lustre_<n>/ (one file per rank)
  parallel_io = "F"                            p_all/p<rank>/<n>/ for every rank
case.py options are read from options.txt unless given after --.

Numerics are free. The problem section of problems/problem3/case.py (domain, grid shape,
initial condition, boundaries, fluid) must be unchanged, and the last output must be at
T_END: step * dt for a constant dt, or save number * t_save with cfl_dt/cfl_adap_dt.
After a whole number of periods the exact solution is the initial vortex, whose exact
cell averages are taken with Gauss-Legendre quadrature.
"""

import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "problems", "problem3", "case.py")
FIXED_PREFIXES = ("x_domain%", "y_domain%", "z_domain%", "bc_", "patch_icpp(", "fluid_pp(")
FIXED_KEYS = {"m", "n", "p", "cyl_coord", "num_patches", "num_fluids"}
# Physics that would change the problem being solved; stretching would make the grid non-uniform.
FORBIDDEN_FLAGS = (
    *("viscous", "bubbles_euler", "bubbles_lagrange", "mhd", "surface_tension", "hypoelasticity", "hyperelasticity"),
    *("chemistry", "acoustic_source", "ib", "relax", "qbmm", "stretch_x", "stretch_y", "stretch_z"),
)
REL_TOL = 1e-9


def _reference_constant(name):
    """A constant from the problem section of problems/problem3/case.py, so the exact solution can't drift from it."""
    with open(REFERENCE) as f:
        return float(re.search(rf"^{name} = ([-+0-9.eE]+)", f.read(), re.M).group(1))


# The vortex tubes, as in problems/problem3/case.py: one along each axis, centered at
# CENTER in its cyclic transverse coordinates (x: (y, z), y: (z, x), z: (x, y)).
GAMMA, EPS, R, L = (_reference_constant(k) for k in ("gamma", "eps", "R", "L"))
CENTER = (-L / 4, L / 4)


def run_case(path, case_args=()):
    """The dictionary a case file prints, run from a scratch copy so nothing is written beside it."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "case.py")
        shutil.copy(path, copy)
        out = subprocess.run([sys.executable, copy, "--mfc", "{}", *case_args], capture_output=True, text=True, check=True, cwd=tmp).stdout
    return json.loads(out.strip().splitlines()[-1])


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _same(a, b):
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=REL_TOL, abs_tol=REL_TOL)
    return str(a).strip() == str(b).strip()


def _true(v):
    return str(v).strip().upper() in ("T", "TRUE", ".TRUE.", "1")


def cfl_based(params):
    return _true(params.get("cfl_dt", "F")) or _true(params.get("cfl_adap_dt", "F"))


def save_time(params, n):
    """Simulation time of output file number n."""
    key = "t_save" if cfl_based(params) else "dt"
    v = _num(params.get(key))
    return None if v is None else n * v


def _normalize(params):
    """Named values (e.g. eos "ideal_gas") as MFC's integer codes, as fingerprint run records store them."""
    sys.path.insert(0, os.path.join(os.path.dirname(REFERENCE), "..", "..", "toolchain"))
    try:
        from mfc.case import Case
    except ImportError:  # outside MFC's Python environment: compare values as written
        return params
    return Case(params).params


def check_params(params):
    """Problems with a case dictionary (values may be strings, as in fingerprint run records)."""
    m = _num(params.get("m"))
    if m is None:
        return ["m is not set"], None
    ref = _normalize(run_case(REFERENCE, ["--resolution", str(int(m) + 1)]))
    params = _normalize(params)
    problems = []

    for k in sorted(k for k in set(ref) | set(params) if k in FIXED_KEYS or k.startswith(FIXED_PREFIXES)):
        if k not in params:
            problems.append(f"{k} is missing (expected {ref[k]})")
        elif k not in ref:
            problems.append(f"{k} = {params[k]} is not part of the problem")
        elif not _same(params[k], ref[k]):
            problems.append(f"{k} = {params[k]}, expected {ref[k]}")
    problems += [f"{k} = T changes the problem" for k in FORBIDDEN_FLAGS if _true(params.get(k, "F"))]
    t_end = ref["dt"] * ref["t_step_stop"]
    if cfl_based(params):
        t_stop = _num(params.get("t_stop"))
    else:
        stop, dt = _num(params.get("t_step_stop")), _num(params.get("dt"))
        t_stop = None if stop is None or dt is None else stop * dt
    if t_stop is None or not math.isclose(t_stop, t_end, rel_tol=REL_TOL):
        problems.append(f"run is set to end at t = {t_stop}, expected {t_end:.12g}")
    return problems, t_end


def tube_deficit(N, order=6):
    """Exact cell averages of one tube's density change, G[b, c] over its N x N cross-section.

    The tubes are ~10 core radii apart, so the density is 1 plus the three tubes' changes to
    within ~1e-20, and each change depends only on that tube's two transverse coordinates."""
    xi, w = np.polynomial.legendre.leggauss(order)
    h = L / N
    centers = -L / 2 + (np.arange(N) + 0.5) * h
    q = (centers[:, None] + 0.5 * h * xi[None, :]).ravel()  # quadrature points, grouped by cell
    B, C = np.meshgrid(q - CENTER[0], q - CENTER[1], indexing="ij")
    T = 1 - (GAMMA - 1) * EPS**2 / (8 * GAMMA * math.pi**2) * np.exp(1 - (B**2 + C**2) / R**2)
    change = (T ** (1 / (GAMMA - 1)) - 1).reshape(N, order, N, order)
    return np.einsum("iajb,a,b->ij", change, w, w) / 4


def value_bytes(size, cells):
    """Bytes per value of a restart file holding `cells` cells: density only (1 variable) or all
    5-7 conserved variables, in double or single precision."""
    per_cell = size / cells
    if per_cell in (4, 8):
        return int(per_cell)
    for nbytes in (8, 4):
        if per_cell / nbytes in (5, 6, 7):
            return nbytes
    raise ValueError(f"restart file of {size} bytes does not fit {cells} cells")


def parallel_output(case_dir, N):
    """(save number, name, blocks) for the last restart_data/lustre_<n>.dat, or None."""
    found = [(int(m.group(1)), f) for f in glob.glob(os.path.join(case_dir, "restart_data", "lustre_*.dat")) if (m := re.search(r"lustre_(\d+)\.dat$", f))]
    if not found:
        return None
    n, path = max(found)
    nbytes = value_bytes(os.path.getsize(path), N**3)
    rho = np.memmap(path, dtype=f"<f{nbytes}", mode="r", shape=(N, N, N), order="F")  # density is the first variable
    return n, os.path.relpath(path, case_dir), [((0, 0, 0), rho)]


def _recon_order(params):
    if _true(params.get("igr", "F")):
        return int(_num(params.get("igr_order")))
    key = "muscl_order" if int(_num(params.get("recon_type", 1))) == 2 else "weno_order"
    return int(_num(params.get(key)))


def decompose(N, ranks, params):
    """Per-rank ((i0, j0, k0), (nx, ny, nz)) on an N^3 grid, as s_mpi_decompose_computational_domain
    in src/common/m_mpi_common.fpp lays them out (3D Cartesian branch)."""
    s = 5 * _recon_order(params)  # num_stcls_min * recon_order
    c = N  # cells per direction (m + 1 = n + 1 = p + 1)
    px, py, pz, found = 1, 1, ranks, False
    if _true(params.get("fft_wrt", "F")):
        fct = 10 * abs(c / py - c / pz)
        for i in range(1, ranks + 1):
            if ranks % i == 0 and c // i >= s and fct >= abs(c / i - c / (ranks // i)) and c / (ranks // i) >= s:
                py, pz, fct, found = i, ranks // i, abs(c / i - c / (ranks // i)), True
    else:
        fct = 10 * abs(c / px - c / py) + 10 * abs(c / py - c / pz)
        for i in range(1, ranks + 1):
            if ranks % i or c // i < s:
                continue
            for j in range(1, ranks // i + 1):
                k = ranks // (i * j)
                if (ranks // i) % j == 0 and c // j >= s:
                    val = abs(c / i - c / j) + abs(c / j - c / k)
                    if fct >= val and c / k >= s:
                        px, py, pz, fct, found = i, j, k, val, True
    if not found and ranks > 1:
        raise ValueError(f"MFC cannot decompose {N}^3 over {ranks} ranks")

    def split(P, coord):
        base, rem = divmod(c, P)
        return (base + 1) * coord if coord < rem else base * coord + rem, base + (coord < rem)

    out = []
    for r in range(ranks):  # MPI_CART_COORDS without reordering: row-major, z fastest
        coords = (r // (py * pz), (r // pz) % py, r % pz)
        (i0, nx), (j0, ny), (k0, nz) = (split(P, co) for P, co in zip((px, py, pz), coords))
        out.append(((i0, j0, k0), (nx, ny, nz)))
    return out


def per_process_output(case_dir, N, params):
    """(save number, name, blocks) for the last complete restart_data/lustre_<n>/ of file_per_process output, or None."""
    dirs = [(int(m.group(1)), d) for d in glob.glob(os.path.join(case_dir, "restart_data", "lustre_*")) if os.path.isdir(d) and (m := re.search(r"lustre_(\d+)$", d))]
    if not dirs:
        return None
    n, d = max(dirs)
    files = {int(m.group(1)): f for f in glob.glob(os.path.join(d, "*.dat")) if (m := re.search(rf"{n}_(\d{{7}})\.dat$", f))}
    ranks = len(files)
    if sorted(files) != list(range(ranks)):
        raise ValueError(f"{os.path.relpath(d, case_dir)}: rank files are not numbered 0..{ranks - 1}")

    def blocks():
        for r, (offsets, shape) in enumerate(decompose(N, ranks, params)):
            nbytes = value_bytes(os.path.getsize(files[r]), math.prod(shape))
            yield offsets, np.memmap(files[r], dtype=f"<f{nbytes}", mode="r", shape=shape, order="F")  # density first

    return n, f"{os.path.relpath(d, case_dir)} ({ranks} ranks)", blocks()


def _fortran_record(path):
    """Payload bytes of a file holding one Fortran unformatted sequential record."""
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    if int(raw[:4].view("<i4")[0]) == len(raw) - 8:
        return raw[4:-4]
    parts, pos = [], 0  # gfortran splits records over 2 GiB; a negative marker means more follow
    while True:
        mark = int(raw[pos : pos + 4].view("<i4")[0])
        parts.append(np.asarray(raw[pos + 4 : pos + 4 + abs(mark)]))
        pos += abs(mark) + 8
        if mark >= 0:
            return np.concatenate(parts)


def _serial_block(step_dir, N):
    """((i0, j0, k0), density) for one rank's p_all/p<rank>/<n>/ directory."""
    recs = {f: _fortran_record(os.path.join(step_dir, f)) for f in ("x_cb.dat", "y_cb.dat", "z_cb.dat", "q_cons_vf1.dat")}
    rho_rec = recs.pop("q_cons_vf1.dat")
    for grid_bytes, data_bytes in ((8, 8), (8, 4), (4, 4)):  # double, mixed and single precision builds
        if any(len(r) % grid_bytes for r in recs.values()):
            continue
        faces = [r.view(f"<f{grid_bytes}") for r in recs.values()]  # cell faces -1..m of this rank
        shape = tuple(len(f) - 1 for f in faces)
        if math.prod(shape) * data_bytes == len(rho_rec):
            offsets = tuple(int(round((f[0] + L / 2) / (L / N))) for f in faces)
            return offsets, rho_rec.view(f"<f{data_bytes}").reshape(shape, order="F")
    raise ValueError(f"{step_dir}: grid and density sizes do not match")


def serial_output(case_dir, N):
    """(save number, name, blocks) for the last save present on every rank under p_all/, or None."""
    ranks = sorted(glob.glob(os.path.join(case_dir, "p_all", "p[0-9]*")))
    steps = [{int(s) for s in os.listdir(r) if s.isdigit()} for r in ranks]
    common = set.intersection(*steps) if steps else set()
    if not common:
        return None
    n = max(common)
    return n, f"p_all/p*/{n} ({len(ranks)} ranks)", (_serial_block(os.path.join(r, str(n)), N) for r in ranks)


def density_errors(blocks, N):
    """L1, L2 and Linf density errors against the exact solution; blocks must tile the grid exactly."""
    G = tube_deficit(N)  # tube along x: G[j, k]; along y: G[k, i]; along z: G[i, j]
    l1 = l2 = linf = 0.0
    boxes = []
    for (i0, j0, k0), rho in blocks:
        nx, ny, nz = rho.shape
        if min(i0, j0, k0) < 0 or max(i0 + nx, j0 + ny, k0 + nz) > N:
            raise ValueError(f"output block at ({i0}, {j0}, {k0}) lies outside the {N}^3 grid")
        boxes.append(((i0, i0 + nx), (j0, j0 + ny), (k0, k0 + nz)))
        ez = 1 + G[i0 : i0 + nx, j0 : j0 + ny]
        for k in range(nz):  # one z-slab at a time to bound memory
            kg = k0 + k
            ex = ez + G[j0 : j0 + ny, kg][None, :] + G[kg, i0 : i0 + nx][:, None]
            e = np.abs(np.asarray(rho[:, :, k], dtype=np.float64) - ex)
            l1, l2, linf = l1 + e.sum(), l2 + (e**2).sum(), max(linf, e.max())
    overlap = any(all(a[d][0] < b[d][1] and b[d][0] < a[d][1] for d in range(3)) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    if overlap or sum(math.prod(hi - lo for lo, hi in box) for box in boxes) != N**3:
        raise ValueError("output blocks do not cover the grid exactly once")
    return l1 / N**3, math.sqrt(l2 / N**3), linf


def check(case_dir, case_args=None):
    """(problems, errors or None) for one case directory."""
    case_py = os.path.join(case_dir, "case.py")
    if case_args is None:
        opts = os.path.join(case_dir, "options.txt")
        case_args = open(opts).read().split() if os.path.isfile(opts) else []
    try:
        params = run_case(case_py, case_args)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [f"case.py did not run: {getattr(exc, 'stderr', '') or exc}"], None

    problems, t_end = check_params(params)
    N = int(params["m"]) + 1
    try:
        if not _true(params.get("parallel_io", "F")):
            found, where = serial_output(case_dir, N), "p_all/p<rank>/<n>/"
        elif _true(params.get("file_per_process", "F")):
            found, where = per_process_output(case_dir, N, params), "restart_data/lustre_<n>/"
        else:
            found, where = parallel_output(case_dir, N), "restart_data/lustre_<n>.dat"
    except (OSError, ValueError) as exc:
        return problems + [str(exc)], None
    if found is None:
        return problems + [f"no {where} output found"], None
    n, name, blocks = found
    t = save_time(params, n)
    if t is None or not math.isclose(t, t_end, rel_tol=REL_TOL):
        problems.append(f"last output {name} is at t = {t}, expected {t_end:.12g}")
    if problems:
        return problems, None
    try:
        return problems, density_errors(blocks, N)
    except (OSError, ValueError) as exc:
        return [str(exc)], None


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    case_args = argv[2:] if len(argv) > 1 and argv[1] == "--" else None
    problems, errors = check(argv[0], case_args)
    for p in problems:
        print(f"  FAIL {p}")
    if errors:
        print(f"  density error vs exact: L1 {errors[0]:.6e}  L2 {errors[1]:.6e}  Linf {errors[2]:.6e}")
    print("PASS" if not problems else "FAIL")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
