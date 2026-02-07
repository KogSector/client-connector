# =============================================================================
# Client Connector Service - Dockerfile
# Port: 3020
# Role: Gateway for AI agents to connect to ConHub infrastructure
# =============================================================================

FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y curl dumb-init && rm -rf /var/lib/apt/lists/*

# Install Python dependencies directly (bypass pyproject build)
RUN pip install --no-cache-dir \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "websockets>=12.0" \
    "httpx>=0.26.0" \
    "python-jose[cryptography]>=3.3.0" \
    "passlib[bcrypt]>=1.7.4" \
    "pydantic>=2.5.0" \
    "pydantic-settings>=2.1.0" \
    "asyncpg>=0.29.0" \
    "sqlalchemy[asyncio]>=2.0.25" \
    "anyio>=4.2.0" \
    "structlog>=24.1.0" \
    "python-dotenv>=1.0.0"

# Copy source code
COPY app ./app
COPY auth ./auth
COPY gateway ./gateway
COPY models ./models
COPY session ./session
COPY transports ./transports

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 3020

# Health check optimized for Azure Container Apps
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:3020/health || exit 1

# Use dumb-init as PID 1 for proper signal handling
ENTRYPOINT ["dumb-init", "--"]

# Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3020"]
