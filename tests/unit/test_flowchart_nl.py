from src.lemon.flowchart.nl import (
    parse_clarify_response,
    parse_flowchart_json,
    flowchart_from_steps,
    simple_clarification_questions,
)


def test_parse_clarify_response_questions():
    text = '{"status":"clarify","questions":["What happens on no?"]}'
    result = parse_clarify_response(text)
    assert result.status == "clarify"
    assert result.questions == ["What happens on no?"]


def test_parse_flowchart_json():
    text = '{"nodes":[{"id":"n1","type":"start","label":"Start"}],"edges":[]}'
    result = parse_flowchart_json(text)
    assert len(result.nodes) == 1


def test_flowchart_from_steps_creates_edges():
    flowchart = flowchart_from_steps("Start -> Do work -> End")
    assert len(flowchart.nodes) == 3
    assert len(flowchart.edges) == 2


def test_simple_clarification_questions_adds_missing_branches():
    questions = simple_clarification_questions("If age > 65, refer to cardiology.")
    assert questions


def test_parse_clarify_response_list_payload():
    text = '["What happens on no?", "Any special case?"]'
    result = parse_clarify_response(text)
    assert result.status == "clarify"
    assert result.questions == ["What happens on no?", "Any special case?"]


def test_parse_flowchart_json_fenced_payload():
    text = "```json\n{\"nodes\": [{\"id\": \"n1\", \"type\": \"start\", \"label\": \"Start\"}], \"edges\": []}\n```"
    result = parse_flowchart_json(text)
    assert len(result.nodes) == 1
