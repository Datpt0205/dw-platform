# The image every code-sandbox 01 measurement runs (ADR-0119 (Proposed)).
# Built once by setup_rootless.sh, which passes BASE_IMAGE pinned by digest and
# owns every pin; there is no default, so a build that forgets it fails.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-compile --only-binary=:all: --require-hashes \
        -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The uid every measured container runs as (`--user=10001` in CAPPED_FLAGS).
USER 10001
WORKDIR /work
