"""Run tests on workflow_code.py with labeled test cases."""

import json
from pathlib import Path

from dotenv import load_dotenv

from src.lemon.testing.harness import TestHarness
from src.lemon.utils.logging import configure_logging, get_logger

# Load environment variables
load_dotenv()

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)


def main():
    # Load workflow code
    code_path = Path("workflow_code.py")
    if not code_path.exists():
        logger.error("workflow_code.py not found!")
        return 1
    
    code = code_path.read_text(encoding="utf-8")
    logger.info(f"✓ Loaded code from {code_path}")
    
    # Load labeled test cases
    test_cases_path = Path("labeled_test_cases.json")
    if not test_cases_path.exists():
        logger.error("labeled_test_cases.json not found!")
        return 1
    
    with open(test_cases_path) as f:
        test_cases = json.load(f)
    
    logger.info(f"✓ Loaded {len(test_cases)} test cases")
    
    # Load valid outputs
    outputs_path = Path("workflow_outputs.json")
    if not outputs_path.exists():
        logger.error("workflow_outputs.json not found!")
        return 1
    
    with open(outputs_path) as f:
        valid_outputs = json.load(f)
    
    logger.info(f"✓ Loaded {len(valid_outputs)} valid outputs")
    
    # Run tests
    logger.info("\n" + "="*80)
    logger.info("🧪 RUNNING TESTS")
    logger.info("="*80 + "\n")
    
    harness = TestHarness(test_cases=test_cases, valid_outputs=valid_outputs)
    results = harness.score(code)
    
    # Display results
    logger.info("\n" + "="*80)
    logger.info("📊 TEST RESULTS")
    logger.info("="*80)
    logger.info(f"\nPassed: {results.passed}/{results.total}")
    logger.info(f"Pass Rate: {results.pass_rate*100:.1f}%")
    logger.info(f"Failed: {len(results.failures)}")
    
    if results.failures:
        logger.info("\n" + "-"*80)
        logger.info("FAILURES (first 10):")
        logger.info("-"*80)
        for i, failure in enumerate(results.failures[:10]):
            logger.info(f"\n{i+1}. Error: {failure.error}")
            logger.info(f"   Test case: {failure.test_case}")
    
    logger.info("\n" + "="*80)
    
    return 0 if results.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
