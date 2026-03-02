/**
 * DecisionConditionEditor - Configuration panel for decision node conditions.
 * Supports simple (single variable) and compound (AND/OR multiple variable) modes.
 *
 * Also contains the SimpleConditionRow sub-component and condition formatting
 * helpers used for previewing conditions as human-readable strings.
 */

import type {
  FlowNode,
  WorkflowVariable,
  DecisionCondition,
  SimpleCondition,
  CompoundCondition,
  ConditionOperator,
  Comparator,
} from '../../types'
import { COMPARATORS_BY_TYPE, COMPARATOR_LABELS, isCompoundCondition } from '../../types'

/**
 * Format a single simple condition as a human-readable string.
 */
function formatSimpleConditionPreview(condition: SimpleCondition, inputs: WorkflowVariable[]): string {
  if (!condition.input_id) return '(no input)'

  const input = inputs.find(inp => inp.id === condition.input_id)
  const inputName = input?.name ?? condition.input_id
  const compLabel = COMPARATOR_LABELS[condition.comparator] ?? condition.comparator

  if (condition.comparator === 'is_true' || condition.comparator === 'is_false') {
    return `${inputName} ${compLabel}`
  }
  if (condition.comparator === 'within_range' || condition.comparator === 'date_between') {
    return `${inputName} ${compLabel} [${condition.value ?? '?'}, ${condition.value2 ?? '?'}]`
  }
  const valueStr = typeof condition.value === 'string'
    ? `"${condition.value}"`
    : String(condition.value ?? '?')
  return `${inputName} ${compLabel} ${valueStr}`
}

/**
 * Format a condition (simple or compound) as a human-readable string.
 */
export function formatConditionPreview(condition: DecisionCondition, inputs: WorkflowVariable[]): string {
  if (isCompoundCondition(condition)) {
    const joiner = ` ${condition.operator.toUpperCase()} `
    const parts = condition.conditions.map(sub => formatSimpleConditionPreview(sub, inputs))
    return parts.join(joiner) || '(empty compound)'
  }
  return formatSimpleConditionPreview(condition, inputs)
}

/**
 * SimpleConditionRow - A single sub-condition row used in both simple and
 * compound modes. Renders input selector, comparator, and value field(s).
 */
