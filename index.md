# Fitting the Union2.1 Supernova Hubble Diagram with Flat ΛCDM

## Introduction

Type Ia supernovae (SNe Ia) are standardizable candles: once their light
curves are corrected for shape and colour, their distance moduli trace
the expansion history of the Universe. The Supernova Cosmology Project's
**Union2.1** compilation — {astra}`inputs.union21_mu` — collects
distance moduli $\mu$ for 580 SNe Ia spanning $0.015 \le z \le 1.414$,
and remains a standard public benchmark for cosmological inference.

This analysis fits a two-parameter **flat ΛCDM** model to that Hubble
diagram and asks a single, sharp question: *what values of the
dark-energy density $\Omega_\Lambda$ and the Hubble constant $H_0$ best
describe the data, and how tightly are they jointly constrained?* SNe Ia
supplied the original evidence for accelerated expansion, so recovering
$\Omega_\Lambda > 0$ from the public compilation both reproduces that
landmark result and exercises the full inference machinery end to end.

## Data

The primary input is the Union2.1 $\mu$–$z$ table
({astra}`inputs.union21_mu`): one row per supernova, giving redshift,
distance modulus, and its statistical uncertainty. The compilation's full
systematic-error covariance matrix — {astra}`inputs.union21_covmat` — is
also available, and is used when the error model is configured to include
systematics.

## Model and methods

For a spatially flat ΛCDM universe with $\Omega_m = 1 - \Omega_\Lambda$,
the dimensionless expansion rate is
$E(z) = \sqrt{\Omega_m (1+z)^3 + \Omega_\Lambda}$, the luminosity distance
is $d_L = (1+z)\,(c/H_0)\int_0^z \mathrm{d}z'/E(z')$, and the model
distance modulus is $\mu(z) = 5\log_{10}(d_L/10\,\mathrm{pc})$. Crucially,
$H_0$ enters $\mu$ only as an **additive constant**, which is exactly
degenerate with the SN absolute magnitude — a structural feature that the
analysis makes an explicit choice about.

The analysis exposes four methodological decisions. The two that most
directly shape the answer are the treatment of that absolute-magnitude
offset and the inference algorithm:

:::{astra} decisions.offset_treatment
:::

:::{astra} decisions.inference_method
:::

The remaining two govern the error budget and the sample selection:

:::{astra} decisions.error_treatment
:::

:::{astra} decisions.redshift_cut
:::

The fit is carried out once, producing the shared χ² surface over
$(\Omega_\Lambda, H_0)$ recorded in {astra}`outputs.fit_result`; the
point estimates and figures below are all derived from it.

## Results

Under the baseline configuration — a χ² grid scan trusting the published
absolute calibration, with statistical-only errors and no additional
redshift cut — the flat-ΛCDM fit yields a dark-energy density of

> $\Omega_\Lambda =$ {astra:value col=value err=error pm=true sig=3}`outputs.omega_lambda_estimate`

and a Hubble constant of

> $H_0 =$ {astra:value col=value err=error pm=true sig=4}`outputs.h0_estimate` $\mathrm{km\,s^{-1}\,Mpc^{-1}}$,

corresponding to a matter density $\Omega_m = 1 - \Omega_\Lambda$. The fit
is excellent, with a reduced χ² near unity across the 580 supernovae. The
data clearly favour $\Omega_\Lambda > 0$: an accelerating universe.

The best-fit model tracks the data across the full redshift range, with
residuals scattered symmetrically about zero:

:::{astra} outputs.hubble_diagram
:caption: The Union2.1 Hubble diagram (distance modulus versus redshift) with the best-fit flat-ΛCDM model overlaid; the lower panel shows the residuals.
:::

The joint constraint on the two parameters shows the characteristic
$\Omega_\Lambda$–$H_0$ degeneracy direction:

:::{astra} outputs.confidence_contour
:caption: 68% and 95% joint confidence regions in the $(\Omega_\Lambda, H_0)$ plane, with the best-fit point marked.
:::

## Discussion

The recovered $\Omega_\Lambda$ sits squarely on the published Union2.1
flat-ΛCDM value, and the tight, positive dark-energy density is a direct
restatement of the evidence for cosmic acceleration. The recovered
$H_0 \approx 70\ \mathrm{km\,s^{-1}\,Mpc^{-1}}$ is not an independent
measurement: it reflects the fiducial absolute calibration ($M$ for
$h = 0.7$) baked into the Union2.1 distance moduli, which the baseline
{astra}`decisions.offset_treatment` deliberately trusts. Selecting instead
to marginalize or profile that offset removes the calibration information
and leaves $\Omega_\Lambda$ constrained while $H_0$ becomes degenerate —
the honest statement of what SNe Ia alone can and cannot measure.

Two axes remain open for exploration through alternative universes:
folding in the full systematic covariance
({astra}`decisions.error_treatment`), which broadens the contours, and
excluding the lowest-redshift supernovae
({astra}`decisions.redshift_cut`), where peculiar velocities contribute
non-cosmological scatter. Both are already parameterized and can be
materialized without touching the code.
