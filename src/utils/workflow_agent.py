"""Workflow analysis agent for reading and analyzing workflow diagrams."""

import os
import sys
from pathlib import Path
from .request_utils import make_request, image_to_base64
from PIL import Image

# Import prompts from the configuration file
# Add project root to path to import workflow_prompts
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from workflow_prompts import (
        SYSTEM_PROMPT as WORKFLOW_ANALYSIS_SYSTEM_PROMPT,
        SINGLE_ANALYSIS_PROMPT,
        MAX_TOKENS as DEFAULT_MAX_TOKENS,
    )
except ImportError:
    # Fallback to defaults if prompts file doesn't exist
    WORKFLOW_ANALYSIS_SYSTEM_PROMPT = """You are an expert workflow analysis assistant."""
    SINGLE_ANALYSIS_PROMPT = "Analyze this workflow and output JSON."
    DEFAULT_MAX_TOKENS = 4096


class WorkflowAgent:
    """Agent for analyzing workflow diagrams with structured reasoning and task execution."""
    
    def __init__(self, system_prompt=None, max_tokens=None):
        """Initialize the workflow agent.
        
        Args:
            system_prompt (str, optional): Custom system prompt. If None, uses prompt from workflow_prompts.py.
            max_tokens (int, optional): Maximum tokens for responses. If None, uses MAX_TOKENS from workflow_prompts.py.
        """
        self.system_prompt = system_prompt or WORKFLOW_ANALYSIS_SYSTEM_PROMPT
        self.max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        self.conversation_history = []
    
    def _load_image(self, image_path):
        """Load and prepare image for API request.
        
        Args:
            image_path (str): Path to image file
            
        Returns:
            tuple: (base64_image, media_type, format)
        """
        img = Image.open(image_path)
        
        # Determine format and media type
        format_map = {
            'JPEG': ('image/jpeg', 'JPEG'),
            'JPG': ('image/jpeg', 'JPEG'),
            'PNG': ('image/png', 'PNG'),
            'WEBP': ('image/webp', 'WEBP'),
            'GIF': ('image/gif', 'GIF'),
        }
        
        img_format = img.format or 'PNG'
        media_type, format_str = format_map.get(img_format.upper(), ('image/png', 'PNG'))
        
        img_base64 = image_to_base64(img, format=format_str)
        return img_base64, media_type
    
    def _create_image_message(self, image_path, text_prompt):
        """Create a message with image and text content.
        
        Args:
            image_path (str): Path to image file
            text_prompt (str): Text prompt/question
            
        Returns:
            dict: Message dictionary
        """
        img_base64, media_type = self._load_image(image_path)
        
        return {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_base64
                    }
                },
                {
                    "type": "text",
                    "text": text_prompt
                }
            ]
        }
    
    def analyze_workflow(self, image_path, analysis_prompt=None):
        """Perform comprehensive workflow analysis and return structured JSON.
        
        This is a single-step analysis that:
        - Performs deep reasoning about the entire workflow
        - Identifies all inputs with their types, formats, and possible values
        - Identifies all decision points and outputs
        - Returns structured JSON that can be parsed to generate test cases
        
        Args:
            image_path (str): Path to workflow image
            analysis_prompt (str, optional): Custom analysis prompt. If None, uses SINGLE_ANALYSIS_PROMPT from workflow_prompts.py.
            
        Returns:
            str: JSON string containing structured workflow analysis
        """
        if analysis_prompt is None:
            analysis_prompt = SINGLE_ANALYSIS_PROMPT

        message = self._create_image_message(image_path, analysis_prompt)
        self.conversation_history.append(message)
        
        response = make_request(
            messages=self.conversation_history,
            max_tokens=self.max_tokens,
            system=self.system_prompt
        )
        
        response_text = response.content[0].text if response.content else ""
        
        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": response_text
        })
        
        return response_text
    
    def analyze_workflow_structured(self, image_path):
        """Perform workflow analysis and return parsed JSON as a dictionary.
        
        Args:
            image_path (str): Path to workflow image
            
        Returns:
            dict: Parsed JSON dictionary containing workflow analysis
        """
        import json
        import re
        
        json_text = self.analyze_workflow(image_path)
        
        # Try to extract JSON from the response (in case there's extra text)
        # Look for JSON object between { and }
        json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
        if json_match:
            json_text = json_match.group(0)
        
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            # If parsing fails, return the raw text with error info
            return {
                "error": "Failed to parse JSON",
                "error_message": str(e),
                "raw_response": json_text
            }
    
    def extract_and_save_inputs(self, workflow_data, output_file="workflow_inputs.json"):
        """Extract inputs from workflow analysis and save in standardized format.
        
        Args:
            workflow_data (dict): Full workflow analysis data
            output_file (str): Path to save the standardized inputs JSON
            
        Returns:
            list: List of standardized input dictionaries
        """
        import json
        from pathlib import Path
        
        if "error" in workflow_data:
            print(f"Warning: Cannot extract inputs from workflow data with error: {workflow_data.get('error_message')}")
            return []
        
        standardized_inputs = []
        inputs = workflow_data.get("inputs", [])
        
        for inp in inputs:
            # Extract and standardize the input
            standardized = {
                "input_name": inp.get("name", ""),
                "input_type": self._normalize_type(inp.get("type", "unknown"), inp.get("format", "")),
                "range": self._extract_range(inp.get("possible_values", {}), inp.get("constraints", "")),
                "description": inp.get("description", "")
            }
            standardized_inputs.append(standardized)
        
        # Save to JSON file
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(standardized_inputs, f, indent=2)
        
        print(f"\n✅ Standardized inputs saved to: {output_path}")
        
        return standardized_inputs
    
    def extract_and_save_outputs(self, workflow_data, output_file="workflow_outputs.json"):
        """Extract all possible outputs from workflow analysis and save in standardized format.
        
        Args:
            workflow_data (dict): Full workflow analysis data
            output_file (str): Path to save the standardized outputs JSON
            
        Returns:
            list: List of standardized output strings
        """
        import json
        from pathlib import Path
        
        if "error" in workflow_data:
            print(f"Warning: Cannot extract outputs from workflow data with error: {workflow_data.get('error_message')}")
            return []
        
        # Extract outputs from multiple sources
        outputs = set()
        
        # From outputs array
        for output in workflow_data.get("outputs", []):
            output_name = output.get("name", "")
            if output_name:
                outputs.add(output_name)
        
        # From workflow_paths (final outputs)
        for path in workflow_data.get("workflow_paths", []):
            path_output = path.get("output", "")
            if path_output:
                outputs.add(path_output)
        
        # From decision point branches (outcomes)
        for decision in workflow_data.get("decision_points", []):
            for branch in decision.get("branches", []):
                branch_outcome = branch.get("outcome", "")
                if branch_outcome and not branch_outcome.startswith("leads to") and not branch_outcome.startswith("next"):
                    outputs.add(branch_outcome)
        
        # Convert to sorted list for consistency
        standardized_outputs = sorted(list(outputs))
        
        # Save to JSON file
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(standardized_outputs, f, indent=2)
        
        print(f"\n✅ Extracted {len(standardized_outputs)} unique outputs")
        print(f"✅ Standardized outputs saved to: {output_path}")
        
        return standardized_outputs
    
    def _normalize_type(self, type_str, format_str):
        """Normalize input type to standard format (Int, Float, str, bool, etc.).
        
        Args:
            type_str (str): Type string from workflow analysis
            format_str (str): Format string from workflow analysis
            
        Returns:
            str: Normalized type (Int, Float, str, bool, date, etc.)
        """
        type_lower = (type_str or "").lower()
        format_lower = (format_str or "").lower()
        
        # Check format first for more specific types
        if "int" in format_lower or "integer" in format_lower:
            return "Int"
        elif "float" in format_lower or "decimal" in format_lower:
            return "Float"
        elif "bool" in format_lower or "boolean" in format_lower:
            return "bool"
        elif "date" in format_lower:
            return "date"
        
        # Check type string
        if "numeric" in type_lower or "number" in type_lower:
            # Default to Float if numeric but format not specified
            return "Float"
        elif "text" in type_lower or "string" in type_lower:
            return "str"
        elif "bool" in type_lower or "boolean" in type_lower:
            return "bool"
        elif "categorical" in type_lower or "enum" in type_lower:
            return "str"  # Categorical is typically string
        elif "date" in type_lower:
            return "date"
        
        # Default fallback
        return "str"
    
    def _extract_range(self, possible_values, constraints):
        """Extract range information in a clever standardized format.
        
        Args:
            possible_values (dict): Possible values dictionary from workflow analysis
            constraints (str): Constraints string from workflow analysis
            
        Returns:
            dict or list or None: Range representation
                - For numeric ranges: {"min": x, "max": y} or {"min": x} or {"max": y}
                - For categorical: ["value1", "value2", ...]
                - For unbounded: None
        """
        if not possible_values:
            # Try to extract from constraints string
            if constraints:
                # Look for numeric patterns in constraints
                import re
                numbers = re.findall(r'\d+\.?\d*', constraints)
                if numbers:
                    nums = [float(n) for n in numbers]
                    if len(nums) >= 2:
                        return {"min": min(nums), "max": max(nums)}
                    elif len(nums) == 1:
                        return {"value": nums[0]}
            return None
        
        pv_type = possible_values.get("type", "").lower()
        
        if pv_type == "range":
            range_dict = {}
            if "min" in possible_values:
                range_dict["min"] = possible_values["min"]
            if "max" in possible_values:
                range_dict["max"] = possible_values["max"]
            return range_dict if range_dict else None
        
        elif pv_type == "enum":
            values = possible_values.get("values", [])
            return values if values else None
        
        elif pv_type == "unbounded":
            return None
        
        # Fallback: check if there are explicit min/max or values
        if "min" in possible_values or "max" in possible_values:
            range_dict = {}
            if "min" in possible_values:
                range_dict["min"] = possible_values["min"]
            if "max" in possible_values:
                range_dict["max"] = possible_values["max"]
            return range_dict
        
        if "values" in possible_values:
            return possible_values["values"]
        
        return None
    
    def reset_conversation(self):
        """Reset the conversation history."""
        self.conversation_history = []

