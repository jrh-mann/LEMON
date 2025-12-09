"""Workflow executor agent for determining outcomes from test cases."""

import json
import sys
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from .request_utils import make_request, image_to_base64
from PIL import Image

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from workflow_prompts import MAX_TOKENS as DEFAULT_MAX_TOKENS
except ImportError:
    DEFAULT_MAX_TOKENS = 4096


# System prompt for workflow execution
EXECUTION_SYSTEM_PROMPT = """You are a workflow execution agent. Your job is to determine the outcome of a workflow given specific input values.

You will be given:
1. A workflow (either as an image or a text description)
2. A set of input values for that workflow
3. A list of valid possible outcomes for this workflow

Your task is to:
- Trace through the workflow step by step using the provided input values
- Follow the decision logic at each decision point
- Determine which path is taken through the workflow
- Select the final outcome/output/action from the provided list of valid outcomes that best matches the result

CRITICAL RULES:
- The outcome must be the exact text of the output box in the workflow (verbatim). Do NOT paraphrase, prepend, append, or combine multiple boxes.
- If the provided list of valid outcomes is present, choose exactly one entry from that list. Do not create new variations.

CRITICAL: You MUST select an outcome from the provided list of valid outcomes. Do not create new outcomes or variations. If the exact outcome isn't in the list, choose the closest match."""


