/**
 * EndNodeConfig - Configuration panel for end (output) nodes.
 * Shows a variable selector dropdown (filtered by workflow output type).
 * For 'string' workflows, "Static value" is replaced by "Value Template" (f-string).
 * For other types, "Static value" shows a type-aware input.
 */

import type { FlowNode, WorkflowInput } from '../../types'

export function EndNodeConfig({
  node,
  analysisInputs,
  workflowOutputType,
  onUpdate,
}: {
  node: FlowNode
  analysisInputs: WorkflowInput[]
  workflowOutputType: string
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Filter variables to only those matching the workflow output type
  // Note: 'json' output type can accept 'json' variables
  const filteredInputs = analysisInputs.filter(inp => inp.type === workflowOutputType)

  // Determine current mode
  const isVariableMode = Boolean(node.output_variable)

  // For strings, the "static" option is actually a template
  const isStringOutput = workflowOutputType === 'string'
  const staticOptionLabel = isStringOutput ? 'Value Template (f-string)' : 'Static Value'
  const staticOptionValue = isStringOutput ? '__template__' : '__static__'

  // Handle switching source
  const handleSourceChange = (value: string) => {
    if (value === '__static__' || value === '__template__') {
      // Switch to static/template mode: clear output_variable
      onUpdate({ output_variable: undefined })
    } else {
      // Switch to variable mode: set output_variable
      // We don't strictly need to clear output_value/template but it keeps things clean
      onUpdate({ output_variable: value, output_value: undefined, output_template: undefined })
    }
  }

  // Render the static value input based on workflow output_type
  const renderStaticInput = () => {
    switch (workflowOutputType) {
      case 'number':
        return (
          <input
            type="number"
            step="any"
            value={node.output_value !== undefined && node.output_value !== '' ? String(node.output_value) : ''}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              onUpdate({ output_value: isNaN(val) ? '' : val })
            }}
            placeholder="Enter a number"
          />
        )
      case 'bool':
        return (
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={Boolean(node.output_value)}
              onChange={(e) => onUpdate({ output_value: e.target.checked })}
            />
            <span>{node.output_value ? 'true' : 'false'}</span>
          </label>
        )
      case 'json':
        return (
          <textarea
            value={typeof node.output_value === 'string' ? node.output_value : JSON.stringify(node.output_value ?? '', null, 2)}
            onChange={(e) => onUpdate({ output_value: e.target.value })}
            placeholder='{"key": "value"}'
            rows={4}
          />
        )
      default:
        return null
    }
  }

  return (
    <>
      <div className="form-divider" />
      <h5>Output Configuration</h5>
      <p className="muted small">
        Workflow output type: <strong>{workflowOutputType}</strong>
      </p>

      {/* Source selector */}
      <div className="form-group">
        <label>Output Source</label>
        <select
          value={isVariableMode ? (node.output_variable || '') : staticOptionValue}
          onChange={(e) => handleSourceChange(e.target.value)}
        >
          <option value={staticOptionValue}>{staticOptionLabel}</option>
          {filteredInputs.map(inp => (
            <option key={inp.id} value={inp.name}>
              {inp.name}
            </option>
          ))}
        </select>

        {/* Helper text */}
        <p className="muted small">
          {isVariableMode
            ? 'Returns the selected variable\'s value directly.'
            : isStringOutput
              ? 'Returns a formatted string using a template.'
              : 'Returns a fixed value you specify below.'}
        </p>
      </div>

      {/* Inputs for non-variable mode */}
      {!isVariableMode && (
        <div className="form-group">
          {isStringOutput ? (
            <>
              <label>Template</label>
              <textarea
                value={node.output_template || ''}
                onChange={(e) => onUpdate({ output_template: e.target.value })}
                placeholder="e.g. Result: {variable_name}"
                rows={3}
              />
              <p className="muted small">
                Use {'{variable}'} to insert input values.
              </p>
            </>
          ) : (
            <>
              <label>Value</label>
              {renderStaticInput()}
            </>
          )}
        </div>
      )}

      {/* Warning if variables are hidden */}
      {analysisInputs.length > 0 && filteredInputs.length === 0 && (
        <p className="muted small warning">
          No variables match the workflow output type ({workflowOutputType}).
        </p>
      )}
    </>
  )
}
