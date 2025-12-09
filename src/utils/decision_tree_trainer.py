"""Decision tree training utilities for workflow learning."""

import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from sklearn.tree import DecisionTreeClassifier, export_text, plot_tree
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    precision_recall_fscore_support
)
import matplotlib.pyplot as plt


class WorkflowDecisionTreeTrainer:
    """Train a decision tree to learn workflow logic from labeled test cases."""
    
    def __init__(self, labeled_data_file: str = "labeled_test_cases.json"):
        """Initialize the trainer.
        
        Args:
            labeled_data_file: Path to labeled test cases JSON file
        """
        self.labeled_data_file = Path(labeled_data_file)
        self.labeled_data = None
        self.X = None
        self.y = None
        self.feature_names = None
        self.label_encoders = {}
        self.target_encoder = None
        self.model = None
        self.X_train = None
        self.X_test = None
        self.y_train = None
        self.y_test = None
        
    def load_data(self) -> List[Dict[str, Any]]:
        """Load labeled test cases from JSON file.
        
        Returns:
            List of labeled test case dictionaries
        """
        if not self.labeled_data_file.exists():
            raise FileNotFoundError(f"Labeled data file not found: {self.labeled_data_file}")
        
        with open(self.labeled_data_file, 'r') as f:
            self.labeled_data = json.load(f)
        
        print(f"Loaded {len(self.labeled_data)} labeled test cases")
        return self.labeled_data
    
    def preprocess_data(self) -> Tuple[pd.DataFrame, pd.Series]:
        """Preprocess labeled data into features and target.
        
        Returns:
            Tuple of (features DataFrame, target Series)
        """
        if self.labeled_data is None:
            self.load_data()
        
        # Extract inputs and outcomes
        features_list = []
        outcomes = []
        
        for case in self.labeled_data:
            if "inputs" not in case or "outcome" not in case:
                continue
            
            inputs = case["inputs"]
            outcome = case["outcome"]
            
            features_list.append(inputs)
            outcomes.append(outcome)
        
        # Convert to DataFrame
        self.X = pd.DataFrame(features_list)
        self.y = pd.Series(outcomes)
        
        # Store feature names
        self.feature_names = list(self.X.columns)
        
        print(f"\nFeatures: {len(self.feature_names)}")
        print(f"  {self.feature_names}")
        print(f"\nUnique outcomes: {self.y.nunique()}")
        print(f"  Sample outcomes: {self.y.unique()[:5]}")
        
        # Encode categorical features
        self._encode_features()
        
        # Encode target
        self._encode_target()
        
        return self.X, self.y
    
    def _encode_features(self):
        """Encode categorical features."""
        for col in self.X.columns:
            if self.X[col].dtype == 'object':
                # Categorical feature - use LabelEncoder
                le = LabelEncoder()
                self.X[col] = le.fit_transform(self.X[col].astype(str))
                self.label_encoders[col] = le
                print(f"  Encoded categorical feature: {col} -> {len(le.classes_)} classes")
            elif self.X[col].dtype == 'bool':
                # Boolean - convert to int
                self.X[col] = self.X[col].astype(int)
                print(f"  Converted boolean feature: {col}")
    
    def _encode_target(self):
        """Encode target variable."""
        self.target_encoder = LabelEncoder()
        self.y = pd.Series(self.target_encoder.fit_transform(self.y))
        print(f"\nEncoded target: {len(self.target_encoder.classes_)} unique outcomes")
    
    def split_data(
        self, 
        test_size: float = 0.2, 
        random_state: int = 42,
        stratify: bool = True
    ):
        """Split data into train and test sets.
        
        Args:
            test_size: Proportion of data for testing
            random_state: Random seed
            stratify: Whether to stratify by target (if possible)
        """
        if self.X is None or self.y is None:
            self.preprocess_data()
        
        # Check if stratification is possible
        stratify_param = None
        if stratify:
            # Check if all classes have at least 2 samples (required for stratification)
            class_counts = self.y.value_counts()
            min_class_count = class_counts.min()
            
            if min_class_count >= 2:
                stratify_param = self.y
                print(f"\nUsing stratified split (all classes have >= 2 samples)")
            else:
                print(f"\n⚠️  Cannot use stratified split: {len(class_counts[class_counts < 2])} classes have < 2 samples")
                print(f"   Falling back to non-stratified split")
        
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            self.X, self.y, 
            test_size=test_size, 
            random_state=random_state,
            stratify=stratify_param
        )
        
        print(f"\nTrain set: {len(self.X_train)} samples")
        print(f"Test set: {len(self.X_test)} samples")
    
    def train(
        self,
        max_depth: Optional[int] = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        criterion: str = 'gini',
        class_weight: Optional[str] = None,
        random_state: int = 42
    ) -> DecisionTreeClassifier:
        """Train decision tree classifier.
        
        Args:
            max_depth: Maximum depth of tree (None = unlimited)
            min_samples_split: Minimum samples to split a node
            min_samples_leaf: Minimum samples in a leaf
            criterion: Split criterion ('gini' or 'entropy')
            class_weight: Class weights ('balanced' or None)
            random_state: Random seed
            
        Returns:
            Trained DecisionTreeClassifier
        """
        if self.X_train is None:
            self.split_data()
        
        self.model = DecisionTreeClassifier(
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            criterion=criterion,
            class_weight=class_weight,
            random_state=random_state
        )
        
        print(f"\nTraining decision tree...")
        print(f"  Max depth: {max_depth or 'unlimited'}")
        print(f"  Min samples split: {min_samples_split}")
        print(f"  Min samples leaf: {min_samples_leaf}")
        print(f"  Criterion: {criterion}")
        
        self.model.fit(self.X_train, self.y_train)
        
        print(f"✅ Training complete!")
        print(f"  Tree depth: {self.model.tree_.max_depth}")
        print(f"  Number of leaves: {self.model.tree_.n_leaves}")
        print(f"  Number of nodes: {self.model.tree_.node_count}")
        
        return self.model
    
    def evaluate(self) -> Dict[str, Any]:
        """Evaluate model performance.
        
        Returns:
            Dictionary with evaluation metrics
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Predictions
        y_train_pred = self.model.predict(self.X_train)
        y_test_pred = self.model.predict(self.X_test)
        
        # Metrics
        train_accuracy = accuracy_score(self.y_train, y_train_pred)
        test_accuracy = accuracy_score(self.y_test, y_test_pred)
        
        # Get unique labels present in test set
        unique_labels = sorted(set(self.y_test.unique()) | set(y_test_pred))
        label_names = [self.target_encoder.classes_[i] for i in unique_labels]
        
        # Classification report
        test_report = classification_report(
            self.y_test, y_test_pred,
            labels=unique_labels,
            target_names=label_names,
            output_dict=True,
            zero_division=0
        )
        
        # Feature importance
        feature_importance = dict(zip(
            self.feature_names,
            self.model.feature_importances_
        ))
        feature_importance = dict(sorted(
            feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        ))
        
        metrics = {
            'train_accuracy': train_accuracy,
            'test_accuracy': test_accuracy,
            'classification_report': test_report,
            'feature_importance': feature_importance,
            'confusion_matrix': confusion_matrix(self.y_test, y_test_pred).tolist()
        }
        
        # Print results
        print(f"\n{'='*60}")
        print("EVALUATION RESULTS")
        print(f"{'='*60}")
        print(f"\nTrain Accuracy: {train_accuracy:.4f}")
        print(f"Test Accuracy: {test_accuracy:.4f}")
        
        print(f"\n{'='*60}")
        print("FEATURE IMPORTANCE")
        print(f"{'='*60}")
        for feature, importance in list(feature_importance.items())[:10]:
            print(f"  {feature:30s}: {importance:.4f}")
        
        print(f"\n{'='*60}")
        print("CLASSIFICATION REPORT")
        print(f"{'='*60}")
        print(classification_report(
            self.y_test, y_test_pred,
            labels=unique_labels,
            target_names=label_names,
            zero_division=0
        ))
        
        return metrics
    
    def visualize_tree(
        self, 
        output_file: str = "decision_tree.png",
        max_depth: int = 5,
        figsize: Tuple[int, int] = (20, 10)
    ):
        """Visualize the decision tree.
        
        Args:
            output_file: Path to save visualization
            max_depth: Maximum depth to show (None = full tree)
            figsize: Figure size
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Get only the classes that the model was actually trained on
        model_classes = self.model.classes_
        class_names = [self.target_encoder.classes_[i] for i in model_classes]
        
        plt.figure(figsize=figsize)
        plot_tree(
            self.model,
            feature_names=self.feature_names,
            class_names=class_names,
            filled=True,
            rounded=True,
            max_depth=max_depth,
            fontsize=8
        )
        plt.title(f"Decision Tree (showing depth {max_depth or 'full'})")
        plt.tight_layout()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"\n✅ Tree visualization saved to: {output_file}")
        plt.close()
    
    def export_tree_text(self, output_file: str = "decision_tree_rules.txt") -> str:
        """Export tree as text rules.
        
        Args:
            output_file: Path to save text rules
            
        Returns:
            Text representation of tree
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Get only the classes that the model was actually trained on
        model_classes = self.model.classes_
        class_names = [self.target_encoder.classes_[i] for i in model_classes]
        
        tree_text = export_text(
            self.model,
            feature_names=self.feature_names,
            class_names=class_names,
            max_depth=10
        )
        
        with open(output_file, 'w') as f:
            f.write(tree_text)
        
        print(f"✅ Tree rules saved to: {output_file}")
        return tree_text
    
    def export_python_function(
        self, 
        output_file: str = "workflow_predictor.py"
    ) -> str:
        """Export trained model as a Python function.
        
        Args:
            output_file: Path to save Python code
            
        Returns:
            Python code as string
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Generate Python code
        code = self._generate_python_code()
        
        with open(output_file, 'w') as f:
            f.write(code)
        
        print(f"✅ Python function saved to: {output_file}")
        return code
    
    def _generate_python_code(self) -> str:
        """Generate Python code for the decision tree."""
        # Get tree structure
        tree = self.model.tree_
        
        code_lines = [
            '"""',
            'Workflow Decision Tree Predictor',
            'Generated from trained decision tree model',
            '"""',
            '',
            'import numpy as np',
            '',
            '',
            'def predict_workflow_outcome(inputs):',
            '    """',
            '    Predict workflow outcome from input values.',
            '    ',
            '    Args:',
            '        inputs: Dictionary with input values',
            '    ',
            '    Returns:',
            '        Predicted outcome string',
            '    """',
            '    # Feature encoding',
        ]
        
        # Add feature encoding
        for feature in self.feature_names:
            if feature in self.label_encoders:
                le = self.label_encoders[feature]
                code_lines.append(f'    # Encode {feature}')
                code_lines.append(f'    {feature}_encoded = {dict(zip(le.classes_, le.transform(le.classes_)))}.get(inputs.get("{feature}"), 0)')
        
        # Add feature extraction
        code_lines.append('    ')
        code_lines.append('    # Extract features in order')
        for feature in self.feature_names:
            if feature in self.label_encoders:
                code_lines.append(f'    {feature}_val = {feature}_encoded')
            elif self.X[feature].dtype == 'bool' or self.X[feature].dtype == 'int64':
                code_lines.append(f'    {feature}_val = int(inputs.get("{feature}", 0))')
            else:
                code_lines.append(f'    {feature}_val = float(inputs.get("{feature}", 0.0))')
        
        code_lines.append('    ')
        code_lines.append('    # Feature vector')
        code_lines.append('    features = [')
        for feature in self.feature_names:
            code_lines.append(f'        {feature}_val,  # {feature}')
        code_lines.append('    ]')
        code_lines.append('    ')
        code_lines.append('    # Predict using tree (simplified - use model.predict() in practice)')
        code_lines.append('    # For full implementation, load the saved model:')
        code_lines.append('    # import pickle')
        code_lines.append('    # with open("workflow_model.pkl", "rb") as f:')
        code_lines.append('    #     model = pickle.load(f)')
        code_lines.append('    # prediction = model.predict([features])[0]')
        code_lines.append('    # return target_encoder.inverse_transform([prediction])[0]')
        code_lines.append('    ')
        code_lines.append('    # Simplified prediction (placeholder)')
        code_lines.append('    return "Use saved model for prediction"')
        
        return '\n'.join(code_lines)
    
    def save_model(
        self, 
        model_file: str = "workflow_model.pkl",
        metadata_file: str = "workflow_model_metadata.json"
    ):
        """Save trained model and metadata.
        
        Args:
            model_file: Path to save model
            metadata_file: Path to save metadata
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Save model
        with open(model_file, 'wb') as f:
            pickle.dump(self.model, f)
        
        # Helper function to convert numpy types to native Python types
        def convert_to_native(obj):
            """Convert numpy types to native Python types for JSON serialization."""
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_to_native(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_native(item) for item in obj]
            else:
                return obj
        
        # Save metadata
        label_encoders_metadata = {}
        for feature, le in self.label_encoders.items():
            classes_list = le.classes_.tolist()
            mapping = dict(zip(classes_list, [int(x) for x in le.transform(le.classes_)]))
            label_encoders_metadata[feature] = {
                'classes': classes_list,
                'mapping': mapping
            }
        
        target_classes_list = self.target_encoder.classes_.tolist()
        target_mapping = dict(zip(
            target_classes_list,
            [int(x) for x in self.target_encoder.transform(self.target_encoder.classes_)]
        ))
        
        metadata = {
            'feature_names': self.feature_names,
            'label_encoders': label_encoders_metadata,
            'target_encoder': {
                'classes': target_classes_list,
                'mapping': target_mapping
            },
            'tree_depth': int(self.model.tree_.max_depth),
            'n_leaves': int(self.model.tree_.n_leaves),
            'n_nodes': int(self.model.tree_.node_count)
        }
        
        # Convert any remaining numpy types
        metadata = convert_to_native(metadata)
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"\n✅ Model saved to: {model_file}")
        print(f"✅ Metadata saved to: {metadata_file}")


def train_workflow_decision_tree(
    labeled_data_file: str = "labeled_test_cases.json",
    test_size: float = 0.2,
    max_depth: Optional[int] = None,
    min_samples_split: int = 2,
    min_samples_leaf: int = 1,
    output_dir: str = ".",
    visualize: bool = True,
    max_viz_depth: int = 5
) -> WorkflowDecisionTreeTrainer:
    """Convenience function to train a workflow decision tree.
    
    Args:
        labeled_data_file: Path to labeled test cases
        test_size: Proportion for test set
        max_depth: Maximum tree depth
        min_samples_split: Minimum samples to split
        min_samples_leaf: Minimum samples in leaf
        output_dir: Directory to save outputs
        visualize: Whether to create visualization
        max_viz_depth: Maximum depth for visualization
        
    Returns:
        Trained WorkflowDecisionTreeTrainer instance
    """
    trainer = WorkflowDecisionTreeTrainer(labeled_data_file)
    trainer.load_data()
    trainer.preprocess_data()
    trainer.split_data(test_size=test_size)
    trainer.train(
        max_depth=max_depth,
        min_samples_split=min_samples_split,
        min_samples_leaf=min_samples_leaf
    )
    trainer.evaluate()
    
    output_path = Path(output_dir)
    
    # Save model
    trainer.save_model(
        model_file=str(output_path / "workflow_model.pkl"),
        metadata_file=str(output_path / "workflow_model_metadata.json")
    )
    
    # Export tree
    trainer.export_tree_text(
        output_file=str(output_path / "decision_tree_rules.txt")
    )
    
    # Visualize
    if visualize:
        trainer.visualize_tree(
            output_file=str(output_path / "decision_tree.png"),
            max_depth=max_viz_depth
        )
    
    return trainer

