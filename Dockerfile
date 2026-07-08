FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

# Data directory is a Docker volume — persists between container restarts
VOLUME ["/app/data"]

CMD ["erddap-mcp"]
