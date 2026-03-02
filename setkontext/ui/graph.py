"""Entity relationship graph builder for Graphviz visualization.

Generates DOT format graphs from entity relationship data.
Pure function with no Streamlit dependency — suitable for testing.
"""

from __future__ import annotations


# Entity type → color mapping
ENTITY_COLORS = {
    "technology": "#3B82F6",   # blue
    "pattern": "#10B981",      # green
    "service": "#F59E0B",      # orange
    "library": "#8B5CF6",      # purple
}

# Relationship type → edge style
EDGE_STYLES = {
    "uses": "solid",
    "depends_on": "solid",
    "replaces": "dashed",
    "conflicts_with": "dotted",
    "related_to": "dotted",
}

EDGE_COLORS = {
    "uses": "#6B7280",
    "depends_on": "#3B82F6",
    "replaces": "#EF4444",
    "conflicts_with": "#EF4444",
    "related_to": "#9CA3AF",
}


def build_entity_dot_graph(
    graph_data: dict, highlight: str | None = None
) -> str:
    """Build a DOT format graph string from entity graph data.

    Args:
        graph_data: Dict with 'nodes' and 'edges' from Repository.get_entity_graph().
        highlight: Optional entity name to highlight with its neighborhood.

    Returns:
        DOT format string for graphviz rendering.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return 'digraph { label="No entities found" }'

    # If highlighting, filter to neighborhood
    if highlight:
        highlight_lower = highlight.lower()
        neighbor_entities = {highlight_lower}
        for edge in edges:
            if edge["from_entity"].lower() == highlight_lower:
                neighbor_entities.add(edge["to_entity"].lower())
            elif edge["to_entity"].lower() == highlight_lower:
                neighbor_entities.add(edge["from_entity"].lower())

        # 2-hop: also include neighbors of neighbors
        first_hop = set(neighbor_entities)
        for edge in edges:
            if edge["from_entity"].lower() in first_hop:
                neighbor_entities.add(edge["to_entity"].lower())
            elif edge["to_entity"].lower() in first_hop:
                neighbor_entities.add(edge["from_entity"].lower())

        nodes = [n for n in nodes if n["entity"].lower() in neighbor_entities]
        edges = [
            e for e in edges
            if e["from_entity"].lower() in neighbor_entities
            and e["to_entity"].lower() in neighbor_entities
        ]

    lines = [
        "digraph {",
        '  graph [layout=fdp, bgcolor="transparent", pad=0.5]',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10]',
        '  edge [fontname="Helvetica", fontsize=8]',
        "",
    ]

    # Build node ID mapping (sanitize names for DOT)
    node_ids: dict[str, str] = {}
    for i, node in enumerate(nodes):
        node_id = f"n{i}"
        node_ids[node["entity"].lower()] = node_id

        color = ENTITY_COLORS.get(node.get("entity_type", ""), "#9CA3AF")
        count = node.get("decision_count", 0) + node.get("learning_count", 0)

        # Scale width based on count
        width = max(1.0, min(2.5, 0.8 + count * 0.2))

        # Highlight the selected entity
        penwidth = "3" if highlight and node["entity"].lower() == highlight.lower() else "1"

        label = node["entity"]
        if count > 0:
            label += f"\\n({count})"

        lines.append(
            f'  {node_id} [label="{label}", fillcolor="{color}20", '
            f'color="{color}", penwidth={penwidth}, width={width}]'
        )

    lines.append("")

    # Build edges
    for edge in edges:
        from_id = node_ids.get(edge["from_entity"].lower())
        to_id = node_ids.get(edge["to_entity"].lower())
        if not from_id or not to_id:
            continue

        rel = edge.get("relationship", "related_to")
        style = EDGE_STYLES.get(rel, "dotted")
        color = EDGE_COLORS.get(rel, "#9CA3AF")

        lines.append(
            f'  {from_id} -> {to_id} [label="{rel}", style={style}, color="{color}"]'
        )

    lines.append("}")
    return "\n".join(lines)
