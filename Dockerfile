FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN python -m pip install --no-cache-dir . && \
    groupadd --system shards && useradd --system --gid shards --home /app shards && \
    mkdir -p /data && chown shards:shards /data
USER shards
ENV SHARDS_DB=/data/state.db SHARDS_BIND=0.0.0.0 SHARDS_PORT=8787
# SHARDS_ALLOW_REMOTE=1 must be passed explicitly by a trusted deployer.
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health/ready',timeout=2).read()" || exit 1
# Requires HTTPS/OAuth proxy and SHARDS_ADMIN_TOKEN secret; never expose the port directly.
CMD ["shards-mcp"]
