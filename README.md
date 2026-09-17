# Finary MCP compatibility relay

Small, reversible workaround for strict legacy MCP clients rejecting the Finary
`get_budget_overview` and `search_spending` output schemas during `tools/list`.

These schemas use `oneOf` with object-only branches but omit the explicit root
`type: "object"` expected by MCP protocol 2025-11-25. The relay adds that redundant
constraint only for those two named tools, only when **every** branch explicitly
requires an object, and only for a negotiated legacy protocol. Unknown shapes
are left unchanged so the client can reject them normally. All nested schema
constraints, input schemas, annotations, pagination and tool results are preserved.

The MCP SDK supplies stdio and Streamable HTTP transports, including sessions,
SSE and cancellation. There is no public listening port, no SDK monkey patch,
no change to Hermes source, and no automatic tool invocation.

## Runtime

Tested with Python 3.11.16 and MCP Python SDK 2.0.0 in the existing Hermes virtual
environment (`anyio` and `httpx2` included). Do not install packages into Hermes
just to run this adapter. Recheck compatibility when its SDK changes.

Store the existing upstream URL, Authorization header and timeout in an
owner-only JSON file (mode 0600), **outside this repository**. Only the exact
official endpoint `https://public-api.finary.com/mcp` is accepted. TLS validation
is enabled; HTTP redirects and environment proxy settings are disabled. The
adapter does not print credentials, financial data, or raw exception messages.

Set only the affected profile's `mcp_servers.finary` to a stdio command:

```yaml
command: /usr/local/lib/hermes-agent/venv/bin/python
args:
  - /opt/finary-mcp-compat/finary_compat.py
  - --config
  - /root/.hermes/profiles/charles/finary-upstream.json
timeout: 60
```

Preserve any existing trust policy, tool filters and other unrelated options.
Back up the original Finary entry privately before changing it. To roll back,
restore **only that entry** and restart the affected gateway; leave other
profile settings and integrations alone. An upstream schema fix makes this
relay unnecessary: verify direct `initialize` + `tools/list`, then roll back.

## Verification

```sh
python3 -m unittest -v
```

Before activating, use an unmodified MCP `ClientSession` over stdio to initialize
the relay and list tools against Finary. Validate catalog loading without
printing account data. This proves discovery compatibility, not every possible
financial tool response. Configuration and all credentials stay off GitHub.
