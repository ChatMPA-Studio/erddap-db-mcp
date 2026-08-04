# =============================================================================
# Stage 1: Builder — install dependencies into a virtual environment
# =============================================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml ./

RUN mkdir -p mcp_server tools scheduler skills && \
    touch mcp_server/__init__.py tools/__init__.py scheduler/__init__.py && \
    pip install --no-cache-dir --prefix=/install . && \
    rm -rf mcp_server tools scheduler skills

# =============================================================================
# Stage 2: Runtime — lean production image
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /install /usr/local

COPY pyproject.toml ./
COPY mcp_server/ mcp_server/
COPY tools/ tools/
COPY scheduler/ scheduler/
COPY skills/ skills/
COPY config.yml ./
RUN pip install --no-cache-dir --no-deps .

COPY healthcheck.py ./

RUN groupadd --gid 1000 mcp && \
    useradd --uid 1000 --gid mcp --shell /bin/false mcp && \
    chown -R mcp:mcp /app
USER mcp

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "-m", "mcp_server"]
