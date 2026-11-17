#!/usr/bin/env python3
import argparse
import json
import math
import os

parser = argparse.ArgumentParser(description="3D IGR Taylor-Green vortex case.")
parser.add_argument("--mfc", type=json.loads, default="{}", metavar="DICT", help="MFC's toolchain's internal state.")
parser.add_argument(
    "--resolution",
    type=int,
    default=100,
    metavar="N",
    help="Grid cells per side of the N^3 cube: the whole problem for strong scaling, each device's share for weak scaling.",
)
parser.add_argument(
    "--scaling",
    type=str,
    choices=["strong", "weak"],
    default="strong",
    help="Strong scaling keeps the problem at N^3 cells; weak scaling grows it with the number of devices.",
)
parser.add_argument("--serial-io", action="store_true", help="Write output with serial I/O instead of parallel I/O.")
parser.add_argument("--rdma", action="store_true", help="Use GPU-direct (RDMA) MPI; needs a GPU-aware MPI library.")
args = parser.parse_args()

# Record the effective options next to this case file.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.txt"), "w") as f:
    f.write(f"--resolution {args.resolution}\n--scaling {args.scaling}\n--serial-io {args.serial_io}\n--rdma {args.rdma}\n")


def closest_three_factors(n):
    """Three factors of n as close to each other as possible, for a cube-like device grid."""
    best_triplet = (1, 1, n)
    min_range = n - 1
    for a in range(1, int(n ** (1 / 3)) + 2):
        if n % a != 0:
            continue
        rem = n // a
        for b in range(a, int(math.sqrt(rem)) + 2):
            if rem % b != 0:
                continue
            c = rem // b
            if c - a < min_range:
                min_range = c - a
                best_triplet = (a, b, c)
    return best_triplet


# Cells per axis of the per-device cube; the unit of work replicated across devices.
s = args.resolution
if args.scaling == "weak":
    # The per-device cube tiled Lx x Ly x Lz times, factored as close to a cube
    # as possible so each device still owns a perfect cube of the domain.
    num_devices = args.mfc.get("nodes", 1) * args.mfc.get("tasks_per_node", 1)
    Lx, Ly, Lz = closest_three_factors(num_devices)
else:
    Lx, Ly, Lz = 1, 1, 1
Nx, Ny, Nz = Lx * s - 1, Ly * s - 1, Lz * s - 1

Re = 1600
L = 1
P0 = 101325
rho0 = 1
C0 = math.sqrt(1.4 * P0)
V0 = 0.1 * C0
mu = V0 * L / Re

cfl = 0.5
dx = 2 * Lx * math.pi * L / (Nx + 1)

dt = cfl * dx / (C0)

tC = L / V0
tEnd = 20 * tC

Nt = int(tEnd / dt)


# Configuring case dictionary
print(
    json.dumps(
        {
            # Logistics
            "run_time_info": "F", # Off to avoid reductions
            "rdma_mpi": "T" if args.rdma else "F",
            # Computational Domain Parameters
            "x_domain%beg": -Lx * math.pi * L,
            "x_domain%end": Lx * math.pi * L,
            "y_domain%beg": -Ly * math.pi * L,
            "y_domain%end": Ly * math.pi * L,
            "z_domain%beg": -Lz * math.pi * L,
            "z_domain%end": Lz * math.pi * L,
            "m": Nx,
            "n": Ny,
            "p": Nz,
            "cyl_coord": "F",
            "dt": dt,
            "t_step_start": 0,
            "t_step_stop": 100,
            "t_step_save": 100,
            # Simulation Algorithm Parameters
            "num_patches": 1,
            "model_eqns": "5eq",
            "num_fluids": 1,
            "time_stepper": "rk3",
            "riemann_solver": "lax_friedrichs",
            "bc_x%beg": -1,
            "bc_x%end": -1,
            "bc_y%beg": -1,
            "bc_y%end": -1,
            "bc_z%beg": -1,
            "bc_z%end": -1,
            "igr": "T",
            "igr_order": 5,
            "igr_iter_solver": 1,
            "num_igr_iters": 5,
            "num_igr_warm_start_iters": 5,
            "alf_factor": 10,
            "viscous": "T",
            # Formatted Database Files Structure Parameters
            "format": "silo",
            "precision": "double",
            "prim_vars_wrt": "T",
            "parallel_io": "F" if args.serial_io else "T",
            # Patch 1: Background (AIR - 2)
            "patch_icpp(1)%geometry": 9,
            "patch_icpp(1)%x_centroid": 0,
            "patch_icpp(1)%y_centroid": 0,
            "patch_icpp(1)%z_centroid": 0,
            "patch_icpp(1)%length_x": 2 * Lx * math.pi * L,
            "patch_icpp(1)%length_y": 2 * Ly * math.pi * L,
            "patch_icpp(1)%length_z": 2 * Lz * math.pi * L,
            "patch_icpp(1)%vel(1)": 0.0,
            "patch_icpp(1)%vel(2)": 0.0,
            "patch_icpp(1)%vel(3)": 0,
            "patch_icpp(1)%pres": 0.0,
            "patch_icpp(1)%hcid": 380,
            "patch_icpp(1)%alpha_rho(1)": 1,
            "patch_icpp(1)%alpha(1)": 1,
            # Fluids Physical Parameters
            "fluid_pp(1)%gamma": 1.0e00 / (1.4 - 1),
            "fluid_pp(1)%eos": "ideal_gas",
            "fluid_pp(1)%Re(1)": 1 / mu,
        }
    )
)
