# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
COPY server/ ./server/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && mkdir -p /opt/copilot-runtime \
    && COPILOT_CLI_EXTRACT_DIR=/opt/copilot-runtime python -m copilot download-runtime


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed Python packages and entry-point scripts
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/copilot-sdk-openai-proxy /usr/local/bin/copilot-sdk-openai-proxy
COPY --from=builder /opt/copilot-runtime /opt/copilot-runtime

# Copy application source
COPY server/ ./server/

EXPOSE 8081

# Authentication: pass COPILOT_GITHUB_TOKEN (or GH_TOKEN / GITHUB_TOKEN) at runtime

# Allow configuring the listening port at runtime (default: 8081)
ENV PORT="8081" \
    COPILOT_CLI_EXTRACT_DIR="/opt/copilot-runtime"

# Use a shell entrypoint so we can expand the PORT env var into the command line
ENTRYPOINT ["/bin/sh", "-c", "exec copilot-sdk-openai-proxy --host 0.0.0.0 --port ${PORT}"]
