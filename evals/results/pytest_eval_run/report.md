# Image Eval Diagnostics: pytest_eval_run

## Bucket Counts

- missed node: 3
- wrong branch direction/label: 3
- variable extraction miss: 3
- extra hallucinated node: 2
- ambiguity unresolved: 1

## Per-Case Bucket Distribution

### diabetes_treatment
- missed node: 1
- extra hallucinated node: 1
- wrong branch direction/label: 1
- variable extraction miss: 1

### liver_pathology
- missed node: 1
- wrong branch direction/label: 1
- variable extraction miss: 1
- ambiguity unresolved: 1

### workflow_test
- missed node: 1
- extra hallucinated node: 1
- wrong branch direction/label: 1
- variable extraction miss: 1

## Trial Notes

### workflow_test trial 1 - composite 5.0
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss

### diabetes_treatment trial 1 - composite 5.0
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss

### liver_pathology trial 1 - composite 5.0
- Buckets: missed node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: could not resolve boxes
