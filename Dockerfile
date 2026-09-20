# shipdoc — batch verification of shipping instructions against draft bills of lading.
#
# WHAT THIS IMAGE IS TODAY
# ------------------------
# A BATCH processor, not a web service. There is no HTTP API yet, so on Azure this
# deploys as a **Container Apps Job** (run on a schedule or on demand), which is the
# right primitive for something that processes an inbox and exits. When the API
# lands, the same image gains an ingress and becomes a Container App — see SETUP.md.
#
# WHAT IS DELIBERATELY NOT IN HERE
# --------------------------------
#   * No secrets. Not the API key, not DATABASE_URL, not a .env. Those arrive as
#     environment variables from Azure App Settings / Container Apps secrets at run
#     time. `.dockerignore` excludes `.env` so a developer's copy cannot be baked in
#     by accident, and `infra/dotenv.py` lets a real environment variable win even if
#     one somehow were.
#   * No Ollama and no GPU. The committed cache answers every prompt this corpus
#     asks, so the image reproduces the published score with no model and no network.
#     Set `llm.provider: deepseek` and supply a key to use a hosted model instead.
#   * No answer key. It lives outside the repository and outside the image.

FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE: a read-only filesystem is a reasonable hardening step and
# .pyc writes would fail noisily. PYTHONUNBUFFERED: without it, logs from a batch job
# appear only when the process exits, which is precisely when you stop needing them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first, so a source edit does not reinstall the world.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[hosted,db]"

# Everything the run actually reads. `dataset/` carries the organisers' loader.py and
# the corpus; `cache/llm/` is what makes a run reproducible with no model.
COPY config/ ./config/
COPY cache/ ./cache/
COPY dataset/ ./dataset/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Non-root. A container that processes third-party documents should not be root, and
# Azure Container Apps does not require it.
RUN useradd --create-home --uid 10001 shipdoc \
    && mkdir -p /app/output \
    && chown -R shipdoc:shipdoc /app
USER shipdoc

# `doctor --fast` exits non-zero when the install, corpus or config is broken, so it
# is a real check rather than a liveness placebo.
HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=2 \
    CMD ["shipdoc", "doctor", "--fast"]

ENTRYPOINT ["shipdoc"]
CMD ["run"]
