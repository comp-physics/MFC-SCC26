#!/usr/bin/env python3
"""
Three isentropic vortex tubes advecting diagonally through a tri-periodic cube.

Three isentropic vortices of Shu (1998), one along each axis on mutually skew lines 5 apart,
are carried by the uniform velocity (0.5, 0.5, 0.5) through the domain [-5, 5]^3. Each tube is an
exact steady solution, and their fields decay like exp(-r^2/R^2), so with core radius R = 0.5
they interact only at the ~1e-9 level. Every PERIOD the flow returns exactly to its starting
state, so the initial condition is the exact solution at the final time.

The problem (domain, initial condition, boundaries, fluid, final time) is fixed and is
checked when grading. The numerics are yours to choose.
"""

import argparse
import json
import math
import os

parser = argparse.ArgumentParser(description="Three diagonally advecting isentropic vortex tubes.")
parser.add_argument("--mfc", type=json.loads, default="{}", metavar="DICT", help="MFC's toolchain's internal state.")
parser.add_argument("--resolution", type=int, default=64, metavar="N", help="Grid cells per direction (N^3 in total).")
args = parser.parse_args()

# Record the effective options next to this case file.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.txt"), "w") as f:
    f.write(f"--resolution {args.resolution}\n")

# ----------------------------------------------------------------------------------------
# The problem. Do not change anything in this section.
# ----------------------------------------------------------------------------------------
gamma = 1.4
eps = 0.5  # vortex strength
R = 0.5  # vortex core radius
L = 10.0  # domain edge length
u0 = 0.5  # advection speed in each direction
PERIOD = L / u0
T_END = 10 * PERIOD  # simulations must end exactly here

# One tube along each axis a, centered at (-L/4, L/4) in its cyclic transverse coordinates (b, c):
# along x at (y, z) = (-2.5, 2.5), along y at (z, x) = (-2.5, 2.5), along z at (x, y) = (-2.5, 2.5).
TUBES = (("x", "y", "z"), ("y", "z", "x"), ("z", "x", "y"))
CENTER = (-L / 4, L / 4)
vel = {"x": [str(u0)], "y": [str(u0)], "z": [str(u0)]}
dT = []
for _, b, c in TUBES:
    r2 = f"(({b} - ({CENTER[0]}))**2 + ({c} - ({CENTER[1]}))**2)/{R**2}"
    du = f"{eps / (2 * math.pi * R)}*exp(0.5*(1 - {r2}))"
    vel[b].append(f"- ({c} - ({CENTER[1]}))*{du}")
    vel[c].append(f"+ ({b} - ({CENTER[0]}))*{du}")
    dT.append(f"{(gamma - 1) * eps**2 / (8 * gamma * math.pi**2)}*exp(1 - {r2})")
T = f"(1 - ({' + '.join(dT)}))"

N = args.resolution
problem = {
    "x_domain%beg": -L / 2,
    "x_domain%end": L / 2,
    "y_domain%beg": -L / 2,
    "y_domain%end": L / 2,
    "z_domain%beg": -L / 2,
    "z_domain%end": L / 2,
    "m": N - 1,
    "n": N - 1,
    "p": N - 1,
    "cyl_coord": "F",
    "bc_x%beg": -1,
    "bc_x%end": -1,
    "bc_y%beg": -1,
    "bc_y%end": -1,
    "bc_z%beg": -1,
    "bc_z%end": -1,
    "num_patches": 1,
    "num_fluids": 1,
    "patch_icpp(1)%geometry": 9,
    "patch_icpp(1)%x_centroid": 0,
    "patch_icpp(1)%y_centroid": 0,
    "patch_icpp(1)%z_centroid": 0,
    "patch_icpp(1)%length_x": L,
    "patch_icpp(1)%length_y": L,
    "patch_icpp(1)%length_z": L,
    "patch_icpp(1)%vel(1)": " ".join(vel["x"]),
    "patch_icpp(1)%vel(2)": " ".join(vel["y"]),
    "patch_icpp(1)%vel(3)": " ".join(vel["z"]),
    "patch_icpp(1)%pres": f"{T}**{gamma / (gamma - 1)}",
    "patch_icpp(1)%alpha_rho(1)": f"{T}**{1 / (gamma - 1)}",
    "patch_icpp(1)%alpha(1)": 1,
    "fluid_pp(1)%gamma": 1 / (gamma - 1),
    "fluid_pp(1)%eos": "ideal_gas",
}

# ----------------------------------------------------------------------------------------
# Numerics: a working baseline. Change anything here (reconstruction, Riemann solver,
# time stepper, time step control, output), as long as the run ends at exactly T_END.
#   Constant dt: set dt and t_step_stop so that t_step_stop * dt == T_END.
#   CFL-based dt (cfl_dt or cfl_adap_dt = "T"): set cfl_target and t_stop = T_END; MFC
#   trims the last step to land on t_stop.
# ----------------------------------------------------------------------------------------
cfl = 0.4
dx = L / N
max_speed = u0 * math.sqrt(3) + eps / (2 * math.pi) + math.sqrt(gamma)  # advection + vortex peak + sound
Nt = math.ceil(T_END / (cfl * dx / max_speed))

numerics = {
    "run_time_info": "F",
    "dt": T_END / Nt,
    "t_step_start": 0,
    "t_step_stop": Nt,
    "t_step_save": Nt,
    "model_eqns": "5eq",
    "mpp_lim": "F",
    "mixture_err": "F",
    "time_stepper": "rk3",
    "weno_order": 5,
    "weno_eps": 1.0e-16,
    "mapped_weno": "T",
    "null_weights": "F",
    "mp_weno": "F",
    "riemann_solver": "hllc",
    "wave_speeds": "direct",
    "avg_state": "arithmetic",
    "format": "silo",
    "precision": "double",
    "prim_vars_wrt": "T",
    "parallel_io": "T",
}

print(json.dumps({**problem, **numerics}))
