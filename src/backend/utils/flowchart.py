"""Flowchart conversion helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def _map_node_type(raw_type: str) -> str:
    mapped = {
        "action": "process",
    }
    return mapped.get(raw_type, raw_type)


def flowchart_from_tree(tree: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    if not tree:
        return {"nodes": [], "edges": []}

    start = tree.get("start")
    if not isinstance(start, dict):
        return {"nodes": [], "edges": []}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen = set()
    stack = [start]

    while stack:
        node = stack.pop()
        node_id = node.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)

        raw_type = str(node.get("type") or "process")
        node_type = _map_node_type(raw_type)
        node_entry = {
            "id": node_id,
            "type": node_type,
            "label": node.get("label") or node_id,
            # Top-left coordinates; frontend auto-layout will adjust.
            "x": 0,
            "y": 0,
        }
        input_ids = node.get("input_ids")
        if isinstance(input_ids, list):
            node_entry["input_ids"] = input_ids
        nodes.append(node_entry)

        for child in node.get("children") or []:
            child_id = child.get("id")
            if not child_id:
                continue
            edges.append(
                {
                    "id": f"{node_id}->{child_id}",
                    "from": node_id,
                    "to": child_id,
                    "label": child.get("edge_label") or "",
                }
            )
            stack.append(child)

    return {"nodes": nodes, "edges": edges}


def tree_from_flowchart(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a nested tree structure from flat nodes and edges lists.
    
    This is the inverse of flowchart_from_tree. Takes a flat list of nodes
    and edges (as used in the frontend) and builds the nested tree structure
    needed by TreeInterpreter.
    
    Args:
        nodes: List of node dicts with id, type, label, etc.
        edges: List of edge dicts with from/source, to/target, label
        
    Returns:
        Tree dict with "start" key containing the nested structure.
        Returns empty dict if no start node found.
        
    Example:
        >>> nodes = [
        ...     {"id": "start", "type": "start", "label": "Start"},
        ...     {"id": "out", "type": "output", "label": "Done"},
        ... ]
        >>> edges = [{"from": "start", "to": "out", "label": ""}]
        >>> tree = tree_from_flowchart(nodes, edges)
        >>> tree["start"]["children"][0]["id"]
        'out'
    """
    if not nodes:
        return {}
    
    # Build node lookup by ID
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        # Copy node data and initialize children list
        node_map[node_id] = {
            "id": node_id,
            "type": node.get("type", "process"),
            "label": node.get("label", node_id),
            "children": [],
        }
# Preserve additional fields
        # NOTE: condition is critical for decision nodes - must be preserved
        # NOTE: calculation is critical for calculation nodes - must be preserved
        for key in ("input_ids", "subworkflow_id", "input_mapping", "output_variable",
                    "output_type", "output_value", "output_template", "condition", "calculation"):
            if key in node:
                node_map[node_id][key] = node[key]
    
    # Build adjacency: parent -> [(child_id, edge_label), ...]
    adjacency: Dict[str, List[tuple]] = {node_id: [] for node_id in node_map}
    for edge in edges:
        # Support both "from"/"to" and "source"/"target" formats
        source = edge.get("from") or edge.get("source")
        target = edge.get("to") or edge.get("target")
        label = edge.get("label", "")
        
        if source in adjacency and target in node_map:
            adjacency[source].append((target, label))
    
    # Build tree by assigning children with edge labels
    for parent_id, children_info in adjacency.items():
        parent_node = node_map[parent_id]
        for child_id, edge_label in children_info:
            child_node = node_map[child_id].copy()
            # Always set edge_label, even if empty (helps debugging branch selection issues)
            child_node["edge_label"] = edge_label if edge_label else ""
            parent_node["children"].append(child_node)
    
    # Find start node
    start_node = None
    for node in nodes:
        if node.get("type") == "start":
            start_node = node_map.get(node.get("id"))
            break
    
    # If no explicit start node, find node with no incoming edges
    if not start_node:
        nodes_with_incoming = set()
        for edge in edges:
            target = edge.get("to") or edge.get("target")
            if target:
                nodes_with_incoming.add(target)
        
        for node_id, node_data in node_map.items():
            if node_id not in nodes_with_incoming:
                start_node = node_data
                break
    
    if not start_node:
        return {}
    
    return {"start": start_node}
