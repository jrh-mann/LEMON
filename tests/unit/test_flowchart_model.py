from src.lemon.flowchart.model import Flowchart


def test_flowchart_from_dict_normalizes_nodes_and_edges():
    data = {
        "nodes": [
            {"id": "n1", "type": "unknown", "label": "Alpha", "color": "bad"},
            {"id": "n1", "label": "Beta"},
        ],
        "edges": [
            {"from": "n1", "to": "n1_1", "label": "Yes"},
            {"from": "missing", "to": "n1"},
        ],
    }

    flowchart = Flowchart.from_dict(data)
    assert len(flowchart.nodes) == 2
    assert flowchart.nodes[0].id == "n1"
    assert flowchart.nodes[1].id != "n1"
    assert flowchart.nodes[0].type == "process"
    assert flowchart.nodes[0].color == "teal"
    assert len(flowchart.edges) == 1
