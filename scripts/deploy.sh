#!/bin/bash
set -e

echo "Building erddap-db-mcp..."
docker compose build

echo "Starting erddap-db-mcp..."
docker compose up -d

echo "Done. Container running."
