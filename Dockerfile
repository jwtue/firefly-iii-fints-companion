# Firefly FinTS Sidecar — small, single container, ARM-capable (Raspberry Pi).
FROM python:3.12-slim AS base

# Non-root user; the app never needs root.
RUN useradd --create-home --uid 10001 sidecar

WORKDIR /app

# Install the project (and its dependencies) from pyproject — single source of
# truth for versions. Copying pyproject + package first keeps the layer cache
# warm as long as neither changes.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

USER sidecar

EXPOSE 8080

# Liveness: the unauthenticated /healthz endpoint, no data exposed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)" || exit 1

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
