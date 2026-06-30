# =============================================================================
# Client Connector Service - Dockerfile
# Port: 8095
# Role: Gateway for AI agents to connect to ConFuse infrastructure
# =============================================================================

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system dependencies for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual environment for easy copying
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "websockets>=12.0" \
    "httpx>=0.26.0" \
    "passlib[bcrypt]>=1.7.4" \
    "pydantic>=2.5.0" \
    "pydantic-settings>=2.1.0" \
    "asyncpg>=0.29.0" \
    "sqlalchemy[asyncio]>=2.0.25" \
    "anyio>=4.2.0" \
    "structlog>=24.1.0" \
    "python-dotenv>=1.0.0"

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user before changing ownership
RUN useradd -m appuser

# Copy source code with strict ownership
COPY --chown=appuser:appuser app ./app

# Set explicit ownership of working directory
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set explicitly for Render fallbacks
ENV PORT=8095
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8095

# Health check optimized for Cloud Run
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8095}/health || exit 1

# Use dumb-init as PID 1 for proper signal handling
ENTRYPOINT ["dumb-init", "--"]

# Run
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8095}"
