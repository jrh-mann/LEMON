"""Script to generate test cases from workflow inputs."""

import argparse

from src.lemon.utils.logging import configure_logging, get_logger
from src.utils import generate_test_cases_from_file


def main():
    configure_logging(level="INFO", json_logs=False)
    logger = get_logger(__name__)

    parser = argparse.ArgumentParser(description="Generate test cases from workflow inputs")
    parser.add_argument(
        "-n",
        "--num-cases",
        type=int,
        default=100,
        help="Number of test cases to generate (default: 100)",
    )
    parser.add_argument(
        "-i",
        "--inputs-file",
        type=str,
        default="workflow_inputs.json",
        help="Path to workflow inputs JSON file (default: workflow_inputs.json)",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        default="test_cases.json",
        help="Path to output test cases JSON file (default: test_cases.json)",
    )
    parser.add_argument(
        "-s",
        "--strategy",
        type=str,
        choices=["comprehensive", "random", "edge_cases"],
        default="comprehensive",
        help="Generation strategy: comprehensive (cover all combinations), random (random sampling), edge_cases (focus on boundaries) (default: comprehensive)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    args = parser.parse_args()

    logger.info(f"Generating {args.num_cases} test cases using '{args.strategy}' strategy...")
    logger.info(f"Input file: {args.inputs_file}")
    logger.info(f"Output file: {args.output_file}\n")

    test_cases = generate_test_cases_from_file(
        inputs_file=args.inputs_file,
        n=args.num_cases,
        strategy=args.strategy,
        output_file=args.output_file,
        seed=args.seed,
    )

    logger.info(f"\nGenerated {len(test_cases)} test cases")
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Saved to: {args.output_file}")


if __name__ == "__main__":
    main()