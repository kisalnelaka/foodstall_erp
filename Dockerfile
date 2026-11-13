# ==============================================================================
# Sumiyuru Stall ERP & Cash Cockpit - Production Containerfile
# High-performance, minimal, secure Python runtime
# ==============================================================================
FROM python:3.12-slim AS runner

# Set environment invariants
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

# Install system dependencies needed for runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY db.py server.py ./
COPY static/ ./static/
COPY data/ ./data/

# Create unprivileged application user
RUN useradd -m -u 1000 sumiyuru && \
    mkdir -p /app/data && \
    chown -R sumiyuru:sumiyuru /app

USER sumiyuru

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

ENTRYPOINT ["python", "server.py"]
