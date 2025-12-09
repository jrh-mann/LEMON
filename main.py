"""Example usage of the workflow agent."""

import json
from src.utils import WorkflowAgent, get_token_stats

# Initialize the workflow agent
agent = WorkflowAgent(max_tokens=16000)  # Increased for comprehensive JSON output

# Perform single-step comprehensive analysis
print("=" * 80)
print("WORKFLOW ANALYSIS - STRUCTURED JSON OUTPUT")
print("=" * 80)
print("\nAnalyzing workflow and generating structured JSON...\n")

# Get structured JSON output
workflow_data = agent.analyze_workflow_structured("workflow.jpeg")

# Extract and save standardized inputs
standardized_inputs = agent.extract_and_save_inputs(workflow_data, "workflow_inputs.json")

# Extract and save standardized outputs
standardized_outputs = agent.extract_and_save_outputs(workflow_data, "workflow_outputs.json")

# Display results
if "error" in workflow_data:
    print("❌ Error parsing JSON:")
    print(workflow_data["error_message"])
    print("\nRaw response:")
    print(workflow_data["raw_response"])
else:
    # Pretty print the JSON
    print("=" * 80)
    print("STRUCTURED WORKFLOW ANALYSIS (JSON)")
    print("=" * 80)
    print(json.dumps(workflow_data, indent=2))
    
    # Also print a summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\nWorkflow: {workflow_data.get('workflow_description', 'N/A')}")
    print(f"Domain: {workflow_data.get('domain', 'N/A')}")
    print(f"\nInputs identified: {len(workflow_data.get('inputs', []))}")
    print(f"Decision points: {len(workflow_data.get('decision_points', []))}")
    print(f"Outputs: {len(workflow_data.get('outputs', []))}")
    print(f"Workflow paths: {len(workflow_data.get('workflow_paths', []))}")
    
    if standardized_inputs:
        print("\n" + "-" * 80)
        print("STANDARDIZED INPUTS:")
        print("-" * 80)
        for inp in standardized_inputs:
            print(f"\n  • {inp.get('input_name', 'N/A')}")
            print(f"    Type: {inp.get('input_type', 'N/A')}")
            range_info = inp.get('range')
            if range_info:
                if isinstance(range_info, dict):
                    if 'min' in range_info and 'max' in range_info:
                        print(f"    Range: {range_info['min']} - {range_info['max']}")
                    elif 'min' in range_info:
                        print(f"    Range: >= {range_info['min']}")
                    elif 'max' in range_info:
                        print(f"    Range: <= {range_info['max']}")
                    elif 'value' in range_info:
                        print(f"    Value: {range_info['value']}")
                elif isinstance(range_info, list):
                    print(f"    Values: {', '.join(str(v) for v in range_info)}")
            else:
                print(f"    Range: Unbounded")
            print(f"    Description: {inp.get('description', 'N/A')}")

print("\n" + "=" * 80)
print("✅ Workflow analysis complete!")
print("=" * 80)

# Display token usage statistics
token_stats = get_token_stats()
print("\n" + "=" * 80)
print("TOKEN USAGE STATISTICS")
print("=" * 80)
print(f"\nTotal Requests: {token_stats['request_count']}")
print(f"Total Input Tokens: {token_stats['total_input_tokens']:,}")
print(f"Total Output Tokens: {token_stats['total_output_tokens']:,}")
print(f"Total Tokens: {token_stats['total_tokens']:,}")
print(f"\nToken tracking saved to: tokens.json")
print("=" * 80)