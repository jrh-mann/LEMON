# Workflow Execution Tests

This directory contains comprehensive tests for the workflow tree interpreter/executor.

## Test Structure

### Test Files

1. **`test_parser.py`** - Condition string parsing
   - Tests tokenization and expression tree building
   - Covers operators: `>=, <=, ==, !=, >, <, AND, OR, NOT`
   - Tests edge cases: whitespace, case sensitivity, syntax errors

2. **`test_evaluator.py`** - Expression evaluation
   - Tests evaluation of parsed expressions with context
   - Covers type coercion (int, float, bool, string, enum)
   - Tests operator precedence and parentheses
   - Tests error handling for missing variables

3. **`test_interpreter.py`** - Full workflow execution
   - End-to-end tests using realistic workflow scenarios
   - Tests tree traversal and branch selection
   - Tests input validation
   - Tests execution path tracking

### Test Fixtures (`fixtures.py`)

Contains 5 comprehensive workflow scenarios:

1. **Simple Age Check** - Basic binary decision
   - Tests: `>=` operator, boolean branching

2. **Cholesterol Risk Assessment** - Multi-level nested decisions
   - Tests: Nested conditions, multiple decision points, `AND` logic

3. **Medication Decision** - OR logic and enums
   - Tests: `OR` operator, string equality, enum values

4. **BMI Classification** - Numeric ranges
   - Tests: Range checks (`>= AND <`), complex nesting

5. **Eligibility Check** - NOT operator
   - Tests: `NOT` operator, compound conditions

Each workflow includes:
- Complete schema (inputs, outputs, tree)
- Parametrized test cases with expected outputs
- Boundary value tests
- Error cases

## Running Tests

```bash
# Run all tests
pytest tests/execution/

# Run specific test file
pytest tests/execution/test_parser.py

# Run specific test class
pytest tests/execution/test_interpreter.py::TestSimpleAgeWorkflow

# Run with verbose output
pytest tests/execution/ -v

# Run only parser tests
pytest tests/execution/ -k parser

# Show test coverage
pytest tests/execution/ --cov=src/backend/execution
```

## Test Coverage Goals

### Parser (20+ tests)
- ✅ All comparison operators
- ✅ All logical operators (AND, OR, NOT)
- ✅ String literals with quotes
- ✅ Boolean literals
- ✅ Float and int literals
- ✅ Whitespace handling
- ✅ Error cases (syntax errors)

### Evaluator (25+ tests)
- ✅ All operator evaluations
- ✅ Type coercion
- ✅ Boolean logic (truth tables)
- ✅ Operator precedence
- ✅ Error cases (missing variables, type mismatches)

### Interpreter (40+ tests)
- ✅ 5 workflow scenarios × 5-10 test cases each
- ✅ Input validation (type checking, range checking, enum checking)
- ✅ Path tracking
- ✅ Edge label matching
- ✅ Error handling (missing inputs, invalid types, unreachable outputs)

**Total: 85+ comprehensive tests**

## Implementation Strategy

### Phase 1: Parser
Start with simple cases:
1. Implement lexer (tokenization)
2. Implement recursive descent parser
3. Build expression tree
4. Make all parser tests pass

### Phase 2: Evaluator
Implement evaluation engine:
1. Recursive expression evaluation
2. Type coercion rules
3. Operator implementations
4. Make all evaluator tests pass

### Phase 3: Interpreter
Wire up tree walking:
1. Tree traversal logic
2. Decision node handling
3. Input validation
4. Make all interpreter tests pass

### Phase 4: Integration
Connect to API:
1. Implement `/api/execute/<workflow_id>` endpoint
2. Return `ExecutionResult` type
3. Add error handling

## Success Criteria

All tests passing means:
- ✅ Parser can handle all condition syntaxes
- ✅ Evaluator correctly evaluates all expressions
- ✅ Interpreter successfully executes all workflow types
- ✅ Input validation catches all error cases
- ✅ Execution paths are correctly tracked
- ✅ Ready to integrate validation loop (generate test cases, run, check results)

## Next Steps After Tests Pass

1. **Add CRUD tools** for workflow editing
2. **Implement test case generation** (comprehensive/boundary strategies)
3. **Implement auto-validation loop**:
   - Generate test cases from inputs
   - Label ground truth with Claude
   - Execute workflow
   - Compare results
   - Provide feedback for refinement
4. **Connect to orchestrator** for autonomous workflow refinement
