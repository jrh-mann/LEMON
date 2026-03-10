"""Tests for auto-generated Anthropic tool schemas.

Verifies that every registered tool produces a valid Anthropic function-calling
schema, and that the generated schemas have the required structure.
"""

from __future__ import annotations

import pytest

from src.backend.tools.discovery import build_tool_registry
from src.backend.tools.schema_gen import generate_all_schemas

# Valid JSON Schema types for properties
VALID_JSON_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "object", "array"}


@pytest.fixture(scope="module")
def registry():
    """Build a ToolRegistry with all discovered tools."""
    return build_tool_registry(".")


@pytest.fixture(scope="module")
def schemas(registry):
    """Generate all Anthropic tool schemas from the registry."""
    return generate_all_schemas(registry)


def test_all_tools_have_schemas(registry, schemas):
    """Every tool in the registry should produce exactly one schema."""
    tool_names = {t.name for t in registry.all_tools()}
    schema_names = {s["function"]["name"] for s in schemas}
    assert tool_names == schema_names, (
        f"Mismatch between tools and schemas.\n"
        f"Missing schemas: {tool_names - schema_names}\n"
        f"Extra schemas: {schema_names - tool_names}"
    )


def test_schema_count(registry, schemas):
    """Sanity check: there should be a reasonable number of tools."""
    assert len(schemas) >= 15, f"Expected at least 15 tools, got {len(schemas)}"


def test_schema_has_required_fields(schemas):
    """Each schema must have the Anthropic function-calling structure."""
    for schema in schemas:
        name = schema.get("function", {}).get("name", "<unknown>")
        assert schema.get("type") == "function", f"{name}: missing type='function'"
        func = schema.get("function")
        assert func is not None, f"{name}: missing 'function' key"
        assert isinstance(func.get("name"), str) and func["name"], f"{name}: missing function name"
        assert isinstance(func.get("description"), str) and func["description"], f"{name}: empty description"
        params = func.get("parameters")
        assert isinstance(params, dict), f"{name}: parameters must be a dict"
        assert params.get("type") == "object", f"{name}: parameters.type must be 'object'"
        assert isinstance(params.get("properties"), dict), f"{name}: parameters.properties must be a dict"
        assert isinstance(params.get("required"), list), f"{name}: parameters.required must be a list"


def test_schema_parameter_types(schemas):
    """Top-level parameter types should be valid JSON Schema types, or type may be
    omitted for union-typed params (oneOf/anyOf) and untyped params (description-only,
    like add_node's 'output' which accepts any JSON value)."""
    for schema in schemas:
        name = schema["function"]["name"]
        properties = schema["function"]["parameters"]["properties"]
        for param_name, param_def in properties.items():
            # Properties with oneOf/anyOf don't need a top-level "type"
            if "oneOf" in param_def or "anyOf" in param_def:
                continue
            param_type = param_def.get("type")
            # A property can omit "type" if it's description-only (accepts any value)
            if param_type is None:
                assert "description" in param_def, (
                    f"{name}.{param_name}: no type and no description"
                )
                continue
            assert param_type in VALID_JSON_SCHEMA_TYPES, (
                f"{name}.{param_name}: invalid type '{param_type}'. "
                f"Valid: {VALID_JSON_SCHEMA_TYPES}"
            )


def test_required_params_exist_in_properties(schemas):
    """All params listed in 'required' must exist in 'properties'."""
    for schema in schemas:
        name = schema["function"]["name"]
        props = schema["function"]["parameters"]["properties"]
        required = schema["function"]["parameters"]["required"]
        for req in required:
            assert req in props, (
                f"{name}: required param '{req}' not found in properties"
            )


def test_individual_tool_to_anthropic_schema(registry):
    """Each tool's to_anthropic_schema() should produce valid output."""
    for tool in registry.all_tools():
        schema = tool.to_anthropic_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool.name
        assert schema["function"]["description"] == tool.description


def test_add_node_has_condition_schema(schemas):
    """add_node should have a condition property with oneOf for simple/compound."""
    add_node = next(s for s in schemas if s["function"]["name"] == "add_node")
    props = add_node["function"]["parameters"]["properties"]
    assert "condition" in props, "add_node missing 'condition' property"
    condition = props["condition"]
    assert "oneOf" in condition, "add_node.condition should have oneOf"
    assert len(condition["oneOf"]) == 2, "condition.oneOf should have 2 variants"


def test_add_node_has_calculation_schema(schemas):
    """add_node should have a calculation property with nested operator/operands."""
    add_node = next(s for s in schemas if s["function"]["name"] == "add_node")
    props = add_node["function"]["parameters"]["properties"]
    assert "calculation" in props, "add_node missing 'calculation' property"
    calc = props["calculation"]
    assert calc.get("type") == "object"
    calc_props = calc.get("properties", {})
    assert "operator" in calc_props, "calculation missing 'operator'"
    assert "operands" in calc_props, "calculation missing 'operands'"
    assert "output" in calc_props, "calculation missing 'output'"


def test_add_node_type_has_enum(schemas):
    """add_node's type parameter should have an enum."""
    add_node = next(s for s in schemas if s["function"]["name"] == "add_node")
    type_prop = add_node["function"]["parameters"]["properties"]["type"]
    assert "enum" in type_prop, "add_node.type should have enum"
    assert "decision" in type_prop["enum"]
    assert "subprocess" in type_prop["enum"]


def test_batch_edit_operations_has_items(schemas):
    """batch_edit_workflow's operations should have items schema."""
    batch = next(s for s in schemas if s["function"]["name"] == "batch_edit_workflow")
    ops = batch["function"]["parameters"]["properties"]["operations"]
    assert ops.get("type") == "array"
    assert "items" in ops, "operations should have items schema"
    assert ops["items"].get("type") == "object"


def test_create_subworkflow_output_type_has_enum(schemas):
    """create_subworkflow's output_type should have enum."""
    cs = next(s for s in schemas if s["function"]["name"] == "create_subworkflow")
    ot = cs["function"]["parameters"]["properties"]["output_type"]
    assert "enum" in ot, "create_subworkflow.output_type should have enum"
    assert set(ot["enum"]) == {"string", "number", "bool", "json"}


def test_list_workflows_has_limit_constraints(schemas):
    """list_workflows_in_library's limit parameter should have min/max."""
    lw = next(s for s in schemas if s["function"]["name"] == "list_workflows_in_library")
    limit = lw["function"]["parameters"]["properties"]["limit"]
    assert limit.get("minimum") == 1
    assert limit.get("maximum") == 100
