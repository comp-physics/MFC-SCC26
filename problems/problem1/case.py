#!/usr/bin/env python3
import json
import math

# Air at rest state; viscosity is 1/Re(1) = 1e-4 Pa s
rho1 = 1.19
p0 = 1.0
gam_a = 1.4
D = 1

# Mach 0.5 freestream: c = 343 m/s, U = 171.5 m/s, Re_L ~ 2e5.
Mach = 0.5
U = Mach * math.sqrt(gam_a * p0 / rho1)

# Configuring case dictionary
print(
    json.dumps(
        {
            # Logistics
            "run_time_info": "T",
            # Computational Domain Parameters
            "x_domain%beg": -2.5 * D,
            "x_domain%end": 5.5 * D,
            "y_domain%beg": -2 * D,
            "y_domain%end": 2 * D,
            "m": 3999,
            "n": 1999,
            "p": 0,
            "cfl_adap_dt": "T",
            "cfl_target": 0.6,
            "n_start": 0,
            "t_stop": 12,
            "t_save": 0.12,
            # Simulation Algorithm Parameters
            "num_patches": 1,
            "model_eqns": "5eq",
            "alt_soundspeed": "F",
            "num_fluids": 1,
            "time_stepper": "rk3",
            "weno_order": 7,
            "weno_eps": 1.0e-16,
            "weno_Re_flux": "F",
            "weno_avg": "F",
            "avg_state": "arithmetic",
            "mapped_weno": "T",
            "null_weights": "F",
            "mp_weno": "F",
            "riemann_solver": "hllc",
            "wave_speeds": "direct",
            "viscous": "T",
            "bc_x%beg": -3,
            "bc_x%end": -3,
            "bc_y%beg": -3,
            "bc_y%end": -3,
            "ib": "T",
            "ib_state_wrt": "T",
            "num_ibs": 1,
            "fd_order": 2,
            # Formatted Database Files Structure Parameters
            "format": "silo",
            "precision": "double",
            "prim_vars_wrt": "T",
            "parallel_io": "T",
            # Patch: Middle
            "patch_icpp(1)%geometry": 3,
            "patch_icpp(1)%x_centroid": 0,
            "patch_icpp(1)%y_centroid": 0,
            "patch_icpp(1)%length_x": 1000 * D,
            "patch_icpp(1)%length_y": 1000 * D,
            "patch_icpp(1)%vel(1)": U,
            "patch_icpp(1)%vel(2)": 0.0e00,
            "patch_icpp(1)%pres": p0,
            "patch_icpp(1)%alpha_rho(1)": (1.0) * rho1,
            "patch_icpp(1)%alpha(1)": 1.0,
            "num_stl_models": 1,
            "patch_ib(1)%geometry": 5,
            "patch_ib(1)%model_id": 1,
            # logo.stl (from logo.png via png2stl.py) is 2 x 0.47 centered at the origin;
            "stl_models(1)%model_filepath": "logo.stl",
            "stl_models(1)%model_translate(1)": 0.0,
            "stl_models(1)%model_translate(2)": 0.0,
            "stl_models(1)%model_threshold": 0.99,
            "patch_ib(1)%slip": "F",
            # Fluids Physical Parameters
            "fluid_pp(1)%gamma": 1.0e00 / (gam_a - 1.0e00),
            "fluid_pp(1)%eos": "ideal_gas",
            "fluid_pp(1)%Re(1)": 10000,
        }
    )
)
