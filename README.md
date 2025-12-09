# LEMON - Workflow Analysis and Test Case Generation Pipeline

LEMON (Latent Expert Model Optimization Network) is a system for converting workflow diagrams into structured, executable code. It uses AI agents to analyze workflow images, extract inputs and decision logic, generate test cases, and produce deterministic Python implementations that guarantee 100% accuracy.

## Overview

LEMON generates deterministic Python code that implements workflow logic exactly. Uses iterative refinement with test-driven validation to guarantee 100% accuracy.

The pipeline consists of:

1. **Workflow Analysis**: Analyze a workflow image to extract structured information
2. **Code Generation**: Generate Python function implementing the workflow logic
3. **Test-Driven Refinement**: Iteratively test and fix code until 100% pass rate
4. **Final Validation**: Validate with additional edge cases before deployment

## Prerequisites

- Python 3.8+
- Anthropic API access (Claude API)
- E2B API key (for secure code execution sandbox)
- A workflow image (JPEG, PNG, etc.)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd LEMON
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
Create a `.env` file in the project root with:
```
ENDPOINT=your_anthropic_endpoint
DEPLOYMENT_NAME=your_deployment_name
API_KEY=your_api_key
E2B_API_KEY=your_e2b_api_key
```

**Getting an E2B API Key:**
- Sign up at [e2b.dev](https://e2b.dev)
- Get your API key from the dashboard
- Add it to your `.env` file

## 🎯 Deterministic Code Generation Pipeline (Recommended)

This approach generates deterministic Python code that implements your workflow exactly, with guaranteed 100% accuracy through test-driven refinement.

### Quick Start: Refinement Loop

Run the complete refinement loop in one command:

```bash
python refine_workflow_code.py
```

**What it does:**
1. Analyzes your workflow image to extract structure
2. Generates 1000 comprehensive test cases
3. Iteratively generates Python code implementing the workflow
4. Tests code in secure sandbox and fixes failures automatically
5. Continues until 100% pass rate is achieved
6. Validates with 200 additional edge cases
7. Outputs verified, production-ready Python code

**Output files:**
- `generated_code.py`: Deterministic Python function ready for deployment
- `tests.json`: Initial 1000 test cases used for refinement
- `final_tests.json`: 200 edge case tests for final validation
- `workflow_inputs.json`: Extracted input structure
- `workflow_outputs.json`: Valid output strings

**Example output:**
```python
def determine_workflow_outcome(inputs: dict) -> str:
    """
    Determine workflow outcome from inputs.
    
    Args:
        inputs: Dictionary with input_name -> value mappings
        
    Returns:
        Outcome string matching one of the valid outputs
    """
    # Deterministic if/elif/else logic implementing your workflow
    if inputs.get('ldl') >= 2.6:
        if inputs.get('prevention_type') == 'Secondary':
            return "Initiate Inclisiran"
        # ... more logic
    # ...
```

**Features:**
- ✅ **100% Deterministic**: No ML guessing, explicit if/else logic
- ✅ **Secure Execution**: Code runs in isolated E2B sandbox
- ✅ **Smart Failure Analysis**: Groups errors by pattern for efficient fixes
- ✅ **Automatic Refinement**: Iteratively fixes code until perfect
- ✅ **Edge Case Validation**: Final validation with boundary tests
- ✅ **Production Ready**: Code is auditable, debuggable, and maintainable

**Options:**
```bash
# Customize workflow image
python refine_workflow_code.py --workflow-image custom_workflow.png

# Adjust max iterations (default: 5)
python refine_workflow_code.py --max-iterations 10
```

---

## Additional Utilities

### Analyze Workflow Structure

Analyze a workflow image to extract structured information about inputs, decision points, and outputs.

```bash
python main.py
```

**What it does:**
- Loads the workflow image (`workflow.jpeg` by default)
- Performs deep analysis of the workflow structure
- Extracts all inputs with their types, formats, and possible values
- Outputs structured JSON with workflow information

**Output files:**
- `workflow_inputs.json`: Standardized list of inputs with types and ranges
- `workflow_outputs.json`: List of valid output strings
- Console output: Full workflow analysis and summary

**Example:**
```bash
python main.py
```

### Generate Test Cases

Generate test cases from the extracted inputs to cover the input domain.

```bash
python generate_test_cases.py [options]
```

**Options:**
- `-n, --num-cases`: Number of test cases to generate (default: 100)
- `-i, --inputs-file`: Path to workflow inputs JSON (default: `workflow_inputs.json`)
- `-o, --output-file`: Path to output test cases JSON (default: `test_cases.json`)
- `-s, --strategy`: Generation strategy - `comprehensive`, `random`, or `edge_cases` (default: `comprehensive`)
- `--seed`: Random seed for reproducibility

**What it does:**
- Reads `workflow_inputs.json`
- Generates N test cases covering all input combinations
- Uses smart sampling to ensure domain coverage
- Saves test cases as JSON

**Output files:**
- `test_cases.json`: Array of test case dictionaries with input values

**Examples:**
```bash
# Generate 100 test cases with comprehensive strategy
python generate_test_cases.py -n 100

# Generate 500 test cases with random sampling
python generate_test_cases.py -n 500 -s random

# Generate edge cases only
python generate_test_cases.py -n 50 -s edge_cases
```

## Complete Pipeline Example

```bash
# Single command - generates verified Python code
python refine_workflow_code.py

# The generated code can be used directly:
python -c "from generated_code import determine_workflow_outcome; print(determine_workflow_outcome({'ldl': 2.7, 'prevention_type': 'Secondary'}))"
```

Or run the steps individually:

```bash
# Step 1: Analyze workflow structure (optional - refinement loop does this automatically)
python main.py

# Step 2: Run refinement loop
python refine_workflow_code.py
```

## Output Files

| File | Description |
|------|-------------|
| `workflow_inputs.json` | Standardized list of workflow inputs with types and ranges |
| `workflow_outputs.json` | List of valid output strings |
| `generated_code.py` | **Deterministic Python function (from refinement loop)** |
| `tests.json` | Initial 1000 test cases for refinement |
| `final_tests.json` | 200 edge case tests for final validation |
| `test_cases.json` | Generated test cases (if using generate_test_cases.py directly) |
| `tokens.json` | Cumulative token usage statistics |

## File Structure

```
LEMON/
├── refine_workflow_code.py      # 🎯 Refinement loop orchestrator
├── main.py                      # Workflow analysis script
├── generate_test_cases.py       # Test case generation script
├── workflow_prompts.py          # Configurable prompts for agents
├── workflow.jpeg                # Your workflow image
├── src/
│   └── utils/
│       ├── code_generator.py    # 🎯 Code generation with failure analysis
│       ├── code_test_harness.py # 🎯 Secure test harness (E2B sandbox)
│       ├── workflow_agent.py    # Workflow analysis agent
│       ├── test_case_generator.py # Test case generator
│       └── request_utils.py     # API utilities
├── requirements.txt
├── .env                         # Environment variables (not in git)
└── README.md
```

## Customization

### Modifying Code Generation Prompts

Edit `src/utils/code_generator.py` to customize:
- `CODE_GENERATION_PROMPT`: Instructions for code generation
- `analyze_failure_patterns()`: How failures are analyzed and reported

### Modifying Workflow Analysis Prompts

Edit `workflow_prompts.py` to customize:
- System prompts for workflow analysis
- Analysis prompts for extracting workflow structure

### Adjusting Test Case Generation

Modify `src/utils/test_case_generator.py` to:
- Change value generation strategies
- Adjust sampling methods
- Customize range handling

### Changing Models

- **Workflow Analysis**: Uses model from `DEPLOYMENT_NAME` in `.env`
- **Code Generation**: Uses model from `DEPLOYMENT_NAME` in `.env`

### Adjusting Refinement Loop

Edit `refine_workflow_code.py` to:
- Change number of initial test cases (default: 1000)
- Change number of final validation cases (default: 200)
- Adjust max iterations (default: 5)
- Modify stagnation detection logic

## Token Tracking

Token usage is automatically tracked in `tokens.json`. View statistics:
```python
from src.utils import get_token_stats
stats = get_token_stats()
print(f"Total tokens: {stats['total_tokens']}")
print(f"Total requests: {stats['request_count']}")
```

## Tips

1. **Start Small**: The refinement loop automatically handles test case generation and validation
2. **Review Failures**: If the loop doesn't converge, check the failure patterns in the console output
3. **Customize Iterations**: Adjust `--max-iterations` if your workflow is complex and needs more refinement cycles
4. **Check Generated Code**: Always review `generated_code.py` before deploying to production

## Troubleshooting

**Issue**: "Missing required environment variables"
- **Solution**: Ensure `.env` file exists with `ENDPOINT`, `DEPLOYMENT_NAME`, `API_KEY`, and `E2B_API_KEY`

**Issue**: "E2B_API_KEY not found" or "Sandbox initialization failed"
- **Solution**: 
  - Sign up at [e2b.dev](https://e2b.dev) and get your API key
  - Add `E2B_API_KEY=your_key` to your `.env` file
  - Verify the key is correct

**Issue**: "Failed to parse JSON"
- **Solution**: Check the raw response in the error output. You may need to adjust prompts in `workflow_prompts.py` or `code_generator.py`

**Issue**: Refinement loop not reaching 100%
- **Solution**: 
  - Check the failure patterns in the console output
  - Review `generated_code.py` to see what was generated
  - Increase `max_iterations` in `refine_workflow_code.py`
  - Verify your workflow image is clear and readable

**Issue**: Code generation produces invalid syntax
- **Solution**: The static validator should catch this. If it persists, check the LLM response format and adjust `CODE_GENERATION_PROMPT` in `code_generator.py`


## Next Steps

After running the refinement loop:

1. **Review Generated Code**: Check `generated_code.py` to verify the logic matches your workflow
2. **Integration**: Import and use the function in your application:
   ```python
   from generated_code import determine_workflow_outcome
   result = determine_workflow_outcome({'ldl': 2.7, 'prevention_type': 'Secondary'})
   ```
3. **Testing**: Use `tests.json` and `final_tests.json` as your test suite
4. **Documentation**: Add docstrings and type hints as needed
5. **Deployment**: Deploy the deterministic function - no ML model needed!

## Why Deterministic Code Generation?

**Key Advantages:**
- ✅ **100% Accuracy**: Guaranteed correctness, no approximation errors
- ✅ **Explainable**: Every decision is explicit in the code
- ✅ **Debuggable**: Can set breakpoints and trace execution
- ✅ **Maintainable**: Standard Python code, easy to modify
- ✅ **No Training Data**: No need to generate thousands of labeled examples
- ✅ **Faster**: Direct execution, no model inference overhead
- ✅ **Medical Grade**: Critical for healthcare applications requiring deterministic logic

## License

[Your License Here]

## Contributing

[Contributing Guidelines Here]

