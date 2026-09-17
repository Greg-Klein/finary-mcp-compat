"""Narrow stdio -> Finary Streamable HTTP compatibility relay (MCP SDK 2.0)."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
from pathlib import Path
import stat
import sys

ENDPOINT = "https://public-api.finary.com/mcp"
TOOLS = frozenset({"get_budget_overview", "search_spending"})
LEGACY_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})


def normalize_tools(result: dict) -> dict:
    """Add a logically redundant object constraint, only where proved safe.

    Every branch must explicitly require an object. Never remove schemas,
    rewrite references, alter results, or guess the type of an unknown schema.
    """
    result = copy.deepcopy(result)
    for tool in result.get("tools", []):
        if not isinstance(tool, dict) or tool.get("name") not in TOOLS:
            continue
        schema = tool.get("outputSchema")
        if not isinstance(schema, dict) or "type" in schema:
            continue
        branches = schema.get("oneOf")
        if (isinstance(branches, list) and branches
                and all(isinstance(branch, dict) and branch.get("type") == "object"
                        for branch in branches)):
            schema["type"] = "object"
    return result


class RelayState:
    def __init__(self):
        self.pending = {}
        self.protocol = None

    def sent(self, message: dict) -> None:
        if "method" in message and "id" in message:
            # Only these two methods need response tracking. Calls and their
            # contents are never retained or inspected by the compatibility fix.
            if message["method"] in ("initialize", "tools/list"):
                if len(self.pending) >= 256:
                    raise RuntimeError("Too many outstanding discovery requests")
                self.pending[message["id"]] = message["method"]

    def received(self, message: dict) -> dict:
        if "method" in message or "id" not in message:
            return message
        method = self.pending.pop(message["id"], None)
        result = message.get("result")
        if not isinstance(result, dict):
            return message
        if method == "initialize":
            self.protocol = result.get("protocolVersion")
        if method == "tools/list" and self.protocol in LEGACY_VERSIONS:
            return {**message, "result": normalize_tools(result)}
        return message


def load_config(path: Path) -> dict:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Upstream config must be an owner-only regular file")
    config = json.loads(path.read_text())
    if config.get("url") != ENDPOINT:
        raise ValueError("Only the official Finary MCP endpoint is allowed")
    headers = config.get("headers", {})
    if (not isinstance(headers, dict) or len(headers) != 1
            or next(iter(headers)).lower() != "authorization"
            or not isinstance(next(iter(headers.values())), str)):
        raise ValueError("Expected the existing Finary Authorization header")
    timeout = config.get("timeout", 60)
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise ValueError("Timeout must be between 1 and 600 seconds")
    return config


async def run(config: dict) -> None:
    import anyio
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server.stdio import stdio_server
    from mcp.shared.message import ClientMessageMetadata, SessionMessage
    from mcp.types import jsonrpc_message_adapter

    state = RelayState()
    async with httpx2.AsyncClient(
        headers=config["headers"], timeout=config.get("timeout", 60),
        follow_redirects=False, trust_env=False,
    ) as http:
        async with streamable_http_client(ENDPOINT, http_client=http) as (remote_in, remote_out):
            async with stdio_server() as (local_in, local_out):
                async with anyio.create_task_group() as group:
                    async def upstream():
                        async for envelope in local_in:
                            if isinstance(envelope, Exception):
                                raise RuntimeError("Invalid incoming MCP message")
                            data = envelope.message.model_dump(by_alias=True, exclude_unset=True)
                            state.sent(data)
                            headers = {}
                            if state.protocol and data.get("method") != "initialize":
                                headers["MCP-Protocol-Version"] = state.protocol
                            await remote_out.send(SessionMessage(
                                envelope.message, ClientMessageMetadata(headers=headers)))
                        group.cancel_scope.cancel()

                    async def downstream():
                        async for envelope in remote_in:
                            if isinstance(envelope, Exception):
                                raise RuntimeError("Upstream MCP transport failed")
                            data = envelope.message.model_dump(by_alias=True, exclude_unset=True)
                            adapted = state.received(data)
                            message = (envelope.message if adapted is data else
                                       jsonrpc_message_adapter.validate_python(adapted))
                            await local_out.send(SessionMessage(message))
                        group.cancel_scope.cancel()

                    group.start_soon(upstream)
                    group.start_soon(downstream)
                await local_out.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    # SDK debug/error tracebacks can contain response bodies. The relay never
    # records tokens, requests, financial results, or exception strings.
    logging.disable(logging.CRITICAL)
    try:
        import anyio
        anyio.run(run, load_config(args.config))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Finary compatibility relay failed; check connectivity and private configuration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
