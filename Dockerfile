FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python package
COPY pyproject.toml .
COPY agentwarden/ ./agentwarden/

RUN pip install --no-cache-dir -e ".[all]"

# Audit log directory
RUN mkdir -p /app/audit

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["agentwarden"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