function SimpleConditionRow({
  condition,
  analysisInputs,
  onChange,
  onRemove,
  showRemoveButton,
}: {
  condition: SimpleCondition
  analysisInputs: WorkflowVariable[]
  onChange: (updated: SimpleCondition) => void
  onRemove?: () => void
  showRemoveButton: boolean
}) {
  const selectedInput = analysisInputs.find(inp => inp.id === condition.input_id)
  const inputType = selectedInput?.type ?? 'string'
  const availableComparators = COMPARATORS_BY_TYPE[inputType] ?? COMPARATORS_BY_TYPE.string
  const enumValues = selectedInput?.enum_values ?? []

  const handleInputChange = (inputId: string) => {
    const newInput = analysisInputs.find(inp => inp.id === inputId)
    const newType = newInput?.type ?? 'string'
    const validComps = COMPARATORS_BY_TYPE[newType] ?? COMPARATORS_BY_TYPE.string
    const newComp = validComps.includes(condition.comparator) ? condition.comparator : validComps[0]
    onChange({ input_id: inputId, comparator: newComp, value: '', value2: undefined })
  }

  const needsSecondValue = condition.comparator === 'within_range' || condition.comparator === 'date_between'
  const noValueNeeded = condition.comparator === 'is_true' || condition.comparator === 'is_false'

  // Render a value input appropriate for the variable type
  const renderValueInput = (isSecondValue = false) => {
    const currentValue = isSecondValue ? condition.value2 : condition.value
    const placeholder = isSecondValue ? 'Max value' : needsSecondValue ? 'Min value' : 'Comparison value'
    const valueKey = isSecondValue ? 'value2' : 'value'

    if (inputType === 'enum' && enumValues.length > 0 && !isSecondValue) {
      return (
        <select
          value={String(currentValue ?? '')}
          onChange={(e) => onChange({ ...condition, [valueKey]: e.target.value })}
        >
          <option value="">Select value...</option>
          {enumValues.map((val: string) => (
            <option key={val} value={val}>{val}</option>
          ))}
        </select>
      )
    }
    if (noValueNeeded) return null
    if (inputType === 'date') {
      return (
        <input type="date" value={String(currentValue ?? '')}
          onChange={(e) => onChange({ ...condition, [valueKey]: e.target.value })} />
      )
    }
    if (inputType === 'number') {
      return (
        <input type="number" value={currentValue !== undefined && currentValue !== '' ? String(currentValue) : ''}
          step="any" placeholder={placeholder}
          onChange={(e) => { const v = parseFloat(e.target.value); onChange({ ...condition, [valueKey]: isNaN(v) ? '' : v }) }} />
      )
    }
    return (
      <input type="text" value={String(currentValue ?? '')} placeholder={placeholder}
        onChange={(e) => onChange({ ...condition, [valueKey]: e.target.value })} />
    )
  }

  return (
    <div className="compound-condition-row">
      {/* Input variable selector */}
      <div className="form-group">
        <label>Variable</label>
        <select value={condition.input_id || ''} onChange={(e) => handleInputChange(e.target.value)}>
          <option value="">Select input...</option>
          {analysisInputs.map(inp => (
            <option key={inp.id} value={inp.id}>{inp.name} ({inp.type})</option>
          ))}
        </select>
      </div>

      {/* Comparator selector */}
      {condition.input_id && (
        <div className="form-group">
          <label>Comparator</label>
          <select value={condition.comparator}
            onChange={(e) => onChange({
              ...condition,
              comparator: e.target.value as Comparator,
              value2: (e.target.value === 'within_range' || e.target.value === 'date_between') ? condition.value2 : undefined
            })}>
            {availableComparators.map(comp => (
              <option key={comp} value={comp}>{COMPARATOR_LABELS[comp]}</option>
            ))}
          </select>
        </div>
      )}

      {/* Value input(s) */}
      {condition.input_id && !noValueNeeded && (
        <div className="form-group">
          <label>{needsSecondValue ? 'Range' : 'Value'}</label>
          {needsSecondValue ? (
            <div className="condition-range-inputs">
              {renderValueInput(false)}
              <span className="condition-range-separator">to</span>
              {renderValueInput(true)}
            </div>
          ) : renderValueInput(false)}
        </div>
      )}

      {/* Remove button for compound mode */}
      {showRemoveButton && onRemove && (
        <button className="btn-icon btn-remove-condition" onClick={onRemove} title="Remove condition">
          &times;
        </button>
      )}
    </div>
  )
}

/**
 * DecisionConditionEditor - Main exported component.
 * Renders the condition editing UI for decision nodes, supporting
 * simple (single condition) and compound (AND/OR) modes.
 */
