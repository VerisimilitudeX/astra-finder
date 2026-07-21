# Project Notes for Claude

This is an ASTRA project orchestrated by `lightcone-cli`. It was just
scaffolded by `lc init` and has not been scoped yet — `astra.yaml` holds
the placeholder example, not real science.

The three entry skills cover the common starting points:

- `/lc-new` — scope from a research question (empty `astra.yaml`).
- `/lc-from-code` — wrap an existing codebase in ASTRA.
- `/lc-from-paper` — reproduce a published paper end-to-end.

Once scoped, the `lc` CLI keeps the substrate in sync:

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
