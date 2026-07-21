FROM python:3.12-slim

# uv, pulled from its official image (fast, reproducible, no curl bootstrap).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# On a Kubernetes / Dask Gateway deployment the pod image IS the execution
# environment, so it must contain lightcone-cli. Installing it here also pulls
# dask, distributed, and the dask-gateway client at pinned, hub-matching
# versions, so this image doubles as a valid Gateway worker. Add project
# dependencies to requirements.txt.
#
# --system installs into the image's Python (no venv in a container), which
# also puts dask-worker / dask-gateway-scheduler on PATH where the Gateway
# backend launches them by name.
COPY requirements.txt .
RUN uv pip install --system --no-cache "lightcone-cli[gateway]" -r requirements.txt

COPY . .
