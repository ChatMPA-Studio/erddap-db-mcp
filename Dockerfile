FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Deps resueltas con uv: el resolver de pip se rinde con backtracking
# (ResolutionImpossible falso sobre fsspec/s3fs) con este set de dependencias.
COPY pyproject.toml .
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .

COPY mcp_server/ mcp_server/
COPY tools/ tools/
COPY skills/ skills/
COPY config.yml .
COPY run_initial_sync.py .
COPY healthcheck.py .

RUN groupadd --gid 1000 mcp && \
    useradd --uid 1000 --gid mcp --shell /bin/false mcp && \
    chown -R mcp:mcp /app
USER mcp

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "-m", "mcp_server"]
