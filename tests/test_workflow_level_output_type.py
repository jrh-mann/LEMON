import pytest
from src.backend.execution.interpreter import TreeInterpreter

class TestWorkflowLevelOutputType:
    """Test workflow-level output_type support in interpreter"""

    def test_output_type_number(self):
        """Test that output_type="number" returns a float"""
        tree = {
            "start": {
                "id": "start",
                "type": "start",
                "children": [{
                    "id": "end",
                    "type": "end",
                    "output_value": "42"
                }]
            }
        }
        
        # This will fail until we add output_type param to __init__
        interpreter = TreeInterpreter(
            tree=tree,
            inputs=[],
            outputs=[],
            output_type="number"
        )
        result = interpreter.execute({})
        
        assert result.success is True
        assert result.output == 42.0
        assert isinstance(result.output, float)

    def test_output_type_bool(self):
        """Test that output_type="bool" returns a boolean"""
        tree = {
            "start": {
                "id": "start",
                "type": "start",
                "children": [{
                    "id": "end",
                    "type": "end",
                    "output_value": "true"
                }]
            }
        }
        
        interpreter = TreeInterpreter(
            tree=tree,
            inputs=[],
            outputs=[],
            output_type="bool"
        )
        result = interpreter.execute({})
        
        assert result.success is True
        assert result.output is True
        assert isinstance(result.output, bool)

    def test_output_type_string_default(self):
        """Test that default output_type is "string" and returns string"""
        tree = {
            "start": {
                "id": "start",
                "type": "start",
                "children": [{
                    "id": "end",
                    "type": "end",
                    "output_value": 42
                }]
            }
        }
        
        # No output_type specified -> defaults to string
        interpreter = TreeInterpreter(
            tree=tree,
            inputs=[],
            outputs=[]
        )
        result = interpreter.execute({})
        
        assert result.success is True
        assert result.output == "42"
        assert isinstance(result.output, str)

    def test_output_type_override_node_output_type(self):
        """Test that workflow output_type overrides node-level output_type (if present)"""
        # Node has 'output_type': 'string' but workflow has 'number'
        tree = {
            "start": {
                "id": "start",
                "type": "start",
                "children": [{
                    "id": "end",
                    "type": "end",
                    "output_value": "123",
                    "output_type": "string"  # Should be ignored
                }]
            }
        }
        
        interpreter = TreeInterpreter(
            tree=tree,
            inputs=[],
            outputs=[],
            output_type="number"
        )
        result = interpreter.execute({})
        
        assert result.success is True
        assert result.output == 123.0
        assert isinstance(result.output, float)
