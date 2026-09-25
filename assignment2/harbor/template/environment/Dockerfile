FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# Everything the agent AND the verifier need is pinned and baked in here.  The
# task runs with network_mode = "no-network", so nothing can be fetched at run
# time -- in particular pytest is installed here and NOT downloaded by
# tests/test.sh.
#
# NOTE on harbor's `test_deps_in_image` rubric criterion, which asks you to
# install test-only deps from tests/test.sh instead: that is incompatible with
# network_mode = "no-network".  Do not "fix" this; the pin is deliberate.
#
# These four runtime packages are a STRICT SUBSET of the Part 3 agent
# environment (matplotlib, numpy, pandas, Pillow, scipy, seaborn).  Adding
# scipy and seaborn here is legitimate -- but it is build time and image size
# paid on every run, so add them only if your task's solution needs them.
#
# TODO: add/remove libraries your task needs.  Keep every version pinned.
RUN pip install --no-cache-dir \
      matplotlib==3.10.5 \
      numpy==2.3.2 \
      pandas==2.3.1 \
      pillow==11.3.0 \
      pytest==8.4.1 \
      pytest-json-ctrf==0.3.5

# Headless rendering, and warm the font cache at build time so the first
# render is neither slow nor different from later ones.
ENV MPLBACKEND=Agg
RUN python -c "import matplotlib.pyplot as plt; f=plt.figure(); f.savefig('/tmp/warm.png')" \
 && rm -f /tmp/warm.png

WORKDIR /app

# TODO: copy in the input data your instruction.md tells the agent to read.
# Put the file next to this Dockerfile (in environment/) first.  Build context
# is the environment/ directory, so the source path has no "environment/" on it.
#   COPY harvest_log.csv /app/harvest_log.csv
