import json
from workflow_code import determine_workflow_outcome

from src.lemon.utils.logging import configure_logging, get_logger

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)

# Load test cases
with open('tests.json', 'r') as f:
    test_cases = json.load(f)

# Run tests
passed = 0
total = len(test_cases)
failures = []

for i, test_case in enumerate(test_cases):
    # Extract inputs (everything except expected_output)
    inputs = {k: v for k, v in test_case.items() if k != 'expected_output'}
    expected = test_case['expected_output']
    
    # Run the function
    actual = determine_workflow_outcome(inputs)
    
    # Compare results (case-insensitive)
    actual_normalized = str(actual).lower() if actual is not None else None
    expected_normalized = str(expected).lower() if expected is not None else None
    if actual_normalized == expected_normalized:
        passed += 1
    else:
        failures.append({
            'test_number': i + 1,
            'inputs': inputs,
            'expected': expected,
            'actual': actual
        })

# Print all failures
logger.info("=" * 80)
logger.info(f"FAILURES ({len(failures)} total):")
logger.info("=" * 80)
logger.info("")

for failure in failures:
    logger.info(f"Test #{failure['test_number']}:")
    logger.info(f"  Inputs: {failure['inputs']}")
    logger.info(f"  Expected: {failure['expected']}")
    logger.info(f"  Actual:   {failure['actual']}")
    logger.info("")

logger.info("=" * 80)
logger.info(f"Passed: {passed}/{total}")
logger.info(f"Pass rate: {passed/total*100:.2f}%")

