# Multi-stage production Dockerfile for Render Deployment
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final minimal runtime image
FROM python:3.12-slim

WORKDIR /app

# Create a non-privileged user for enhanced container security
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Copy installed python dependencies from builder
COPY --from=builder /root/.local /home/botuser/.local
ENV PATH=/home/botuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source code and configurations
COPY config/ ./config/
COPY src/ ./src/
COPY tests/ ./tests/

# Set ownership
RUN chown -R botuser:botuser /app

USER botuser

# Expose Render web service port (defaults to 8080 or PORT env var)
EXPOSE 8080

# Health check matching Render /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.getenv('PORT', '8080'); urllib.request.urlopen(f'http://localhost:{port}/healthz')" || exit 1

# Start the bot orchestrator and web health service
CMD ["python", "-m", "src.main"]
