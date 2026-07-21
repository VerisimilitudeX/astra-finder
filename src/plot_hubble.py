"""Hubble diagram: Union2.1 data with the best-fit flat-LCDM model overlaid."""

from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import cosmology as cosmo


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, help="Union2.1 mu_vs_z file")
    ap.add_argument("--fit", required=True, help="fit_result output directory")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    names, z, mu, muerr = cosmo.load_mu_data(args.data)
    with open(os.path.join(args.fit, "fit_result.json")) as fh:
        fit = json.load(fh)

    oml = fit["omega_lambda"]["value"]
    # H0 may be degenerate (marginalized/profiled). Fall back to the value
    # implied by the data's calibration so the model curve still tracks the
    # points; the shape (Omega_Lambda) is what the overlay illustrates.
    H0 = fit["h0"]["value"]
    if H0 is None or not fit["h0"]["constrained"]:
        H0 = _best_offset_H0(z, mu, muerr, oml)

    fig, (ax, axr) = plt.subplots(
        2, 1, sharex=True, figsize=(7, 6),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05},
    )

    ax.errorbar(z, mu, yerr=muerr, fmt=".", ms=4, elinewidth=0.6,
                color="0.4", ecolor="0.75", alpha=0.7, label="Union2.1 (580 SNe Ia)")

    z_curve = np.logspace(np.log10(z.min() * 0.9), np.log10(z.max() * 1.05), 300)
    mu_curve = cosmo.mu_model(z_curve, oml, H0)
    label = (rf"flat $\Lambda$CDM: $\Omega_\Lambda={oml:.3f}$, "
             rf"$H_0={H0:.1f}$")
    ax.plot(z_curve, mu_curve, "-", color="crimson", lw=1.8, label=label)

    ax.set_xscale("log")
    ax.set_ylabel(r"distance modulus $\mu$")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.set_title("Union2.1 Hubble diagram")

    resid = mu - cosmo.mu_model(z, oml, H0)
    axr.errorbar(z, resid, yerr=muerr, fmt=".", ms=3, elinewidth=0.5,
                 color="0.4", ecolor="0.8", alpha=0.7)
    axr.axhline(0.0, color="crimson", lw=1.2)
    axr.set_xscale("log")
    axr.set_ylabel(r"$\Delta\mu$")
    axr.set_xlabel("redshift $z$")
    axr.set_ylim(-1.2, 1.2)

    os.makedirs(args.out, exist_ok=True)
    fig.savefig(os.path.join(args.out, "hubble_diagram.png"), dpi=150, bbox_inches="tight")
    print(f"[plot_hubble] wrote hubble_diagram.png (Omega_Lambda={oml:.3f}, H0={H0:.2f})")


def _best_offset_H0(z, mu, muerr, oml):
    """H0 implied by the least-squares offset at fixed Omega_Lambda."""
    d = mu - cosmo.mu_shape(z, oml)
    w = 1.0 / muerr ** 2
    m = float(np.sum(w * d) / np.sum(w))          # best additive offset
    return float(cosmo.C_KMS / 10 ** ((m - 25.0) / 5.0))


if __name__ == "__main__":
    main()
