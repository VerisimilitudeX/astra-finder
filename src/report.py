"""Extract a single scalar metric from the fit result.

Reads ``fit_result.json`` from the fit output directory and writes a
small JSON holding one quantity (H0 or Omega_Lambda) with its
uncertainty, so each metric is its own ASTRA output.
"""

from __future__ import annotations

import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit", required=True, help="fit_result output directory")
    ap.add_argument("--quantity", required=True, choices=["h0", "omega_lambda"])
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    with open(os.path.join(args.fit, "fit_result.json")) as fh:
        fit = json.load(fh)

    block = fit[args.quantity]
    if args.quantity == "h0":
        name, unit = "H0", "km/s/Mpc"
    else:
        name, unit = "Omega_Lambda", None

    metric = {
        "name": name,
        "value": block["value"],
        "error": block.get("error"),
        "unit": unit,
        "constrained": block.get("constrained", True),
        "model": fit.get("model"),
        "decisions": fit.get("decisions"),
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{args.quantity}.json"), "w") as fh:
        json.dump(metric, fh, indent=2)

    if metric["constrained"] and metric["value"] is not None:
        unit_s = f" {unit}" if unit else ""
        err_s = f" +/- {metric['error']:.4f}" if metric["error"] is not None else ""
        print(f"[report] {name} = {metric['value']:.4f}{err_s}{unit_s}")
    else:
        print(f"[report] {name} = unconstrained (degenerate under this offset treatment)")


if __name__ == "__main__":
    main()
