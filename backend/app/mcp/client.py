import asyncio
import logging
import time
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.config import get_settings
from app.mcp.registry import registry
from app.redaction import sanitize_payload

logger = logging.getLogger(__name__)

ALLOWLIST = {
    "get_machine_information",
    "get_error_code",
    "get_maintenance_history",
    "get_operating_limits",
    "get_machine_status",
}


async def discover_tools() -> list[dict]:
    settings = get_settings()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(settings.mcp_tool_timeout_seconds):
            tools = await _list_tools(settings.mcp_server_url, settings.mcp_server_token)
    except Exception as exc:
        logger.warning("mcp discovery failed: %s", exc.__class__.__name__)
        return []
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    catalog = []
    for tool in tools:
        name = tool["name"]
        catalog.append(
            {
                **tool,
                "allowlisted": name in ALLOWLIST,
                "read_only": True,
                "latency_ms": elapsed,
            }
        )
    return catalog


async def call_allowlisted_tool(name: str, arguments: dict[str, Any], manufacturer: str | None) -> dict:
    settings = get_settings()
    started = time.perf_counter()
    audit = {
        "tool": name,
        "manufacturer": manufacturer,
        "allowlisted": name in ALLOWLIST,
        "mode": "mock" if registry.resolve(manufacturer) else "unknown",
    }
    if name not in ALLOWLIST:
        return _error(
            name,
            arguments,
            "not_allowlisted",
            "Tool is not on the read-only allowlist.",
            started,
            audit,
            manufacturer,
        )
    adapter = registry.resolve(manufacturer) if manufacturer else None
    if manufacturer and adapter is None:
        return _error(
            name,
            arguments,
            "no_adapter",
            "No demo adapter is registered for that manufacturer, and no live OEM schema is bundled.",
            started,
            audit,
            manufacturer,
        )
    try:
        registry.assert_live_not_guessed()
    except Exception as exc:
        return _error(name, arguments, "live_refused", str(exc), started, audit, manufacturer)
    try:
        async with asyncio.timeout(settings.mcp_tool_timeout_seconds):
            payload = await _call_tool(settings.mcp_server_url, settings.mcp_server_token, name, arguments)
    except TimeoutError:
        return _error(name, arguments, "timeout", "Manufacturer tool exceeded the request deadline.", started, audit, manufacturer)
    except Exception as exc:
        logger.warning("mcp tool %s failed: %s", name, exc.__class__.__name__)
        return _error(
            name,
            arguments,
            "error",
            f"Manufacturer tool call failed ({exc.__class__.__name__}).",
            started,
            audit,
            manufacturer,
        )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    sanitized = sanitize_payload(payload)
    ok = bool(isinstance(sanitized, dict) and sanitized.get("ok", True) and not sanitized.get("is_error"))
    status = "ok" if ok else "error"
    return {
        "tool_name": name,
        "arguments": sanitize_payload(arguments),
        "result": sanitized,
        "status": status,
        "is_mock": bool(isinstance(sanitized, dict) and sanitized.get("mock", True)),
        "error": None if ok else "Tool returned an error payload.",
        "latency_ms": elapsed,
        "manufacturer": manufacturer,
        "audit": audit,
        "succeeded": ok,
    }


def _error(name, arguments, status, message, started, audit, manufacturer) -> dict:
    return {
        "tool_name": name,
        "arguments": sanitize_payload(arguments),
        "result": {
            "ok": False,
            "demo": True,
            "mock": True,
            "error": status,
            "message": message,
            "disclaimer": "The tool call did not succeed. Do not treat this as a machine reading.",
        },
        "status": status,
        "is_mock": True,
        "error": message,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "manufacturer": manufacturer,
        "audit": audit,
        "succeeded": False,
    }


async def _open_session(url: str, token: str):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = create_mcp_http_client(headers=headers or None)
    return client


async def _list_tools(url: str, token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    client = create_mcp_http_client(headers=headers)
    async with client:
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
    tools = []
    for tool in listed.tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": schema if isinstance(schema, dict) else {},
            }
        )
    return tools


async def _call_tool(url: str, token: str, name: str, arguments: dict) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    client = create_mcp_http_client(headers=headers)
    async with client:
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
    if getattr(result, "is_error", False):
        return {"ok": False, "is_error": True, "mock": True, "message": _text_content(result)}
    if getattr(result, "structured_content", None) is not None:
        payload = result.structured_content
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "value": payload}
    text = _text_content(result)
    if text.startswith("{") or text.startswith("["):
        import json

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"ok": True, "mock": True, "text": text}


def _text_content(result) -> str:
    chunks = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks)
