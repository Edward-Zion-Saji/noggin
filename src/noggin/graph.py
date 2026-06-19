"""Markdown knowledge graph materialization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import GraphWriteError
from .models import Observation, content_hash
from .observability import log_event, utc_now
from .paths import default_graph_dir
from .store import BrainStore


class KnowledgeGraphWriter:
    """Write one Markdown file per graph node.

    The graph strategy is:

    Source event
      -> Noggin Workers produce observations as subject/predicate/object triples
      -> SQLite stores observations, entities, and edges with provenance
      -> this writer materializes each entity as `nodes/<slug>.md`
      -> node files link to each other with wiki links
    """

    def __init__(self, store: BrainStore, graph_dir: str | Path | None = None):
        self.store = store
        self.graph_dir = Path(graph_dir).expanduser() if graph_dir else default_graph_dir(store.db_path)
        self.nodes_dir = self.graph_dir / "nodes"

    def sync_observations(self, observations: list[Observation]) -> dict[str, Any]:
        """Sync nodes touched by observations."""

        names: list[str] = []
        for observation in observations:
            names.append(observation.subject)
            if observation.object:
                names.append(observation.object)
        return self.sync_nodes(names)

    def sync_all(self) -> dict[str, Any]:
        """Rewrite the full Markdown graph from store state."""

        entities = self.store.list_entities(limit=100_000)
        return self.sync_nodes([entity["name"] for entity in entities], write_index=True)

    def sync_nodes(self, names: list[str], *, write_index: bool = True) -> dict[str, Any]:
        """Rewrite selected node files."""

        unique_names = _dedupe_names(names)
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        written: list[dict[str, str]] = []
        try:
            for name in unique_names:
                graph = self.store.entity_graph(name)
                if not graph:
                    continue
                path = self.node_path(name)
                path.write_text(self.render_node(graph), encoding="utf-8")
                written.append({"name": name, "path": str(path)})
            if write_index:
                self.write_index()
        except OSError as exc:
            raise GraphWriteError(f"failed to write markdown knowledge graph: {exc}") from exc
        log_event("brain.graph.synced", graph_dir=str(self.graph_dir), nodes=len(written))
        return {"graph_dir": str(self.graph_dir), "nodes_written": len(written), "nodes": written}

    def list_nodes(self, *, limit: int = 500) -> list[dict[str, str]]:
        """Return known graph nodes with their Markdown file paths."""

        rows = self.store.list_entities(limit=limit)
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "path": str(self.node_path(row["name"])),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def node(self, name: str) -> dict[str, Any] | None:
        """Return graph metadata for one node."""

        graph = self.store.entity_graph(name)
        if not graph:
            return None
        return {"path": str(self.node_path(name)), **graph}

    def node_path(self, name: str) -> Path:
        """Return the node markdown path for an entity name."""

        return self.nodes_dir / f"{node_slug(name)}.md"

    def render_node(self, graph: dict[str, Any]) -> str:
        """Render one entity graph as Markdown."""

        entity = graph["entity"]
        name = entity["name"]
        lines = [
            "---",
            f"id: {entity['id']}",
            f"name: {yaml_string(name)}",
            f"type: {yaml_string(entity['type'])}",
            f"updated_at: {yaml_string(utc_now())}",
            "---",
            "",
            f"# {name}",
            "",
            "## Strategy",
            "",
            (
                "This node is arranged by Noggin Workers from source-grounded "
                "observations. SQLite stores the event log and edges; this file "
                "materializes the current graph view."
            ),
            "",
            "## Observations",
            "",
        ]
        if graph["observations"]:
            for observation in graph["observations"]:
                lines.extend(
                    [
                        (
                            f"- **{observation['kind']}** "
                            f"({observation['confidence']:.2f}): {observation['content']}"
                        ),
                        (
                            f"  - Evidence: `{observation['event_id']}` from "
                            f"`{observation['source']}` by `{observation['actor']}` "
                            f"in `{observation['workspace']}`."
                        ),
                    ]
                )
        else:
            lines.append("- No direct observations yet.")
        lines.extend(["", "## Outgoing Links", ""])
        lines.extend(_edge_lines(graph["outgoing"], direction="outgoing") or ["- None."])
        lines.extend(["", "## Incoming Links", ""])
        lines.extend(_edge_lines(graph["incoming"], direction="incoming") or ["- None."])
        lines.extend(["", "## Provenance", ""])
        event_ids = sorted({item["event_id"] for item in graph["observations"]})
        if event_ids:
            lines.extend(f"- `{event_id}`" for event_id in event_ids)
        else:
            lines.append("- No events recorded.")
        lines.append("")
        return "\n".join(lines)

    def write_index(self) -> Path:
        """Write graph index with links to every node."""

        self.graph_dir.mkdir(parents=True, exist_ok=True)
        rows = self.list_nodes(limit=100_000)
        lines = [
            "---",
            "name: Noggin Knowledge Graph",
            f"updated_at: {yaml_string(utc_now())}",
            "---",
            "",
            "# Noggin Knowledge Graph",
            "",
            "Each entity node is a Markdown file generated from Noggin Workers' graph triples.",
            "",
            "## Nodes",
            "",
        ]
        if rows:
            for row in rows:
                lines.append(f"- [[nodes/{node_slug(row['name'])}|{row['name']}]]")
        else:
            lines.append("- No nodes yet.")
        lines.append("")
        path = self.graph_dir / "index.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def node_slug(name: str) -> str:
    """Return a filesystem-safe stable node slug."""

    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    stem = cleaned[:72].strip("-") or "node"
    return f"{stem}-{content_hash(name)[:8]}"


def yaml_string(value: object) -> str:
    """Return a conservative quoted YAML scalar."""

    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _dedupe_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = " ".join(str(name or "").split()).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _edge_lines(edges: list[dict[str, Any]], *, direction: str) -> list[str]:
    lines: list[str] = []
    for edge in edges:
        linked = edge["to_entity"] if direction == "outgoing" else edge["from_entity"]
        relation = edge["relation"]
        lines.append(
            f"- [[{node_slug(linked)}|{linked}]] - `{relation}` "
            f"({edge['confidence']:.2f}, evidence `{edge['evidence_event_id']}`)"
        )
    return lines
