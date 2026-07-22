FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# This image runs as a Dask Gateway worker pod with the user's NFS home
# mounted at /home/jovyan. A uid-1000 passwd entry keeps outputs owned
# by the user and getpass.getuser() (called by snakemake) working.
RUN useradd --create-home --uid 1000 jovyan
USER jovyan
