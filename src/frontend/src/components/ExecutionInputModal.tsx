import { useState, useCallback } from 'react'
import type { WorkflowInput } from '../types'

interface ExecutionInputModalProps {
  inputs: WorkflowInput[]
  onCancel: () => void
  onSubmit: (values: Record<string, unknown>) => void
}

/**
 * Modal dialog for collecting workflow input values before execution.
 * Renders appropriate input controls based on each input's type (string, int, float, bool, enum, date).
 */
export default function ExecutionInputModal({
  inputs,
  onCancel,
  onSubmit,
}: ExecutionInputModalProps) {
  // Initialize values with defaults based on input types
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {}
    for (const input of inputs) {
      switch (input.type) {
        case 'bool':
          initial[input.name] = false
          break
        case 'int':
        case 'float':
          initial[input.name] = input.range?.min ?? 0
          break
        case 'enum':
          // Use first enum value as default
          const enumVals = input.enum_values ?? input.enum ?? []
          initial[input.name] = enumVals[0] ?? ''
          break
        case 'date':
          // Default to today's date in ISO format
          initial[input.name] = new Date().toISOString().split('T')[0]
          break
        case 'string':
        default:
          initial[input.name] = ''
          break
      }
    }
    return initial
  })

  // Handle value changes for any input
  const handleChange = useCallback((name: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [name]: value }))
  }, [])

  // Handle form submission
  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      onSubmit(values)
    },
    [values, onSubmit]
  )

  // Render appropriate input control based on type
  const renderInput = (input: WorkflowInput) => {
    const inputId = `exec-input-${input.name}`
    const value = values[input.name]

    switch (input.type) {
      case 'bool':
        return (
          <div className="input-field checkbox-field">
            <input
              id={inputId}
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => handleChange(input.name, e.target.checked)}
            />
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
          </div>
        )

      case 'int':
        return (
          <div className="input-field">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
            <input
              id={inputId}
              type="number"
              step="1"
              min={input.range?.min}
              max={input.range?.max}
              value={Number(value)}
              onChange={(e) => handleChange(input.name, parseInt(e.target.value, 10))}
            />
          </div>
        )

      case 'float':
        return (
          <div className="input-field">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
            <input
              id={inputId}
              type="number"
              step="0.01"
              min={input.range?.min}
              max={input.range?.max}
              value={Number(value)}
              onChange={(e) => handleChange(input.name, parseFloat(e.target.value))}
            />
          </div>
        )

      case 'enum':
        const enumValues = input.enum_values ?? input.enum ?? []
        return (
          <div className="input-field">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
            <select
              id={inputId}
              value={String(value)}
              onChange={(e) => handleChange(input.name, e.target.value)}
            >
              {enumValues.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )

      case 'date':
        return (
          <div className="input-field">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
            <input
              id={inputId}
              type="date"
              value={String(value)}
              onChange={(e) => handleChange(input.name, e.target.value)}
            />
          </div>
        )

      case 'string':
      default:
        return (
          <div className="input-field">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <p className="input-description">{input.description}</p>
            )}
            <input
              id={inputId}
              type="text"
              value={String(value)}
              onChange={(e) => handleChange(input.name, e.target.value)}
              placeholder={`Enter ${input.name}`}
            />
          </div>
        )
    }
  }

  return (
    <div className="execution-input-modal-overlay" onClick={onCancel}>
      <div
        className="execution-input-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>Workflow Inputs</h3>
        <p className="muted small">
          Provide values for the workflow inputs before running
        </p>

        <form onSubmit={handleSubmit}>
          <div className="inputs-list">
            {inputs.map((input) => (
              <div key={input.id || input.name} className="input-row">
                {renderInput(input)}
              </div>
            ))}
          </div>

          <div className="modal-actions">
            <button type="button" className="ghost" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="primary run-btn">
              Run Workflow
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
