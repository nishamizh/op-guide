"""Official MCP Python SDK server (MCPServer, the FastMCP successor in mcp 2.x).

Tools are read-only demo fixtures. There is no start, stop, jog, or guard-bypass tool.
"""

import os

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from manufacturer.fixtures import (
    error_code as lookup_error_code,
)
from manufacturer.fixtures import (
    machine_information,
    machine_status,
    maintenance_history,
    operating_limits,
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

mcp = MCPServer(
    "manualmind-manufacturer",
    instructions=(
        "Read-only fictional manufacturer adapter for the ManualMind demo. "
        "Every payload is mock data. Do not treat it as live telemetry. "
        "No tool can start, stop, disable guards, or change equipment."
    ),
)


def _clean(value: str, limit: int = 80) -> str:
    text = "".join(ch for ch in (value or "") if ch.isprintable()).strip()
    return text[:limit]


@mcp.tool(annotations=READ_ONLY)
def get_machine_information(manufacturer: str, model: str) -> dict:
    """Return fictional demo identity data for a manufacturer and model. Read-only."""
    return machine_information(_clean(manufacturer), _clean(model))


@mcp.tool(annotations=READ_ONLY)
def get_error_code(manufacturer: str, model: str, error_code: str) -> dict:
    """Return a fictional demo error-code definition. Read-only. Not a live OEM lookup."""
    return lookup_error_code(_clean(manufacturer), _clean(model), _clean(error_code, 16))


@mcp.tool(annotations=READ_ONLY)
def get_maintenance_history(machine_id: str) -> dict:
    """Return fictional demo maintenance records for a machine id. Read-only."""
    return maintenance_history(_clean(machine_id, 40))


@mcp.tool(annotations=READ_ONLY)
def get_operating_limits(model: str, manufacturer: str = "") -> dict:
    """Return fictional demo operating limits copied from the demo manuals. Read-only."""
    return operating_limits(_clean(model), _clean(manufacturer))


@mcp.tool(annotations=READ_ONLY)
def get_machine_status(machine_id: str) -> dict:
    """Return a fictional demo status snapshot. Read-only. Not live telemetry."""
    return machine_status(_clean(machine_id, 40))


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8092"))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
