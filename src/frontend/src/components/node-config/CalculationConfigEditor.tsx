/**
 * CalculationConfigEditor - Configuration panel for calculation nodes.
 * Allows selecting an operator, configuring operands (variable references
 * or literals), and specifying the output variable name.
 *
 * Also contains formatCalculationPreview helper for rendering a
 * human-readable formula string.
 */

import { useMemo, useCallback } from 'react'
import type {
  FlowNode,
  WorkflowVariable,
  CalculationConfig as CalculationConfigType,
  Operand,
} from '../../types'
import { getOperator, getOperatorsByCategory } from '../../types'
import { formatCalculationPreview } from './calculationPreview'

const EMPTY_CALCULATION: CalculationConfigType = {
  output: { name: '', description: '' },
  operator: 'add',
  operands: [],
}

export function CalculationConfigEditor({
  node,
  analysisInputs,
  onUpdate,
}: {
  node: FlowNode
  analysisInputs: WorkflowVariable[]
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Get current calculation config or create empty one
  const calculation = useMemo(
    () => node.calculation ?? EMPTY_CALCULATION,
    [node.calculation]
  )

  // Get the selected operator definition
  const selectedOperator = getOperator(calculation.operator)
  const minOperands = selectedOperator?.minArity ?? 2
  const maxOperands = selectedOperator?.maxArity ?? null // null = unlimited

  // Filter to only numeric variables
  const numericVariables = analysisInputs.filter(v =>
    v.type === 'number'
  )

  // Validate the calculation configuration
  const validateCalculation = useCallback((calc: CalculationConfigType): string[] => {
    const errors: string[] = []

    // Check output name
    if (!calc.output.name.trim()) {
      errors.push('Output variable name is required')
    }

    // Check operator
    const op = getOperator(calc.operator)
    if (!op) {
      errors.push(`Unknown operator: ${calc.operator}`)
    } else {
      // Check operand count
      if (calc.operands.length < op.minArity) {
        errors.push(`${op.displayName} requires at least ${op.minArity} operand(s)`)
      }
      if (op.maxArity !== null && calc.operands.length > op.maxArity) {
        errors.push(`${op.displayName} accepts at most ${op.maxArity} operand(s)`)
      }
    }

    // Check each operand
    calc.operands.forEach((operand, idx) => {
      if (operand.kind === 'variable') {
        if (!operand.ref) {
          errors.push(`Operand ${idx + 1}: Variable reference is required`)
        } else {
          // Check if variable exists
          const varExists = analysisInputs.some(v => v.id === operand.ref)
          if (!varExists) {
            errors.push(`Operand ${idx + 1}: Variable "${operand.ref}" not found`)
          }
        }
      } else if (operand.kind === 'literal') {
        if (operand.value === undefined || operand.value === null || isNaN(operand.value)) {
          errors.push(`Operand ${idx + 1}: Numeric value is required`)
        }
      }
    })

    return errors
  }, [analysisInputs])
  const validationErrors = useMemo(
    () => validateCalculation(calculation),
    [calculation, validateCalculation]
  )

  // Update the calculation field on the node
  const updateCalculation = (updates: Partial<CalculationConfigType>) => {
    const newCalculation: CalculationConfigType = {
      ...calculation,
      ...updates,
    }
    onUpdate({ calculation: newCalculation })
  }

  // Update output name
  const updateOutputName = (name: string) => {
    updateCalculation({
      output: { ...calculation.output, name }
    })
  }

  // Update output description
  const updateOutputDescription = (description: string) => {
    updateCalculation({
      output: { ...calculation.output, description }
    })
  }

  // Handle operator change - reset operands if arity requirements change
  const handleOperatorChange = (operatorName: string) => {
    const newOp = getOperator(operatorName)
    if (!newOp) return

    // Adjust operands array to meet new arity requirements
    let newOperands = [...calculation.operands]

    // If we have fewer than min, add empty variable operands
    while (newOperands.length < newOp.minArity) {
      newOperands.push({ kind: 'variable', ref: '' })
    }

    // If we have more than max (and max is not null), truncate
    if (newOp.maxArity !== null && newOperands.length > newOp.maxArity) {
      newOperands = newOperands.slice(0, newOp.maxArity)
    }

    updateCalculation({
      operator: operatorName,
      operands: newOperands
    })
  }

  // Update a specific operand
  const updateOperand = (index: number, operand: Operand) => {
    const newOperands = [...calculation.operands]
    newOperands[index] = operand
    updateCalculation({ operands: newOperands })
  }

  // Add a new operand (for variadic operators)
  const addOperand = () => {
    if (maxOperands !== null && calculation.operands.length >= maxOperands) return
    updateCalculation({
      operands: [...calculation.operands, { kind: 'variable', ref: '' }]
    })
  }

  // Remove an operand (respecting minimum arity)
  const removeOperand = (index: number) => {
    if (calculation.operands.length <= minOperands) return
    const newOperands = calculation.operands.filter((_, i) => i !== index)
    updateCalculation({ operands: newOperands })
  }

  // Toggle operand between variable and literal
  const toggleOperandKind = (index: number) => {
    const current = calculation.operands[index]
    if (current.kind === 'variable') {
      updateOperand(index, { kind: 'literal', value: 0 })
    } else {
      updateOperand(index, { kind: 'variable', ref: '' })
    }
  }

  // Group operators by category for the dropdown
  const unaryOps = getOperatorsByCategory('unary')
  const binaryOps = getOperatorsByCategory('binary')
  const variadicOps = getOperatorsByCategory('variadic')

  // Check if we can add more operands
  const canAddOperand = maxOperands === null || calculation.operands.length < maxOperands
  const canRemoveOperand = calculation.operands.length > minOperands

  return (
    <>
      <div className="form-divider" />
      <h5>Calculation Configuration</h5>
      <p className="muted small">Define a mathematical operation on workflow variables.</p>

      {/* Output variable name */}
      <div className="form-group">
        <label>Output Variable Name</label>
        <input
          type="text"
          value={calculation.output.name}
          onChange={(e) => updateOutputName(e.target.value)}
          placeholder="e.g., BMI, TotalScore"
        />
        <p className="muted small">
          Name for the calculated result. Will create variable: var_{'{slug}'}_number
        </p>
      </div>

      {/* Output description (optional) */}
      <div className="form-group">
        <label>Description (optional)</label>
        <input
          type="text"
          value={calculation.output.description || ''}
          onChange={(e) => updateOutputDescription(e.target.value)}
          placeholder="e.g., Body Mass Index"
        />
      </div>

      <div className="form-divider" />

      {/* Operator selector */}
      <div className="form-group">
        <label>Operator</label>
        <select
          value={calculation.operator}
          onChange={(e) => handleOperatorChange(e.target.value)}
        >
          <optgroup label="Unary (1 operand)">
            {unaryOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
          <optgroup label="Binary (2 operands)">
            {binaryOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
          <optgroup label="Variadic (2+ operands)">
            {variadicOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
        </select>
        {selectedOperator && (
          <p className="muted small">{selectedOperator.description}</p>
        )}
      </div>

      <div className="form-divider" />

      {/* Operands section */}
      <div className="form-group">
        <label>
          Operands
          {selectedOperator && (
            <span className="operand-count">
              {' '}({calculation.operands.length}/{maxOperands ?? '\u221e'})
            </span>
          )}
        </label>

        {numericVariables.length === 0 && (
          <div className="calc-warning">
            <p className="muted small warning">
              No numeric variables defined. Add int, float, or number variables in the Variables panel.
            </p>
          </div>
        )}

        <div className="operands-list">
          {calculation.operands.map((operand, index) => (
            <div className="operand-row" key={index}>
              <span className="operand-index">{index + 1}.</span>

              {/* Kind toggle button */}
              <button
                className="operand-kind-toggle ghost"
                onClick={() => toggleOperandKind(index)}
                title={operand.kind === 'variable' ? 'Switch to literal value' : 'Switch to variable'}
              >
                {operand.kind === 'variable' ? 'var' : '123'}
              </button>

              {/* Operand value input */}
              {operand.kind === 'variable' ? (
                <select
                  className="operand-input"
                  value={operand.ref || ''}
                  onChange={(e) => updateOperand(index, { kind: 'variable', ref: e.target.value })}
                >
                  <option value="">Select variable...</option>
                  {numericVariables.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.type})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  className="operand-input"
                  value={operand.value ?? ''}
                  onChange={(e) => updateOperand(index, {
                    kind: 'literal',
                    value: parseFloat(e.target.value) || 0
                  })}
                  placeholder="Enter number"
                  step="any"
                />
              )}

              {/* Remove button */}
              {canRemoveOperand && (
                <button
                  className="operand-remove ghost"
                  onClick={() => removeOperand(index)}
                  title="Remove operand"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Add operand button (for variadic) */}
        {canAddOperand && (
          <button
            className="ghost add-operand-btn"
            onClick={addOperand}
          >
            + Add Operand
          </button>
        )}
      </div>

      {/* Formula preview */}
      <div className="form-divider" />
      <div className="calc-preview">
        <label>Preview</label>
        <div className="calc-formula">
          {formatCalculationPreview(calculation, analysisInputs)}
        </div>
      </div>

      {/* Validation errors */}
      {validationErrors.length > 0 && (
        <div className="calc-validation-errors">
          <label className="error-label">Validation Issues</label>
          <ul className="error-list">
            {validationErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
