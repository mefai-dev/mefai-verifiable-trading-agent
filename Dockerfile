# MEFAI . The Verifiable Trading Agent . offline verification image.
#
# This image runs the deterministic, fully offline verification suite against
# the shipped synthetic sample database. It needs no API keys, no live
# infrastructure, no private database and no network at run time.
#
#   docker build -t mefai-verify .
#   docker run --rm mefai-verify
#
# The default command regenerates the sample book from its seeded generator and
# then proves: the reproducible backtest digest, the dataset Merkle root, and
# that the stored outcome labels match the public scoring rule, finishing with
# the unit-test suite and a single PASS / FAIL banner.

# Pinned base for a deterministic toolchain.
FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first so the layer caches across source edits.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the repository (the sample generator regenerates the DB
# deterministically at run time, so no network is needed).
COPY . .

# Make sure the canonical verifier is executable.
RUN chmod +x scripts/verify_offline.sh

# Default: run the offline verification suite so `docker run <image>` just works.
CMD ["sh", "scripts/verify_offline.sh"]
