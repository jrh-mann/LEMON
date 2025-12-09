"""Script to train a decision tree from labeled workflow test cases."""

import argparse
from pathlib import Path
from src.utils.decision_tree_trainer import train_workflow_decision_tree, WorkflowDecisionTreeTrainer


def main():
    parser = argparse.ArgumentParser(description="Train decision tree from labeled workflow test cases")
    parser.add_argument(
        "-i", "--input",
        type=str,
        default="labeled_test_cases.json",
        help="Path to labeled test cases JSON file (default: labeled_test_cases.json)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=".",
        help="Directory to save outputs (default: current directory)"
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Proportion of data for testing (default: 0.2)"
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Maximum depth of tree (default: None = unlimited)"
    )
    parser.add_argument(
        "--min-samples-split",
        type=int,
        default=2,
        help="Minimum samples to split a node (default: 2)"
    )
    parser.add_argument(
        "--min-samples-leaf",
        type=int,
        default=1,
        help="Minimum samples in a leaf (default: 1)"
    )
    parser.add_argument(
        "--criterion",
        type=str,
        choices=['gini', 'entropy'],
        default='gini',
        help="Split criterion (default: gini)"
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip tree visualization"
    )
    parser.add_argument(
        "--viz-depth",
        type=int,
        default=5,
        help="Maximum depth for visualization (default: 5)"
    )
    parser.add_argument(
        "--class-weight",
        type=str,
        choices=['balanced', 'none'],
        default='none',
        help="Class weights (default: none)"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("WORKFLOW DECISION TREE TRAINING")
    print("=" * 80)
    print(f"\nInput file: {args.input}")
    print(f"Output directory: {args.output_dir}")
    print(f"Test size: {args.test_size}")
    print(f"Max depth: {args.max_depth or 'unlimited'}")
    print(f"Min samples split: {args.min_samples_split}")
    print(f"Min samples leaf: {args.min_samples_leaf}")
    print(f"Criterion: {args.criterion}")
    print()
    
    # Create output directory
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Train model
    trainer = train_workflow_decision_tree(
        labeled_data_file=args.input,
        test_size=args.test_size,
        max_depth=args.max_depth,
        min_samples_split=args.min_samples_split,
        min_samples_leaf=args.min_samples_leaf,
        output_dir=args.output_dir,
        visualize=not args.no_visualize,
        max_viz_depth=args.viz_depth
    )
    
    print("\n" + "=" * 80)
    print("✅ TRAINING COMPLETE!")
    print("=" * 80)
    print(f"\nOutput files saved to: {output_path}")
    print("  - workflow_model.pkl (trained model)")
    print("  - workflow_model_metadata.json (model metadata)")
    print("  - decision_tree_rules.txt (text representation)")
    if not args.no_visualize:
        print("  - decision_tree.png (visualization)")


if __name__ == "__main__":
    main()