export function DecisionConditionEditor({
  node,
  analysisInputs,
  onUpdate,
}: {
  node: FlowNode
  analysisInputs: WorkflowVariable[]
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  const condition = node.condition
  const compound = condition ? isCompoundCondition(condition) : false

  // Default simple condition for new/empty state
  const defaultSimple: SimpleCondition = { input_id: '', comparator: 'eq' as Comparator, value: '' }

  // Extract current sub-conditions (compound) or single condition (simple)
  const subConditions: SimpleCondition[] = compound
    ? (condition as CompoundCondition).conditions
    : condition && !isCompoundCondition(condition) ? [condition as SimpleCondition] : [defaultSimple]

  const currentOperator: ConditionOperator = compound ? (condition as CompoundCondition).operator : 'and'

  // Switch between simple and compound mode
  const handleModeToggle = (mode: 'simple' | 'compound') => {
    if (mode === 'compound' && !compound) {
      // Convert simple -> compound with the existing condition + an empty row
      const existing = condition && !isCompoundCondition(condition)
        ? (condition as SimpleCondition) : defaultSimple
      const newCondition: CompoundCondition = {
        operator: 'and',
        conditions: [existing, { ...defaultSimple }],
      }
      onUpdate({ condition: newCondition })
    } else if (mode === 'simple' && compound) {
      // Convert compound -> simple using the first sub-condition
      const first = subConditions[0] ?? defaultSimple
      onUpdate({ condition: first })
    }
  }

  // Update a single sub-condition at index i
  const handleSubConditionChange = (i: number, updated: SimpleCondition) => {
    if (compound) {
      const newSubs = [...subConditions]
      newSubs[i] = updated
      const newCondition: CompoundCondition = { operator: currentOperator, conditions: newSubs }
      onUpdate({ condition: newCondition })
    } else {
      // Simple mode: just replace the whole condition
      onUpdate({ condition: updated })
    }
  }

  // Add a new empty sub-condition (compound only)
  const handleAddSubCondition = () => {
    const newSubs = [...subConditions, { ...defaultSimple }]
    onUpdate({ condition: { operator: currentOperator, conditions: newSubs } as CompoundCondition })
  }

  // Remove a sub-condition at index i (compound only, min 2)
  const handleRemoveSubCondition = (i: number) => {
    if (subConditions.length <= 2) return
    const newSubs = subConditions.filter((_, idx) => idx !== i)
    onUpdate({ condition: { operator: currentOperator, conditions: newSubs } as CompoundCondition })
  }

  // Change AND/OR operator
  const handleOperatorChange = (op: ConditionOperator) => {
    if (compound) {
      onUpdate({ condition: { operator: op, conditions: subConditions } as CompoundCondition })
    }
  }

  return (
    <>
      <div className="form-divider" />
      <h5>Decision Condition</h5>
      <p className="muted small">Define when this decision evaluates to true.</p>

      {analysisInputs.length === 0 ? (
        <div className="condition-warning">
          <p className="muted small warning">
            No variables defined. Add variables in the Variables panel first.
          </p>
        </div>
      ) : (
        <>
          {/* Mode toggle: Simple / Compound */}
          <div className="form-group">
            <label>Mode</label>
            <div className="condition-mode-toggle">
              <button
                className={`btn-toggle ${!compound ? 'active' : ''}`}
                onClick={() => handleModeToggle('simple')}
              >
                Simple
              </button>
              <button
                className={`btn-toggle ${compound ? 'active' : ''}`}
                onClick={() => handleModeToggle('compound')}
              >
                Compound
              </button>
            </div>
          </div>

          {/* AND/OR selector for compound mode */}
          {compound && (
            <div className="form-group">
              <label>Operator</label>
              <div className="condition-mode-toggle">
                <button
                  className={`btn-toggle ${currentOperator === 'and' ? 'active' : ''}`}
                  onClick={() => handleOperatorChange('and')}
                >
                  AND
                </button>
                <button
                  className={`btn-toggle ${currentOperator === 'or' ? 'active' : ''}`}
                  onClick={() => handleOperatorChange('or')}
                >
                  OR
                </button>
              </div>
            </div>
          )}

          {/* Sub-condition rows */}
          {subConditions.map((sub, i) => (
            <div key={i}>
              {compound && i > 0 && (
                <div className="compound-operator-label">{currentOperator.toUpperCase()}</div>
              )}
              <SimpleConditionRow
                condition={sub}
                analysisInputs={analysisInputs}
                onChange={(updated) => handleSubConditionChange(i, updated)}
                onRemove={() => handleRemoveSubCondition(i)}
                showRemoveButton={compound && subConditions.length > 2}
              />
            </div>
          ))}

          {/* Add sub-condition button (compound only) */}
          {compound && (
            <button className="btn btn-sm" onClick={handleAddSubCondition}>
              + Add condition
            </button>
          )}

          {/* Condition preview */}
          {condition && (
            <div className="condition-preview">
              <p className="muted small">
                <strong>Preview:</strong> {formatConditionPreview(condition, analysisInputs)}
              </p>
            </div>
          )}
        </>
      )}
    </>
  )
}
