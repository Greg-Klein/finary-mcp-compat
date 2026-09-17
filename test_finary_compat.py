import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from finary_compat import ENDPOINT, RelayState, load_config, normalize_tools


def catalog():
    return {"tools": [{"name": name, "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object"},
        "outputSchema": {"oneOf": [
            {"type": "object", "properties": {"amount": {"$ref": "#/$defs/Money"}}},
            {"type": "object", "properties": {"availability": {"const": "requires_paid_plan"}}}
        ], "$defs": {"Money": {"type": "string"}}}}
        for name in ("get_budget_overview", "search_spending", "other_tool")],
        "nextCursor": "next-page"}


class CompatibilityTests(unittest.TestCase):
    def test_only_redundant_root_constraints_added(self):
        original = catalog()
        before = copy.deepcopy(original)
        patched = normalize_tools(original)
        self.assertEqual(original, before)
        for tool in patched["tools"][:2]:
            self.assertEqual(tool["outputSchema"].pop("type"), "object")
        self.assertEqual(patched, before)

    def test_unknown_or_nonobject_shapes_unchanged(self):
        for schema in ({}, {"oneOf": []}, {"oneOf": [{"type": "string"}]},
                       {"oneOf": [{"type": "object"}, {"type": "null"}]},
                       {"oneOf": [{"$ref": "#/$defs/Unknown"}]},
                       {"type": "array"}, {"type": "object"}, None, True):
            value = {"tools": [{"name": "search_spending", "outputSchema": schema}]}
            self.assertEqual(normalize_tools(value), value)

    def test_idempotent(self):
        value = normalize_tools(catalog())
        self.assertEqual(normalize_tools(value), value)

    def initialized(self, protocol="2025-11-25"):
        state = RelayState()
        state.sent({"id": 0, "method": "initialize"})
        state.received({"id": 0, "result": {"protocolVersion": protocol}})
        return state

    def test_correlated_paginated_tools_only(self):
        state = self.initialized()
        state.sent({"id": 1, "method": "tools/list"})
        state.sent({"id": "1", "method": "tools/call"})
        call = {"id": "1", "result": {"structuredContent": {"amount": "123456789.123456"}}}
        self.assertIs(state.received(call), call)
        response = state.received({"id": 1, "result": catalog()})
        self.assertEqual(response["result"], normalize_tools(catalog()))
        self.assertEqual(state.pending, {})

    def test_modern_uninitialized_errors_and_notifications_unchanged(self):
        for state in (RelayState(), self.initialized("2026-07-28")):
            state.sent({"id": 1, "method": "tools/list"})
            response = {"id": 1, "result": catalog()}
            self.assertIs(state.received(response), response)
        state = self.initialized()
        state.sent({"id": 2, "method": "tools/list"})
        error = {"id": 2, "error": {"code": -32603, "message": "upstream error"}}
        self.assertIs(state.received(error), error)
        self.assertEqual(state.pending, {})
        notification = {"method": "notifications/tools/list_changed"}
        self.assertIs(state.received(notification), notification)
        server_request = {"id": 9, "method": "ping"}
        self.assertIs(state.received(server_request), server_request)

    def test_config_permissions_endpoint_and_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upstream.json"
            valid = {"url": ENDPOINT, "headers": {"Authorization": "Bearer TEST"}}
            path.write_text(json.dumps(valid))
            os.chmod(path, 0o600)
            self.assertEqual(load_config(path), valid)
            os.chmod(path, 0o644)
            with self.assertRaises(ValueError):
                load_config(path)
            os.chmod(path, 0o600)
            for change in ({"url": "https://example.com/mcp"},
                           {"headers": {"Host": "example.com"}}, {"timeout": -1}):
                path.write_text(json.dumps({**valid, **change}))
                with self.assertRaises(ValueError):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
