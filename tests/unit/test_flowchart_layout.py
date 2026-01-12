from src.lemon.flowchart.layout import count_edge_crossings, layout_flowchart
from src.lemon.flowchart.model import Flowchart


def test_count_edge_crossings_detects_intersection():
    flowchart = Flowchart.from_dict(
        {
            "nodes": [
                {"id": "a", "type": "start", "label": "A", "x": 0, "y": 0},
                {"id": "b", "type": "process", "label": "B", "x": 10, "y": 0},
                {"id": "c", "type": "process", "label": "C", "x": 0, "y": 10},
                {"id": "d", "type": "end", "label": "D", "x": 10, "y": 10},
            ],
            "edges": [
                {"from": "a", "to": "d"},
                {"from": "b", "to": "c"},
            ],
        }
    )

    assert count_edge_crossings(flowchart) == 1


def test_layout_flowchart_assigns_positions():
    flowchart = Flowchart.from_dict(
        {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start"},
                {"id": "step", "type": "process", "label": "Step"},
                {"id": "end", "type": "end", "label": "End"},
            ],
            "edges": [
                {"from": "start", "to": "step"},
                {"from": "step", "to": "end"},
            ],
        }
    )

    layout_flowchart(flowchart)
    for node in flowchart.nodes:
        assert node.x is not None
        assert node.y is not None
