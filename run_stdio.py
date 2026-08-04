"""Entry point para Claude Desktop (transporte stdio).

Claude Desktop lanza este script directamente; no requiere servidor HTTP corriendo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from mcp_server.server import mcp

mcp.run(transport="stdio")
