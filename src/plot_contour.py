"""Confidence contours in the (Omega_Lambda, H0) plane from the chi-square grid."""

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
    ap.add_argument("--fit", required=True, help="fit_result output directory")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    grid = np.load(os.path.join(args.fit, "chi2_grid.npz"))
    oml_grid = grid["omega_lambda_grid"]
    h0_grid = grid["H0_grid"]
    chi2 = grid["chi2"]
    dchi2 = chi2 - chi2.min()

    with open(os.path.join(args.fit, "fit_result.json")) as fh:
        fit = json.load(fh)
    h0_constrained = fit["h0"]["constrained"]

    fig, ax = plt.subplots(figsize=(6, 5.5))

    # dchi2[k, j]: k indexes Omega_Lambda (rows), j indexes H0 (cols).
    # contourf expects Z[y, x] with x=H0, y=Omega_Lambda.
    levels = [cosmo.DELTA_CHI2_2D["68"], cosmo.DELTA_CHI2_2D["95"]]
    cf = ax.contourf(h0_grid, oml_grid, dchi2, levels=[0] + levels,
                     colors=["#1f77b4", "#9ecae1"], alpha=0.8)
    ax.contour(h0_grid, oml_grid, dchi2, levels=levels,
               colors="k", linewidths=0.8)

    k, j = np.unravel_index(int(np.argmin(chi2)), chi2.shape)
    ax.plot(h0_grid[j], oml_grid[k], "*", color="crimson", ms=14,
            markeredgecolor="k", label="best fit")

    # Zoom to the 95% region (plus padding) when H0 is constrained, so the
    # ellipse fills the frame instead of sitting in a large empty box.
    inside = dchi2 <= cosmo.DELTA_CHI2_2D["95"]
    if h0_constrained and inside.any():
        ks, js = np.where(inside)
        oml_in, h0_in = oml_grid[ks], h0_grid[js]
        oml_pad = 0.4 * (oml_in.max() - oml_in.min() + 1e-6)
        h0_pad = 0.4 * (h0_in.max() - h0_in.min() + 1e-6)
        ax.set_xlim(h0_in.min() - h0_pad, h0_in.max() + h0_pad)
        ax.set_ylim(oml_in.min() - oml_pad, oml_in.max() + oml_pad)

    ax.set_xlabel(r"$H_0$ [km s$^{-1}$ Mpc$^{-1}$]")
    ax.set_ylabel(r"$\Omega_\Lambda$")
    title = "68% / 95% confidence (flat $\\Lambda$CDM)"
    if not h0_constrained:
        title += "\n($H_0$ degenerate under this offset treatment)"
    ax.set_title(title)

    proxy68 = plt.Rectangle((0, 0), 1, 1, fc="#1f77b4", alpha=0.8)
    proxy95 = plt.Rectangle((0, 0), 1, 1, fc="#9ecae1", alpha=0.8)
    ax.legend([proxy68, proxy95, ax.lines[0]], ["68%", "95%", "best fit"],
              loc="best", frameon=False, fontsize=9)

    os.makedirs(args.out, exist_ok=True)
    fig.savefig(os.path.join(args.out, "confidence_contour.png"), dpi=150,
                bbox_inches="tight")
    print(f"[plot_contour] wrote confidence_contour.png "
          f"(best: Omega_Lambda={oml_grid[k]:.3f}, H0={h0_grid[j]:.2f})")


if __name__ == "__main__":
    main()
