FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN python -m pip install --no-cache-dir . && \
    groupadd --system shards && useradd --system --gid shards --home /app shards && \
    mkdir -p /data && chown shards:shards /data
USER shards
ENV SHARDS_DB=/data/state.db SHARDS_BIND=0.0.0.0 SHARDS_PORT=8787 SHARDS_ALLOW_REMOTE=1
EXPOSE 8787
# Requires HTTPS/OAuth proxy and SHARDS_ADMIN_TOKEN secret; never expose the port directly.
CMD ["shards-mcp"]
