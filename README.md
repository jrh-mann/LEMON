# LEMON - Workflow Analysis and Test Case Generation Pipeline

LEMON (Latent Expert Model Optimization Network) is a system for converting workflow diagrams into structured, executable decision trees. It uses AI agents to analyze workflow images, extract inputs and decision logic, generate test cases, and produce labeled training data for decision tree models.

## Overview

The pipeline consists of three main steps:

1. **Workflow Analysis**: Analyze a workflow image to extract structured information about inputs, decision points, and outputs
2. **Test Case Generation**: Generate comprehensive test cases covering the input domain
3. **Workflow Execution**: Execute the workflow with test cases to produce labeled input/output pairs

## Prerequisites

- Python 3.8+
- Anthropic API access (Claude API)
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
```

## Pipeline Steps

### Step 1: Analyze Workflow

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
- Console output: Full workflow analysis and summary

**Example:**
```bash
python main.py
```

The analysis will produce a JSON file with inputs like:
```json
[
  {
    "input_name": "total_cholesterol",
    "input_type": "Float",
    "range": {"min": 0, "max": 20},
    "description": "Total cholesterol level from lipid test results"
  },
  ...
]
```

### Step 2: Generate Test Cases

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

### Step 3: Execute Workflow and Generate Labels

Execute the workflow with test cases to determine outcomes and create labeled training data.

```bash
python execute_workflow.py [options]
```

**Options:**
- `-t, --test-cases`: Path to test cases JSON (default: `test_cases.json`)
- `-w, --workflow`: Path to workflow image (default: `workflow.jpeg`)
- `--text-mode`: Use text mode instead of image mode (requires `--workflow-text`)
- `--workflow-text`: Path to workflow text description file (for text mode)
- `-o, --output`: Path to output labeled test cases (default: `labeled_test_cases.json`)
- `--max-workers`: Number of parallel workers (default: 10)
- `--model`: Model to use (default: `claude-haiku-4-5`)
- `--limit`: Limit number of test cases to process (for testing)
- `--quiet`: Suppress progress output

**What it does:**
- Loads test cases from JSON
- For each test case, executes the workflow to determine the outcome
- Uses parallel processing for speed (10 workers by default)
- Saves incrementally to prevent data loss on interruption
- Produces labeled input/output pairs

**Output files:**
- `labeled_test_cases.json`: Array of labeled test cases with inputs and outcomes

**Examples:**
```bash
# Execute all test cases with default settings
python execute_workflow.py

# Execute with custom model and workers
python execute_workflow.py --model claude-haiku-4-5 --max-workers 20

# Test with first 10 cases
python execute_workflow.py --limit 10

# Use text mode instead of image
python execute_workflow.py --text-mode --workflow-text workflow_description.txt
```

## Complete Pipeline Example

Run the entire pipeline from start to finish:

```bash
# Step 1: Analyze workflow
python main.py

# Step 2: Generate 200 test cases
python generate_test_cases.py -n 200

# Step 3: Execute workflow and generate labels
python execute_workflow.py

# Step 4: Train decision tree model
python train_decision_tree.py

