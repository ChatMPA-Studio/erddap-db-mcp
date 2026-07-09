"""Entry point para Claude Desktop (transporte stdio).

Claude Desktop lanza este script directamente; no requiere servidor HTTP corriendo.
"""
import asyncio
import os
import sys

# Asegurar que el paquete se encuentra aunque se llame desde otra carpeta
sys.path.insert(0, os.path.dirname(__file__))

from mcp_server.server import main

asyncio.run(main())
