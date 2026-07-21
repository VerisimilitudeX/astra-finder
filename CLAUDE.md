# Project Notes for Claude

This is an ASTRA project orchestrated by `lightcone-cli`. It has been
scoped (via `/lc-new`) but not yet implemented — `astra.yaml` is the
source of truth for structure, decisions, and provenance.

## Project Notes

**Science.** Fit the SCP Union2.1 SN Ia Hubble diagram (distance modulus
mu vs redshift z, 580 SNe over 0.015 ≤ z ≤ 1.414) with **flat ΛCDM**,
Ω_m = 1 − Ω_Λ. Two free parameters: **H0** and **Ω_Λ**. Report both with
uncertainties, plus the Hubble diagram and the (Ω_Λ, H0) confidence
contours.

**Physics the code must implement.** For flat ΛCDM,
E(z) = sqrt(Ω_m(1+z)³ + Ω_Λ); luminosity distance
d_L = (1+z)·(c/H0)·∫₀ᶻ dz'/E(z'); model distance modulus
μ = 5·log10(d_L / 10pc). SNe alone constrain only Ω_Λ and the
combination M − 5·log10(H0), so H0 is degenerate with the absolute
magnitude — hence the `offset_treatment` decision (default: analytic
marginalization of the constant magnitude offset).

**Data.** `union21_mu` is the linked `SCPUnion2.1_mu_vs_z.txt` (columns:
SN name, z, μ, μ_error). `union21_covmat` is `SCPUnion2.1_covmat_sys.txt`
from the same SCP page — needed **only** for the `with_systematics`
universe; the default `baseline` universe uses diagonal errors only, so
the covmat file is not required to run the default path.

**Implementation status.** Not written yet. The recipes reference
`src/fit.py` (runs the fit → `fit_result`), `src/report.py` (extracts a
scalar metric from `fit_result`), `src/plot_hubble.py`, and
`src/plot_contour.py`. `fit_result` is the shared intermediate — the fit
runs once; metrics and plots derive from it. Every decision must be
parameterized via its CLI flag (`--method`, `--offset`, `--errors`,
`--zcut`), never hardcoded.

## lightcone-cli workflow

Once implemented, the `lc` CLI keeps the substrate in sync:

```
lc run                    # all outputs in the default universe
lc run output_id          # one specific output
lc status                 # show what's materialized vs stale vs missing
lc verify                 # validate the provenance chain
```

Outputs land in `results/<universe>/<output_id>/` along with a sidecar
`.lightcone-manifest.json` recording the recipe, container, decisions,
input hashes, and output hash.

## Report

`index.md` + `myst.yml` are a template MyST report wired to the MySTRA
plugin. The report references analysis elements by path — inline mentions
with the `{astra}` role, block embeds with the `{astra}` directive, live
numbers with `{astra:value}` — so never hard-type a measured value in the
prose. Preview with `myst start` (requires the MyST CLI, `npm i -g mystmd`).
