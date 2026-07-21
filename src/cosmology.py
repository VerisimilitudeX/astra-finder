"""Flat Lambda-CDM cosmology and SN Ia chi-square machinery.

Shared library for the Union2.1 fit. Everything here is pure physics /
linear algebra; the entry-point scripts (fit.py, report.py, plot_*.py)
import from it.

Model
-----
Flat Lambda-CDM with Omega_m = 1 - Omega_Lambda. The dimensionless
expansion rate is

    E(z) = sqrt( Omega_m (1 + z)^3 + Omega_Lambda ).

The luminosity distance is D_L = (1 + z) (c / H0) * I(z), with
I(z) = int_0^z dz' / E(z'), and the model distance modulus is

    mu(z) = 5 log10(D_L / 10pc)
          = 5 log10[(1 + z) I(z)]  +  5 log10(c / H0) + 25
          = mu_shape(z; Omega_Lambda)  +  offset(H0).

H0 enters only through the additive ``offset(H0)`` term, which is exactly
the structure that makes it degenerate with the SN absolute magnitude.
``mu_shape`` depends on Omega_Lambda alone, so the fit computes it once
per Omega_Lambda value and adds the (cheap) H0 offset afterwards.
"""

from __future__ import annotations

import numpy as np

# Speed of light in km/s. With H0 in km/s/Mpc, c / H0 is in Mpc, and
# 5 log10(Mpc / 10pc) = 5 log10(1e5) = 25 supplies the additive constant.
C_KMS = 299792.458


# --------------------------------------------------------------------------
# Data IO
# --------------------------------------------------------------------------
def load_mu_data(path):
    """Load the Union2.1 ``mu_vs_z`` table.

    Columns: SN name, z, mu, mu_error, P_lowmass (last ignored). Comment
    lines start with ``#``. Returns (names, z, mu, mu_err) as arrays.
    """
    names, z, mu, muerr = [], [], [], []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            names.append(parts[0])
            z.append(float(parts[1]))
            mu.append(float(parts[2]))
            muerr.append(float(parts[3]))
    return (
        np.array(names),
        np.array(z, dtype=float),
        np.array(mu, dtype=float),
        np.array(muerr, dtype=float),
    )


def load_covmat(path):
    """Load the full Union2.1 systematic covariance matrix (N x N)."""
    return np.loadtxt(path)


def redshift_mask(z, redshift_cut):
    """Boolean keep-mask over the supernovae for a redshift-cut option.

    ``low_z_cut`` drops z < 0.023 (peculiar-velocity contaminated);
    ``none`` keeps everything.
    """
    if redshift_cut == "low_z_cut":
        return z >= 0.023
    return np.ones(len(z), dtype=bool)


# --------------------------------------------------------------------------
# Cosmology
# --------------------------------------------------------------------------
def _inv_E(zp, omega_lambda):
    omega_m = 1.0 - omega_lambda
    return 1.0 / np.sqrt(omega_m * (1.0 + zp) ** 3 + omega_lambda)


def comoving_integral(z, omega_lambda, n_grid=4096):
    """I(z_i) = int_0^{z_i} dz' / E(z') for every z_i, vectorized.

    Builds one fine z-grid to max(z), cumulatively trapezoid-integrates
    1/E on it, then interpolates to each supernova redshift.
    """
    z = np.asarray(z, dtype=float)
    grid = np.linspace(0.0, float(z.max()), n_grid)
    integrand = _inv_E(grid, omega_lambda)
    cum = np.concatenate(
        [[0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(grid))]
    )
    return np.interp(z, grid, cum)


def mu_shape(z, omega_lambda):
    """H0-independent part of the distance modulus, 5 log10[(1+z) I(z)]."""
    integral = comoving_integral(z, omega_lambda)
    return 5.0 * np.log10((1.0 + z) * integral)


def offset(H0):
    """Additive distance-modulus offset from H0: 5 log10(c / H0) + 25."""
    return 5.0 * np.log10(C_KMS / np.asarray(H0, dtype=float)) + 25.0


def mu_model(z, omega_lambda, H0):
    """Full model distance modulus mu(z; Omega_Lambda, H0)."""
    return mu_shape(z, omega_lambda) + offset(H0)


# --------------------------------------------------------------------------
# Error model
# --------------------------------------------------------------------------
def inverse_covariance(muerr, covmat, error_treatment, mask):
    """Inverse data covariance for the (masked) supernova sample.

    ``statistical_only`` uses the diagonal per-SN variances; the
    ``muerr`` passed in is assumed already restricted to the kept SNe.
    ``with_systematics`` inverts the full covariance restricted to the
    kept rows/columns via ``mask`` (a boolean mask over the *full* set).
    """
    if error_treatment == "with_systematics":
        if covmat is None:
            raise ValueError("with_systematics requires a covariance matrix")
        cov = covmat[np.ix_(mask, mask)]
        return np.linalg.inv(cov)
    return np.diag(1.0 / muerr ** 2)


