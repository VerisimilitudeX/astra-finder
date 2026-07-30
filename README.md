# ASTRA Discoverability

[![ASTRA verified](https://verisimilitudex.github.io/astra-finder/badges/VerisimilitudeX--astra-finder.svg)](https://verisimilitudex.github.io/astra-finder/)

**https://verisimilitudex.github.io/astra-finder/**

An index of reproducible [ASTRA](https://github.com/VerisimilitudeX/astra-finder/blob/master/astra.yaml) analyses on GitHub. Every six hours a
GitHub Action sweeps GitHub — by code search, by topic, and by seed list —
for public repositories carrying an `astra.yaml` at their root, validates
each spec against the ASTRA schema, and publishes the result to GitHub
Pages.

## What the index provides

- **Analyses** ranked by stars, searchable, each expandable to its
  description, findings (label + claim from the spec's `findings:`),
  outputs, and tags.
- **Verification** — a repo is *verified* only if its spec passes ASTRA
  schema validation and every declared input file and recipe script
  actually exists in the repository. Verified repos get an embeddable
  badge served from this site.
- **Data lineage** — every declared data file is content-addressed by its
  git blob hash. Identical files connect independent analyses of the same
  data regardless of file name, and each file has a page
  (`dataset.html?h=<hash>`) listing every repo that carries it as an input
  or committed output, with direct raw-file links.

## Structure

```
site/                  static site (GitHub Pages)
scripts/build_index.py the indexer (runs in CI with GITHUB_TOKEN)
scripts/seeds.txt      known repos merged into every run
.github/workflows/     build + deploy every 6h and on push
```

## Getting listed

Put a valid `astra.yaml` at the root of a public GitHub repository. The
next sweep will find it — or add the repo to `scripts/seeds.txt` via PR to
skip the code-search indexing lag. Tag the repo `astra` to be found by the
topic channel too.

---

This repository also contains the reference analysis that seeds the index:
a Union2.1 flat-ΛCDM Hubble-diagram fit (`astra.yaml`, `src/`, `data/`),
runnable with [lightcone-cli](https://pypi.org/project/lightcone-cli/):

```bash
pip install -U lightcone-cli
lc status
lc run
```