class WorkflowExecutor:
    """Agent for executing workflows with test cases to determine outcomes."""
    
    def __init__(
        self, 
        workflow_source: str,
        use_image: bool = True,
        workflow_text: Optional[str] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = "claude-haiku-4-5",
        valid_outputs: Optional[List[str]] = None
    ):
        """Initialize the workflow executor.
        
        Args:
            workflow_source: Path to workflow image (if use_image=True) or workflow text description
            use_image: If True, use image mode. If False, use text mode.
            workflow_text: Text description of workflow (required if use_image=False)
            max_tokens: Maximum tokens for responses
            model: Model to use for execution (default: claude-3-5-haiku-20241022)
            valid_outputs: List of valid output strings to choose from (if None, allows free-form outputs)
        """
        self.use_image = use_image
        self.workflow_source = workflow_source
        self.workflow_text = workflow_text
        self.max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        self.model = model
        self.conversation_history = []
        self.system_prompt = EXECUTION_SYSTEM_PROMPT
        self.valid_outputs = valid_outputs
        
        # Load workflow context once
        if use_image:
            if not Path(workflow_source).exists():
                raise FileNotFoundError(f"Workflow image not found: {workflow_source}")
        else:
            if not workflow_text:
                raise ValueError("workflow_text is required when use_image=False")
    
    def _load_image(self, image_path):
        """Load and prepare image for API request."""
        img = Image.open(image_path)
        
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
    
    def _create_execution_prompt(self, test_case: Dict[str, Any]) -> str:
        """Create prompt for executing workflow with test case inputs.
        
        Args:
            test_case: Dictionary of input values
            
        Returns:
            Execution prompt string
        """
        # Format inputs nicely
        inputs_str = "\n".join([f"  - {key}: {value}" for key, value in test_case.items()])
        
        # Add valid outputs section if provided
        valid_outputs_section = ""
        if self.valid_outputs:
            outputs_list = "\n".join([f"  {i+1}. {outcome}" for i, outcome in enumerate(self.valid_outputs)])
            valid_outputs_section = f"""

VALID OUTCOMES (you MUST choose one of these):
{outputs_list}

IMPORTANT: The "outcome" field in your response MUST be exactly one of the outcomes listed above. Use the exact box text verbatim. Do not create variations, paraphrase, or add prefixes/suffixes."""
        
        prompt = f"""Given the following input values for this workflow:

{inputs_str}{valid_outputs_section}

Please trace through the workflow and determine:
1. What path is taken through the workflow (which decision branches are followed)
2. What the final outcome/output/action is (must be from the valid outcomes list if provided)
   - The outcome must be verbatim text from the workflow output box. Do NOT add extra words, prefixes/suffixes, or paraphrase.
   - If a valid outcomes list is provided, pick exactly one entry from that list (no new variations).

Output your response in the following JSON format:
{{
  "path_taken": "Description of the path through the workflow",
  "decision_points": [
    {{
      "decision": "Decision point name",
      "condition": "Condition evaluated",
      "result": "Which branch was taken and why"
    }}
  ],
  "outcome": "The final outcome/output/action (MUST match one of the valid outcomes exactly if provided; verbatim box text)",
  "output_type": "Type of output (e.g., action, referral, result, etc.)",
  "reasoning": "Brief explanation of how you arrived at this outcome"
}}

Be precise and follow the workflow logic exactly."""
        
        return prompt
    
    def _create_initial_message(self, test_case: Dict[str, Any]):
        """Create the initial message with workflow context and test case.
        
        Args:
            test_case: Dictionary of input values
            
        Returns:
            Message dictionary
        """
        execution_prompt = self._create_execution_prompt(test_case)
        
        if self.use_image:
            # Image mode: send image + prompt
            img_base64, media_type = self._load_image(self.workflow_source)
            
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
                        "text": execution_prompt
                    }
                ]
            }
        else:
            # Text mode: send workflow text + prompt
            workflow_context = f"""Here is the workflow description:

{self.workflow_text}

---

{execution_prompt}"""
            
            return {
                "role": "user",
                "content": workflow_context
            }
    
    def execute(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow with a test case and determine the outcome.
        
        Args:
            test_case: Dictionary of input values
            
        Returns:
            Dictionary containing outcome information
        """
        # Reset conversation for each new test case (or keep history for context)
        # For now, reset to avoid confusion
        self.conversation_history = []
        
        message = self._create_initial_message(test_case)
        self.conversation_history.append(message)
        
        response = make_request(
            messages=self.conversation_history,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            model=self.model
        )
        
        response_text = response.content[0].text if response.content else ""
        
        # Try to parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
                # Add the test case inputs to the result
                result["inputs"] = test_case
                
                # Validate outcome if valid_outputs is provided
                if self.valid_outputs and "outcome" in result:
                    outcome = result["outcome"]
                    # Check if outcome exactly matches one of the valid outputs
                    if outcome not in self.valid_outputs:
                        # Try to find closest match
                        closest_match = self._find_closest_output(outcome)
                        if closest_match:
                            result["outcome_original"] = outcome
                            result["outcome"] = closest_match
                            result["outcome_validated"] = True
                        else:
                            result["outcome_validated"] = False
                            result["validation_error"] = f"Outcome '{outcome}' not in valid outputs list"
                    else:
                        result["outcome_validated"] = True
                
                return result
            except json.JSONDecodeError:
                pass
        
        # If JSON parsing fails, return structured response
        return {
            "inputs": test_case,
            "outcome": response_text,
            "raw_response": response_text,
            "error": "Could not parse JSON response"
        }
    
    def _find_closest_output(self, outcome: str) -> Optional[str]:
        """Find the closest matching output from valid_outputs using fuzzy matching.
        
        Args:
            outcome: Outcome string to match
            
        Returns:
            Closest matching output string, or None if no good match found
        """
        if not self.valid_outputs:
            return None
        
        outcome_lower = outcome.lower().strip()
        
        # First, try exact case-insensitive match
        for valid_out in self.valid_outputs:
            if valid_out.lower().strip() == outcome_lower:
                return valid_out
        
        # Try substring matching (if outcome contains valid output or vice versa)
        for valid_out in self.valid_outputs:
            valid_out_lower = valid_out.lower().strip()
            if outcome_lower in valid_out_lower or valid_out_lower in outcome_lower:
                return valid_out
        
        # Try word-based matching (check if key words match)
        outcome_words = set(outcome_lower.split())
        best_match = None
        best_score = 0
        
        for valid_out in self.valid_outputs:
            valid_out_words = set(valid_out.lower().strip().split())
            # Calculate Jaccard similarity (intersection over union)
            intersection = len(outcome_words & valid_out_words)
            union = len(outcome_words | valid_out_words)
            if union > 0:
                score = intersection / union
                if score > best_score and score > 0.3:  # Require at least 30% similarity
                    best_score = score
                    best_match = valid_out
        
        return best_match
    
    def execute_batch(
        self, 
        test_cases: List[Dict[str, Any]],
        output_file: Optional[str] = None,
        verbose: bool = True,
        save_incremental: bool = True,
        max_workers: int = 10
    ) -> List[Dict[str, Any]]:
        """Execute workflow for multiple test cases.
        
        Args:
            test_cases: List of test case dictionaries
            output_file: Optional path to save labeled results
            verbose: If True, print progress
            save_incremental: If True, save after each test case (prevents data loss on interruption)
            max_workers: Number of parallel workers (default: 5). Set to 1 for sequential processing.
            
        Returns:
            List of labeled test cases with outcomes
        """
        labeled_cases = []
        save_lock = threading.Lock()
        
        # Load existing results if file exists (for resuming)
        if output_file and Path(output_file).exists() and save_incremental:
            try:
                with open(output_file, 'r') as f:
                    labeled_cases = json.load(f)
                if verbose:
                    print(f"Resuming from existing file: {len(labeled_cases)} cases already processed")
            except (json.JSONDecodeError, IOError):
                labeled_cases = []
        
        # Track which test cases we've already processed
        processed_indices = set()
        if labeled_cases:
            # Extract indices from existing results (assuming they're in order)
            processed_indices = set(range(len(labeled_cases)))
        
        # Filter out already processed test cases
        remaining_test_cases = [
            (idx, test_case) 
            for idx, test_case in enumerate(test_cases) 
            if idx not in processed_indices
        ]
        
        if not remaining_test_cases:
            if verbose:
                print("All test cases already processed!")
            return labeled_cases
        
        # Convert existing labeled_cases to list of (idx, result) tuples for parallel processing
        # We'll merge them back at the end
        existing_results = [(idx, case) for idx, case in enumerate(labeled_cases)]
        
        if verbose:
            print(f"Processing {len(remaining_test_cases)} remaining test cases...")
            if max_workers > 1:
                print(f"Using {max_workers} parallel workers")
        
        def process_single_case(idx_and_case):
            """Process a single test case (for parallel execution)."""
            idx, test_case = idx_and_case
            try:
                result = self.execute(test_case)
                return idx, result, None
            except Exception as e:
                return idx, None, e
        
        # Sequential processing (max_workers=1)
        if max_workers == 1:
            for idx, test_case in remaining_test_cases:
                if verbose:
                    total = len(test_cases)
                    print(f"Processing test case {idx + 1}/{total}...")
                
                try:
                    result = self.execute(test_case)
                    labeled_cases.append(result)
                    
                    # Save incrementally to prevent data loss
                    if output_file and save_incremental:
                        with save_lock:
                            self._save_labeled_cases(labeled_cases, output_file)
                except KeyboardInterrupt:
                    if verbose:
                        print(f"\n⚠️  Interrupted! Saving {len(labeled_cases)} completed test cases...")
                    if output_file:
                        with save_lock:
                            self._save_labeled_cases(labeled_cases, output_file)
                    raise
                except Exception as e:
                    if verbose:
                        print(f"⚠️  Error processing test case {idx + 1}: {e}")
                    # Save progress even on error
                    if output_file and save_incremental:
                        with save_lock:
                            self._save_labeled_cases(labeled_cases, output_file)
                    continue
        else:
            # Parallel processing
            completed_count = len(labeled_cases)
            total_count = len(test_cases)
            all_results = existing_results.copy()  # Start with existing results
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_idx = {
                    executor.submit(process_single_case, (idx, test_case)): idx
                    for idx, test_case in remaining_test_cases
                }
                
                # Process completed tasks as they finish
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        result_idx, result, error = future.result()
                        
                        if error:
                            if verbose:
                                print(f"⚠️  Error processing test case {idx + 1}: {error}")
                            continue
                        
                        # Add result with its index
                        all_results.append((idx, result))
                        completed_count += 1
                        
                        if verbose:
                            print(f"Completed test case {idx + 1}/{total_count} (Total completed: {completed_count})")
                        
                        # Save incrementally (thread-safe)
                        if output_file and save_incremental:
                            with save_lock:
                                # Sort by index and save
                                sorted_cases = sorted(all_results, key=lambda x: x[0])
                                # Extract just the results (without indices)
                                results_only = [case[1] for case in sorted_cases]
                                self._save_labeled_cases(results_only, output_file)
                        
                    except KeyboardInterrupt:
                        if verbose:
                            print(f"\n⚠️  Interrupted! Saving {completed_count} completed test cases...")
                        if output_file:
                            with save_lock:
                                sorted_cases = sorted(all_results, key=lambda x: x[0])
                                results_only = [case[1] for case in sorted_cases]
                                self._save_labeled_cases(results_only, output_file)
                        raise
                    except Exception as e:
                        if verbose:
                            print(f"⚠️  Unexpected error: {e}")
            
            # Sort final results by index to maintain order
            all_results = sorted(all_results, key=lambda x: x[0])
            labeled_cases = [case[1] for case in all_results]
        
        # Final save (in case save_incremental was False)
        if output_file:
            self._save_labeled_cases(labeled_cases, output_file)
            if verbose:
                print(f"\n✅ Saved {len(labeled_cases)} labeled test cases to {output_file}")
        
        return labeled_cases
    
    def _save_labeled_cases(self, labeled_cases: List[Dict[str, Any]], output_file: str):
        """Save labeled test cases to JSON file.
        
        Args:
            labeled_cases: List of labeled test cases
            output_file: Path to output file
        """
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(labeled_cases, f, indent=2)


def execute_test_cases(
    test_cases_file: str = "test_cases.json",
    workflow_source: str = "workflow.jpeg",
    use_image: bool = True,
    workflow_text: Optional[str] = None,
    output_file: str = "labeled_test_cases.json",
    max_tokens: Optional[int] = None,
        verbose: bool = True,
        save_incremental: bool = True,
        max_workers: int = 10,
        model: Optional[str] = "claude-haiku-4-5",
        valid_outputs_file: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Convenience function to execute test cases and generate labeled outputs.
    
    Args:
        test_cases_file: Path to test cases JSON file
        workflow_source: Path to workflow image (if use_image=True)
        use_image: If True, use image mode. If False, use text mode.
        workflow_text: Text description of workflow (required if use_image=False)
        output_file: Path to save labeled test cases
        max_tokens: Maximum tokens for responses
        verbose: If True, print progress
        save_incremental: If True, save after each test case (prevents data loss on interruption)
        max_workers: Number of parallel workers
        model: Model to use
        valid_outputs_file: Path to JSON file containing list of valid outputs (optional)
        
    Returns:
        List of labeled test cases with outcomes
    """
    # Load test cases
    with open(test_cases_file, 'r') as f:
        test_cases = json.load(f)
    
    # Load valid outputs if provided
    valid_outputs = None
    if valid_outputs_file and Path(valid_outputs_file).exists():
        with open(valid_outputs_file, 'r') as f:
            valid_outputs = json.load(f)
        if verbose:
            print(f"Loaded {len(valid_outputs)} valid outputs from {valid_outputs_file}")
    elif valid_outputs_file:
        if verbose:
            print(f"Warning: Valid outputs file not found: {valid_outputs_file}")
    
    # Create executor
    executor = WorkflowExecutor(
        workflow_source=workflow_source,
        use_image=use_image,
        workflow_text=workflow_text,
        max_tokens=max_tokens,
        model=model,
        valid_outputs=valid_outputs
    )
    
    # Execute all test cases
    labeled_cases = executor.execute_batch(
        test_cases=test_cases,
        output_file=output_file,
        verbose=verbose,
        save_incremental=save_incremental,
        max_workers=max_workers
    )
    
    return labeled_cases

