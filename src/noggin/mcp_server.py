"""Minimal stdio MCP server for Noggin tools."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO

from .brain import BrainService
from .errors import BrainError


TOOLS: list[dict[str, Any]] = [
    {
        "name": "brain_ingest",
        "description": "Store source activity in the local brain with provenance and extraction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "source": {"type": "string", "default": "agent"},
                "kind": {"type": "string", "default": "note"},
                "workspace": {"type": "string", "default": "default"},
                "actor": {"type": "string", "default": "unknown"},
                "source_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "brain_recall",
        "description": "Search the local brain and return evidence-backed observations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "workspace": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_reflect",
        "description": "Synthesize matching brain context into compact bullets with sources.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
                "workspace": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_skill_propose",
        "description": "Create a guarded skill proposal from a lesson or mistake.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "title": {"type": "string"},
                "target_path": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "brain_graph_sync",
        "description": "Materialize the Markdown knowledge graph from Noggin memory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "brain_graph_list",
        "description": "List Markdown knowledge graph nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 500}},
        },
    },
    {
        "name": "brain_graph_show",
        "description": "Show one Markdown knowledge graph node by entity name.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


@dataclass
class McpServer:
    brain: BrainService
    stdin: BinaryIO = sys.stdin.buffer
    stdout: BinaryIO = sys.stdout.buffer

    def run_forever(self) -> None:
        """Read MCP messages until EOF."""

        while True:
            message = _read_message(self.stdin)
            if message is None:
                break
            response = self.handle(message)
            if response is not None:
                _write_message(self.stdout, response)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        try:
            if method == "initialize":
                return _result(
                    request_id,
                    {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "noggin", "version": "0.1.0"},
                    },
                )
            if method == "notifications/initialized":
                return None
            if method == "tools/list":
                return _result(request_id, {"tools": TOOLS})
            if method == "tools/call":
                params = message.get("params") or {}
                return _result(request_id, self._call_tool(params))
            if method == "resources/list":
                return _result(
                    request_id,
                    {
                        "resources": [
                            {
                                "uri": "brain://stats",
                                "name": "Noggin Stats",
                                "mimeType": "application/json",
                            },
                            {
                                "uri": "brain://events/recent",
                                "name": "Recent Noggin Events",
                                "mimeType": "application/json",
                            },
                            {
                                "uri": "brain://graph/nodes",
                                "name": "Noggin Markdown Graph Nodes",
                                "mimeType": "application/json",
                            },
                        ]
                    },
                )
            if method == "resources/read":
                uri = (message.get("params") or {}).get("uri")
                return _result(request_id, {"contents": [_resource_content(self.brain, uri)]})
            return _error(request_id, -32601, f"unknown method: {method}")
        except BrainError as exc:
            return _error(request_id, -32000, f"{exc.__class__.__name__}: {exc}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "brain_ingest":
            result = self.brain.ingest(
                args["content"],
                source=args.get("source", "agent"),
                kind=args.get("kind", "note"),
                workspace=args.get("workspace", "default"),
                actor=args.get("actor", "unknown"),
                source_id=args.get("source_id"),
                idempotency_key=args.get("idempotency_key"),
                metadata=args.get("metadata") or {},
            )
        elif name == "brain_recall":
            result = {
                "results": self.brain.recall(
                    args["query"],
                    limit=int(args.get("limit", 10)),
                    workspace=args.get("workspace"),
                )
            }
        elif name == "brain_reflect":
            result = self.brain.reflect(
                args["query"],
                limit=int(args.get("limit", 8)),
                workspace=args.get("workspace"),
            )
        elif name == "brain_skill_propose":
            result = {
                "proposal": self.brain.propose_skill(
                    args["content"],
                    title=args.get("title"),
                    target_path=args.get("target_path"),
                    reason=args.get("reason"),
                )
            }
        elif name == "brain_graph_sync":
            result = self.brain.sync_graph()
        elif name == "brain_graph_list":
            result = {"nodes": self.brain.list_graph_nodes(limit=int(args.get("limit", 500)))}
        elif name == "brain_graph_show":
            result = {"node": self.brain.graph_node(args["name"])}
        else:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"unknown tool: {name}"}],
            }
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


def run_mcp(db_path: str | None = None) -> None:
    McpServer(BrainService(db_path=db_path)).run_forever()


def _resource_content(brain: BrainService, uri: str) -> dict[str, Any]:
    if uri == "brain://stats":
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(brain.stats(), indent=2),
        }
    if uri == "brain://events/recent":
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(brain.store.recent_events(limit=25), indent=2),
        }
    if uri == "brain://graph/nodes":
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(brain.list_graph_nodes(limit=500), indent=2),
        }
    return {"uri": uri, "mimeType": "text/plain", "text": "Unknown brain resource."}


def _read_message(stream: BinaryIO) -> dict[str, Any] | None:
    first = stream.readline()
    if not first:
        return None
    if first.lower().startswith(b"content-length:"):
        length = int(first.split(b":", 1)[1].strip())
        while True:
            line = stream.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        body = stream.read(length)
        return json.loads(body.decode("utf-8"))
    return json.loads(first.decode("utf-8"))


def _write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
