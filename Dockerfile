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

ENTRYPOINT ["python", "-c", "import os, uvicorn; from agentwarden.server.app import create_app; app = create_app(runtime=os.getenv('AGENTWARDEN_RUNTIME','generic'), backend=os.getenv('AGENTWARDEN_BACKEND','ollama'), shadow_mode=os.getenv('AGENTWARDEN_SHADOW_MODE','false').lower()=='true', backend_url=os.getenv('OLLAMA_BASE_URL') if os.getenv('AGENTWARDEN_BACKEND','ollama')=='ollama' else None); uvicorn.run(app, host='0.0.0.0', port=8000)"]
