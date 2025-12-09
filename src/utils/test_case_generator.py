"""Test case generator for workflow inputs."""

import json
import random
import os
from pathlib import Path
from typing import List, Dict, Any, Union
from PIL import Image

# Import request utilities for API calls
import sys
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from src.utils.request_utils import make_image_request, image_to_base64


class TestCaseGenerator:
    """Generate test cases from workflow inputs JSON."""
    
    def __init__(self, inputs_file="workflow_inputs.json"):
        """Initialize the test case generator.
        
        Args:
            inputs_file (str): Path to workflow inputs JSON file
        """
        self.inputs_file = Path(inputs_file)
        self.inputs = self._load_inputs()
    
    def _load_inputs(self) -> List[Dict[str, Any]]:
        """Load inputs from JSON file.
        
        Returns:
            List of input dictionaries
        """
        if not self.inputs_file.exists():
            raise FileNotFoundError(f"Inputs file not found: {self.inputs_file}")
        
        with open(self.inputs_file, 'r') as f:
            return json.load(f)
    
    def _generate_values_for_input(self, inp: Dict[str, Any], num_samples: int = 5) -> List[Any]:
        """Generate possible values for a single input.
        
        Args:
            inp: Input dictionary with input_name, input_type, range, description
            num_samples: Number of samples to generate for continuous ranges
            
        Returns:
            List of possible values for this input
        """
        input_type = inp.get("input_type", "str")
        range_info = inp.get("range")
        
        # Boolean type
        if input_type == "bool":
            return [True, False]
        
        # Categorical/Enum (list of values)
        if isinstance(range_info, list):
            return range_info
        
        # Numeric range
        if isinstance(range_info, dict):
            min_val = range_info.get("min")
            max_val = range_info.get("max")
            value = range_info.get("value")  # Single value
            
            if value is not None:
                return [value]
            
            if input_type == "Int":
                if min_val is not None and max_val is not None:
                    # Generate edge cases and some random samples
                    values = [min_val, max_val]
                    if max_val > min_val:
                        mid = (min_val + max_val) // 2
                        values.append(mid)
                        # Add some random samples
                        for _ in range(num_samples - 3):
                            values.append(random.randint(min_val, max_val))
                    return list(set(values))  # Remove duplicates
                elif min_val is not None:
                    return [min_val, min_val + 10, min_val + 100]
                elif max_val is not None:
                    return [max_val, max_val - 10, max_val - 100]
                else:
                    return [0, 1, 10, 100, -1, -10]
            
            elif input_type == "Float":
                if min_val is not None and max_val is not None:
                    # Generate edge cases and some random samples
                    values = [min_val, max_val]
                    if max_val > min_val:
                        mid = (min_val + max_val) / 2
                        values.append(mid)
                        # Add some random samples
                        for _ in range(num_samples - 3):
                            values.append(random.uniform(min_val, max_val))
                    return list(set(values))  # Remove duplicates
                elif min_val is not None:
                    return [min_val, min_val + 0.1, min_val + 1.0]
                elif max_val is not None:
                    return [max_val, max_val - 0.1, max_val - 1.0]
                else:
                    return [0.0, 0.1, 1.0, 10.0, -1.0, -10.0]
        
        # String type without specific range
        if input_type == "str":
            # Generate some example strings
            return ["value1", "value2", "example", ""]
        
        # Date type
        if input_type == "date":
            return ["2024-01-01", "2024-06-15", "2024-12-31"]
        
        # Default fallback
        return [None]
    
    def generate_test_cases(
        self, 
        n: int, 
        strategy: str = "comprehensive",
        seed: int = None
    ) -> List[Dict[str, Any]]:
        """Generate N test cases covering the input domain.
        
        Args:
            n: Number of test cases to generate
            strategy: Generation strategy
                - "comprehensive": Try to cover all combinations of discrete values, then fill with random
                - "random": Randomly sample from all possible values
                - "edge_cases": Focus on edge cases (min, max, boundaries)
            seed: Random seed for reproducibility
            
        Returns:
            List of test case dictionaries, each with input_name -> value mappings
        """
        if seed is not None:
            random.seed(seed)
        
        # Generate possible values for each input
        input_value_sets = {}
        for inp in self.inputs:
            input_name = inp["input_name"]
            input_value_sets[input_name] = self._generate_values_for_input(inp)
        
        if strategy == "comprehensive":
            return self._generate_comprehensive(n, input_value_sets)
        elif strategy == "random":
            return self._generate_random(n, input_value_sets)
        elif strategy == "edge_cases":
            return self._generate_edge_cases(n, input_value_sets)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _generate_comprehensive(
        self, 
        n: int, 
        input_value_sets: Dict[str, List[Any]]
    ) -> List[Dict[str, Any]]:
        """Generate comprehensive test cases covering all combinations where possible."""
        test_cases = []
        
        # First, generate all combinations of discrete values (for small combinations)
        discrete_inputs = {}
        continuous_inputs = {}
        
        for name, values in input_value_sets.items():
            # Consider it discrete if it has <= 10 values
            if len(values) <= 10:
                discrete_inputs[name] = values
            else:
                continuous_inputs[name] = values
        
        # Calculate total combinations
        total_combinations = 1
        for values in discrete_inputs.values():
            total_combinations *= len(values)
        
        # If total combinations is manageable, generate all
        if total_combinations <= n:
            from itertools import product
            
            discrete_names = list(discrete_inputs.keys())
            discrete_value_lists = [discrete_inputs[name] for name in discrete_names]
            
            for combo in product(*discrete_value_lists):
                test_case = dict(zip(discrete_names, combo))
                # Add random values for continuous inputs
                for name, values in continuous_inputs.items():
                    test_case[name] = random.choice(values)
                test_cases.append(test_case)
            
            # Fill remaining with random samples
            while len(test_cases) < n:
                test_case = {}
                for name, values in input_value_sets.items():
                    test_case[name] = random.choice(values)
                # Avoid duplicates
                if test_case not in test_cases:
                    test_cases.append(test_case)
        else:
            # Too many combinations, use smart sampling
            # Generate edge cases first, then random
            test_cases = self._generate_edge_cases(min(n // 2, 50), input_value_sets)
            
            # Fill rest with random
            while len(test_cases) < n:
                test_case = {}
                for name, values in input_value_sets.items():
                    test_case[name] = random.choice(values)
                if test_case not in test_cases:
                    test_cases.append(test_case)
        
        return test_cases[:n]
    
    def _generate_random(
        self, 
        n: int, 
        input_value_sets: Dict[str, List[Any]]
    ) -> List[Dict[str, Any]]:
        """Generate random test cases."""
        test_cases = []
        
        for _ in range(n):
            test_case = {}
            for name, values in input_value_sets.items():
                test_case[name] = random.choice(values)
            test_cases.append(test_case)
        
        return test_cases
    
    def _generate_edge_cases(
        self, 
        n: int, 
        input_value_sets: Dict[str, List[Any]]
    ) -> List[Dict[str, Any]]:
        """Generate edge case test cases (min, max, boundaries)."""
        test_cases = []
        
        # For each input, prioritize edge values
        edge_values = {}
        for name, values in input_value_sets.items():
            if isinstance(values, list) and len(values) > 0:
                # For numeric, get min/max
                if all(isinstance(v, (int, float)) for v in values):
                    edge_values[name] = [min(values), max(values)]
                    if len(values) > 2:
                        mid = sorted(values)[len(values) // 2]
                        edge_values[name].append(mid)
                else:
                    # For categorical, use all values
                    edge_values[name] = values
            else:
                edge_values[name] = values
        
        # Generate combinations prioritizing edge values
        from itertools import product
        
        edge_names = list(edge_values.keys())
        edge_value_lists = [edge_values[name] for name in edge_names]
        
        for combo in product(*edge_value_lists):
            if len(test_cases) >= n:
                break
            test_case = dict(zip(edge_names, combo))
            test_cases.append(test_case)
        
        # Fill remaining with random if needed
        while len(test_cases) < n:
            test_case = {}
            for name, values in input_value_sets.items():
                test_case[name] = random.choice(values)
            if test_case not in test_cases:
                test_cases.append(test_case)
        
        return test_cases[:n]
    
    def save_test_cases(
        self, 
        test_cases: List[Dict[str, Any]], 
        output_file: str = "test_cases.json"
    ):
        """Save test cases to JSON file.
        
        Args:
            test_cases: List of test case dictionaries
            output_file: Path to output file
        """
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(test_cases, f, indent=2)
        
        print(f"✅ Saved {len(test_cases)} test cases to {output_path}")
    
    def label_test_cases(
        self,
        test_cases: List[Dict[str, Any]],
        workflow_image_path: str,
        valid_outputs: List[str],
        model: str = None,
        batch_size: int = 20
    ) -> List[Dict[str, Any]]:
        """Label test cases with expected outputs using Claude Haiku.
        
        Args:
            test_cases: List of test case dictionaries (with inputs only)
            workflow_image_path: Path to workflow image file
            valid_outputs: List of valid output strings from workflow_outputs.json
            model: Model deployment name to use (defaults to HAIKU_DEPLOYMENT_NAME or tries "haiku")
            batch_size: Number of test cases to process per API call (default: 20)
            
        Returns:
            List of test case dictionaries with 'expected_output' field added
        """
        # Determine which model to use
        if model is None:
            model = os.getenv("HAIKU_DEPLOYMENT_NAME")
            if not model:
                # Try default haiku name, fallback to main model
                model = os.getenv("DEPLOYMENT_NAME", "haiku")
        
        print(f"🏷️  Labeling {len(test_cases)} test cases using model: {model}")
        print(f"   Batch size: {batch_size}")
        
        # Load workflow image
        img = Image.open(workflow_image_path)
        img_format = img.format or 'PNG'
        format_map = {
            'JPEG': 'PNG',
            'JPG': 'PNG',
            'PNG': 'PNG',
            'WEBP': 'PNG',
            'GIF': 'PNG',
        }
        format_str = format_map.get(img_format.upper(), 'PNG')
        
        labeled_test_cases = []
        total_batches = (len(test_cases) + batch_size - 1) // batch_size
        
        # Process test cases in batches
        for batch_idx in range(0, len(test_cases), batch_size):
            batch = test_cases[batch_idx:batch_idx + batch_size]
            batch_num = (batch_idx // batch_size) + 1
            
            print(f"   Processing batch {batch_num}/{total_batches} ({len(batch)} test cases)...")
            
            # Create prompt for this batch
            prompt = self._create_labeling_prompt(batch, valid_outputs)
            
            try:
                # Make API request with image and prompt
                response = make_image_request(
                    image=img,
                    prompt=prompt,
                    max_tokens=4096,
                    model=model,
                    image_format=format_str
                )
                
                response_text = response.content[0].text if response.content else ""
                
                # Parse the response to extract expected outputs
                batch_labeled = self._parse_labeling_response(batch, response_text, valid_outputs)
                labeled_test_cases.extend(batch_labeled)
                
            except Exception as e:
                print(f"   ⚠️  Error labeling batch {batch_num}: {str(e)}")
                print(f"   Continuing with unlabeled test cases...")
                # Add test cases without expected_output (will be handled later)
                for tc in batch:
                    labeled_tc = tc.copy()
                    labeled_tc["expected_output"] = None
                    labeled_test_cases.append(labeled_tc)
        
        # Count successfully labeled
        labeled_count = sum(1 for tc in labeled_test_cases if tc.get("expected_output") is not None)
        print(f"✅ Labeled {labeled_count}/{len(test_cases)} test cases successfully")
        
        return labeled_test_cases
    
    def _create_labeling_prompt(self, test_cases: List[Dict[str, Any]], valid_outputs: List[str]) -> str:
        """Create prompt for labeling a batch of test cases.
        
        Args:
            test_cases: Batch of test case dictionaries
            valid_outputs: List of valid output strings
            
        Returns:
            Prompt string for Claude
        """
        # Format test cases as JSON
        test_cases_json = json.dumps(test_cases, indent=2)
        
        prompt = f"""You are analyzing a workflow diagram. For each test case below, determine what the expected output should be according to the workflow.

VALID OUTPUTS (you must choose exactly one of these):
{json.dumps(valid_outputs, indent=2)}

TEST CASES TO LABEL:
{test_cases_json}

For each test case, determine the expected output by following the workflow logic shown in the image. The output must be EXACTLY one of the valid outputs listed above.

Return your response as a JSON array with the same length as the test cases array. Each element should be a string containing the expected output for that test case.

Example format:
[
  "Output string 1",
  "Output string 2",
  "Output string 3"
]

Return ONLY the JSON array, no other text."""
        
        return prompt
    
    def _parse_labeling_response(
        self, 
        test_cases: List[Dict[str, Any]], 
        response_text: str, 
        valid_outputs: List[str]
    ) -> List[Dict[str, Any]]:
        """Parse Claude's response to extract expected outputs.
        
        Args:
            test_cases: Original test case batch
            response_text: Claude's response text
            valid_outputs: List of valid outputs for validation
            
        Returns:
            List of test cases with expected_output field added
        """
        import re
        
        # Try to extract JSON array from response
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            json_text = json_match.group(0)
        else:
            json_text = response_text.strip()
        
        try:
            expected_outputs = json.loads(json_text)
            
            # Validate we got the right number of outputs
            if not isinstance(expected_outputs, list):
                raise ValueError("Response is not a list")
            
            if len(expected_outputs) != len(test_cases):
                print(f"   ⚠️  Warning: Expected {len(test_cases)} outputs, got {len(expected_outputs)}")
                # Pad or truncate as needed
                if len(expected_outputs) < len(test_cases):
                    expected_outputs.extend([None] * (len(test_cases) - len(expected_outputs)))
                else:
                    expected_outputs = expected_outputs[:len(test_cases)]
            
            # Add expected_output to each test case
            labeled_test_cases = []
            for tc, expected_output in zip(test_cases, expected_outputs):
                labeled_tc = tc.copy()
                
                # Validate output is in valid_outputs
                if expected_output in valid_outputs:
                    labeled_tc["expected_output"] = expected_output
                else:
                    # Try to find closest match or set to None
                    if expected_output:
                        print(f"   ⚠️  Warning: Output '{expected_output}' not in valid outputs list")
                    labeled_tc["expected_output"] = None
                
                labeled_test_cases.append(labeled_tc)
            
            return labeled_test_cases
            
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Error parsing JSON response: {str(e)}")
            print(f"   Response preview: {response_text[:200]}...")
            # Return test cases without expected_output
            labeled_test_cases = []
            for tc in test_cases:
                labeled_tc = tc.copy()
                labeled_tc["expected_output"] = None
                labeled_test_cases.append(labeled_tc)
            return labeled_test_cases


def generate_test_cases_from_file(
    inputs_file: str = "workflow_inputs.json",
    n: int = 100,
    strategy: str = "comprehensive",
    output_file: str = "test_cases.json",
    seed: int = None
) -> List[Dict[str, Any]]:
    """Convenience function to generate test cases from inputs file.
    
    Args:
        inputs_file: Path to workflow inputs JSON file
        n: Number of test cases to generate
        strategy: Generation strategy ("comprehensive", "random", "edge_cases")
        output_file: Path to save test cases
        seed: Random seed for reproducibility
        
    Returns:
        List of test case dictionaries
    """
    generator = TestCaseGenerator(inputs_file)
    test_cases = generator.generate_test_cases(n, strategy=strategy, seed=seed)
    generator.save_test_cases(test_cases, output_file)
    return test_cases

