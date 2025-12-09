"""Script to predict workflow outcomes using trained decision tree model."""

import argparse
import json
import pickle
from pathlib import Path
from src.utils.decision_tree_trainer import WorkflowDecisionTreeTrainer


def load_model(model_file: str = "workflow_model.pkl", metadata_file: str = "workflow_model_metadata.json"):
    """Load trained model and metadata."""
    with open(model_file, 'rb') as f:
        model = pickle.load(f)
    
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    return model, metadata


def encode_inputs(inputs: dict, metadata: dict) -> list:
    """Encode input dictionary to feature vector."""
    feature_names = metadata['feature_names']
    label_encoders = metadata['label_encoders']
    
    features = []
    for feature in feature_names:
        value = inputs.get(feature)
        
        if feature in label_encoders:
            # Categorical feature - encode using mapping
            mapping = label_encoders[feature]['mapping']
            # Reverse mapping to get encoded value
            reverse_mapping = {v: k for k, v in mapping.items()}
            # Find the encoded value
            encoded_value = mapping.get(str(value), 0)
            features.append(encoded_value)
        elif isinstance(value, bool):
            features.append(int(value))
        elif isinstance(value, (int, float)):
            features.append(float(value))
        else:
            features.append(0)
    
    return features


def predict(inputs: dict, model_file: str = "workflow_model.pkl", metadata_file: str = "workflow_model_metadata.json") -> str:
    """Predict workflow outcome from inputs.
    
    Args:
        inputs: Dictionary with input values
        model_file: Path to saved model
        metadata_file: Path to metadata file
        
    Returns:
        Predicted outcome string
    """
    model, metadata = load_model(model_file, metadata_file)
    
    # Encode inputs
    features = encode_inputs(inputs, metadata)
    
    # Predict
    prediction = model.predict([features])[0]
    
    # Decode outcome
    target_classes = metadata['target_encoder']['classes']
    outcome = target_classes[prediction]
    
    return outcome


def main():
    parser = argparse.ArgumentParser(description="Predict workflow outcome from inputs")
    parser.add_argument(
        "-i", "--inputs",
        type=str,
        help="JSON file with input values, or JSON string"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="workflow_model.pkl",
        help="Path to trained model (default: workflow_model.pkl)"
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default="workflow_model_metadata.json",
        help="Path to model metadata (default: workflow_model_metadata.json)"
    )
    
    args = parser.parse_args()
    
    # Load inputs
    if args.inputs:
        if Path(args.inputs).exists():
            with open(args.inputs, 'r') as f:
                inputs = json.load(f)
        else:
            # Try parsing as JSON string
            inputs = json.loads(args.inputs)
    else:
        # Interactive mode - prompt for inputs
        print("Enter input values (or press Enter to use defaults):")
        inputs = {}
        # You could add interactive prompts here
    
    # Predict
    outcome = predict(inputs, args.model, args.metadata)
    
    print(f"\nPredicted Outcome: {outcome}")
    print(f"\nInputs used:")
    for key, value in inputs.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()

