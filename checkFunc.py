import json
from workflow_code import determine_workflow_outcome

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
    if expected is None:
        expected = ""
    # Compare results
    if actual.lower() == expected.lower():
        passed += 1
    else:
        failures.append({
            'test_number': i + 1,
            'inputs': inputs,
            'expected': expected,
            'actual': actual
        })

# Print all failures
print("=" * 80)
print(f"FAILURES ({len(failures)} total):")
print("=" * 80)
print()

for failure in failures:
    print(f"Test #{failure['test_number']}:")
    print(f"  Inputs: {failure['inputs']}")
    print(f"  Expected: {failure['expected']}")
    print(f"  Actual:   {failure['actual']}")
    print()

print("=" * 80)
print(f"Passed: {passed}/{total}")
print(f"Pass rate: {passed/total*100:.2f}%")