# The runtime the Code_Aster analyses run best in.
#
# It carries what pip cannot: Code_Aster, which is a native solver with its own
# Python. Everything the scripts import is declared in `partcad.yaml` as
# `pythonRequirements` and installed by PartCAD into the environment it creates
# -- this image is a *runtime*, and the package has to work in a conda or venv
# sandbox on a host with Code_Aster installed too.
#
# amd64 only: conda-forge builds Code_Aster for 64-bit x86 Linux and Windows,
# and nothing official exists for 64-bit ARM Linux.
ARG PYTHON_VERSION=3.11
ARG ARCH=amd64
FROM ghcr.io/partcad/partcad-container-python:py${PYTHON_VERSION}-${ARCH}

LABEL partcad.image="1"
LABEL org.opencontainers.image.source="https://github.com/partcad/partcad-cae-code-aster"

USER root
ENV DEBIAN_FRONTEND=noninteractive

# What pip's gmsh wheel opens at import: it is built with its GUI, and the X and
# GL libraries that GUI links against have to be present even when nothing is
# drawn.
RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
       libglu1-mesa libxcursor1 libxft2 libxinerama1 libxrender1 libxi6 \
  && rm -rf /var/lib/apt/lists/*

# Code_Aster from conda-forge, into a prefix of its own: it brings its own
# Python, MPI-free MUMPS, MED and HDF5, all reached through that prefix, so none
# of it lands where it could shadow the interpreter PartCAD runs in. micromamba
# is fetched by version, checked against the hash conda-forge publishes, and
# removed with its cache in the same layer.
RUN set -eu; \
    MICROMAMBA_VERSION=2.9.0; \
    CODE_ASTER_VERSION=18.1.8; \
    SHA256=8761c382127e6363bd9e0a2451aa3ef90d071a79133f736e2f759a3bf13040dd; \
    python3 -c 'import hashlib, io, os, sys, tarfile, urllib.request; url, want = sys.argv[1], sys.argv[2]; blob = urllib.request.urlopen(url).read(); got = hashlib.sha256(blob).hexdigest(); got == want or sys.exit("%s hashes to %s, not the pinned %s" % (url, got, want)); open("/usr/local/bin/micromamba", "wb").write(tarfile.open(fileobj=io.BytesIO(blob), mode="r:bz2").extractfile("bin/micromamba").read()); os.chmod("/usr/local/bin/micromamba", 0o755)' \
      "https://conda.anaconda.org/conda-forge/linux-64/micromamba-${MICROMAMBA_VERSION}-0.tar.bz2" "${SHA256}"; \
    micromamba create --yes --root-prefix /tmp/mamba --prefix /opt/code_aster \
      --channel conda-forge "code-aster=${CODE_ASTER_VERSION}"; \
    rm -rf /tmp/mamba /usr/local/bin/micromamba

# Where `code_aster_common.find_run_aster()` looks even when PATH says nothing.
# A symlink rather than an edit to PATH, because PartCAD builds a sandbox inside
# this container and a sandbox rebuilds PATH.
RUN ln -s /opt/code_aster/bin/run_aster /usr/local/bin/run_aster

ENV PC_CONTAINER_ALLOWED_COMMANDS='{"python": "/usr/local/bin/python3", "run_aster": "/usr/local/bin/run_aster"}'

# Two checks: the base image's own, and this package's, which runs a small
# study the way the analyses will.
COPY verify_image.py /tmp/verify_image.py
RUN python3 /pc/verify.py \
  && python3 /tmp/verify_image.py \
  && rm /tmp/verify_image.py

USER pc
