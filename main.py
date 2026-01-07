"""Example usage of the workflow analyzer."""

import json
from pathlib import Path

from src.lemon.analysis.agent import WorkflowAnalyzer
from src.lemon.utils.logging import configure_logging, get_logger
from src.lemon.utils.token_tracker import get_token_stats

# Configure logging for CLI output (keep it human-readable)
configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)

# Initialize the workflow analyzer
analyzer = WorkflowAnalyzer(max_tokens=16000)  # Increased for comprehensive JSON output

# Perform single-step comprehensive analysis
logger.info("=" * 80)
logger.info("WORKFLOW ANALYSIS - STRUCTURED JSON OUTPUT")
logger.info("=" * 80)
logger.info("\nAnalyzing workflow and generating structured JSON...\n")

# Get structured analysis
analysis = analyzer.analyze(Path("workflow.jpeg"))
workflow_data = analysis.model_dump()

# Extract and save standardized inputs
standardized_inputs_models = analyzer.extract_standardized_inputs(analysis)
standardized_inputs = [x.model_dump(exclude_none=True) for x in standardized_inputs_models]
Path("workflow_inputs.json").write_text(json.dumps(standardized_inputs, indent=2), encoding="utf-8")

# Extract and save standardized outputs
standardized_outputs = analyzer.extract_outputs(analysis)
Path("workflow_outputs.json").write_text(
    json.dumps(standardized_outputs, indent=2), encoding="utf-8"
)

# Display results
# Pretty print the JSON
logger.info("=" * 80)
logger.info("STRUCTURED WORKFLOW ANALYSIS (JSON)")
logger.info("=" * 80)
logger.info(json.dumps(workflow_data, indent=2))

# Also print a summary
logger.info("\n" + "=" * 80)
logger.info("SUMMARY")
logger.info("=" * 80)
logger.info(f"\nWorkflow: {workflow_data.get('workflow_description', 'N/A')}")
logger.info(f"Domain: {workflow_data.get('domain', 'N/A')}")
logger.info(f"\nInputs identified: {len(workflow_data.get('inputs', []))}")
logger.info(f"Decision points: {len(workflow_data.get('decision_points', []))}")
logger.info(f"Outputs: {len(workflow_data.get('outputs', []))}")
logger.info(f"Workflow paths: {len(workflow_data.get('workflow_paths', []))}")

if standardized_inputs:
    logger.info("\n" + "-" * 80)
    logger.info("STANDARDIZED INPUTS:")
    logger.info("-" * 80)
    for inp in standardized_inputs:
        logger.info(f"\n  • {inp.get('input_name', 'N/A')}")
        logger.info(f"    Type: {inp.get('input_type', 'N/A')}")
        range_info = inp.get("range")
        if range_info:
            if isinstance(range_info, dict):
                if "min" in range_info and "max" in range_info:
                    logger.info(f"    Range: {range_info['min']} - {range_info['max']}")
                elif "min" in range_info:
                    logger.info(f"    Range: >= {range_info['min']}")
                elif "max" in range_info:
                    logger.info(f"    Range: <= {range_info['max']}")
                elif "value" in range_info:
                    logger.info(f"    Value: {range_info['value']}")
            elif isinstance(range_info, list):
                logger.info(f"    Values: {', '.join(str(v) for v in range_info)}")
        else:
            logger.info("    Range: Unbounded")
        logger.info(f"    Description: {inp.get('description', 'N/A')}")

logger.info("\n" + "=" * 80)
logger.info("Workflow analysis complete!")
logger.info("=" * 80)

# Display token usage statistics
token_stats = get_token_stats()
logger.info("\n" + "=" * 80)
logger.info("TOKEN USAGE STATISTICS")
logger.info("=" * 80)
logger.info(f"\nTotal Requests: {token_stats['request_count']}")
logger.info(f"Total Input Tokens: {token_stats['total_input_tokens']:,}")
logger.info(f"Total Output Tokens: {token_stats['total_output_tokens']:,}")
logger.info(f"Total Tokens: {token_stats['total_tokens']:,}")
logger.info("\nToken tracking saved to: tokens.json")
logger.info("=" * 80)