# --------------------------------------------------------------------------
# Chi-square building blocks
# --------------------------------------------------------------------------
def grid_coefficients(z, mu, cinv, omega_lambda_grid):
    """Per-Omega_Lambda chi-square coefficients A0, B0 and the scalar E.

    With residual r0 = mu_obs - mu_shape(Omega_Lambda) (before any H0
    offset or nuisance offset), and 1 the all-ones vector:

        A0 = r0^T Cinv r0,   B0 = r0^T Cinv 1,   E = 1^T Cinv 1.

    Any additive offset ``m`` (whether H0's offset or a free nuisance)
    gives chi2(m) = A0 - 2 m B0 + m^2 E, which these coefficients build
    cheaply for the whole grid.
    """
    ones = np.ones(len(z))
    cinv_ones = cinv @ ones
    E = float(ones @ cinv_ones)
    A0 = np.empty(len(omega_lambda_grid))
    B0 = np.empty(len(omega_lambda_grid))
    for k, oml in enumerate(omega_lambda_grid):
        r0 = mu - mu_shape(z, oml)
        cinv_r0 = cinv @ r0
        A0[k] = float(r0 @ cinv_r0)
        B0[k] = float(ones @ cinv_r0)
    return A0, B0, E


def chi2_at(z, mu, cinv, omega_lambda, H0, offset_treatment):
    """Chi-square at a single (Omega_Lambda, H0) point.

    ``fixed`` trusts the calibration: the only offset is offset(H0).
    ``profiling`` / ``analytic_marginalization`` add a free magnitude
    offset that is minimized / integrated out analytically, which makes
    the result independent of H0 (A0 - B0^2 / E).
    """
    ones = np.ones(len(z))
    r0 = mu - mu_shape(z, omega_lambda)
    cinv_r0 = cinv @ r0
    A0 = float(r0 @ cinv_r0)
    B0 = float(ones @ cinv_r0)
    E = float(ones @ (cinv @ ones))
    if offset_treatment == "fixed":
        m = float(offset(H0))
        return A0 - 2.0 * m * B0 + m * m * E
    chi2 = A0 - B0 * B0 / E
    if offset_treatment == "analytic_marginalization":
        chi2 += np.log(E / (2.0 * np.pi))
    return chi2


def chi2_grid(A0, B0, E, H0_grid, offset_treatment):
    """Full 2D chi-square surface over (Omega_Lambda, H0).

    ``fixed`` varies with H0 through offset(H0). ``profiling`` and
    ``analytic_marginalization`` are flat in H0 (H0 degenerate with the
    free offset) and are broadcast across the H0 axis.
    """
    if offset_treatment == "fixed":
        m = offset(H0_grid)  # (n_H0,)
        return (
            A0[:, None]
            - 2.0 * np.outer(B0, m)
            + (m[None, :] ** 2) * E
        )
    chi2_1d = A0 - B0 ** 2 / E
    if offset_treatment == "analytic_marginalization":
        chi2_1d = chi2_1d + np.log(E / (2.0 * np.pi))
    return np.repeat(chi2_1d[:, None], len(H0_grid), axis=1)


# --------------------------------------------------------------------------
# Interval extraction from a Delta-chi2 profile
# --------------------------------------------------------------------------
def _cross(x, prof, i, target, direction):
    """Linear-interpolate the x where prof crosses ``target`` near index i.

    ``direction`` is -1 to look at the low side (between i-1 and i) or
    +1 for the high side (between i and i+1). Falls back to x[i] at edges.
    """
    j = i + direction
    if j < 0 or j >= len(x):
        return x[i]
    p0, p1 = prof[i], prof[j]
    if p1 == p0:
        return x[i]
    frac = (target - p0) / (p1 - p0)
    return x[i] + frac * (x[j] - x[i])


def interval_from_profile(x, prof, delta=1.0):
    """68% interval (Delta-chi2 <= delta) from a 1D profile.

    Returns (lo, hi, err, constrained). ``constrained`` is True only when
    the profile rises above ``delta`` on both sides within the grid, so a
    flat (degenerate) direction reports constrained=False.
    """
    below = prof <= delta
    if not below.any():
        return np.nan, np.nan, np.nan, False
    idx = np.where(below)[0]
    lo_i, hi_i = int(idx[0]), int(idx[-1])
    constrained = bool(prof[0] > delta and prof[-1] > delta)
    lo = _cross(x, prof, lo_i, delta, -1)
    hi = _cross(x, prof, hi_i, delta, +1)
    err = 0.5 * (hi - lo)
    return lo, hi, err, constrained


def summarize_grid(chi2, omega_lambda_grid, H0_grid):
    """Best fit and 1-sigma profile intervals from a 2D chi-square grid.

    Omega_Lambda interval profiles over H0; H0 interval profiles over
    Omega_Lambda. Delta-chi2 = 1 gives the 68% profile-likelihood range.
    """
    k, j = np.unravel_index(int(np.argmin(chi2)), chi2.shape)
    chi2_min = float(chi2[k, j])
    dchi2 = chi2 - chi2_min

    oml_lo, oml_hi, oml_err, oml_con = interval_from_profile(
        omega_lambda_grid, dchi2.min(axis=1)
    )
    h0_lo, h0_hi, h0_err, h0_con = interval_from_profile(
        H0_grid, dchi2.min(axis=0)
    )
    return {
        "omega_lambda_best": float(omega_lambda_grid[k]),
        "omega_lambda_err": float(oml_err),
        "omega_lambda_lo": float(oml_lo),
        "omega_lambda_hi": float(oml_hi),
        "omega_lambda_constrained": oml_con,
        "H0_best": float(H0_grid[j]),
        "H0_err": float(h0_err),
        "H0_lo": float(h0_lo),
        "H0_hi": float(h0_hi),
        "H0_constrained": h0_con,
        "chi2_min": chi2_min,
        "best_index": (int(k), int(j)),
    }


# Delta-chi2 thresholds for 2-parameter joint confidence regions.
DELTA_CHI2_2D = {"68": 2.30, "95": 6.17}
