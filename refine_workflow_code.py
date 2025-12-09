"""Refinement loop: Generate -> Validate -> Test -> Fix."""

import json
import ast
import sys
import argparse
import os
from pathlib import Path

# Add src to path if needed
sys.path.append(str(Path(__file__).parent))

from src.utils.code_generator import generate_workflow_code
from src.utils.code_test_harness import CodeTestHarness
from src.utils.workflow_agent import WorkflowAgent
from src.utils.test_case_generator import TestCaseGenerator
from src.utils.request_utils import get_token_stats


def validate_code_structure(code: str) -> bool:
    """Static analysis to ensure code is runnable before sending to sandbox."""
    try:
        tree = ast.parse(code)
        
        # Check for function definition
        has_function = any(
            isinstance(node, ast.FunctionDef) and node.name == 'determine_workflow_outcome'
            for node in ast.walk(tree)
        )
        
        if not has_function:
            print("❌ Validation Failed: Missing function 'determine_workflow_outcome'")
            return False
            
        return True
    except SyntaxError as e:
        print(f"❌ Validation Failed: Syntax Error - {e}")
        return False


def refinement_loop(workflow_image="workflow.jpeg", max_iterations=None):
    """Main refinement loop for generating and validating workflow code.
    
    Args:
        workflow_image: Path to workflow image file
        max_iterations: Maximum number of refinement iterations (None = run forever until 100%)
    """
    # 1. Setup
    print("🚀 Starting Pipeline...")
    
    # Show model being used
    model_name = os.getenv("DEPLOYMENT_NAME", "Not set in .env")
    print(f"   Using model: {model_name}")
    
    # Get initial token stats
    initial_token_stats = get_token_stats()
    
    # Check if analysis files already exist
    inputs_file = Path("workflow_inputs.json")
    outputs_file = Path("workflow_outputs.json")
    analysis_file = Path("workflow_analysis.json")  # Full analysis file
    
    if inputs_file.exists() and outputs_file.exists():
        print("   ✅ Found existing workflow analysis files, skipping analysis step")
        print(f"      - {inputs_file}")
        print(f"      - {outputs_file}")
        print("   💡 To re-analyze, delete these files and run again")
        
        # Load existing files
        with open(outputs_file) as f:
            valid_outputs = json.load(f)
        with open(inputs_file) as f:
            standardized_inputs = json.load(f)
        
        # Try to load full workflow analysis if it exists
        if analysis_file.exists():
            print(f"      - {analysis_file} (full analysis)")
            with open(analysis_file) as f:
                data = json.load(f)
        else:
            # Fallback to minimal version if full analysis doesn't exist
            data = {
                "inputs": standardized_inputs,
                "outputs": [{"name": output} for output in valid_outputs]
            }
    else:
        # Analyze image to get inputs/outputs structure
        print("   Analyzing workflow structure...")
        token_stats_before = get_token_stats()
        agent = WorkflowAgent(max_tokens=16000)
        data = agent.analyze_workflow_structured(workflow_image)
        token_stats_after = get_token_stats()
        tokens_used = token_stats_after['total_tokens'] - token_stats_before['total_tokens']
        input_tokens = token_stats_after['total_input_tokens'] - token_stats_before['total_input_tokens']
        output_tokens = token_stats_after['total_output_tokens'] - token_stats_before['total_output_tokens']
        print(f"   📊 Token usage: {tokens_used:,} total ({input_tokens:,} input + {output_tokens:,} output)")
        
        # Check if analysis failed
        if "error" in data:
            print(f"\n❌ Workflow analysis failed!")
            print(f"   Error: {data.get('error_message', 'Unknown error')}")
            
            # Save raw response for debugging
            raw_response = data.get('raw_response', '')
            debug_file = None
            if raw_response:
                debug_file = "workflow_analysis_raw_response.txt"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(raw_response)
                print(f"\n   💾 Raw response saved to: {debug_file}")
                print(f"   Raw response preview (first 500 chars):")
                preview = raw_response[:500] + "..." if len(raw_response) > 500 else raw_response
                print(f"   {preview}")
            
            print(f"\n   Troubleshooting:")
            print(f"   1. Check that your workflow image is clear and readable")
            print(f"   2. Verify the image path is correct: {workflow_image}")
            print(f"   3. Try running 'python main.py' separately to debug the analysis")
            if debug_file:
                print(f"   4. Check the raw response file: {debug_file}")
            print(f"   5. The JSON may be too large - try increasing MAX_TOKENS in workflow_prompts.py")
            print(f"   6. Check workflow_prompts.py if you need to adjust the analysis prompt")
            return
        
        # Save intermediate files for debugging/reference
        valid_outputs = agent.extract_and_save_outputs(data, "workflow_outputs.json")
        standardized_inputs = agent.extract_and_save_inputs(data, "workflow_inputs.json")
        
        # Save full workflow analysis for later use
        with open("workflow_analysis.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"   ✅ Full workflow analysis saved to: workflow_analysis.json")
        
        # Check if extraction succeeded
        if not valid_outputs:
            print(f"\n❌ Failed to extract valid outputs from workflow analysis!")
            print(f"   The workflow analysis may not have identified any outputs.")
            print(f"   Check the raw analysis data or try running 'python main.py' to debug.")
            return
        
        if not standardized_inputs:
            print(f"\n❌ Failed to extract inputs from workflow analysis!")
            print(f"   The workflow analysis may not have identified any inputs.")
            print(f"   Check the raw analysis data or try running 'python main.py' to debug.")
            return
        
        # Verify files were created
        if not outputs_file.exists():
            print(f"\n❌ workflow_outputs.json was not created!")
            print(f"   This should not happen if extraction succeeded. Check file permissions.")
            return
        
        if not inputs_file.exists():
            print(f"\n❌ workflow_inputs.json was not created!")
            print(f"   This should not happen if extraction succeeded. Check file permissions.")
            return
    
    # 2. Generate or Load Test Cases
    tests_file = Path("tests.json")
    gen = TestCaseGenerator("workflow_inputs.json")
    
    if tests_file.exists():
        print("   ✅ Found existing test cases file, loading...")
        print(f"      - {tests_file}")
        print("   💡 To regenerate test cases, delete this file and run again")
        with open(tests_file) as f:
            labeled_test_cases = json.load(f)
        print(f"   ✅ Loaded {len(labeled_test_cases)} labeled test cases")
    else:
        # Generate Initial Tests (Comprehensive Strategy)
        print("🧪 Generating 1000 initial test cases...")
        # 'comprehensive' tries all combinations of discrete values + random continuous
        test_cases = gen.generate_test_cases(1000, "comprehensive")
        
        # 3. Label Test Cases with Expected Outputs
        print("\n🏷️  Labeling test cases with expected outputs using Claude Haiku...")
        token_stats_before = get_token_stats()
        labeled_test_cases = gen.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=workflow_image,
            valid_outputs=valid_outputs
        )
        token_stats_after = get_token_stats()
        tokens_used = token_stats_after['total_tokens'] - token_stats_before['total_tokens']
        input_tokens = token_stats_after['total_input_tokens'] - token_stats_before['total_input_tokens']
        output_tokens = token_stats_after['total_output_tokens'] - token_stats_before['total_output_tokens']
        gen.save_test_cases(labeled_test_cases, "tests.json")
        print(f"   ✅ Saved {len(labeled_test_cases)} labeled test cases to tests.json")
        print(f"   📊 Token usage: {tokens_used:,} total ({input_tokens:,} input + {output_tokens:,} output)")
    
    harness = CodeTestHarness("tests.json", valid_outputs)
    
    # 4. Refinement Loop
    failures = None
    best_score = 0.0
    code = None
    iteration = 0
    
    print(f"\n🔄 Starting refinement loop (will run until 100% accuracy is reached)")
    if max_iterations:
        print(f"   Max iterations: {max_iterations}")
    else:
        print(f"   Running indefinitely until convergence (Ctrl+C to stop)")
    
    try:
        while True:
            iteration += 1
            if max_iterations and iteration > max_iterations:
                print(f"\n⚠️ Reached max iterations ({max_iterations}). Stopping.")
                break
            
            print(f"\n🔄 Iteration {iteration}" + (f"/{max_iterations}" if max_iterations else ""))
            
            # A. Generate
            # Get token stats before generation
            token_stats_before = get_token_stats()
            code = generate_workflow_code(workflow_image, data, valid_outputs, failures, test_cases_file="tests.json")
            # Get token stats after generation
            token_stats_after = get_token_stats()
            tokens_used = token_stats_after['total_tokens'] - token_stats_before['total_tokens']
            input_tokens = token_stats_after['total_input_tokens'] - token_stats_before['total_input_tokens']
            output_tokens = token_stats_after['total_output_tokens'] - token_stats_before['total_output_tokens']
            print(f"   📊 Token usage: {tokens_used:,} total ({input_tokens:,} input + {output_tokens:,} output)")
            
            # B. Static Validation (Quick Win)
            if not validate_code_structure(code):
                print("⚠️ Generated invalid code structure. Retrying...")
                print("\n" + "="*80)
                print(f"GENERATED CODE (INVALID - Iteration {iteration}):")
                print("="*80)
                print(code)
                print("="*80 + "\n")
                continue 
                
            # Save current draft
            with open("generated_code.py", "w") as f:
                f.write(code)
            
            # Print generated code for debugging
            print("\n" + "="*80)
            print(f"GENERATED CODE (Iteration {iteration}):")
            print("="*80)
            print(code)
            print("="*80 + "\n")
            
            # C. Sandbox Testing
            print("   Running sandbox tests...")
            score_data = harness.score(code)
            current_score = score_data['pass_rate']
            print(f"📊 Score: {current_score*100:.1f}% ({score_data['passed']}/{score_data['total']})")
            
            # Print failure details if there are failures
            if score_data['failures']:
                print(f"\n   Failures ({len(score_data['failures'])}):")
                # Show first 3 failures as examples
                for i, failure in enumerate(score_data['failures'][:3], 1):
                    print(f"      {i}. {failure.get('error', 'Unknown error')}")
                    test_case = failure.get('test_case', {})
                    if test_case:
                        # Show a compact representation of the test case
                        case_str = ", ".join([f"{k}={v}" for k, v in list(test_case.items())[:3]])
                        if len(test_case) > 3:
                            case_str += "..."
                        print(f"         Input: {case_str}")
                if len(score_data['failures']) > 3:
                    print(f"      ... and {len(score_data['failures']) - 3} more failures")
            
            # D. Success Check
            if current_score == 1.0:
                print("✅ Initial Validation Passed (100%)")
                break
                
            # E. Progress tracking (no early stopping)
            if current_score < best_score:
                print(f"⚠️ Warning: Score regressed (Best: {best_score*100:.1f}%). Continuing...")
            elif current_score > best_score:
                print(f"📈 Progress: Improved from {best_score*100:.1f}% to {current_score*100:.1f}%")
                
            best_score = max(best_score, current_score)
            failures = score_data['failures']
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️ Interrupted by user (Ctrl+C)")
        print(f"   Best score achieved: {best_score*100:.1f}%")
        print(f"   Current code saved to: generated_code.py")
        if code:
            print(f"   You can resume by running the script again (it will use the saved code as a starting point)")
        return
    
    # 5. Final Validation (Adversarial/Edge Cases)
    if best_score == 1.0:
        print("\n🔒 Final Validation (Adversarial Edge Cases)...")
        final_tests_file = Path("final_tests.json")
        
        if final_tests_file.exists():
            print("   ✅ Found existing final test cases file, loading...")
            print(f"      - {final_tests_file}")
            with open(final_tests_file) as f:
                final_labeled_tests = json.load(f)
            print(f"   ✅ Loaded {len(final_labeled_tests)} final test cases")
        else:
            # Explicitly use 'edge_cases' strategy for final sign-off
            # This targets min/max/boundary values specifically
            final_tests = gen.generate_test_cases(200, "edge_cases")
            # Label the final test cases as well
            print("🏷️  Labeling final edge case test cases...")
            token_stats_before = get_token_stats()
            final_labeled_tests = gen.label_test_cases(
                test_cases=final_tests,
                workflow_image_path=workflow_image,
                valid_outputs=valid_outputs
            )
            token_stats_after = get_token_stats()
            tokens_used = token_stats_after['total_tokens'] - token_stats_before['total_tokens']
            input_tokens = token_stats_after['total_input_tokens'] - token_stats_before['total_input_tokens']
            output_tokens = token_stats_after['total_output_tokens'] - token_stats_before['total_output_tokens']
            gen.save_test_cases(final_labeled_tests, "final_tests.json")
            print(f"   ✅ Saved {len(final_labeled_tests)} final test cases to final_tests.json")
            print(f"   📊 Token usage: {tokens_used:,} total ({input_tokens:,} input + {output_tokens:,} output)")
        
        final_harness = CodeTestHarness("final_tests.json", valid_outputs)
        final_score = final_harness.score(code)
        print(f"🏁 Final Edge Case Score: {final_score['pass_rate']*100:.1f}%")
        
        if final_score['pass_rate'] == 1.0:
            print("🎉 SUCCESS! Code Verified & Ready to Ship.")
            print(f"✅ Final code saved to: generated_code.py")
        else:
            print("❌ Failed on edge cases. Review 'final_tests.json' for details.")
            print(f"   Failures: {len(final_score['failures'])}")
    else:
        print("❌ Failed to converge to 100% accuracy.")
        print(f"   Best score achieved: {best_score*100:.1f}%")
    
    # Final token usage summary
    final_token_stats = get_token_stats()
    total_tokens_used = final_token_stats['total_tokens'] - initial_token_stats['total_tokens']
    total_input_tokens = final_token_stats['total_input_tokens'] - initial_token_stats['total_input_tokens']
    total_output_tokens = final_token_stats['total_output_tokens'] - initial_token_stats['total_output_tokens']
    total_requests = final_token_stats['request_count'] - initial_token_stats['request_count']
    
    print("\n" + "="*80)
    print("TOKEN USAGE SUMMARY")
    print("="*80)
    print(f"Total tokens used: {total_tokens_used:,}")
    print(f"  - Input tokens: {total_input_tokens:,}")
    print(f"  - Output tokens: {total_output_tokens:,}")
    print(f"Total API requests: {total_requests}")
    if total_requests > 0:
        print(f"Average tokens per request: {total_tokens_used // total_requests:,}")
    print("="*80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Refinement loop: Generate deterministic Python code from workflow with test-driven validation"
    )
    parser.add_argument(
        "--workflow-image",
        type=str,
        default="workflow.jpeg",
        help="Path to workflow image file (default: workflow.jpeg)"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of refinement iterations (default: None = run forever until 100%%)"
    )
    
    args = parser.parse_args()
    refinement_loop(workflow_image=args.workflow_image, max_iterations=args.max_iterations)

