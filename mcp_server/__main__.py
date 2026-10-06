from mcp_server.config import PORT, MCP_BASE_PATH, setup_logging, print_startup_summary
from mcp_server.data_store import init_db
from mcp_server.server import mcp

setup_logging()
print_startup_summary()
init_db()

mcp.run(transport="http", host="0.0.0.0", port=PORT, path=MCP_BASE_PATH, stateless_http=True)