# Step 5: Use model to predict outcomes
python predict_workflow.py -i new_inputs.json
```

## Output Files

| File | Description |
|------|-------------|
| `workflow_inputs.json` | Standardized list of workflow inputs with types and ranges |
| `test_cases.json` | Generated test cases covering the input domain |
| `labeled_test_cases.json` | Labeled training data with inputs and outcomes |
| `tokens.json` | Cumulative token usage statistics |

## File Structure

```
LEMON/
├── main.py                      # Workflow analysis script
├── generate_test_cases.py       # Test case generation script
├── execute_workflow.py          # Workflow execution script
├── workflow_prompts.py          # Configurable prompts for agents
├── workflow.jpeg                # Your workflow image
├── src/
│   └── utils/
│       ├── workflow_agent.py    # Workflow analysis agent
│       ├── workflow_executor.py # Workflow execution agent
│       ├── test_case_generator.py # Test case generator
│       └── request_utils.py     # API utilities
├── requirements.txt
├── .env                         # Environment variables (not in git)
└── README.md
```

## Customization

### Modifying Prompts

Edit `workflow_prompts.py` to customize:
- System prompts for workflow analysis
- Analysis prompts for extracting workflow structure
- Execution prompts for determining outcomes

### Adjusting Test Case Generation

Modify `src/utils/test_case_generator.py` to:
- Change value generation strategies
- Adjust sampling methods
- Customize range handling

### Changing Models

- **Workflow Analysis**: Uses model from `DEPLOYMENT_NAME` in `.env`
- **Workflow Execution**: Uses `claude-haiku-4-5` by default (faster, cheaper)

Override execution model:
```bash
python execute_workflow.py --model your-model-name
```

## Token Tracking

Token usage is automatically tracked in `tokens.json`. View statistics:
```python
from src.utils import get_token_stats
stats = get_token_stats()
print(f"Total tokens: {stats['total_tokens']}")
print(f"Total requests: {stats['request_count']}")
```

## Tips

1. **Start Small**: Use `--limit 10` when testing to avoid wasting tokens
2. **Resume Execution**: If interrupted, re-run `execute_workflow.py` - it will resume from where it left off
3. **Parallel Processing**: Increase `--max-workers` for faster execution (be mindful of API rate limits)
4. **Incremental Saving**: Results are saved after each test case, so progress isn't lost on interruption

## Troubleshooting

**Issue**: "Missing required environment variables"
- **Solution**: Ensure `.env` file exists with `ENDPOINT`, `DEPLOYMENT_NAME`, and `API_KEY`

**Issue**: "Failed to parse JSON"
- **Solution**: Check the raw response in the error output. You may need to adjust prompts in `workflow_prompts.py`

**Issue**: Execution is slow
- **Solution**: Increase `--max-workers` (default is 10). Be aware of API rate limits.

**Issue**: Out of memory errors
- **Solution**: Reduce `--max-workers` or process test cases in batches using `--limit`

### Step 4: Train Decision Tree

Train a decision tree model to learn the workflow logic from labeled test cases.

```bash
python train_decision_tree.py [options]
```

**Options:**
- `-i, --input`: Path to labeled test cases JSON (default: `labeled_test_cases.json`)
- `-o, --output-dir`: Directory to save outputs (default: current directory)
- `--test-size`: Proportion for test set (default: 0.2)
- `--max-depth`: Maximum tree depth (default: None = unlimited)
- `--min-samples-split`: Minimum samples to split (default: 2)
- `--min-samples-leaf`: Minimum samples in leaf (default: 1)
- `--criterion`: Split criterion - `gini` or `entropy` (default: gini)
- `--no-visualize`: Skip tree visualization
- `--viz-depth`: Maximum depth for visualization (default: 5)

**What it does:**
- Loads labeled test cases
- Preprocesses inputs and outcomes
- Trains a decision tree classifier
- Evaluates model performance
- Saves model and exports tree visualization

**Output files:**
- `workflow_model.pkl`: Trained decision tree model
- `workflow_model_metadata.json`: Model metadata (encoders, feature names, etc.)
- `decision_tree_rules.txt`: Text representation of tree rules
- `decision_tree.png`: Visual tree diagram

**Examples:**
```bash
# Train with default settings
python train_decision_tree.py

# Train with limited depth
python train_decision_tree.py --max-depth 10

# Train with custom test split
python train_decision_tree.py --test-size 0.3
```

### Step 5: Predict Workflow Outcomes

Use the trained model to predict workflow outcomes for new inputs.

```bash
python predict_workflow.py -i inputs.json
```

**Examples:**
```bash
# Predict from JSON file
python predict_workflow.py -i inputs.json

# Predict from JSON string
python predict_workflow.py -i '{"total_cholesterol": 7.5, "prevention_type": "Primary", ...}'
```

## Next Steps

After generating `labeled_test_cases.json` and training the model, you can:
1. Use the trained model to predict outcomes for new cases
2. Validate workflow logic
3. Generate documentation
4. Create automated tests
5. Deploy the model in production

## License

[Your License Here]

## Contributing

[Contributing Guidelines Here]

