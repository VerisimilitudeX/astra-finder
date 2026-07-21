# Per-project environment for the lightcone-hub deployment: base on the
# deployment's worker image (dask/dask-gateway/snakemake/lightcone-cli at
# hub-matching versions) and add science deps on top. The Gateway worker
# pod image IS the recipe environment, so recipes run unwrapped inside it;
# the project itself is mounted into the worker (no COPY needed here).
FROM europe-west1-docker.pkg.dev/lightconehub/lightcone/lightcone-worker-default:2026.07.12

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
