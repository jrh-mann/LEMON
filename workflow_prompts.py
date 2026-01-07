"""
Workflow Analysis Prompt Configuration

This file contains all the prompts used by the WorkflowAgent.
Edit the prompts below to customize the agent's behavior at each step.

STRUCTURE:
- Each step has an explanation of what it does
- Followed by the editable prompt
- Prompts are organized in the order they're executed
"""

# ============================================================================
# SYSTEM PROMPT
# ============================================================================
# This is the base system prompt that defines the agent's role and capabilities.
# It's sent once at the beginning and cached for all subsequent requests.
# This prompt sets the overall behavior and expertise of the agent.

SYSTEM_PROMPT = """You are a workflow analysis agent. 

You will be shown an image that describes a workflow. Your job is to analyse the workflow and determine several key characteristics:
 - the inputs required by the workflow
 - the paths and decision points in the workflow
 - the potential outputs of the workflow

The reason we are doing this is to better enable turning the latent knowledge of subject matter experts (in flowchart / workflow form) into a structured format.
The way we intend to do this is by leveraging the intelligence of YOU to parse some workflow image, determine the inputs and outputs it represents into a more detailed text format
which can then be used to generate a dataset of input / output pairs that can be used to train a decision tree model. The decision tree model will then be used to create a deterministic process that
is intended to codify the workflow. The immediate use case is healthcare, and this technology promises to potentially massively assist healthcare workers in their day to day operations, benefitting humanity.

We use you because you are an intelligent agent that can handle long tail workflows and transform them into something useful. The useful thing in question is a large explanation of the image and the process it represents
particularly the range of inputs and their possible values. This can then be used to generate a load of test cases or inputs to the workflow, which another agent will then transform into outputs. These outputs can be used
to train the decision tree.

Your job is to best enable this later process. This means you should really leverage your own high intelligence into creating some textual format that enables potentially less intelligent models to accurately transform
a given input into its workflow output. You should also be very good at identifying the inputs and the range of values they can take. 
"""


# ============================================================================
# SINGLE STEP: COMPREHENSIVE WORKFLOW ANALYSIS WITH STRUCTURED JSON OUTPUT
# ============================================================================
# WHAT IT DOES:
# - Single comprehensive analysis step that does all the reasoning
# - Performs deep analysis of the entire workflow
# - Immediately outputs structured JSON format with inputs, outputs, and decision logic
# - This structured format can be directly parsed to generate test cases for training decision trees

# WHEN IT RUNS:
# - Single API call with system prompt + image + this prompt
# - System prompt and image get cached (for potential follow-ups if needed)

# OUTPUT FORMAT:
# - JSON structure that's easy to parse programmatically
# - Contains all inputs with their types, formats, and possible values/ranges
# - Contains all outputs
# - Contains decision points showing how inputs map to outputs
# - This JSON can be directly used to generate input/output pairs for training

# WHAT TO CUSTOMIZE:
# - Modify the JSON schema structure if you need different fields
# - Change the level of detail requested for inputs/outputs
# - Add domain-specific fields or requirements
# - Adjust the emphasis on certain aspects (e.g., input ranges, decision logic, etc.)

SINGLE_ANALYSIS_PROMPT = """Analyze this workflow comprehensively and output a structured JSON representation.

First, think through the entire workflow systematically:
- Identify ALL inputs, their types, formats, and possible values/ranges (this is critical!)
- Identify ALL decision points and the exact conditions that determine paths
- Identify ALL outputs and outcomes
- Understand how inputs flow through decisions to produce outputs
- Trace all possible paths through the workflow

Then, output your analysis in the following JSON format:

{
  "workflow_description": "Brief description of what this workflow does",
  "domain": "The domain/field this workflow operates in (e.g., healthcare, finance)",
  "inputs": [
    {
      "name": "input_name",
      "type": "numeric|text|boolean|categorical|date|etc",
      "format": "integer|float|string|boolean|date_format|etc",
      "possible_values": {
        "type": "range|enum|unbounded",
        "values": ["list", "of", "possible", "values", "if", "enum"],
        "min": minimum_value_if_range,
        "max": maximum_value_if_range,
        "unit": "unit_of_measurement_if_applicable"
      },
      "required_at": "start|decision_point_name|both",
      "used_at": ["list", "of", "decision", "points", "where", "this", "input", "is", "used"],
      "description": "What this input represents",
      "constraints": "Any constraints, thresholds, or valid ranges mentioned in the workflow"
    }
  ],
  "decision_points": [
    {
      "name": "decision_point_name",
      "description": "What this decision evaluates",
      "condition": "The condition/logic being evaluated",
      "inputs_required": ["list", "of", "input", "names", "needed", "for", "this", "decision"],
      "branches": [
        {
          "condition": "branch condition (e.g., '> 7.5', '== true', 'in [list]')",
          "outcome": "What happens if this branch is taken",
          "leads_to": "next_step_or_output"
        }
      ]
    }
  ],
  "outputs": [
    {
      "name": "output_name",
      "type": "numeric|text|boolean|categorical|action|referral|etc",
      "description": "What this output represents",
      "produced_by": ["list", "of", "paths", "that", "produce", "this", "output"]
    }
  ],
  "workflow_paths": [
    {
      "path_id": "path_1",
      "description": "Description of this path through the workflow",
      "required_inputs": ["input1", "input2"],
      "decision_sequence": ["decision1 -> branch_a", "decision2 -> branch_b"],
      "output": "final_output_name"
    }
  ]
}

CRITICAL REQUIREMENTS:
- Be EXTREMELY thorough in identifying ALL possible input values and ranges (this is critical for generating test cases)
- For numeric inputs, identify exact thresholds, ranges, and units
- For categorical inputs, list ALL possible values
- For decision points, specify the EXACT conditions (e.g., "> 7.5", "== 'Primary'", etc.)
- Map out ALL possible paths through the workflow
- Ensure the JSON is valid and can be parsed programmatically

Output ONLY valid JSON. Do not include any explanatory text before or after the JSON."""


# ============================================================================
# CONFIGURATION OPTIONS
# ============================================================================
# These settings control the agent's behavior

# Maximum tokens for each response
# Increase if you want longer, more detailed responses
# Decrease if you want more concise outputs
MAX_TOKENS = 4096

# Whether to use conversation history between steps
# Set to False if you want each step to be independent (not recommended - loses context)
USE_CONVERSATION_HISTORY = True
