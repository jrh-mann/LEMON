"""Helpers for workflow variable tools.

This module provides utilities for managing workflow variables in the unified
variable system. All variables (user inputs, subprocess outputs, calculated
values) are stored in a single 'variables' list with a 'source' field.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Valid variable source types
VALID_SOURCES = {"input", "subprocess", "calculated", "constant"}

# Valid internal types for variables
# Note: 'number' is the unified numeric type (stored as float internally)
# 'int' and 'float' are deprecated but kept for backwards compatibility
VALID_TYPES = {"number", "int", "float", "bool", "string", "enum", "date"}


def ensure_workflow_analysis(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure workflow_analysis exists with the unified variable structure.
    
    The new structure uses 'variables' instead of 'inputs'. Each variable has
    a 'source' field indicating its origin (input, subprocess, calculated, constant).
    
    Args:
        session_state: The session state dict to ensure has workflow_analysis
        
    Returns:
        The workflow_analysis dict with guaranteed 'variables' and 'outputs' keys
    """
    if "workflow_analysis" not in session_state:
        session_state["workflow_analysis"] = {"variables": [], "outputs": []}
    
    workflow_analysis = session_state["workflow_analysis"]
    
    # Ensure 'variables' key exists (replaces old 'inputs')
    if "variables" not in workflow_analysis:
        workflow_analysis["variables"] = []
    
    # Migrate legacy 'inputs' to 'variables' if present
    if "inputs" in workflow_analysis and workflow_analysis["inputs"]:
        for inp in workflow_analysis["inputs"]:
            # Add source='input' if migrating from old format
            if "source" not in inp:
                inp["source"] = "input"
            workflow_analysis["variables"].append(inp)
        workflow_analysis["inputs"] = []  # Clear legacy field
    
    if "outputs" not in workflow_analysis:
        workflow_analysis["outputs"] = []
    
    return workflow_analysis


def normalize_variable_name(name: str) -> str:
    """Normalize a variable name for case-insensitive comparison.
    
    Args:
        name: The variable name to normalize
        
    Returns:
        Lowercase, trimmed version of the name
    """
    return name.strip().lower()


# Alias for backwards compatibility
normalize_input_name = normalize_variable_name


def get_variables_by_source(
    workflow_analysis: Dict[str, Any],
    source: str
) -> List[Dict[str, Any]]:
    """Get all variables with a specific source type.
    
    Args:
        workflow_analysis: The workflow analysis dict
        source: The source type to filter by ('input', 'subprocess', 'calculated', 'constant')
        
    Returns:
        List of variables with the specified source
    """
    variables = workflow_analysis.get("variables", [])
    return [v for v in variables if v.get("source") == source]


def get_input_variables(workflow_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get all user-input variables (source='input').
    
    These are the variables that users provide values for at execution time.
    
    Args:
        workflow_analysis: The workflow analysis dict
        
    Returns:
        List of input variables
    """
    return get_variables_by_source(workflow_analysis, "input")


def get_derived_variables(workflow_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get all derived variables (subprocess, calculated, constant).
    
    These are variables whose values are computed during workflow execution.
    
    Args:
        workflow_analysis: The workflow analysis dict
        
    Returns:
        List of derived variables (non-input sources)
    """
    variables = workflow_analysis.get("variables", [])
    return [v for v in variables if v.get("source") != "input"]


def find_variable_by_name(
    workflow_analysis: Dict[str, Any],
    name: str
) -> Optional[Dict[str, Any]]:
    """Find a variable by name (case-insensitive).
    
    Args:
        workflow_analysis: The workflow analysis dict
        name: The variable name to find
        
    Returns:
        The variable dict if found, None otherwise
    """
    normalized = normalize_variable_name(name)
    for var in workflow_analysis.get("variables", []):
        if normalize_variable_name(var.get("name", "")) == normalized:
            return var
    return None


def find_variable_by_id(
    workflow_analysis: Dict[str, Any],
    var_id: str
) -> Optional[Dict[str, Any]]:
    """Find a variable by ID.
    
    Args:
        workflow_analysis: The workflow analysis dict
        var_id: The variable ID to find
        
    Returns:
        The variable dict if found, None otherwise
    """
    for var in workflow_analysis.get("variables", []):
        if var.get("id") == var_id:
            return var
    return None
