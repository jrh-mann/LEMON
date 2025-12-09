"""Script to execute workflow with test cases and generate labeled outputs."""

import argparse
import json
from pathlib import Path
from src.utils import execute_test_cases, WorkflowExecutor


def main():
    parser = argparse.ArgumentParser(description="Execute workflow with test cases to determine outcomes")
    parser.add_argument(
        "-t", "--test-cases",
        type=str,
        default="test_cases.json",
        help="Path to test cases JSON file (default: test_cases.json)"
    )
    parser.add_argument(
        "-w", "--workflow",
        type=str,
        default="workflow.jpeg",
        help="Path to workflow image (default: workflow.jpeg)"
    )
    parser.add_argument(
        "--text-mode",
        action="store_true",
        help="Use text mode instead of image mode (requires --workflow-text)"
    )
    parser.add_argument(
        "--workflow-text",
        type=str,
        default=None,
        help="Path to workflow text description file (required for text mode)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="labeled_test_cases.json",
        help="Path to output labeled test cases JSON file (default: labeled_test_cases.json)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Maximum tokens for responses (default: from workflow_prompts.py)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of test cases to process (for testing)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Number of parallel workers (default: 10). Set to 1 for sequential processing."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-haiku-4-5",
        help="Model to use for execution (default: haiku-4.5)"
    )
    parser.add_argument(
        "--valid-outputs",
        type=str,
        default="workflow_outputs.json",
        help="Path to JSON file containing list of valid outputs (default: workflow_outputs.json). If file doesn't exist, allows free-form outputs."
    )
    
    args = parser.parse_args()
    
    # Load workflow text if in text mode
    workflow_text = None
    if args.text_mode:
        if args.workflow_text:
            with open(args.workflow_text, 'r') as f:
                workflow_text = f.read()
        else:
            parser.error("--workflow-text is required when using --text-mode")
    
    # Load test cases to check count (execute_test_cases will load them again)
    with open(args.test_cases, 'r') as f:
        test_cases = json.load(f)
    
    if args.limit:
        # If limiting, we need to save a temporary file or handle it differently
        # For now, just note it - execute_test_cases doesn't support limit
        print(f"Note: --limit option not yet supported with valid outputs. Processing all test cases.")
    
    print(f"Executing workflow with {len(test_cases)} test cases...")
    print(f"Mode: {'Image' if not args.text_mode else 'Text'}")
    print(f"Workflow source: {args.workflow}")
    print(f"Output file: {args.output}")
    
    # Check if valid outputs file exists
    valid_outputs_file = args.valid_outputs if Path(args.valid_outputs).exists() else None
    if valid_outputs_file:
        print(f"Using valid outputs from: {valid_outputs_file}")
    else:
        print(f"Warning: Valid outputs file not found ({args.valid_outputs}). Allowing free-form outputs.")
    print()
    
    # Use execute_test_cases convenience function which handles valid_outputs
    labeled_cases = execute_test_cases(
        test_cases_file=args.test_cases,
        workflow_source=args.workflow,
        use_image=not args.text_mode,
        workflow_text=workflow_text,
        output_file=args.output,
        max_tokens=args.max_tokens,
        verbose=not args.quiet,
        save_incremental=True,
        max_workers=args.max_workers,
        model=args.model,
        valid_outputs_file=valid_outputs_file
    )
    
    print(f"\n✅ Completed! Generated {len(labeled_cases)} labeled test cases")
    print(f"   Saved to: {args.output}")


if __name__ == "__main__":
    main()

