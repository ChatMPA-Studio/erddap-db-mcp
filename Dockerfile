FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install fastmcp server extras explicitly first, then all other deps
COPY pyproject.toml .
RUN pip install --no-cache-dir "fastmcp-slim[server]>=2.0.0" && \
    pip install --no-cache-dir .

COPY mcp_server/ mcp_server/
COPY tools/ tools/
COPY scheduler/ scheduler/
COPY skills/ skills/
COPY config.yml .
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
