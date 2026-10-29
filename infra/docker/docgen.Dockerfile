# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# The sandbox. Code an LLM wrote from text a customer supplied runs in this
# image, so the rule for every line below is: nothing here is worth reaching.
#
# It holds no application package, no database driver, no object-store client
# and no credentials. What it does hold is a document toolchain — the brandkit
# engine, the five OOXML libraries, LibreOffice for PDF, poppler for page
# images, pandoc for reading text back out — and a service with four routes.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/docgen/pyproject.toml apps/docgen/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/python/dw_kernel/pyproject.toml packages/python/dw_kernel/pyproject.toml
COPY packages/python/dw_platform/pyproject.toml packages/python/dw_platform/pyproject.toml
COPY packages/python/dw_agent_runtime/pyproject.toml packages/python/dw_agent_runtime/pyproject.toml
COPY packages/python/dw_knowledge/pyproject.toml packages/python/dw_knowledge/pyproject.toml
COPY packages/python/dw_memory/pyproject.toml packages/python/dw_memory/pyproject.toml
COPY packages/python/dw_connectors/pyproject.toml packages/python/dw_connectors/pyproject.toml
COPY packages/python/dw_observability/pyproject.toml packages/python/dw_observability/pyproject.toml
COPY packages/python/dw_evals/pyproject.toml packages/python/dw_evals/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --no-dev --package dw-docgen

# Only this app's source. The other workspace packages are deliberately absent:
# a sandbox that carries the CRM's SQL models has something to read.
COPY apps/docgen apps/docgen
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package dw-docgen

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Security updates from the base image's distribution, applied at build time.
# The runtime stage installs no packages of its own, so everything trivy reports
# here comes from the base — and a base image is rebuilt on its own schedule,
# which is slower than a CVE with a released fix deserves. Measured on
# 2026-09-18: three HIGH `libpcre2` issues (out-of-bounds write, arbitrary code
# execution via a crafted regular expression), all already fixed upstream.
# Deliberately `upgrade`, not a pinned package list: the next one will be in a
# different library, and a list would have to be edited to find it.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# libreoffice-writer-nogui: DOCX -> PDF with no X11 and, deliberately, no JRE.
#   The Java stack is only needed by Base and by some filters; if a conversion
#   turns out to need it the image test fails loudly rather than silently
#   producing a blank page, and the fix is one package.
# poppler-utils: pdftoppm, which turns a PDF page into an image the QA gate can
#   look at.
# pandoc: reads text back out of a generated file, which is how the number check
#   sees what the document actually says.
# fonts-liberation + fonts-dejavu-core: metric-compatible with the Office fonts
#   and both cover Vietnamese diacritics. A .docx does not embed fonts, so these
#   only make the server-rendered PDF match what Word shows.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libreoffice-writer-nogui \
        poppler-utils \
        pandoc \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 dw && useradd --uid 1001 --gid dw --no-create-home dw

# The session pool (ADR 0025): each session's shell runs under one of these
# uids, never the service's. Entries rather than bare numbers because
# LibreOffice cannot set up a user installation for a uid with no passwd entry
# (measured 2026-10-29: "User installation could not be completed"). The base
# and count match DW_DOCGEN_SESSION_UID_BASE/COUNT, and the service refuses to
# start when they disagree.
RUN for n in $(seq 0 1023); do         uid=$((20000 + n));         echo "dws$n:x:$uid:$uid::/nonexistent:/usr/sbin/nologin" >> /etc/passwd;         echo "dws$n:x:$uid:" >> /etc/group;     done

WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
# Third-party, pinned at a tag, never edited here. See vendor/brandkit/README.md.
COPY --chown=root:root vendor/brandkit /opt/brandkit

# `brandkit` on PATH, because that is what the skill teaches the model to type.
RUN printf '#!/bin/sh\nexec python3 /opt/brandkit/brandkit/cli.py "$@"\n' > /usr/local/bin/brandkit \
    && chmod 0555 /usr/local/bin/brandkit

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/opt/brandkit \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DW_DOCGEN_ROOT=/work

# Nothing in the image is owned by the user that runs it, so a compromised
# script cannot rewrite the engine it was told to call.
#
# `dw` is the default, and the docgen service refuses to start as `dw`: it
# needs uid 0 with five capabilities to give each session its own uid, which
# compose grants (ADR 0025). So this image run bare fails loudly rather than
# running every session as one uid. The gateway runs as `dw`.
USER dw
EXPOSE 8110

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8110/health', timeout=3).status == 200 else 1)"]

CMD ["uvicorn", "dw_docgen.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8110"]
