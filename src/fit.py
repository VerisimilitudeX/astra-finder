"""Fit flat Lambda-CDM to the Union2.1 Hubble diagram.

Produces the ``fit_result`` artifact: a chi-square surface over
(Omega_Lambda, H0) plus the best-fit point, uncertainties, and goodness
of fit. The metrics and plots downstream all derive from this, so the fit
runs exactly once.

The four tracked decisions map to CLI flags:
    --method   grid_scan | optimizer | mcmc          (inference_method)
    --offset   fixed | profiling | analytic_marginalization
    --errors   statistical_only | with_systematics   (error_treatment)
    --zcut     none | low_z_cut                       (redshift_cut)
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np

import cosmology as cosmo

# Parameter grid: fine enough that grid discreteness is well below the
# statistical uncertainties. Omega_Lambda spans the physical [0, 1];
# H0 brackets the SN-calibrated value with room for the contour.
OMEGA_LAMBDA_GRID = np.linspace(0.0, 1.0, 501)
H0_GRID = np.linspace(55.0, 85.0, 601)


def _refine_optimizer(z, mu, cinv, offset_treatment, start):
    """Best fit + errors via numerical optimization and a finite-diff Hessian."""
    from scipy.optimize import minimize

    fixed = offset_treatment == "fixed"

    def f(theta):
        oml = theta[0]
        H0 = theta[1] if fixed else 70.0
        return cosmo.chi2_at(z, mu, cinv, oml, H0, offset_treatment)

    x0 = [start[0], start[1]] if fixed else [start[0], 70.0]
    res = minimize(f, x0, method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-6, "maxiter": 4000})
    oml = float(res.x[0])
    H0 = float(res.x[1]) if fixed else np.nan

    # Finite-difference Hessian of chi2 at the minimum -> cov = 2 H^-1.
    out = {"omega_lambda_best": oml, "chi2_min": float(res.fun)}
    steps = np.array([1e-3, 0.2])
    if fixed:
        theta = np.array([oml, H0])
        H = np.zeros((2, 2))
        for i in range(2):
            for jj in range(2):
                ei, ej = np.zeros(2), np.zeros(2)
                ei[i] = steps[i]
                ej[jj] = steps[jj]
                fpp = f(theta + ei + ej)
                fpm = f(theta + ei - ej)
                fmp = f(theta - ei + ej)
                fmm = f(theta - ei - ej)
                H[i, jj] = (fpp - fpm - fmp + fmm) / (4.0 * steps[i] * steps[jj])
        try:
            cov = 2.0 * np.linalg.inv(H)
            oml_err = float(np.sqrt(cov[0, 0]))
            h0_err = float(np.sqrt(cov[1, 1]))
        except np.linalg.LinAlgError:
            oml_err = h0_err = np.nan
        out.update(
            omega_lambda_err=oml_err, omega_lambda_constrained=True,
            H0_best=H0, H0_err=h0_err, H0_constrained=True,
        )
    else:
        # 1D Hessian in Omega_Lambda only.
        d2 = (f([oml + steps[0], 0]) - 2 * res.fun + f([oml - steps[0], 0])) / steps[0] ** 2
        oml_err = float(np.sqrt(2.0 / d2)) if d2 > 0 else np.nan
        out.update(
            omega_lambda_err=oml_err, omega_lambda_constrained=True,
            H0_best=np.nan, H0_err=np.nan, H0_constrained=False,
        )
    return out


def _refine_mcmc(z, mu, cinv, offset_treatment, start, n_steps=40000, seed=0):
    """Best fit + errors via a Metropolis-Hastings sampler (uniform box prior)."""
    rng = np.random.default_rng(seed)
    fixed = offset_treatment == "fixed"
    oml_lo, oml_hi = OMEGA_LAMBDA_GRID[0], OMEGA_LAMBDA_GRID[-1]
    h0_lo, h0_hi = H0_GRID[0], H0_GRID[-1]

    def logp(oml, H0):
        if not (oml_lo <= oml <= oml_hi):
            return -np.inf
        if fixed and not (h0_lo <= H0 <= h0_hi):
            return -np.inf
        return -0.5 * cosmo.chi2_at(z, mu, cinv, oml, H0, offset_treatment)

    oml, H0 = float(start[0]), float(start[1]) if fixed else 70.0
    lp = logp(oml, H0)
    step_oml, step_h0 = 0.01, 0.5
    chain = []
    for _ in range(n_steps):
        oml_p = oml + rng.normal(0, step_oml)
        H0_p = (H0 + rng.normal(0, step_h0)) if fixed else 70.0
        lp_p = logp(oml_p, H0_p)
        if np.log(rng.random()) < lp_p - lp:
            oml, H0, lp = oml_p, H0_p, lp_p
        chain.append((oml, H0))
    chain = np.array(chain[n_steps // 4:])  # discard burn-in

    oml_s = chain[:, 0]
    out = {
        "omega_lambda_best": float(np.median(oml_s)),
        "omega_lambda_err": float(0.5 * (np.percentile(oml_s, 84) - np.percentile(oml_s, 16))),
        "omega_lambda_constrained": True,
    }
    if fixed:
        h0_s = chain[:, 1]
        out.update(
            H0_best=float(np.median(h0_s)),
            H0_err=float(0.5 * (np.percentile(h0_s, 84) - np.percentile(h0_s, 16))),
            H0_constrained=True,
        )
    else:
        out.update(H0_best=np.nan, H0_err=np.nan, H0_constrained=False)
    out["chi2_min"] = float(cosmo.chi2_at(z, mu, cinv, out["omega_lambda_best"],
                                          out.get("H0_best", 70.0) if fixed else 70.0,
                                          offset_treatment))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, help="Union2.1 mu_vs_z file")
    ap.add_argument("--covmat", required=True, help="Union2.1 systematic covariance file")
    ap.add_argument("--method", required=True,
                    choices=["grid_scan", "optimizer", "mcmc"])
    ap.add_argument("--offset", required=True,
                    choices=["fixed", "profiling", "analytic_marginalization"])
    ap.add_argument("--errors", required=True,
                    choices=["statistical_only", "with_systematics"])
    ap.add_argument("--zcut", required=True, choices=["none", "low_z_cut"])
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    names, z_all, mu_all, muerr_all = cosmo.load_mu_data(args.data)
    covmat = cosmo.load_covmat(args.covmat) if args.errors == "with_systematics" else None

    mask = cosmo.redshift_mask(z_all, args.zcut)
    z, mu, muerr = z_all[mask], mu_all[mask], muerr_all[mask]
    n_sn = int(mask.sum())

    cinv = cosmo.inverse_covariance(muerr, covmat, args.errors, mask)

    # The chi-square grid is always computed: it feeds the contour plot and
    # provides the starting point / fallback summary for every method.
    A0, B0, E = cosmo.grid_coefficients(z, mu, cinv, OMEGA_LAMBDA_GRID)
    grid = cosmo.chi2_grid(A0, B0, E, H0_GRID, args.offset)
    grid_summary = cosmo.summarize_grid(grid, OMEGA_LAMBDA_GRID, H0_GRID)

    start = (grid_summary["omega_lambda_best"], grid_summary["H0_best"])
    if args.method == "grid_scan":
        summ = grid_summary
    elif args.method == "optimizer":
        summ = _refine_optimizer(z, mu, cinv, args.offset, start)
    else:
        summ = _refine_mcmc(z, mu, cinv, args.offset, start)

    n_params = 2  # Omega_Lambda and H0 (or Omega_Lambda + nuisance offset)
    dof = n_sn - n_params
    chi2_min = summ["chi2_min"]

    oml = summ["omega_lambda_best"]
    result = {
        "model": "flat_lcdm",
        "omega_lambda": {
            "value": oml,
            "error": summ.get("omega_lambda_err"),
            "lo": summ.get("omega_lambda_lo"),
            "hi": summ.get("omega_lambda_hi"),
            "constrained": summ.get("omega_lambda_constrained", True),
        },
        "omega_m": {"value": 1.0 - oml, "error": summ.get("omega_lambda_err")},
        "h0": {
            "value": summ.get("H0_best"),
            "error": summ.get("H0_err"),
            "lo": summ.get("H0_lo"),
            "hi": summ.get("H0_hi"),
            "constrained": summ.get("H0_constrained", False),
            "unit": "km/s/Mpc",
        },
        "chi2_min": chi2_min,
        "dof": dof,
        "chi2_per_dof": chi2_min / dof if dof > 0 else None,
        "n_sn": n_sn,
        "decisions": {
            "inference_method": args.method,
            "offset_treatment": args.offset,
            "error_treatment": args.errors,
            "redshift_cut": args.zcut,
        },
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "fit_result.json"), "w") as fh:
        json.dump(result, fh, indent=2)

    # Grid arrays for the confidence-contour plot.
    np.savez_compressed(
        os.path.join(args.out, "chi2_grid.npz"),
        omega_lambda_grid=OMEGA_LAMBDA_GRID,
        H0_grid=H0_GRID,
        chi2=grid,
        chi2_min=float(np.min(grid)),
        omega_lambda_best=oml,
        H0_best=summ.get("H0_best", np.nan),
    )

    h0_txt = (f"{result['h0']['value']:.2f} +/- {result['h0']['error']:.2f}"
              if result["h0"]["constrained"] else "unconstrained (degenerate)")
    print(f"[fit] n_sn={n_sn} chi2/dof={result['chi2_per_dof']:.3f} "
          f"Omega_Lambda={oml:.4f} +/- {summ.get('omega_lambda_err', float('nan')):.4f} "
          f"H0={h0_txt}")


if __name__ == "__main__":
    main()
