# syntax=docker/dockerfile:1.7
# Multi-stage image: uv resolves the locked environment in a builder stage,
# the runtime stage only carries the venv and runs as an unprivileged user.
#
# Supply chain: every base image is pinned by digest (multi-arch index); the tag is kept
# for readability. Dependabot's "docker" ecosystem (.github/dependabot.yml) opens PRs that
# bump tag and digest together, so literal FROM lines are used instead of ARGs.

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# 1) Dependencies only: cached until pyproject.toml / uv.lock change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# 2) The project itself, installed non-editable so the venv is self-contained.
COPY pyproject.toml uv.lock README.md ./
COPY search_iwara ./search_iwara
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS runtime
LABEL org.opencontainers.image.title="search-iwara" \
      org.opencontainers.image.description="Local Oreno3D metadata mirror with SQLite search and a FastAPI UI" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system --gid 10001 searchiwara \
 && useradd --system --uid 10001 --gid searchiwara --home-dir /data --no-create-home \
      --shell /usr/sbin/nologin searchiwara \
 && install -d -o searchiwara -g searchiwara -m 0750 /data

COPY --from=builder --chown=root:root /app/.venv /app/.venv
# Loops used by the compose "sync" and "backup" services (jitter, exit-code handling).
COPY --chown=root:root --chmod=0755 deploy/docker/sync-loop.sh deploy/docker/backup-loop.sh /usr/local/bin/

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEARCH_IWARA_DB=/data/oreno3d.sqlite3 \
    SEARCH_IWARA_BACKUP_DIR=/data/backups \
    SEARCH_IWARA_LOG_FORMAT=json

USER searchiwara:searchiwara
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# Migrate (idempotent) then serve. Proxy headers are trusted from loopback only;
# set --forwarded-allow-ips to your reverse proxy address if it runs elsewhere.
CMD ["sh", "-c", "search-iwara db migrate && exec search-iwara serve --host 0.0.0.0 --port 8000"]
