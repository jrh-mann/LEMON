"""Script to generate test cases from workflow inputs."""

import argparse
from src.utils import generate_test_cases_from_file


def main():
    parser = argparse.ArgumentParser(description="Generate test cases from workflow inputs")
    parser.add_argument(
        "-n", "--num-cases",
        type=int,
        default=100,
        help="Number of test cases to generate (default: 100)"
    )
    parser.add_argument(
        "-i", "--inputs-file",
        type=str,
        default="workflow_inputs.json",
        help="Path to workflow inputs JSON file (default: workflow_inputs.json)"
    )
    parser.add_argument(
        "-o", "--output-file",
        type=str,
        default="test_cases.json",
        help="Path to output test cases JSON file (default: test_cases.json)"
    )
    parser.add_argument(
        "-s", "--strategy",
        type=str,
        choices=["comprehensive", "random", "edge_cases"],
        default="comprehensive",
        help="Generation strategy: comprehensive (cover all combinations), random (random sampling), edge_cases (focus on boundaries) (default: comprehensive)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    
    args = parser.parse_args()
    
    print(f"Generating {args.num_cases} test cases using '{args.strategy}' strategy...")
    print(f"Input file: {args.inputs_file}")
    print(f"Output file: {args.output_file}\n")
    
    test_cases = generate_test_cases_from_file(
        inputs_file=args.inputs_file,
        n=args.num_cases,
        strategy=args.strategy,
        output_file=args.output_file,
        seed=args.seed
    )
    
    print(f"\n✅ Generated {len(test_cases)} test cases")
    print(f"   Strategy: {args.strategy}")
    print(f"   Saved to: {args.output_file}")


if __name__ == "__main__":
    main()

